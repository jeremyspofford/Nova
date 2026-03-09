"""
Nova Memory Service — main entrypoint.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nova_contracts.logging import configure_logging

from app.cleanup import cleanup_loop
from app.compaction import compaction_loop
from app.config import settings
from app.db.database import run_schema_migrations
from app.health import health_router
from app.partitions import partition_loop
from app.reembed import reembed_loop
from app.router import context_router, router

configure_logging("memory-service", settings.log_level)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Memory Service starting — running schema migrations")
    await run_schema_migrations()

    _cleanup_task = asyncio.create_task(cleanup_loop(), name="cleanup")
    _compaction_task = asyncio.create_task(compaction_loop(), name="compaction")
    _partition_task = asyncio.create_task(partition_loop(), name="partitions")
    _reembed_task = asyncio.create_task(reembed_loop(), name="reembed")
    log.info("Memory Service ready")

    yield

    log.info("Memory Service shutting down")
    _cleanup_task.cancel()
    _compaction_task.cancel()
    _partition_task.cancel()
    _reembed_task.cancel()
    await asyncio.gather(_cleanup_task, _compaction_task, _partition_task, _reembed_task, return_exceptions=True)


app = FastAPI(
    title="Nova Memory Service",
    version="0.1.0",
    description="Unified PostgreSQL + pgvector memory backend for Nova agents",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(router)
app.include_router(context_router)
