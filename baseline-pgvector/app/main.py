"""
Baseline pgvector memory service — the simplest possible memory system.

Embed text, store in pgvector, retrieve by cosine similarity.
No graph, no decomposition, no LLM calls during ingestion.
This is the control group for the benchmark framework.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.config import settings
from app.db import close_pool, init_pool
from app.routes import router as memory_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


# ── Health endpoints ─────────────────────────────────────────────────────

health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/live")
async def liveness():
    """Liveness probe — is the process alive?"""
    return {"status": "alive"}


@health_router.get("/ready")
async def readiness():
    """Readiness probe — can the service handle traffic?"""
    checks = {}
    try:
        from app.db import get_pool

        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


# ── Lifespan ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Baseline pgvector service starting")
    await init_pool()
    log.info("Baseline pgvector service ready")
    yield
    log.info("Baseline pgvector service shutting down")
    await close_pool()
    log.info("Baseline pgvector service shutdown complete")


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nova Baseline pgvector Memory",
    version="0.1.0",
    description="Minimal pgvector-only memory provider for benchmarking",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(memory_router)
