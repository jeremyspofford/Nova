"""Verifying phase — run health checks, mark goal complete (or back to review on failure)."""
from __future__ import annotations

import logging

import httpx

from ..db import get_pool

log = logging.getLogger(__name__)

# Service health endpoints to probe. Use docker-internal hostnames since cortex runs in
# the same compose network.
HEALTH_ENDPOINTS = [
    ("orchestrator", "http://orchestrator:8000/health/ready"),
    ("llm-gateway", "http://llm-gateway:8001/health/ready"),
    ("memory-service", "http://memory-service:8002/health/ready"),
]


async def run_verifying(goal_id: str) -> bool:
    """Run health checks. Returns True if goal completed successfully, False otherwise.

    On success: goal status -> completed, maturation_status cleared, GOAL_COMPLETED emitted.
    On failure: maturation_status -> review, audit comment posted for human investigation.
    """
    pool = get_pool()
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, url in HEALTH_ENDPOINTS:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    failures.append(f"{name}: HTTP {resp.status_code}")
                    continue
                data = resp.json()
                if data.get("status") != "ready":
                    failures.append(f"{name}: status={data.get('status')}")
            except Exception as e:
                failures.append(f"{name}: {type(e).__name__}: {e}")

    if failures:
        # Roll back to review with a comment so the human can investigate
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE goals SET maturation_status = 'review',
                                       updated_at = NOW()
                   WHERE id = $1::uuid""",
                goal_id,
            )
            await conn.execute(
                """INSERT INTO comments (entity_type, entity_id, author_type, author_name, body)
                   VALUES ('goal', $1::uuid, 'nova', 'cortex',
                           'Verification failed:\n' || $2)""",
                goal_id, "\n".join(f"- {f}" for f in failures),
            )
        log.warning("Verification failed for goal %s: %s", goal_id, failures)
        return False

    # All healthy — mark goal complete
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET status = 'completed',
                                   maturation_status = NULL,
                                   progress = 1.0,
                                   updated_at = NOW()
               WHERE id = $1::uuid""",
            goal_id,
        )
    from ..stimulus import emit, GOAL_COMPLETED
    await emit(GOAL_COMPLETED, "cortex", payload={"goal_id": goal_id})
    log.info("Verification passed for goal %s — marked completed", goal_id)
    return True
