"""
Nova Memory Service — main entrypoint.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.database import run_schema_migrations
from app.health import health_router
from app.router import context_router, router

logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Memory Service starting — running schema migrations")
    await run_schema_migrations()
    log.info("Memory Service ready")
    yield
    log.info("Memory Service shutting down")


app = FastAPI(
    title="Nova Memory Service",
    version="0.1.0",
    description="Unified PostgreSQL + pgvector memory backend for Nova agents",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(router)
app.include_router(context_router)
