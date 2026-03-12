"""
Nova Memory Service — main entrypoint.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nova_contracts.logging import configure_logging

from app.config import settings
from app.db.database import AsyncSessionLocal, run_schema_migrations
from app.embedding import get_embedding
from app.engram.consolidation import bootstrap_self_model, consolidation_loop
from app.engram.ingestion import ingestion_loop
from app.engram.router import engram_router
from app.engram.neural_router.serve import load_latest_model
from app.health import health_router

configure_logging("memory-service", settings.log_level)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Memory Service starting — running schema migrations")
    await run_schema_migrations()

    _ingestion_task = asyncio.create_task(ingestion_loop(), name="engram-ingestion")
    _consolidation_task = asyncio.create_task(consolidation_loop(), name="engram-consolidation")
    asyncio.create_task(_warmup_embedding(), name="warmup")
    asyncio.create_task(_bootstrap_self_model(), name="engram-bootstrap")
    _neural_router_task = asyncio.create_task(_neural_router_refresh(), name="neural-router-refresh")
    log.info("Memory Service ready")

    yield

    log.info("Memory Service shutting down")
    _ingestion_task.cancel()
    _consolidation_task.cancel()
    _neural_router_task.cancel()
    await asyncio.gather(
        _ingestion_task, _consolidation_task, _neural_router_task,
        return_exceptions=True,
    )


async def _neural_router_refresh():
    """Background task: periodically check for newer neural router model."""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await load_latest_model(session)
        except Exception:
            log.debug("Neural router model refresh failed", exc_info=True)
        await asyncio.sleep(settings.neural_router_model_check_interval)


app = FastAPI(
    title="Nova Memory Service",
    version="0.1.0",
    description="Engram-based cognitive memory backend for Nova agents",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(engram_router)


async def _warmup_embedding():
    """Fire a dummy embedding to force the model to load into RAM."""
    try:
        async with AsyncSessionLocal() as session:
            await get_embedding("warmup", session)
        log.info("Embedding warmup complete")
    except Exception:
        log.warning("Embedding warmup failed (model may not be available yet)", exc_info=True)


async def _bootstrap_self_model():
    """Seed default self-model engrams on first run."""
    try:
        async with AsyncSessionLocal() as session:
            created = await bootstrap_self_model(session)
            if created:
                await session.commit()
                log.info("Bootstrapped %d self-model engrams", created)
    except Exception:
        log.debug("Self-model bootstrap skipped (table may not exist yet)", exc_info=True)
