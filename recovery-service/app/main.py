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
from .routes import router

logger = logging.getLogger("nova.recovery")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from .db import init_pool, close_pool
    from .scheduler import checkpoint_loop

    await init_pool()
    checkpoint_task = asyncio.create_task(checkpoint_loop())
    logger.info("Recovery service ready — port %s, backups at %s", settings.port, settings.backup_dir)
    yield
    checkpoint_task.cancel()
    await close_pool()


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
