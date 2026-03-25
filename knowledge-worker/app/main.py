"""Knowledge Worker -- FastAPI app with autonomous crawl scheduling."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.client import close_clients, get_llm_client, get_orchestrator_client, init_clients
from app.config import settings
from app.credentials.health import run_credential_health_loop
from app.queue import close_queues, init_queues, push_to_engram
from app.scheduler import run_scheduling_loop

logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_health_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler_task, _health_task
    await init_clients()
    await init_queues()

    # Start the crawl scheduling loop as a background task
    _scheduler_task = asyncio.create_task(run_scheduling_loop(
        config=settings,
        get_orch_client=get_orchestrator_client,
        get_llm_client=get_llm_client,
        push_to_engram=push_to_engram,
    ))

    # Start the credential health check loop as a background task
    _health_task = asyncio.create_task(run_credential_health_loop(
        config=settings,
        get_orch_client=get_orchestrator_client,
    ))
    log.info("Knowledge worker started (scheduler and credential health check running)")

    yield

    # Shutdown: cancel background tasks, close connections
    for task in (_scheduler_task, _health_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await close_queues()
    await close_clients()


app = FastAPI(title="Nova Knowledge Worker", lifespan=lifespan)


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    try:
        client = get_orchestrator_client()
        resp = await client.get("/health/live", timeout=5)
        if resp.status_code != 200:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "orchestrator_unreachable"},
            )
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "orchestrator_unreachable"},
        )
    return {"status": "ready"}
