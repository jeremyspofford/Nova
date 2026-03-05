"""Docker API helper for service management."""

import logging

import docker
from docker.errors import DockerException

logger = logging.getLogger("nova.recovery.docker")

# Nova services we care about (container name prefix: nova-)
NOVA_SERVICES = [
    "postgres",
    "redis",
    "orchestrator",
    "llm-gateway",
    "memory-service",
    "chat-api",
    "dashboard",
]


def _client() -> docker.DockerClient:
    return docker.DockerClient.from_env()


def list_service_status() -> list[dict]:
    """Return status for all Nova containers."""
    results = []
    try:
        client = _client()
        containers = client.containers.list(all=True)
        # Build lookup by container name
        by_name: dict[str, docker.models.containers.Container] = {}
        for c in containers:
            by_name[c.name] = c

        for svc in NOVA_SERVICES:
            # Match containers with common naming patterns
            container = None
            for name, c in by_name.items():
                if svc in name and ("nova" in name or svc == name):
                    container = c
                    break

            if container:
                results.append({
                    "service": svc,
                    "container_name": container.name,
                    "status": container.status,  # running, exited, restarting, etc.
                    "health": _get_health(container),
                })
            else:
                results.append({
                    "service": svc,
                    "container_name": None,
                    "status": "not_found",
                    "health": "unknown",
                })
    except DockerException as e:
        logger.warning("Docker API unavailable: %s", e)
        for svc in NOVA_SERVICES:
            results.append({
                "service": svc,
                "container_name": None,
                "status": "unknown",
                "health": "unknown",
            })
    return results


def _get_health(container) -> str:
    """Extract health status from container inspect data."""
    try:
        state = container.attrs.get("State", {})
        health = state.get("Health", {})
        return health.get("Status", "none")
    except Exception:
        return "unknown"


def restart_service(service_name: str) -> dict:
    """Restart a Nova service container."""
    try:
        client = _client()
        containers = client.containers.list(all=True)
        for c in containers:
            if service_name in c.name and ("nova" in c.name or service_name == c.name):
                c.restart(timeout=30)
                return {"service": service_name, "action": "restarted", "ok": True}
        return {"service": service_name, "action": "not_found", "ok": False, "error": f"Container for '{service_name}' not found"}
    except DockerException as e:
        return {"service": service_name, "action": "error", "ok": False, "error": str(e)}


def restart_all_services() -> list[dict]:
    """Restart all Nova services (except postgres, redis, recovery)."""
    results = []
    for svc in NOVA_SERVICES:
        if svc in ("postgres", "redis"):
            continue
        results.append(restart_service(svc))
    return results
