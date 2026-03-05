"""
Redis-backed response cache for deterministic LLM completions and embeddings.

Cache key = SHA-256 of the canonical request body.  Streaming requests are
never cached (non-deterministic by nature, and results are consumed
incrementally).  Responses are stored as JSON with a configurable TTL
(default 300 s from config.response_cache_ttl).
"""
from __future__ import annotations

import hashlib
import json
import logging

import redis.asyncio as redis

from app.config import settings

log = logging.getLogger(__name__)

_redis: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _cache_key(prefix: str, body: dict) -> str:
    """Deterministic cache key from a request dict."""
    canonical = json.dumps(body, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:24]
    return f"nova:cache:{prefix}:{digest}"


async def get_cached(prefix: str, body: dict) -> dict | None:
    """Return cached response dict, or None on miss / error."""
    if settings.response_cache_ttl <= 0:
        return None
    try:
        r = await _get_redis()
        raw = await r.get(_cache_key(prefix, body))
        if raw:
            log.debug("Cache HIT for %s", prefix)
            return json.loads(raw)
    except Exception as e:
        log.warning("Cache read error, treating as miss: %s", e)
    return None


async def set_cached(prefix: str, body: dict, response: dict) -> None:
    """Store a response in the cache with the configured TTL."""
    if settings.response_cache_ttl <= 0:
        return
    try:
        r = await _get_redis()
        key = _cache_key(prefix, body)
        await r.setex(key, settings.response_cache_ttl, json.dumps(response, default=str))
    except Exception as e:
        log.warning("Cache write error: %s", e)


async def close() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
