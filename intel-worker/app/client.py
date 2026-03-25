"""HTTP client for orchestrator API calls — delegates to nova-worker-common."""
import httpx

from nova_worker_common.http_client import create_client

from app.config import settings

_client: httpx.AsyncClient | None = None


async def init_client() -> None:
    global _client
    _client = create_client(
        base_url=settings.orchestrator_url,
        headers={"X-Admin-Secret": settings.admin_secret},
        service_name="Intel-Worker",
    )


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialized")
    return _client


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None
