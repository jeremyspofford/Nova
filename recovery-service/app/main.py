"""
Nova Recovery Service — resilient backup, restore, and disaster recovery.

Designed to stay alive when all other Nova services are down.
Only depends on: Postgres (for backups) and Docker socket (for service management).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .inference.routes import router as inference_router
from .routes import router

logger = logging.getLogger("nova.recovery")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from .db import init_pool, close_pool
    from .scheduler import checkpoint_loop

    from .inference.hardware import sync_hardware_from_file
    from .redis_client import close_redis

    await init_pool()
    checkpoint_task = asyncio.create_task(checkpoint_loop())

    # Sync hardware info from data/hardware.json (written by setup.sh) into Redis
    try:
        await sync_hardware_from_file()
    except Exception:
        logger.warning("Hardware sync failed — will detect on first request", exc_info=True)

    logger.info("Recovery service ready — port %s, backups at %s", settings.port, settings.backup_dir)
    yield
    checkpoint_task.cancel()
    await close_pool()
    await close_redis()


app = FastAPI(
    title="Nova Recovery Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(inference_router)
