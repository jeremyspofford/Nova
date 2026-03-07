"""Sync platform_config (DB) → Redis so LLM gateway picks up saved settings on boot."""
from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from app.config import settings
from app.db import get_pool

log = logging.getLogger(__name__)


def _gateway_redis_url() -> str:
    """Redis URL targeting db1 (llm-gateway's database)."""
    return settings.redis_url.rsplit("/", 1)[0] + "/1"


async def push_config_to_redis(key: str, value) -> None:
    """Write a single config key to the gateway Redis (db1)."""
    r = aioredis.from_url(_gateway_redis_url(), decode_responses=True)
    try:
        raw = json.dumps(value) if not isinstance(value, str) else value
        await r.set(f"nova:config:{key}", raw)
    finally:
        await r.aclose()


async def sync_llm_config_to_redis() -> None:
    """Push all llm.* config from DB to Redis so LLM gateway has correct values on boot."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM platform_config WHERE key LIKE 'llm.%'"
            )
        if not rows:
            return

        r = aioredis.from_url(_gateway_redis_url(), decode_responses=True)
        try:
            for row in rows:
                val = row["value"]
                if val is not None:
                    raw = json.dumps(val) if not isinstance(val, str) else val
                    await r.set(f"nova:config:{row['key']}", raw)
        finally:
            await r.aclose()

        log.info("Synced %d llm config keys to Redis", len(rows))
    except Exception as e:
        log.warning("Config sync to Redis failed (non-fatal): %s", e)
