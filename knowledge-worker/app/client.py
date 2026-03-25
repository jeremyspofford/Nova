"""HTTP clients for orchestrator and LLM gateway API calls."""
from nova_worker_common.http_client import create_client

from app.config import settings

_orchestrator_client = None
_llm_client = None


async def init_clients() -> None:
    global _orchestrator_client, _llm_client
    _orchestrator_client = create_client(
        base_url=settings.orchestrator_url,
        headers={"X-Admin-Secret": settings.admin_secret},
        service_name="KnowledgeWorker",
    )
    _llm_client = create_client(
        base_url=settings.llm_gateway_url,
        service_name="KnowledgeWorker",
    )


def get_orchestrator_client():
    if _orchestrator_client is None:
        raise RuntimeError("Orchestrator HTTP client not initialized")
    return _orchestrator_client


def get_llm_client():
    if _llm_client is None:
        raise RuntimeError("LLM HTTP client not initialized")
    return _llm_client


async def close_clients() -> None:
    global _orchestrator_client, _llm_client
    if _orchestrator_client:
        await _orchestrator_client.aclose()
        _orchestrator_client = None
    if _llm_client:
        await _llm_client.aclose()
        _llm_client = None
