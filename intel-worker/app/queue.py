"""Dual-Redis queue helpers — push to engram (db0) and intel (db6) queues."""
import json
import logging
from urllib.parse import urlparse, urlunparse

import redis.asyncio as aioredis

from app.config import settings

log = logging.getLogger(__name__)

_redis_intel: aioredis.Redis | None = None  # db6
_redis_engram: aioredis.Redis | None = None  # db0


async def init_queues() -> None:
    global _redis_intel, _redis_engram
    _redis_intel = aioredis.from_url(settings.redis_url, decode_responses=True)
    parsed = urlparse(settings.redis_url)
    engram_url = urlunparse(parsed._replace(path="/0"))
    _redis_engram = aioredis.from_url(engram_url, decode_responses=True)
    log.info("Redis queues initialized (intel=db6, engram=db0)")


async def push_to_engram_queue(item: dict) -> None:
    """Push content to memory-service's engram ingestion queue."""
    payload = {
        "raw_text": f"{item.get('title', '')}\n\n{item.get('body', '')}",
        "source_type": "intel",
        "metadata": {
            "feed_name": item.get("feed_name", ""),
            "url": item.get("url", ""),
            "content_item_id": item.get("id", ""),
        },
    }
    await _redis_engram.lpush("engram:ingestion:queue", json.dumps(payload))


async def push_to_intel_queue(item: dict) -> None:
    """Push notification to Cortex's intel new-items queue."""
    payload = {
        "content_item_id": item.get("id", ""),
        "feed_id": item.get("feed_id", ""),
        "title": item.get("title", ""),
        "category": item.get("category", ""),
    }
    await _redis_intel.lpush("intel:new_items", json.dumps(payload))


async def close_queues() -> None:
    global _redis_intel, _redis_engram
    if _redis_intel:
        await _redis_intel.aclose()
        _redis_intel = None
    if _redis_engram:
        await _redis_engram.aclose()
        _redis_engram = None
