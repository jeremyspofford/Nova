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


async def get_task_status(task_id: str) -> dict | None:
    """Poll orchestrator for task status. Returns task dict or None on error."""
    try:
        orch = get_orchestrator()
        resp = await orch.get(
            f"/api/v1/pipeline/tasks/{task_id}",
            headers={"Authorization": f"Bearer {settings.cortex_api_key}"},
        )
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            log.warning("Task %s not found in orchestrator", task_id)
            return None
        else:
            log.warning("Failed to get task %s: HTTP %d", task_id, resp.status_code)
            return None
    except Exception as e:
        log.warning("Error polling task %s: %s", task_id, e)
        return None
