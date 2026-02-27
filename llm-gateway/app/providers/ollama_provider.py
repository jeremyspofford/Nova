"""
Ollama provider — direct HTTP client for local model serving.
Ideal for development: instant setup, hot-swapping models, Apple Silicon support.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx
from nova_contracts import (
    CompleteRequest,
    CompleteResponse,
    EmbedRequest,
    EmbedResponse,
    ModelCapability,
    StreamChunk,
    ToolCall,
)

from app.config import settings
from app.providers.base import ModelProvider

log = logging.getLogger(__name__)


class OllamaProvider(ModelProvider):
    """
    Direct Ollama integration — OpenAI-compatible API at /api/chat.
    Not used for production (41 TPS peak vs vLLM's 793 TPS), but
    invaluable for local development with zero cloud cost.
    """

    def __init__(self, base_url: str = settings.ollama_base_url, default_model: str = "llama3.2"):
        self._base_url = base_url
        self._default_model = default_model

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def capabilities(self) -> set[ModelCapability]:
        return {
            ModelCapability.chat,
            ModelCapability.streaming,
            ModelCapability.embeddings,
        }

    async def complete(self, request: CompleteRequest) -> CompleteResponse:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        async with httpx.AsyncClient(base_url=self._base_url, timeout=120.0) as client:
            resp = await client.post("/api/chat", json={
                "model": request.model or self._default_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": request.temperature},
            })
            resp.raise_for_status()
            data = resp.json()

        return CompleteResponse(
            content=data["message"]["content"],
            model=data.get("model", request.model),
            tool_calls=[],
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            cost_usd=None,  # local inference is free
            finish_reason="stop",
        )

    async def stream(self, request: CompleteRequest) -> AsyncIterator[StreamChunk]:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        async with httpx.AsyncClient(base_url=self._base_url, timeout=120.0) as client:
            async with client.stream("POST", "/api/chat", json={
                "model": request.model or self._default_model,
                "messages": messages,
                "stream": True,
                "options": {"temperature": request.temperature},
            }) as resp:
                resp.raise_for_status()
                import json
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    done = chunk.get("done", False)
                    yield StreamChunk(
                        delta=content,
                        finish_reason="stop" if done else None,
                    )

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        embeddings = []

        async with httpx.AsyncClient(base_url=self._base_url, timeout=60.0) as client:
            for text in request.texts:
                resp = await client.post("/api/embeddings", json={
                    "model": request.model or self._default_model,
                    "prompt": text,
                })
                resp.raise_for_status()
                data = resp.json()
                embeddings.append(data["embedding"])

        return EmbedResponse(
            embeddings=embeddings,
            model=request.model,
            input_tokens=0,  # Ollama doesn't report token counts for embeddings
        )
