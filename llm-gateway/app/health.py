import time

from fastapi import APIRouter
from app.config import settings

health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/live")
async def liveness():
    return {"status": "alive"}


@health_router.get("/ready")
async def readiness():
    checks = {}

    # Check Ollama connectivity (informational — not required for readiness)
    import httpx
    from app.registry import get_ollama_base_url
    ollama_url = await get_ollama_base_url()
    try:
        async with httpx.AsyncClient(base_url=ollama_url, timeout=3.0) as c:
            r = await c.get("/api/tags")
            checks["ollama"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        checks["ollama"] = f"unreachable: {e}"

    # Check Redis connectivity (required for rate limiting + caching)
    try:
        from app.rate_limiter import _get_redis
        r = await _get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Ollama is optional — only Redis is required for readiness
    redis_ok = checks.get("redis") == "ok"
    return {"status": "ready" if redis_ok else "degraded", "checks": checks}


@health_router.get("/providers")
async def provider_status():
    """Return availability and model count for each configured LLM provider."""
    from app.registry import get_provider_catalog
    return get_provider_catalog()


@health_router.post("/providers/{slug}/test")
async def test_provider(slug: str):
    """Send a minimal completion to a provider and report latency."""
    from app.registry import get_provider_catalog, get_provider
    from nova_contracts import CompleteRequest, Message

    catalog = get_provider_catalog()
    entry = next((p for p in catalog if p["slug"] == slug), None)
    if not entry:
        return {"ok": False, "latency_ms": 0, "error": f"Unknown provider: {slug}"}
    if not entry["available"]:
        return {"ok": False, "latency_ms": 0, "error": "Provider not configured"}

    model = entry["default_model"]
    try:
        provider = await get_provider(model)
        req = CompleteRequest(
            model=model,
            messages=[Message(role="user", content="Say hi")],
            max_tokens=5,
        )
        t0 = time.monotonic()
        await provider.complete(req)
        latency = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "latency_ms": latency}
    except Exception as e:
        return {"ok": False, "latency_ms": 0, "error": str(e)}


@health_router.get("/providers/ollama/status")
async def ollama_status():
    """Return detailed Ollama health info including WoL state."""
    from app.registry import get_ollama_provider, get_routing_strategy

    ollama = get_ollama_provider()
    strategy = await get_routing_strategy()

    from app.registry import get_ollama_base_url, get_wol_mac
    ollama_url = await get_ollama_base_url()
    wol_mac = await get_wol_mac()

    result = {
        "healthy": ollama.healthy,
        "base_url": ollama_url,
        "routing_strategy": strategy,
        "wol_configured": bool(wol_mac),
        "gpu_available": False,
    }

    # Detect GPU availability from Ollama's /api/ps (running models show GPU layers)
    # or from /api/tags response details
    try:
        async with httpx.AsyncClient(base_url=ollama_url, timeout=3.0) as c:
            r = await c.get("/api/ps")
            if r.status_code == 200:
                ps_data = r.json()
                for m in ps_data.get("models", []):
                    # size_vram > 0 means GPU is being used
                    if m.get("size_vram", 0) > 0:
                        result["gpu_available"] = True
                        break
    except Exception:
        pass

    if wol_mac:
        import time as _time
        wol_age = _time.monotonic() - ollama._wol_sent_at if ollama._wol_sent_at > 0 else None
        result["wol_last_sent_seconds_ago"] = int(wol_age) if wol_age is not None else None

    return result


@health_router.get("/inflight")
async def health_inflight():
    """Return count of in-flight requests to local inference backends."""
    from app.router import get_local_inflight
    return {"local_inflight": get_local_inflight()}


@health_router.get("/startup")
async def startup():
    return {"status": "started"}
