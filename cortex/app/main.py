"""Nova Cortex — autonomous brain service."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_pool, close_pool
from .health import health_router
from .router import cortex_router

logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
log = logging.getLogger("nova.cortex")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    log.info("Cortex service ready — port %s, cycle interval %ds",
             settings.port, settings.cycle_interval_seconds)

    yield

    log.info("Cortex shutting down")
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
