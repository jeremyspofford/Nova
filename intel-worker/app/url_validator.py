"""SSRF prevention — validate feed URLs before fetching."""
import ipaddress
from urllib.parse import urlparse

BLOCKED_HOSTS = {
    "localhost", "0.0.0.0", "redis", "postgres", "orchestrator", "memory-service",
    "llm-gateway", "cortex", "recovery", "chat-api", "chat-bridge",
    "dashboard", "intel-worker", "metadata.google.internal",
    "host.docker.internal",
}


def validate_url(url: str) -> str | None:
    """Return error message if URL is unsafe, None if OK."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Scheme '{parsed.scheme}' not allowed"
    hostname = parsed.hostname or ""
    if hostname.lower() in BLOCKED_HOSTS:
        return f"Host '{hostname}' is blocked"
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return f"Private/loopback/link-local IP '{ip}' not allowed"
    except ValueError:
        pass
    return None
