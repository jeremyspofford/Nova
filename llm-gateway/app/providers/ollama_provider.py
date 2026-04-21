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


def _tool_to_ollama(tool) -> dict:
    """Convert a ToolDefinition to Ollama's /api/chat tools format
    (OpenAI-compatible function wrapper)."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_ollama_tool_calls(raw_calls: list) -> list[ToolCall]:
    """Convert Ollama tool_calls into Nova's ToolCall contract."""
    import uuid
    out: list[ToolCall] = []
    for tc in raw_calls or []:
        fn = tc.get("function", {}) or {}
        args = fn.get("arguments", {})
        # Ollama sometimes returns a dict, sometimes a JSON-encoded string
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        out.append(ToolCall(
            id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            name=fn.get("name", ""),
            arguments=args if isinstance(args, dict) else {},
        ))
    return out


def _serialize_messages_for_ollama(messages) -> list[dict]:
    """Serialize Nova messages for Ollama /api/chat, preserving tool turns.

    Nova allows content to be str | list[ContentBlock]. Ollama expects str
    content on user/assistant/system, and role='tool' with stringified content
    for tool results. Tool-call emission (role='assistant' with tool_calls)
    must round-trip so multi-round tool loops keep context."""
    out: list[dict] = []
    for m in messages:
        raw_content = m.content
        # Flatten ContentBlock list to plain string for Ollama
        if isinstance(raw_content, list):
            parts: list[str] = []
            for b in raw_content:
                if hasattr(b, "text") and getattr(b, "text", None):
                    parts.append(b.text)
                elif isinstance(b, dict) and b.get("type") == "text":
                    parts.append(b.get("text", ""))
            content = "\n".join(p for p in parts if p)
        else:
            content = raw_content or ""
        msg_dict: dict = {"role": m.role, "content": content}
        if getattr(m, "tool_calls", None):
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in m.tool_calls
            ]
        if getattr(m, "tool_call_id", None):
            msg_dict["tool_call_id"] = m.tool_call_id
        out.append(msg_dict)
    return out


class OllamaProvider(ModelProvider):
    """
    Direct Ollama integration — OpenAI-compatible API at /api/chat.
    Includes health gating: a fast probe prevents 120s hangs when offline.
    """

    def __init__(self, base_url: str = settings.ollama_base_url, default_model: str = "llama3.2"):
        self._base_url = base_url
        self._default_model = default_model
        # Health state
        self._healthy: bool = False  # conservative — verify before reporting online
        self._last_health_check: float = 0.0
        self._wol_sent_at: float = 0.0
        self._health_lock = asyncio.Lock()

    async def _get_base_url(self) -> str:
        """Get the current Ollama base URL (runtime-configurable via dashboard)."""
        from app.registry import get_ollama_base_url
        url = await get_ollama_base_url()
        if url != self._base_url:
            log.info("Ollama base URL changed: %s -> %s", self._base_url, url)
            self._base_url = url
            self._healthy = True  # reset health for new URL
            self._last_health_check = 0.0
        return url

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def capabilities(self) -> set[ModelCapability]:
        return {
            ModelCapability.chat,
            ModelCapability.streaming,
            ModelCapability.embeddings,
            ModelCapability.function_calling,
        }

    @property
    def is_local(self) -> bool:
        return True

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
        base_url = await self._get_base_url()
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
                    base_url=base_url,
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
                log.warning("Ollama unreachable at %s: %s", base_url, e)

                # Fire WoL if configured and not recently sent
                from app.registry import get_wol_mac, get_wol_broadcast
                wol_mac = await get_wol_mac()
                if wol_mac and (now - self._wol_sent_at) > settings.wol_boot_wait_seconds:
                    self._wol_sent_at = now
                    wol_broadcast = await get_wol_broadcast()
                    from app.wol import send_wol
                    asyncio.create_task(send_wol(wol_mac, wol_broadcast))
                    log.info("WoL packet sent to %s (broadcast %s)", wol_mac, wol_broadcast)

                raise RuntimeError(f"Ollama unreachable at {base_url}") from e

    async def complete(self, request: CompleteRequest) -> CompleteResponse:
        await self._ensure_healthy()
        messages = _serialize_messages_for_ollama(request.messages)
        body = {
            "model": request.model or self._default_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        if request.tools:
            body["tools"] = [_tool_to_ollama(t) for t in request.tools]

        async with httpx.AsyncClient(base_url=self._base_url, timeout=settings.ollama_request_timeout) as client:
            resp = await client.post("/api/chat", json=body)
            resp.raise_for_status()
            data = resp.json()

        msg = data.get("message", {})
        tool_calls = _parse_ollama_tool_calls(msg.get("tool_calls", []))
        finish_reason = "tool_calls" if tool_calls else "stop"

        return CompleteResponse(
            content=msg.get("content", "") or "",
            model=data.get("model", request.model),
            tool_calls=tool_calls,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            cost_usd=None,  # local inference is free
            finish_reason=finish_reason,
        )

    async def stream(self, request: CompleteRequest) -> AsyncIterator[StreamChunk]:
        await self._ensure_healthy()
        messages = _serialize_messages_for_ollama(request.messages)
        body = {
            "model": request.model or self._default_model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": request.temperature},
        }
        if request.tools:
            body["tools"] = [_tool_to_ollama(t) for t in request.tools]

        async with httpx.AsyncClient(base_url=self._base_url, timeout=settings.ollama_request_timeout) as client:
            async with client.stream("POST", "/api/chat", json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    msg = chunk.get("message", {}) or {}
                    content = msg.get("content", "") or ""
                    done = chunk.get("done", False)
                    # Ollama emits tool_calls on the final chunk when the model
                    # decides to invoke tools — pass them through verbatim.
                    tool_calls = _parse_ollama_tool_calls(msg.get("tool_calls", []))

                    input_tokens = None
                    output_tokens = None
                    finish_reason = None
                    if done:
                        input_tokens = chunk.get("prompt_eval_count")
                        output_tokens = chunk.get("eval_count")
                        finish_reason = "tool_calls" if tool_calls else "stop"

                    yield StreamChunk(
                        delta=content,
                        finish_reason=finish_reason,
                        tool_calls=tool_calls,
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
