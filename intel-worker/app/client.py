"""HTTP client for orchestrator API calls — delegates to nova-worker-common.

The ``X-Admin-Secret`` header is resolved per-request (not baked in at client
init) so that runtime secret rotation via the dashboard propagates to this
worker within the resolver's 30s cache window.
"""
import httpx

from nova_worker_common.admin_secret import AdminSecretResolver
from nova_worker_common.http_client import create_client

from app.config import settings

_client: httpx.AsyncClient | None = None
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


async def init_client() -> None:
    global _client, _resolver
    _resolver = AdminSecretResolver(
        redis_url=settings.redis_url,
        fallback=settings.admin_secret,
    )
    _client = create_client(
        base_url=settings.orchestrator_url,
        service_name="Intel-Worker",
    )
    _client.auth = _AdminSecretAuth(_resolver)


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialized")
    return _client


async def close_client() -> None:
    global _client, _resolver
    if _client:
        await _client.aclose()
        _client = None
    if _resolver:
        await _resolver.close()
        _resolver = None
