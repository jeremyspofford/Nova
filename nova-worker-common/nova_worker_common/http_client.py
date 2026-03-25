"""HTTP client factory for Nova worker services."""
import httpx


def create_client(
    base_url: str,
    headers: dict[str, str] | None = None,
    service_name: str = "Nova",
    timeout: float = 30.0,
) -> httpx.AsyncClient:
    """Create an httpx AsyncClient with Nova defaults.

    Caller is responsible for calling ``await client.aclose()`` on shutdown.
    """
    default_headers = {"User-Agent": f"{service_name}/1.0"}
    if headers:
        default_headers.update(headers)
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        headers=default_headers,
    )
