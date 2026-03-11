"""Health endpoints for Cortex service."""
from fastapi import APIRouter

from .config import settings
from .db import get_pool

health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/live")
async def liveness():
    return {"status": "alive"}


@health_router.get("/ready")
async def readiness():
    checks = {}

    # Postgres
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # Dependent services
    import httpx
    for svc, url in [
        ("orchestrator", settings.orchestrator_url),
        ("llm_gateway", settings.llm_gateway_url),
        ("memory_service", settings.memory_service_url),
    ]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"{url}/health/live")
                checks[svc] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
        except Exception as e:
            checks[svc] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


@health_router.get("/startup")
async def startup():
    return {"status": "started"}
