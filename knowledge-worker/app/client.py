"""HTTP clients for orchestrator and LLM gateway API calls.

The ``X-Admin-Secret`` header on the orchestrator client is resolved per-request
(not baked in at client init) so that runtime secret rotation via the dashboard
propagates to this worker within the resolver's 30s cache window.
"""
import httpx

from nova_worker_common.admin_secret import AdminSecretResolver
from nova_worker_common.http_client import create_client

from app.config import settings

_orchestrator_client = None
_llm_client = None
_resolver: AdminSecretResolver | None = None


class _AdminSecretAuth(httpx.Auth):
    """httpx auth hook that injects the current admin secret on every request."""

    requires_request_body = False
    requires_response_body = False

    def __init__(self, resolver: AdminSecretResolver):
        self._resolver = resolver

    async def async_auth_flow(self, request):
        request.headers["X-Admin-Secret"] = await self._resolver.get()
        yield request


async def init_clients() -> None:
    global _orchestrator_client, _llm_client, _resolver
    _resolver = AdminSecretResolver(
        redis_url=settings.redis_url,
        fallback=settings.admin_secret,
    )
    _orchestrator_client = create_client(
        base_url=settings.orchestrator_url,
        service_name="KnowledgeWorker",
    )
    _orchestrator_client.auth = _AdminSecretAuth(_resolver)
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
    global _orchestrator_client, _llm_client, _resolver
    if _orchestrator_client:
        await _orchestrator_client.aclose()
        _orchestrator_client = None
    if _llm_client:
        await _llm_client.aclose()
        _llm_client = None
    if _resolver:
        await _resolver.close()
        _resolver = None
