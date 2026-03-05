"""Nova Orchestrator — main entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from nova_contracts.logging import configure_logging

from app.clients import close_clients
from app.config import settings
from app.db import close_db, init_db
from app.health import health_router
from app.pipeline_router import router as pipeline_router
from app.queue import queue_worker
from app.reaper import reaper_loop
from app.router import router
from app.store import ensure_primary_agent, recover_stale_agents

configure_logging("orchestrator", settings.log_level)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Orchestrator starting")

    # Recover Redis agents stuck in 'running' from a previous crashed process
    recovered = await recover_stale_agents()
    if recovered:
        log.info("Startup: recovered %d stale agent(s) to idle", recovered)

    # Initialize Postgres pool and apply versioned schema migrations
    await init_db()

    # Guarantee one canonical Nova agent exists; prune any duplicates
    primary = await ensure_primary_agent()
    log.info("Primary agent ready: %s model=%s", primary.id, primary.config.model)

    # Load MCP servers from DB and connect to enabled ones
    from app.pipeline.tools import load_mcp_servers
    mcp_count = await load_mcp_servers()
    log.info("MCP servers loaded: %d connected", mcp_count)

    # Start background tasks — stored so we can cancel on shutdown
    _queue_task  = asyncio.create_task(queue_worker(),  name="queue-worker")
    _reaper_task = asyncio.create_task(reaper_loop(),   name="reaper")
    log.info("Queue worker and reaper started")

    yield

    log.info("Orchestrator shutting down")
    _queue_task.cancel()
    _reaper_task.cancel()
    # Wait briefly for graceful shutdown
    await asyncio.gather(_queue_task, _reaper_task, return_exceptions=True)

    # Gracefully stop MCP server subprocesses
    from app.pipeline.tools import stop_all_servers
    await stop_all_servers()

    await close_clients()
    await close_db()


app = FastAPI(
    title="Nova Orchestrator",
    version="0.2.0",
    description="Agent lifecycle management and task routing",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(router)
app.include_router(pipeline_router)
