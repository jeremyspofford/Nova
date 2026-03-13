"""Wrapper provider that delegates to whichever local backend is active."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Optional, Set

from nova_contracts.llm import (
    CompleteRequest, CompleteResponse, StreamChunk,
    EmbedRequest, EmbedResponse, ModelCapability,
)
from .base import ModelProvider
from .ollama_provider import OllamaProvider
from .vllm_provider import VLLMProvider

logger = logging.getLogger(__name__)

DEFAULT_URLS = {
    "ollama": "http://ollama:11434",
    "vllm": "http://nova-vllm:8000",
    "sglang": "http://nova-sglang:8000",
}

READY_STATES = {"ready"}


class LocalInferenceProvider(ModelProvider):
    """
    Wrapper that reads active backend config from Redis and delegates.

    Config keys (in Redis nova:config:*):
    - inference.backend: "ollama" | "vllm" | "sglang" | "none"
    - inference.state: "ready" | "draining" | "starting" | "error"
    - inference.url: override URL (empty = default for backend)
    """

    def __init__(self):
        self._current_backend: Optional[str] = None
        self._current_url: str = ""
        self._delegate: Optional[ModelProvider] = None
        self._local_models: Set[str] = set()
        self._state: str = "ready"
        self._config_cache_time = 0.0
        self._config_ttl = 5.0
        self._refresh_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "local"

    @property
    def capabilities(self) -> set[ModelCapability]:
        if self._delegate:
            return self._delegate.capabilities
        return set()

    @property
    def is_available(self) -> bool:
        return (self._state in READY_STATES and
                self._delegate is not None and
                self._delegate.is_available)

    @property
    def is_local(self) -> bool:
        return True

    def is_local_model(self, model: str) -> bool:
        """Check if a model name belongs to the active local backend."""
        return model in self._local_models

    def update_local_models(self, models: Set[str]) -> None:
        """Update the set of known local models (called by discovery)."""
        self._local_models = models

    async def refresh_config(self) -> None:
        """Read backend config from Redis and swap delegate if changed."""
        now = time.monotonic()
        if (now - self._config_cache_time) < self._config_ttl:
            return

        async with self._refresh_lock:
            # Re-check after acquiring lock (another coroutine may have updated)
            now = time.monotonic()
            if (now - self._config_cache_time) < self._config_ttl:
                return

            self._config_cache_time = now

            try:
                from app.registry import _get_redis_config
                backend = await _get_redis_config("inference.backend", "ollama")
                state = await _get_redis_config("inference.state", "ready")
                url_override = await _get_redis_config("inference.url", "")
            except Exception:
                logger.debug("Failed to read inference config from Redis, keeping current state")
                return

            self._state = state

            if backend != self._current_backend or url_override != self._current_url:
                self._current_backend = backend
                self._current_url = url_override
                self._delegate = self._create_delegate(backend, url_override)
                self._local_models.clear()
                logger.info("Local inference backend changed to: %s", backend)

    def _create_delegate(self, backend: str, url_override: str) -> Optional[ModelProvider]:
        """Create a new provider instance for the given backend."""
        if backend == "none":
            return None

        url = url_override or DEFAULT_URLS.get(backend, "")
        if not url:
            logger.warning("No URL for backend %s", backend)
            return None

        if backend == "ollama":
            return OllamaProvider(base_url=url)
        elif backend == "vllm":
            return VLLMProvider(base_url=url)
        else:
            logger.warning("Unknown backend: %s", backend)
            return None

    async def complete(self, request: CompleteRequest) -> CompleteResponse:
        await self.refresh_config()
        self._assert_available()
        return await self._delegate.complete(request)

    async def stream(self, request: CompleteRequest) -> AsyncIterator[StreamChunk]:
        await self.refresh_config()
        self._assert_available()
        async for chunk in self._delegate.stream(request):
            yield chunk

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        await self.refresh_config()
        self._assert_available()
        return await self._delegate.embed(request)
