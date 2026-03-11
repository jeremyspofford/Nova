"""HTTP client pool for inter-service communication."""
from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)

_orchestrator: httpx.AsyncClient | None = None
_llm: httpx.AsyncClient | None = None
_memory: httpx.AsyncClient | None = None


def _make_client(base_url: str, timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        limits=httpx.Limits(max_connections=10),
    )


async def init_clients() -> None:
    """Create httpx client pool. Call once at startup."""
    global _orchestrator, _llm, _memory
    _orchestrator = _make_client(settings.orchestrator_url, timeout=60.0)
    _llm = httpx.AsyncClient(
        base_url=settings.llm_gateway_url,
        timeout=120.0,
        limits=httpx.Limits(max_connections=10),
        headers={"X-Caller": "cortex"},
    )
    _memory = _make_client(settings.memory_service_url)
    log.info("HTTP clients ready")


async def close_clients() -> None:
    """Close all httpx clients. Call at shutdown."""
    for client in (_orchestrator, _llm, _memory):
        if client:
            await client.aclose()
    log.info("HTTP clients closed")


def get_orchestrator() -> httpx.AsyncClient:
    if _orchestrator is None:
        raise RuntimeError("Orchestrator client not initialized")
    return _orchestrator


def get_llm() -> httpx.AsyncClient:
    if _llm is None:
        raise RuntimeError("LLM client not initialized")
    return _llm


def get_memory() -> httpx.AsyncClient:
    if _memory is None:
        raise RuntimeError("Memory client not initialized")
    return _memory
