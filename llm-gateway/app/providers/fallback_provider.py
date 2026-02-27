"""
FallbackProvider — wraps multiple providers, tries them in order on failure.
If Anthropic is rate-limited, falls back to OpenAI; if that fails, tries Ollama.
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

from app.providers.base import ModelProvider

log = logging.getLogger(__name__)


class FallbackProvider(ModelProvider):
    """
    Wraps an ordered list of providers with automatic failover.
    Providers are tried in order; the first successful response wins.
    """

    def __init__(self, providers: list[ModelProvider], timeout_seconds: float = 30.0):
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider")
        self._providers = providers
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return f"fallback({','.join(p.name for p in self._providers)})"

    @property
    def capabilities(self) -> set[ModelCapability]:
        # Union of all provider capabilities
        result: set[ModelCapability] = set()
        for p in self._providers:
            result |= p.capabilities
        return result

    async def complete(self, request: CompleteRequest) -> CompleteResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                log.debug("Attempting completion with provider: %s", provider.name)
                return await provider.complete(request)
            except Exception as e:
                log.warning("Provider %s failed: %s — trying next", provider.name, e)
                last_error = e

        raise RuntimeError(f"All providers failed. Last error: {last_error}") from last_error

    async def stream(self, request: CompleteRequest) -> AsyncIterator[StreamChunk]:
        # Streaming fallback: try providers until one succeeds on first chunk
        for provider in self._providers:
            try:
                async for chunk in provider.stream(request):
                    yield chunk
                return
            except Exception as e:
                log.warning("Streaming provider %s failed: %s — trying next", provider.name, e)

        raise RuntimeError("All streaming providers failed")

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            if not provider.supports(ModelCapability.embeddings):
                continue
            try:
                return await provider.embed(request)
            except Exception as e:
                log.warning("Embed provider %s failed: %s", provider.name, e)
                last_error = e

        raise RuntimeError(f"All embedding providers failed. Last error: {last_error}") from last_error
