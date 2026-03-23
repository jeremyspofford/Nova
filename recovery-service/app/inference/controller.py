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
    "sglang": {"profile": "local-sglang", "service": "nova-sglang", "container": "nova-sglang"},
}

# Backends that support model switching (single-model servers)
SWITCHABLE_BACKENDS = {"vllm", "sglang"}

# Env var name per backend for the model
MODEL_ENV_VARS = {"vllm": "VLLM_MODEL", "sglang": "SGLANG_MODEL"}

# Track active switch progress
_switch_progress: Optional[dict] = None

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
    result = {"backend": backend, "state": state, "container_status": container_status}
    # Fetch the active model from the backend's OpenAI-compatible endpoint
    if state == "ready" and container_status and container_status.get("running"):
        result["active_model"] = await _probe_active_model(backend)
    progress = get_switch_progress()
    if progress:
        result["switch_progress"] = progress
    if state == "error":
        error = await read_config("inference.error", "")
        if error:
            result["error"] = error
    return result


async def _probe_active_model(backend: str) -> str | None:
    """Query the backend's /v1/models endpoint for the active model name."""
    import httpx
    urls = {
        "vllm": "http://nova-vllm:8000/v1/models",
        "sglang": "http://nova-sglang:8000/v1/models",
        "ollama": "http://ollama:11434/api/tags",
    }
    url = urls.get(backend)
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(url)
            data = resp.json()
            if backend == "ollama":
                models = data.get("models", [])
                return models[0]["name"] if models else None
            else:
                items = data.get("data", [])
                return items[0]["id"] if items else None
    except Exception:
        return None


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
    """Fire-and-forget backend start. Returns immediately; poll status for progress."""
    if backend not in BACKENDS:
        raise ValueError(f"Unknown backend: {backend}. Valid: {list(BACKENDS.keys())}")

    current_state = await read_config("inference.state", "stopped")
    current_backend = await read_config("inference.backend", "none")

    # Idempotent: if this backend is already starting, just return success
    if current_state in ("starting", "switching") and current_backend == backend:
        return {"status": "already_starting", "backend": backend}
    if current_state in ("starting", "switching"):
        raise ValueError(f"Cannot start {backend}: already {current_state} {current_backend}")

    # Capture old backend BEFORE overwriting Redis — _do_start_backend needs
    # this to know what to stop.
    old_backend = current_backend if current_backend != backend else None

    await write_config_state("inference.state", "starting")
    await write_config_state("inference.backend", backend)
    asyncio.create_task(_do_start_backend(backend, old_backend=old_backend))
    return {"status": "accepted", "backend": backend}


async def _do_start_backend(backend: str, *, old_backend: str | None = None) -> None:
    """Background task: start backend container and wait for healthy."""
    global _switch_progress
    info = BACKENDS[backend]

    try:
        # Stop old backend if switching (e.g. ollama → vllm)
        if old_backend and old_backend in BACKENDS and old_backend != "none":
            _switch_progress = {"step": "stopping", "detail": f"Stopping {old_backend}..."}
            await _stop_backend(old_backend)

        _switch_progress = {"step": "starting", "detail": f"Starting {backend}..."}
        result = await start_profiled_service(info["profile"], info["service"])
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Failed to start container"))

        # vLLM/SGLang need longer — first start downloads model from HuggingFace
        timeout = 600 if backend in SWITCHABLE_BACKENDS else 120
        _switch_progress = {"step": "loading", "detail": f"Waiting for {backend} to be ready..."}
        await _wait_for_healthy(info["container"], backend, timeout=timeout)

        await write_config_state("inference.state", "ready")
        await write_config_state("inference.error", "")
        _switch_progress = {"step": "ready", "detail": f"{backend} is ready"}
        logger.info("Backend %s started successfully", backend)
        _start_health_monitor(backend)
    except Exception as e:
        await write_config_state("inference.state", "error")
        await write_config_state("inference.error", str(e))
        _switch_progress = {"step": "error", "detail": str(e)}
        logger.error("Failed to start backend %s: %s", backend, e)
    finally:
        await asyncio.sleep(60)
        _switch_progress = None


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


