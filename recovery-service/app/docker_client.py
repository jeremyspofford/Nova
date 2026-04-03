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

# Optional services gated behind compose profiles
OPTIONAL_SERVICES = {
    "chat-bridge": "bridges",
    "website": "website",
    "ollama": "local-ollama",
    "nova-vllm": "local-vllm",
    "nova-sglang": "local-sglang",
    "cloudflared": "cloudflare-tunnel",
    "tailscale": "tailscale",
    "editor-vscode": "editor-vscode",
    "editor-neovim": "editor-neovim",
}


def _client() -> docker.DockerClient:
    return docker.DockerClient.from_env()


def _get_ports(container) -> list[int]:
    """Extract host ports from container port mappings."""
    try:
        ports_cfg = container.attrs.get("NetworkSettings", {}).get("Ports") or {}
        host_ports: list[int] = []
        for _container_port, bindings in ports_cfg.items():
            if bindings:
                for b in bindings:
                    port = b.get("HostPort")
                    if port:
                        host_ports.append(int(port))
        return sorted(set(host_ports))
    except Exception:
        return []


def _find_container(by_name: dict, svc: str):
    """Find a container matching a service name."""
    for name, c in by_name.items():
        if svc in name and ("nova" in name or svc == name):
            return c
    return None


def _container_to_status(svc: str, container, *, optional: bool = False, profile: str | None = None) -> dict:
    """Build a status dict from a container (or None)."""
    if container:
        return {
            "service": svc,
            "container_name": container.name,
            "status": container.status,
            "health": _get_health(container),
            "ports": _get_ports(container),
            "optional": optional,
            **({"profile": profile} if profile else {}),
        }
    return {
        "service": svc,
        "container_name": None,
        "status": "not_found",
        "health": "unknown",
        "ports": [],
        "optional": optional,
        **({"profile": profile} if profile else {}),
    }


def list_service_status() -> list[dict]:
    """Return status for all Nova containers."""
    results = []
    try:
        client = _client()
        containers = client.containers.list(all=True)
        by_name: dict[str, docker.models.containers.Container] = {}
        for c in containers:
            by_name[c.name] = c

        for svc in NOVA_SERVICES:
            container = _find_container(by_name, svc)
            results.append(_container_to_status(svc, container))
    except DockerException as e:
        logger.warning("Docker API unavailable: %s", e)
        for svc in NOVA_SERVICES:
            results.append({
                "service": svc,
                "container_name": None,
                "status": "unknown",
                "health": "unknown",
                "ports": [],
                "optional": False,
            })
    return results


def list_all_service_status() -> dict:
    """Return status for core services (+ recovery) and optional profile-gated services."""
    core = []
    optional = []
    try:
        client = _client()
        containers = client.containers.list(all=True)
        by_name: dict[str, docker.models.containers.Container] = {}
        for c in containers:
            by_name[c.name] = c

        # Core services
        for svc in NOVA_SERVICES:
            container = _find_container(by_name, svc)
            core.append(_container_to_status(svc, container))

        # Recovery itself
        recovery_container = _find_container(by_name, "recovery")
        core.append(_container_to_status("recovery", recovery_container))

        # Optional profile-gated services
        for svc, profile in OPTIONAL_SERVICES.items():
            container = _find_container(by_name, svc)
            optional.append(_container_to_status(svc, container, optional=True, profile=profile))

    except DockerException as e:
        logger.warning("Docker API unavailable: %s", e)
        for svc in NOVA_SERVICES:
            core.append({"service": svc, "container_name": None, "status": "unknown", "health": "unknown", "ports": [], "optional": False})
        core.append({"service": "recovery", "container_name": None, "status": "unknown", "health": "unknown", "ports": [], "optional": False})
        for svc, profile in OPTIONAL_SERVICES.items():
            optional.append({"service": svc, "container_name": None, "status": "unknown", "health": "unknown", "ports": [], "optional": True, "profile": profile})

    return {"core": core, "optional": optional}


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


def check_container_status(name: str) -> dict:
    """Check status of an arbitrary container by name substring."""
    try:
        client = _client()
        containers = client.containers.list(all=True)
        for c in containers:
            if name in c.name:
                return {
                    "name": name,
                    "container_name": c.name,
                    "status": c.status,
                    "health": _get_health(c),
                    "running": c.status == "running",
                }
        return {"name": name, "container_name": None, "status": "not_found", "health": "unknown", "running": False}
    except DockerException as e:
        logger.warning("Docker API error checking %s: %s", name, e)
        return {"name": name, "container_name": None, "status": "error", "health": "unknown", "running": False}


def get_container_logs(service_name: str, tail: int = 100) -> str:
    """Get recent logs from a Nova service container."""
    try:
        client = _client()
        containers = client.containers.list(all=True)
        for c in containers:
            if service_name in c.name and ("nova" in c.name or service_name == c.name):
                return c.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        return f"Container for '{service_name}' not found"
    except DockerException as e:
        return f"Docker error: {e}"


def restart_all_services() -> list[dict]:
    """Restart all Nova services (except postgres, redis, recovery)."""
    results = []
    for svc in NOVA_SERVICES:
        if svc in ("postgres", "redis"):
            continue
        results.append(restart_service(svc))
    return results
