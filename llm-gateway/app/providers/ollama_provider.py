"""
Ollama provider — direct HTTP client for local/remote model serving.
Health-aware: probes Ollama with a fast 3s check before routing requests.
When unreachable, fires Wake-on-LAN in the background and raises immediately.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
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
    Includes health gating: a fast probe prevents 120s hangs when offline.
    """

    def __init__(self, base_url: str = settings.ollama_base_url, default_model: str = "llama3.2"):
        self._base_url = base_url
        self._default_model = default_model
        # Health state
        self._healthy: bool = True  # optimistic on startup
        self._last_health_check: float = 0.0
        self._wol_sent_at: float = 0.0
        self._health_lock = asyncio.Lock()

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

    @property
    def healthy(self) -> bool:
        """Current cached health status."""
        return self._healthy

    async def _ensure_healthy(self) -> None:
        """
        Fast health gate: check if Ollama is reachable before sending real requests.
        Caches result for ollama_health_check_interval seconds.
        On failure, fires WoL in the background and raises RuntimeError.
        """
        now = time.monotonic()
        if self._healthy and (now - self._last_health_check) < settings.ollama_health_check_interval:
            return  # recently checked and healthy — 0ms overhead

        async with self._health_lock:
            # Re-check after acquiring lock (another coroutine may have updated)
            now = time.monotonic()
            if self._healthy and (now - self._last_health_check) < settings.ollama_health_check_interval:
                return

            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=settings.ollama_health_check_timeout,
                ) as client:
                    r = await client.get("/api/tags")
                    r.raise_for_status()
                self._healthy = True
                self._last_health_check = now
                return
            except Exception as e:
                self._healthy = False
                self._last_health_check = now
                log.warning("Ollama unreachable at %s: %s", self._base_url, e)

                # Fire WoL if configured and not recently sent
                if settings.wol_mac_address and (now - self._wol_sent_at) > settings.wol_boot_wait_seconds:
                    self._wol_sent_at = now
                    from app.wol import send_wol
                    asyncio.create_task(send_wol(settings.wol_mac_address, settings.wol_broadcast_ip))
                    log.info("WoL packet sent to %s (broadcast %s)", settings.wol_mac_address, settings.wol_broadcast_ip)

                raise RuntimeError(f"Ollama unreachable at {self._base_url}") from e

    async def complete(self, request: CompleteRequest) -> CompleteResponse:
        await self._ensure_healthy()
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        async with httpx.AsyncClient(base_url=self._base_url, timeout=settings.ollama_request_timeout) as client:
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
        await self._ensure_healthy()
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        async with httpx.AsyncClient(base_url=self._base_url, timeout=settings.ollama_request_timeout) as client:
            async with client.stream("POST", "/api/chat", json={
                "model": request.model or self._default_model,
                "messages": messages,
                "stream": True,
                "options": {"temperature": request.temperature},
            }) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    done = chunk.get("done", False)

                    input_tokens = None
                    output_tokens = None
                    if done:
                        input_tokens = chunk.get("prompt_eval_count")
                        output_tokens = chunk.get("eval_count")

                    yield StreamChunk(
                        delta=content,
                        finish_reason="stop" if done else None,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        await self._ensure_healthy()
        async with httpx.AsyncClient(base_url=self._base_url, timeout=settings.ollama_request_timeout) as client:
            resp = await client.post("/api/embed", json={
                "model": request.model or self._default_model,
                "input": request.texts,
            })
            resp.raise_for_status()
            data = resp.json()

        return EmbedResponse(
            embeddings=data["embeddings"],
            model=request.model,
            input_tokens=0,  # Ollama doesn't report token counts for embeddings
        )
