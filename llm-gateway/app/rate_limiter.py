"""
Per-provider sliding-window rate limiter backed by Redis.

Each free-tier provider has a known daily quota.  Before dispatching a
request we check the counter and reject with 429 if the quota is exhausted.
Paid APIs and local Ollama are unlimited and bypass the limiter.
"""
from __future__ import annotations

import logging
import time

import redis.asyncio as redis

from app.config import settings

log = logging.getLogger(__name__)

# ── Known free-tier daily quotas ─────────────────────────────────────────────
# key = provider name prefix used in model IDs
PROVIDER_QUOTAS: dict[str, int] = {
    "groq":       14_400,   # 14,400 req/day
    "gemini":       250,    # 250 req/day
    "cerebras":   5_000,    # ~1M tokens/day ≈ 5k requests (conservative estimate)
    "openrouter":   200,    # ~50-200 req/day depending on model
    "github":       150,    # 50-150 req/day
}

# Window size in seconds (24 hours)
_WINDOW = 86_400

# Singleton Redis connection (lazy-initialised)
_redis: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _provider_prefix(model: str) -> str | None:
    """Extract the provider prefix from a model ID, or None if not quota-limited."""
    for prefix in PROVIDER_QUOTAS:
        if model.startswith(f"{prefix}/") or model.startswith(f"{prefix}_"):
            return prefix
    return None


async def check_rate_limit(model: str) -> tuple[bool, str | None, int | None]:
    """
    Check whether a request for *model* is within the provider's daily quota.

    Returns (allowed, provider_prefix, remaining).
    - allowed=True  → proceed
    - allowed=False → reject with 429; *provider_prefix* names the quota bucket
    """
    prefix = _provider_prefix(model)
    if prefix is None:
        return True, None, None  # unlimited (Ollama, paid APIs, subscriptions)

    try:
        r = await _get_redis()
        key = f"nova:ratelimit:{prefix}"
        now = time.time()
        window_start = now - _WINDOW

        pipe = r.pipeline()
        # Remove entries older than the window
        pipe.zremrangebyscore(key, "-inf", window_start)
        # Count current window entries
        pipe.zcard(key)
        # Add this request (score = timestamp, member = unique-ish)
        pipe.zadd(key, {f"{now}:{id(model)}": now})
        # Expire the whole key after the window so it self-cleans
        pipe.expire(key, _WINDOW + 60)
        results = await pipe.execute()

        current_count = results[1]  # zcard result
        quota = PROVIDER_QUOTAS[prefix]
        remaining = max(quota - current_count - 1, 0)

        if current_count >= quota:
            # Over quota — remove the entry we just added
            await r.zremrangebyscore(key, now, now)
            log.warning(
                "Rate limit exceeded for provider %s (%d/%d daily)",
                prefix, current_count, quota,
            )
            return False, prefix, 0

        return True, prefix, remaining

    except Exception as e:
        # Redis down → fail open (allow the request)
        log.warning("Rate limiter Redis error, failing open: %s", e)
        return True, None, None


async def close() -> None:
    """Shut down the Redis connection pool."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
