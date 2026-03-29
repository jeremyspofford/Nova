"""Nova Chat Bridge — multi-platform chat integration."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nova_contracts.logging import configure_logging

from app.adapters.base import PlatformAdapter
from app.adapters.telegram import TelegramAdapter
from app.config import settings

configure_logging("chat-bridge", settings.log_level)
log = logging.getLogger(__name__)

# Registry of all platform adapters
ADAPTERS: list[PlatformAdapter] = [
    TelegramAdapter(),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    active = []
    for adapter in ADAPTERS:
        if adapter.is_configured():
            try:
                await adapter.setup(app)
                active.append(adapter.platform_name)
                log.info("Adapter enabled: %s", adapter.platform_name)
            except Exception as e:
                log.error("Failed to start adapter %s: %s", adapter.platform_name, e, exc_info=True)

    if not active:
        log.warning("No platform adapters configured. Set TELEGRAM_BOT_TOKEN or SLACK_BOT_TOKEN in .env")
    else:
        log.info("Chat bridge started with adapters: %s", ", ".join(active))

    yield

    for adapter in ADAPTERS:
        if adapter.is_configured():
            try:
                await adapter.shutdown()
            except Exception as e:
                log.error("Error shutting down adapter %s: %s", adapter.platform_name, e)
    log.info("Chat bridge shut down")


app = FastAPI(
    title="Nova Chat Bridge",
    version="0.1.0",
    description="Multi-platform chat integration for Nova",
    lifespan=lifespan,
)


@app.get("/health/live")
async def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness():
    import httpx
    checks: dict[str, str] = {}

    # Check orchestrator
    try:
        async with httpx.AsyncClient(base_url=settings.orchestrator_url, timeout=3.0) as c:
            r = await c.get("/health/ready")
            checks["orchestrator"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        checks["orchestrator"] = f"error: {e}"

    # Report active adapters
    for adapter in ADAPTERS:
        checks[f"adapter_{adapter.platform_name}"] = (
            "configured" if adapter.is_configured() else "not_configured"
        )

    all_ok = checks.get("orchestrator") == "ok"
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


@app.get("/api/status")
async def adapter_status():
    """Status of all platform adapters — used by dashboard Settings UI."""
    return {
        "adapters": [
            {
                "platform": a.platform_name,
                "configured": a.is_configured(),
            }
            for a in ADAPTERS
        ]
    }
