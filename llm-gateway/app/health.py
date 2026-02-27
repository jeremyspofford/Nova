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

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


@health_router.get("/startup")
async def startup():
    return {"status": "started"}
