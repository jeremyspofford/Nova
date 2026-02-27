"""
LLM Gateway FastAPI router.
Exposes /complete, /stream, /embed endpoints backed by ModelProvider abstraction.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from nova_contracts import (
    CompleteRequest,
    CompleteResponse,
    EmbedRequest,
    EmbedResponse,
    ModelInfo,
)

from app.registry import get_provider

log = logging.getLogger(__name__)
router = APIRouter(tags=["llm"])


@router.post("/complete", response_model=CompleteResponse)
async def complete(request: CompleteRequest):
    """Non-streaming LLM completion."""
    provider = get_provider(request.model)
    response = await provider.complete(request)
    log.info(
        "complete model=%s in=%d out=%d cost=$%.4f",
        response.model, response.input_tokens, response.output_tokens, response.cost_usd or 0,
    )
    return response


@router.post("/stream")
async def stream(request: CompleteRequest):
    """
    Server-Sent Events streaming completion.
    Each chunk is a JSON line; the final chunk has finish_reason set.
    """
    provider = get_provider(request.model)

    async def generate() -> AsyncIterator[bytes]:
        try:
            async for chunk in provider.stream(request):
                yield f"data: {chunk.model_dump_json()}\n\n".encode()
            yield b"data: [DONE]\n\n"
        except Exception as e:
            log.error("Stream error from %s (model=%s): %s", provider.name, request.model, e)
            error_payload = json.dumps({"error": str(e), "provider": provider.name})
            yield f"data: {error_payload}\n\n".encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    """Generate embeddings for a list of texts."""
    provider = get_provider(request.model)
    return await provider.embed(request)


@router.get("/models", response_model=list[ModelInfo])
async def list_models():
    """List available models and their capabilities."""
    from app.registry import MODEL_REGISTRY
    return [
        ModelInfo(
            id=model_id,
            provider=provider.name,
            capabilities=list(provider.capabilities),
            context_window=128000,
            max_output_tokens=8096,
        )
        for model_id, provider in MODEL_REGISTRY.items()
    ]
