"""Backend lifecycle controller — start/stop/switch inference containers."""
import asyncio
import logging
from typing import Optional

from app.compose_client import start_profiled_service, stop_profiled_service
from app.docker_client import check_container_status
from app.redis_client import read_config, write_config_state

logger = logging.getLogger(__name__)

BACKENDS = {
    "ollama": {"profile": "local-ollama", "service": "ollama", "container": "nova-ollama"},
    "vllm": {"profile": "local-vllm", "service": "nova-vllm", "container": "nova-vllm"},
}

_health_task: Optional[asyncio.Task] = None
_health_failures: int = 0
_health_backoff: float = 30.0


async def get_backend_status() -> dict:
    backend = await read_config("inference.backend", "ollama")
    state = await read_config("inference.state", "stopped")
    container_status = None
    if backend in BACKENDS:
        info = BACKENDS[backend]
        container_status = check_container_status(info["container"])
    return {"backend": backend, "state": state, "container_status": container_status}


async def list_backends() -> list[dict]:
    results = []
    for name, info in BACKENDS.items():
        status = check_container_status(info["container"])
        results.append({
            "name": name,
            "profile": info["profile"],
            "service": info["service"],
            "container_running": isinstance(status, dict) and status.get("status") == "running",
        })
    return results


async def start_backend(backend: str) -> dict:
    if backend not in BACKENDS:
        raise ValueError(f"Unknown backend: {backend}. Valid: {list(BACKENDS.keys())}")
    info = BACKENDS[backend]
    current = await read_config("inference.backend", "")
    if current and current != backend and current != "none":
        await _stop_backend(current)

    await write_config_state("inference.state", "starting")
    await write_config_state("inference.backend", backend)
    try:
        await start_profiled_service(info["profile"], info["service"])
        await _wait_for_healthy(info["container"], backend, timeout=120)
        await write_config_state("inference.state", "ready")
        logger.info("Backend %s started successfully", backend)
    except Exception as e:
        await write_config_state("inference.state", "error")
        logger.error("Failed to start backend %s: %s", backend, e)
        raise
    _start_health_monitor(backend)
    return await get_backend_status()


async def stop_backend(backend: Optional[str] = None) -> dict:
    if backend is None:
        backend = await read_config("inference.backend", "")
    if not backend or backend == "none":
        return {"backend": "none", "state": "stopped"}
    await _stop_backend(backend)
    await write_config_state("inference.backend", "none")
    await write_config_state("inference.state", "stopped")
    return await get_backend_status()


async def switch_backend(new_backend: str) -> dict:
    return await start_backend(new_backend)


async def _stop_backend(backend: str) -> None:
    if backend not in BACKENDS:
        return
    info = BACKENDS[backend]
    await write_config_state("inference.state", "draining")
    logger.info("Draining backend %s...", backend)
    await _drain_requests(timeout=15)
    _stop_health_monitor()
    try:
        await stop_profiled_service(info["profile"], info["service"])
    except Exception as e:
        logger.warning("Error stopping %s: %s", backend, e)


async def _drain_requests(timeout: float = 15.0) -> None:
    import httpx
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get("http://llm-gateway:8001/health/inflight")
                if r.status_code == 200:
                    count = r.json().get("local_inflight", 0)
                    if count == 0:
                        logger.info("Drain complete — no in-flight requests")
                        return
                    logger.info("Draining: %d requests in-flight", count)
        except Exception:
            pass
        await asyncio.sleep(1)
    logger.warning("Drain timeout after %.0fs, proceeding with shutdown", timeout)


async def _wait_for_healthy(container_name: str, backend: str, timeout: float = 120.0) -> None:
    import httpx
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        status = check_container_status(container_name)
        if isinstance(status, dict) and status.get("status") == "running":
            if backend == "vllm":
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        r = await client.get("http://nova-vllm:8000/health")
                        if r.status_code == 200:
                            return
                except Exception:
                    pass
            elif backend == "ollama":
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        r = await client.get("http://ollama:11434/api/tags")
                        if r.status_code == 200:
                            return
                except Exception:
                    pass
            else:
                return
        await asyncio.sleep(5)
    raise TimeoutError(f"Container {container_name} did not become healthy within {timeout}s")


def _start_health_monitor(backend: str) -> None:
    global _health_task, _health_failures, _health_backoff
    _stop_health_monitor()
    _health_failures = 0
    _health_backoff = 30.0
    _health_task = asyncio.create_task(_health_monitor_loop(backend))


def _stop_health_monitor() -> None:
    global _health_task
    if _health_task and not _health_task.done():
        _health_task.cancel()
        _health_task = None


async def _health_monitor_loop(backend: str) -> None:
    global _health_failures, _health_backoff
    while True:
        await asyncio.sleep(_health_backoff)
        try:
            info = BACKENDS.get(backend, {})
            container_name = info.get("container", "")
            cs = check_container_status(container_name) if container_name else {}
            is_running = isinstance(cs, dict) and cs.get("status") == "running"
            if not is_running:
                _health_failures += 1
                logger.warning("Backend %s health check failed (%d/3)", backend, _health_failures)
                if _health_failures >= 3:
                    logger.error("Backend %s: 3 consecutive failures, attempting restart", backend)
                    try:
                        await start_profiled_service(info["profile"], info["service"])
                        _health_failures = 0
                        _health_backoff = 30.0
                        await write_config_state("inference.state", "ready")
                    except Exception as e:
                        logger.error("Failed to restart %s: %s", backend, e)
                        _health_backoff = min(_health_backoff * 2, 120.0)
                        await write_config_state("inference.state", "error")
            else:
                _health_failures = 0
                _health_backoff = 30.0
        except asyncio.CancelledError:
            logger.debug("Health monitor for %s cancelled", backend)
            raise
        except Exception as e:
            logger.error("Health monitor error: %s", e)
