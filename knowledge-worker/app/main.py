"""Knowledge Worker -- minimal FastAPI app for health endpoints."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.client import close_clients, get_orchestrator_client, init_clients
from app.config import settings
from app.queue import close_queues, init_queues

logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_clients()
    await init_queues()
    log.info("Knowledge worker started")
    yield
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
