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

    # Check Ollama connectivity
    import httpx
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=5.0) as c:
            r = await c.get("/api/tags")
            checks["ollama"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        checks["ollama"] = f"error: {e}"

    # Check Redis connectivity (used for rate limiting + caching)
    try:
        from app.rate_limiter import _get_redis
        r = await _get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


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
        provider = get_provider(model)
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


@health_router.get("/startup")
async def startup():
    return {"status": "started"}
