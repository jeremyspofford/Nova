"""Effectiveness matrix — hourly aggregation of model outcome scores.

Computes avg outcome_score per (model, task_type) from usage_events
and pushes the result to Redis for the llm-gateway tier resolver.

The gateway reads this at `nova:cache:model_effectiveness` to filter
tier preference lists — models that consistently underperform for a
task type get deprioritised automatically.
"""
from __future__ import annotations

import asyncio
import json
import logging

from .db import get_pool
from .store import get_redis

log = logging.getLogger(__name__)

REDIS_KEY = "nova:cache:model_effectiveness"
REDIS_TTL = 3600  # 1 hour — matches the computation interval


async def compute_and_publish() -> int:
    """Aggregate outcome scores and publish to Redis.

    Returns the number of (model, task_type) entries in the matrix.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT model,
                   COALESCE(metadata->>'task_type', 'unknown') AS task_type,
                   AVG(outcome_score) AS avg_score,
                   COUNT(*) AS sample_count
            FROM usage_events
            WHERE outcome_score IS NOT NULL
              AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY 1, 2
        """)

    matrix = {}
    for row in rows:
        key = f"{row['model']}:{row['task_type']}"
        matrix[key] = {
            "avg_score": round(float(row["avg_score"]), 3),
            "sample_count": int(row["sample_count"]),
        }

    try:
        redis = get_redis()
        await redis.set(REDIS_KEY, json.dumps(matrix), ex=REDIS_TTL)
        log.info("Published effectiveness matrix: %d entries", len(matrix))
    except Exception:
        log.warning("Redis unavailable — effectiveness matrix not published", exc_info=True)

    return len(matrix)


async def effectiveness_loop() -> None:
    """Background loop — recompute every hour."""
    while True:
        try:
            await compute_and_publish()
        except Exception:
            log.exception("Effectiveness matrix computation failed")
        await asyncio.sleep(3600)
