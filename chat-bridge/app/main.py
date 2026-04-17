"""Nova Chat Bridge — multi-platform chat integration."""
from __future__ import annotations

import json
import logging
import time as _time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from nova_contracts.logging import configure_logging

from app.adapters.base import PlatformAdapter
from app.adapters.telegram import TelegramAdapter
from app.config import settings

configure_logging("chat-bridge", settings.log_level)
log = logging.getLogger(__name__)

# ── Admin secret resolver (Redis-backed, env fallback, 30s cache) ────────────
# The admin secret can be rotated at runtime via the orchestrator. This service
# re-reads `nova:config:auth.admin_secret` from Redis db 1 every 30s. If the
# value is unusable, operators can clear it with:
#   redis-cli -n 1 DEL nova:config:auth.admin_secret
# to revert to the bootstrap env value.

_ADMIN_SECRET_CACHE_TTL = 30  # seconds
_admin_secret_cache: dict[str, Any] = {"value": None, "ts": 0.0}
_config_redis = None


async def _get_admin_secret() -> str:
    now = _time.monotonic()
    if (
        now - _admin_secret_cache["ts"] < _ADMIN_SECRET_CACHE_TTL
        and _admin_secret_cache["value"] is not None
    ):
        return _admin_secret_cache["value"]

    value: str | None = None
    try:
        global _config_redis
        if _config_redis is None:
            import redis.asyncio as aioredis
            _config_redis = aioredis.from_url(
                settings.redis_url.rsplit("/", 1)[0] + "/1",
                decode_responses=True,
            )
        raw = await _config_redis.get("nova:config:auth.admin_secret")
        if raw:
            try:
                parsed = json.loads(raw)
                value = parsed if isinstance(parsed, str) and parsed else raw
            except (json.JSONDecodeError, TypeError):
                value = raw
    except Exception:
        log.debug("Failed to read admin secret from Redis, using env fallback")

    if not value:
        value = settings.nova_admin_secret

    _admin_secret_cache["value"] = value
    _admin_secret_cache["ts"] = now
    return value

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
    # Close the admin-secret config Redis connection (lazy-opened)
    global _config_redis
    if _config_redis is not None:
        try:
            await _config_redis.aclose()
        finally:
            _config_redis = None
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


@app.post("/reload-telegram")
async def reload_telegram(request: Request):
    """Reload Telegram adapter with new config. Called by dashboard after saving bot token."""
    admin_secret = request.headers.get("X-Admin-Secret", "")
    if admin_secret != await _get_admin_secret():
        raise HTTPException(status_code=403, detail="Forbidden")

    # Read new token from Redis runtime config (DB 1 = nova:config:* store)
    import redis.asyncio as aioredis
    config_redis_url = settings.redis_url.rsplit("/", 1)[0] + "/1"
    r = aioredis.from_url(config_redis_url, decode_responses=True)
    try:
        token = await r.get("nova:config:telegram.bot_token")
    finally:
        await r.aclose()

    if not token:
        raise HTTPException(status_code=400, detail="No bot token configured")

    # Shutdown existing telegram adapter
    for adapter in ADAPTERS:
        if adapter.platform_name == "telegram":
            await adapter.shutdown()
            ADAPTERS.remove(adapter)
            break

    # Start new adapter with updated token
    object.__setattr__(settings, "telegram_bot_token", token)
    new_adapter = TelegramAdapter()  # reads from module-level settings
    if new_adapter.is_configured():
        await new_adapter.setup(app)
        ADAPTERS.append(new_adapter)

    return {"status": "reloaded"}
