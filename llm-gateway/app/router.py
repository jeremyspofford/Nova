"""
LLM Gateway FastAPI router.
Exposes /complete, /stream, /embed endpoints backed by ModelProvider abstraction.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from nova_contracts import (
    CompleteRequest,
    CompleteResponse,
    EmbedRequest,
    EmbedResponse,
    ModelInfo,
)

from app.rate_limiter import check_rate_limit
from app.registry import get_provider
from app.response_cache import get_cached, set_cached

log = logging.getLogger(__name__)
router = APIRouter(tags=["llm"])


async def _enforce_rate_limit(model: str) -> None:
    allowed, prefix, remaining = await check_rate_limit(model)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily quota exhausted for provider '{prefix}'. Try a different provider or wait until the quota resets.",
        )


@router.post("/complete", response_model=CompleteResponse)
async def complete(request: CompleteRequest):
    """Non-streaming LLM completion."""
    await _enforce_rate_limit(request.model)

    # Check cache (only for temperature=0 deterministic requests)
    cache_body = None
    if request.temperature == 0:
        cache_body = request.model_dump(exclude={"metadata", "stream"})
        cached = await get_cached("complete", cache_body)
        if cached:
            return CompleteResponse(**cached)

    provider = await get_provider(request.model)
    response = await provider.complete(request)
    log.info(
        "complete model=%s in=%d out=%d cost=$%.4f",
        response.model, response.input_tokens, response.output_tokens, response.cost_usd or 0,
    )

    if cache_body is not None:
        await set_cached("complete", cache_body, response.model_dump())

    return response


@router.post("/stream")
async def stream(request: CompleteRequest):
    """
    Server-Sent Events streaming completion.
    Each chunk is a JSON line; the final chunk has finish_reason set.
    """
    await _enforce_rate_limit(request.model)
    provider = await get_provider(request.model)

    async def generate() -> AsyncIterator[bytes]:
        try:
            async for chunk in provider.stream(request):
                yield f"data: {chunk.model_dump_json()}\n\n".encode()
            yield b"data: [DONE]\n\n"
        except Exception as e:
            log.error("Stream error from %s (model=%s): %s", provider.name, request.model, e)
            # Nova internal SSE format — intentionally different from the OpenAI-compat
            # endpoint (/v1/chat/completions) which uses {"error": {"message": ..., "type": ...}}.
            error_payload = json.dumps({"error": str(e), "provider": provider.name})
            yield f"data: {error_payload}\n\n".encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    """Generate embeddings for a list of texts."""
    await _enforce_rate_limit(request.model)

    # Embeddings are always deterministic — cache unconditionally
    cache_body = request.model_dump()
    cached = await get_cached("embed", cache_body)
    if cached:
        return EmbedResponse(**cached)

    provider = await get_provider(request.model)
    response = await provider.embed(request)

    await set_cached("embed", cache_body, response.model_dump())
    return response


@router.get("/models", response_model=list[ModelInfo])
async def list_models():
    """List available models and their capabilities."""
    from app.registry import MODEL_REGISTRY, get_model_spec
    results = []
    for model_id, provider in MODEL_REGISTRY.items():
        ctx_window, max_out = get_model_spec(model_id)
        results.append(ModelInfo(
            id=model_id,
            provider=provider.name,
            capabilities=list(provider.capabilities),
            context_window=ctx_window,
            max_output_tokens=max_out,
        ))
    return results
