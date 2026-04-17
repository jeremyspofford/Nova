from fastapi import APIRouter
from app.config import settings
from app.store import get_redis

health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/live")
async def liveness():
    return {"status": "alive"}


@health_router.get("/ready")
async def readiness():
    checks = {}

    try:
        redis = get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    import httpx
    for svc, url in [
        ("memory_service", settings.memory_service_url),
        ("llm_gateway", settings.llm_gateway_url),
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
