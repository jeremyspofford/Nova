"""HTTP client for orchestrator API calls."""
import httpx
from app.config import settings

_client: httpx.AsyncClient | None = None


async def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=settings.orchestrator_url,
        timeout=30.0,
        headers={"X-Admin-Secret": settings.admin_secret},
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
