"""Intel Worker — minimal FastAPI app for health endpoints + background polling."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.client import close_client, get_client, init_client
from app.config import settings
from app.queue import close_queues, init_queues

logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)

_poller_task: asyncio.Task | None = None
_poller_healthy = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_client()
    await init_queues()
    global _poller_task, _poller_healthy
    from app.poller import run_polling_loop
    _poller_task = asyncio.create_task(run_polling_loop())
    _poller_healthy = True
    log.info("Intel worker started — polling loop active")
    yield
    if _poller_task:
        _poller_task.cancel()
    await close_queues()
    await close_client()


app = FastAPI(title="Nova Intel Worker", lifespan=lifespan)


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    if not _poller_healthy:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    try:
        client = get_client()
        resp = await client.get("/health/live", timeout=5)
        if resp.status_code != 200:
            return JSONResponse(status_code=503, content={"status": "orchestrator_unreachable"})
    except Exception:
        return JSONResponse(status_code=503, content={"status": "orchestrator_unreachable"})
    return {"status": "ready"}
