"""Nova Cortex — autonomous brain service."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .clients import init_clients, close_clients
from .config import settings
from .db import init_pool, close_pool
from .stimulus import close_redis
from .budget import close_redis as close_budget_redis
from .health import health_router
from .router import cortex_router
from . import loop

logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
log = logging.getLogger("nova.cortex")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await init_clients()
    await loop.start()

    # Recover in-flight tasks from last run
    try:
        from .task_monitor import dispatch as _monitor_dispatch
        from .db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT g.id as goal_id, g.current_plan->>'task_id' as task_id
                FROM goals g
                WHERE g.status = 'active'
                  AND g.current_plan->>'task_id' IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM tasks t
                      WHERE t.id::text = g.current_plan->>'task_id'
                        AND t.status NOT IN ('complete', 'failed', 'cancelled')
                  )
            """)
            for row in rows:
                if row["task_id"]:
                    _monitor_dispatch(row["task_id"], str(row["goal_id"]), 0, "recovered")
            if rows:
                log.info("Recovered %d in-flight tasks from previous run", len(rows))
    except Exception as e:
        log.warning("Failed to recover in-flight tasks: %s", e)

    log.info("Cortex service ready — port %s, cycle interval %ds",
             settings.port, settings.cycle_interval_seconds)

    yield

    log.info("Cortex shutting down")
    await loop.stop()
    await close_clients()
    await close_redis()
    await close_budget_redis()
    await close_pool()


app = FastAPI(
    title="Nova Cortex",
    version="0.1.0",
    description="Autonomous brain service — thinking loop, goals, drives",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(cortex_router)
