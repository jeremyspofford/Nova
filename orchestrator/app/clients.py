"""
HTTP clients for downstream services.
Uses httpx with connection pooling; clients are module-level singletons.
"""
from __future__ import annotations

import httpx

from app.config import settings

_memory_client: httpx.AsyncClient | None = None
_llm_client: httpx.AsyncClient | None = None
_orchestrator_client: httpx.AsyncClient | None = None


def get_memory_client() -> httpx.AsyncClient:
    global _memory_client
    if _memory_client is None or _memory_client.is_closed:
        _memory_client = httpx.AsyncClient(
            base_url=settings.memory_service_url,
            timeout=30.0,
            limits=httpx.Limits(max_connections=20),
        )
    return _memory_client


def get_llm_client() -> httpx.AsyncClient:
    global _llm_client
    if _llm_client is None or _llm_client.is_closed:
        _llm_client = httpx.AsyncClient(
            base_url=settings.llm_gateway_url,
            timeout=120.0,
            limits=httpx.Limits(max_connections=20),
        )
    return _llm_client


def get_orchestrator_client() -> httpx.AsyncClient:
    """Self-referencing client for cross-agent task dispatch."""
    global _orchestrator_client
    if _orchestrator_client is None or _orchestrator_client.is_closed:
        # Loopback to our own port — works inside Docker on the same container
        _orchestrator_client = httpx.AsyncClient(
            base_url="http://localhost:8000",
            timeout=120.0,
            limits=httpx.Limits(max_connections=10),
        )
    return _orchestrator_client


async def close_clients() -> None:
    if _memory_client and not _memory_client.is_closed:
        await _memory_client.aclose()
    if _llm_client and not _llm_client.is_closed:
        await _llm_client.aclose()
    if _orchestrator_client and not _orchestrator_client.is_closed:
        await _orchestrator_client.aclose()