async def switch_model(backend: str, model: str) -> dict:
    """Switch the model on a single-model backend (vLLM, SGLang).
    Runs drain protocol, updates .env, restarts container.
    """
    if backend not in SWITCHABLE_BACKENDS:
        raise ValueError(f"Backend '{backend}' does not support model switching. "
                         f"Switchable backends: {sorted(SWITCHABLE_BACKENDS)}")
    if backend not in BACKENDS:
        raise ValueError(f"Unknown backend: {backend}")

    current_state = await read_config("inference.state", "stopped")
    current_backend = await read_config("inference.backend", "none")

    if current_backend != backend:
        raise ValueError(f"Cannot switch model: backend '{backend}' is not active "
                         f"(current: '{current_backend}')")
    if current_state == "switching":
        raise ValueError("A model switch is already in progress")

    asyncio.create_task(_do_switch_model(backend, model))
    return {"status": "accepted", "backend": backend, "model": model}


async def _do_switch_model(backend: str, model: str) -> None:
    """Background task: drain, update env, restart container."""
    global _switch_progress
    info = BACKENDS[backend]
    env_var = MODEL_ENV_VARS[backend]

    try:
        _switch_progress = {"step": "draining", "detail": "Waiting for in-flight requests..."}
        await write_config_state("inference.state", "switching")

        await _drain_requests(timeout=15)

        _switch_progress = {"step": "stopping", "detail": f"Stopping {backend}..."}
        _stop_health_monitor()
        await stop_profiled_service(info["profile"], info["service"])

        _switch_progress = {"step": "updating", "detail": f"Setting model to {model}..."}
        from app.env_manager import patch_env
        patch_env({env_var: model})

        _switch_progress = {"step": "starting", "detail": f"Starting {backend} with {model}..."}
        await start_profiled_service(info["profile"], info["service"])

        _switch_progress = {"step": "loading", "detail": "Loading model into GPU..."}
        await _wait_for_healthy(info["container"], backend, timeout=180)

        await write_config_state("inference.state", "ready")
        _switch_progress = {"step": "ready", "detail": f"Now serving {model}"}
        logger.info("Model switch complete: %s → %s", backend, model)

        _start_health_monitor(backend)
    except Exception as e:
        await write_config_state("inference.state", "error")
        _switch_progress = {"step": "error", "detail": str(e)}
        logger.error("Model switch failed for %s: %s", backend, e)
    finally:
        await asyncio.sleep(60)
        _switch_progress = None


def get_switch_progress() -> Optional[dict]:
    """Return current switch progress, or None if no switch in progress."""
    return _switch_progress


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

    health_endpoints = {
        "vllm": f"http://{container_name}:8000/v1/models",
        "sglang": f"http://{container_name}:8000/v1/models",
        "ollama": "http://ollama:11434/api/tags",
    }
    endpoint = health_endpoints.get(backend)
    if not endpoint:
        return  # custom/none backends don't need health checks

    restart_count = 0
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        status = check_container_status(container_name)
        container_state = status.get("status", "") if isinstance(status, dict) else ""

        # Detect crash-looping: container is restarting or exited
        if container_state in ("restarting", "exited", "dead"):
            restart_count += 1
            if restart_count >= 3:
                raise RuntimeError(
                    f"Container {container_name} is crash-looping (state: {container_state}). "
                    f"Check logs with: docker compose logs {container_name}"
                )

        if container_state == "running":
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(endpoint)
                    if r.status_code == 200:
                        return
            except Exception:
                pass

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
    import httpx

    health_urls = {
        "ollama": "http://ollama:11434/api/tags",
        "vllm": "http://nova-vllm:8000/health",
        "sglang": "http://nova-sglang:8000/health",
    }

    while True:
        await asyncio.sleep(_health_backoff)
        try:
            info = BACKENDS.get(backend, {})
            container_name = info.get("container", "")
            cs = check_container_status(container_name) if container_name else {}
            is_running = isinstance(cs, dict) and cs.get("status") == "running"

            # Container running isn't enough — a crash-looping container
            # briefly shows "running" before the process exits.  Probe the
            # actual HTTP health endpoint to confirm.
            is_healthy = False
            if is_running:
                url = health_urls.get(backend)
                if url:
                    try:
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            r = await client.get(url)
                            is_healthy = r.status_code == 200
                    except Exception:
                        is_healthy = False
                else:
                    # Unknown backend type with no URL — trust container status
                    is_healthy = True

            if not is_healthy:
                _health_failures += 1
                reason = "not running" if not is_running else "health endpoint unreachable"
                logger.warning("Backend %s health check failed (%d/3): %s",
                               backend, _health_failures, reason)
                if _health_failures >= 3:
                    logger.error("Backend %s: 3 consecutive failures, attempting restart", backend)
                    try:
                        await write_config_state("inference.state", "starting")
                        await start_profiled_service(info["profile"], info["service"])
                        await _wait_for_healthy(container_name, backend, timeout=120)
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
