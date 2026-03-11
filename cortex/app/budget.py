"""Budget tracking — reads usage_events to compute daily spend."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from .config import settings
from .db import get_pool

log = logging.getLogger(__name__)

# Redis connection for publishing budget tier
_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def get_daily_spend() -> float:
    """Sum cost_usd from usage_events for today (UTC)."""
    pool = get_pool()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_events WHERE created_at >= $1",
            today_start,
        )
    return float(result)


async def get_budget_status() -> dict:
    """Return current budget state."""
    daily_spend = await get_daily_spend()
    budget = settings.daily_budget_usd
    remaining = max(0.0, budget - daily_spend)
    pct_used = (daily_spend / budget * 100) if budget > 0 else 0.0

    return {
        "daily_budget_usd": budget,
        "daily_spend_usd": round(daily_spend, 4),
        "remaining_usd": round(remaining, 4),
        "percent_used": round(pct_used, 1),
        "budget_exceeded": daily_spend >= budget,
        "tier": _compute_tier(pct_used),
    }


def _compute_tier(pct_used: float) -> str:
    """Determine model tier based on budget usage.

    < 50%: best (use top-tier models for all work)
    50-80%: mid (shift background work to cheaper models)
    80-100%: cheap (local/cheapest models only)
    >= 100%: none (health checks only, no LLM calls)
    """
    if pct_used >= 100:
        return "none"
    if pct_used >= 80:
        return "cheap"
    if pct_used >= 50:
        return "mid"
    return "best"


async def publish_budget_tier() -> str:
    """Compute budget tier and publish to Redis for gateway consumption.

    The llm-gateway reads nova:config:cortex.budget_tier to apply budget
    ceilings on cortex-originated LLM requests.
    """
    status = await get_budget_status()
    tier = status["tier"]
    try:
        r = await _get_redis()
        await r.set("nova:config:cortex.budget_tier", tier, ex=600)
    except Exception as e:
        log.warning("Failed to publish budget tier to Redis: %s", e)
    return tier
