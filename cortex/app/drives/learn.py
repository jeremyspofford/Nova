"""Learn drive — identify and act on capability gaps.

Reads nova:signals:capability_gaps from Redis (published hourly by the
orchestrator's effectiveness matrix computation). When capability gaps
exist (all models underperform for a task_type), reports high urgency
so cortex prioritizes learning actions.
"""
from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from ..config import settings
from . import DriveContext, DriveResult

log = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
CAPABILITY_GAP_KEY = "nova:signals:capability_gaps"

# Capability gaps are published by the orchestrator to its Redis (db2),
# not the cortex Redis (db5). Derive the orchestrator URL from our base.
_ORCHESTRATOR_REDIS_DB = 2


async def _get_redis() -> aioredis.Redis:
    """Connect to the orchestrator's Redis DB where capability gaps are published."""
    global _redis
    if _redis is None:
        # Replace the db number in the URL to point at orchestrator's db2
        import re
        base_url = re.sub(r"/\d+$", "", settings.redis_url)
        _redis = aioredis.from_url(
            f"{base_url}/{_ORCHESTRATOR_REDIS_DB}", decode_responses=True,
        )
    return _redis


async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Check for capability gaps and report urgency."""
    try:
        r = await _get_redis()
        raw = await r.get(CAPABILITY_GAP_KEY)
        if not raw:
            return DriveResult(
                name="learn", priority=4, urgency=0.0,
                description="No capability gaps detected",
            )

        gaps = json.loads(raw)
        if not gaps:
            return DriveResult(
                name="learn", priority=4, urgency=0.0,
                description="No capability gaps detected",
            )

        # Urgency scales with number and severity of gaps
        worst_score = min(g["best_score"] for g in gaps)
        urgency = min(1.0, 0.4 + 0.2 * len(gaps) + 0.3 * (1.0 - worst_score))

        gap_summary = ", ".join(
            f"{g['task_type']} (best={g['best_score']:.2f}, n={g['sample_count']})"
            for g in gaps
        )

        return DriveResult(
            name="learn",
            priority=4,
            urgency=round(urgency, 2),
            description=f"Capability gaps detected: {gap_summary}",
            proposed_action=(
                f"Investigate capability gaps in: {', '.join(g['task_type'] for g in gaps)}. "
                "Consider: improving context retrieval, adjusting system prompts, "
                "or reviewing recent low-scoring interactions for patterns."
            ),
            context={"gaps": gaps},
        )

    except Exception as e:
        log.debug("Learn drive assessment failed: %s", e)
        return DriveResult(
            name="learn", priority=4, urgency=0.0,
            description="Learn drive error — no signal",
        )
