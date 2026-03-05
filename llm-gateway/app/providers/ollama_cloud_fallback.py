"""
OllamaCloudFallback — tries Ollama first, falls back to a cloud provider with model override.

Solves the model-name mismatch: cloud providers don't know "llama3.2" but they know
"groq/llama-3.3-70b-versatile". This provider transparently swaps the model name on fallback.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from nova_contracts import (
    CompleteRequest,
    CompleteResponse,
    EmbedRequest,
    EmbedResponse,
    ModelCapability,
    StreamChunk,
)

from app.config import settings
from app.providers.base import ModelProvider

log = logging.getLogger(__name__)


class OllamaCloudFallback(ModelProvider):
    """Try Ollama, on failure retry with a cloud model via the cloud fallback chain."""

    def __init__(self, ollama: ModelProvider, cloud: ModelProvider):
        self._ollama = ollama
        self._cloud = cloud

    @property
    def name(self) -> str:
        return f"ollama-cloud-fallback({self._ollama.name},{self._cloud.name})"

    @property
    def capabilities(self) -> set[ModelCapability]:
        return self._ollama.capabilities | self._cloud.capabilities

    def _cloud_model(self, original_model: str | None) -> str:
        """Return the cloud fallback model for chat/completion requests."""
        return settings.ollama_cloud_fallback_model

    def _cloud_embed_model(self, original_model: str | None) -> str:
        """Return the cloud fallback model for embedding requests."""
        return settings.ollama_cloud_fallback_embed_model

    async def complete(self, request: CompleteRequest) -> CompleteResponse:
        try:
            return await self._ollama.complete(request)
        except Exception as e:
            cloud_model = self._cloud_model(request.model)
            log.info("Ollama failed (%s), falling back to %s", e, cloud_model)
            fallback_req = request.model_copy(update={"model": cloud_model})
            return await self._cloud.complete(fallback_req)

    async def stream(self, request: CompleteRequest) -> AsyncIterator[StreamChunk]:
        try:
            async for chunk in self._ollama.stream(request):
                yield chunk
            return
        except Exception as e:
            cloud_model = self._cloud_model(request.model)
            log.info("Ollama stream failed (%s), falling back to %s", e, cloud_model)
            fallback_req = request.model_copy(update={"model": cloud_model})
            async for chunk in self._cloud.stream(fallback_req):
                yield chunk

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        try:
            return await self._ollama.embed(request)
        except Exception as e:
            cloud_model = self._cloud_embed_model(request.model)
            log.info("Ollama embed failed (%s), falling back to %s", e, cloud_model)
            fallback_req = request.model_copy(update={"model": cloud_model})
            return await self._cloud.embed(fallback_req)
