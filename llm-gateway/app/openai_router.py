"""
OpenAI-compatible endpoints for the Nova LLM Gateway.

  POST /v1/chat/completions  — non-streaming and streaming completions
  GET  /v1/models            — list all registered Nova model IDs

Client configuration examples:

  VS Code Continue.dev (config.json):
    {
      "title": "Nova (Qwen 2.5 7B)",
      "provider": "openai",
      "model": "qwen2.5:7b",
      "apiBase": "http://localhost:8001/v1",
      "apiKey": "unused"
    }

  curl:
    curl http://localhost:8001/v1/chat/completions \\
      -H "Content-Type: application/json" \\
      -d '{"model": "qwen2.5:7b",
           "messages": [{"role": "user", "content": "hello"}]}'

Model IDs must be valid Nova model IDs as listed in registry.py.
"""
from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.openai_compat import (
    OAIChatCompletionRequest,
    OAIStreamChunk,
    OAIStreamChoice,
    OAIStreamDelta,
    make_stream_chunk,
    nova_response_to_oai,
    oai_request_to_nova,
)
from app.config import settings
from app.editor_tracker import detect_editor_slug, record_connection, get_connections
from app.rate_limiter import check_rate_limit
from app.registry import MODEL_REGISTRY, DEFAULT_MODEL_KEY, get_provider
from app.tier_resolver import resolve_model, BudgetExhaustedError

log = logging.getLogger(__name__)
openai_router = APIRouter(prefix="/v1", tags=["openai-compat"])


@openai_router.post("/chat/completions")
async def chat_completions(req: OAIChatCompletionRequest, raw_request: Request):
    """OpenAI-compatible chat completion endpoint (streaming and non-streaming)."""
    # Tier resolution: OAI requests may not have tier/task_type — heuristic inference handles it
    caller = raw_request.headers.get("x-caller")
    try:
        nova_req = oai_request_to_nova(req)
        resolved = await resolve_model(
            model=req.model, tier=getattr(req, "tier", None),
            task_type=getattr(req, "task_type", None),
            request=nova_req, caller=caller,
        )
        req.model = resolved
        nova_req.model = resolved
    except BudgetExhaustedError:
        return {"error": {"message": "Daily budget exceeded", "type": "budget_exhausted"}}
    except ValueError as e:
        return {"error": {"message": str(e), "type": "server_error"}}

    allowed, prefix, _remaining = await check_rate_limit(req.model)
    if not allowed:
        return {"error": {"message": f"Daily quota exhausted for provider '{prefix}'.", "type": "rate_limit_error"}}
    provider = await get_provider(req.model)

    if req.stream:
        chunk_id = f"chatcmpl-{uuid4().hex[:24]}"

        async def generate():
            try:
                # OpenAI spec: first chunk carries role only, content empty
                role_chunk = OAIStreamChunk(
                    id=chunk_id,
                    created=int(time.time()),
                    model=req.model,
                    choices=[OAIStreamChoice(delta=OAIStreamDelta(role="assistant"))],
                )
                yield f"data: {role_chunk.model_dump_json()}\n\n".encode()

                async for chunk in provider.stream(nova_req):
                    oai_chunk = make_stream_chunk(
                        delta_text=chunk.delta,
                        chunk_id=chunk_id,
                        model=req.model,
                        finish_reason=chunk.finish_reason,
                    )
                    yield f"data: {oai_chunk.model_dump_json()}\n\n".encode()

                # Track editor connection after successful stream (non-blocking)
                _track_editor(raw_request)
                yield b"data: [DONE]\n\n"

            except Exception as e:
                log.error("OpenAI-compat stream error (model=%s): %s", req.model, e)
                error_payload = json.dumps({
                    "error": {"message": str(e), "type": "server_error"}
                })
                yield f"data: {error_payload}\n\n".encode()
                yield b"data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    else:
        response = await provider.complete(nova_req)
        log.info(
            "openai-compat complete model=%s in=%d out=%d cost=$%.6f",
            req.model,
            response.input_tokens,
            response.output_tokens,
            response.cost_usd or 0,
        )
        # Track editor connection (non-critical, best-effort)
        _track_editor(raw_request)
        return nova_response_to_oai(response, request_model=req.model)


@openai_router.get("/models")
async def list_models_oai():
    """Return all registered Nova model IDs in OpenAI list format."""
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model", "created": now, "owned_by": "nova"}
            for model_id in MODEL_REGISTRY
            if model_id != DEFAULT_MODEL_KEY
        ],
    }


def _track_editor(request: Request) -> None:
    """Fire-and-forget editor tracking. Runs in background to not slow responses."""
    import asyncio
    asyncio.create_task(_record_editor(request))


async def _record_editor(request: Request) -> None:
    """Detect and record editor connection from request headers."""
    try:
        user_agent = request.headers.get("user-agent")
        # Check for editor hint header (set by dashboard test connection)
        editor_hint = request.headers.get("x-nova-editor")
        slug = detect_editor_slug(editor_hint, user_agent)
        if slug:
            await record_connection(slug, user_agent)
    except Exception:
        pass  # Non-critical


@openai_router.get("/editor-connections")
async def editor_connections():
    """Return connection state for all known editors."""
    connections = await get_connections()
    endpoint = settings.gateway_public_url
    auth_required = settings.require_auth
    return {
        "connections": connections,
        "endpoint": endpoint,
        "auth_required": auth_required,
    }
