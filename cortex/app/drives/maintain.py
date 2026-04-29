"""Maintain drive — keep Nova healthy.

Urgency is based on:
- Service health check results
- health.degraded stimulus events

Side-effects:
- Triages newly-created goals (goal.created stimuli) and routes complex
  goals into the maturation pipeline by setting maturation_status='scoping'.
  Triage is dispatched as a background task so the LLM call (up to 30s)
  doesn't gate the drive cycle.
"""
from __future__ import annotations

import asyncio
import logging

from ..clients import get_llm, get_memory, get_orchestrator
from ..db import get_pool
from ..maturation.triage import triage_goal_complexity
from ..stimulus import GOAL_CREATED
from . import DriveContext, DriveResult

log = logging.getLogger(__name__)

SERVICES = [
    ("orchestrator", get_orchestrator),
    ("llm_gateway", get_llm),
    ("memory_service", get_memory),
]


# Module-level dedupe — prevents duplicate in-flight triages when the same
# goal_id stimulus is observed across overlapping cycles.
_inflight_triages: set[str] = set()


async def _triage_one(goal_id: str) -> None:
    """Triage a single goal in the background. Safe to fire-and-forget."""
    if goal_id in _inflight_triages:
        return
    _inflight_triages.add(goal_id)
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT title, description, maturation_status FROM goals WHERE id = $1::uuid",
                goal_id,
            )
            if not row:
                log.debug("Triage: goal %s not found", goal_id)
                return
            if row["maturation_status"] is not None:
                # Already triaged or in a phase — skip
                return
            verdict = await triage_goal_complexity(row["title"], row["description"])
            # `scoping` is the first active phase. Simple goals stay at NULL
            # maturation_status (legacy fast path).
            new_status = "scoping" if verdict == "complex" else None
            if new_status:
                await conn.execute(
                    "UPDATE goals SET maturation_status = $1, complexity = $2, updated_at = NOW() "
                    "WHERE id = $3::uuid",
                    new_status, verdict, goal_id,
                )
                log.info("Triage: goal %s classified %s → maturation=%s",
                         goal_id, verdict, new_status)
            else:
                await conn.execute(
                    "UPDATE goals SET complexity = $1, updated_at = NOW() WHERE id = $2::uuid",
                    verdict, goal_id,
                )
                log.info("Triage: goal %s classified %s (no maturation)", goal_id, verdict)
    except Exception as e:
        log.warning("Triage failed for goal %s: %s", goal_id, e)
    finally:
        _inflight_triages.discard(goal_id)


def _dispatch_triage(ctx: DriveContext) -> None:
    """Spawn background triage tasks for any goal.created stimuli.

    Returns immediately — the actual LLM call runs in a detached task so it
    never blocks the drive evaluate() cadence.
    """
    for stim in ctx.stimuli_of_type(GOAL_CREATED):
        payload = stim.get("payload") or {}
        goal_id = payload.get("goal_id")
        if not goal_id:
            continue
        # Don't await — run triage in the background.
        asyncio.create_task(_triage_one(goal_id))


async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Assess maintain drive urgency based on service health and stimuli."""
    # Side-effect: dispatch background triage for newly-created goals.
    # Non-blocking — the LLM call runs detached so it can't gate the cycle.
    if ctx:
        _dispatch_triage(ctx)

    checks: dict[str, str] = {}

    for name, get_client in SERVICES:
        try:
            client = get_client()
            resp = await client.get("/health/live", timeout=5.0)
            checks[name] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            checks[name] = f"error: {type(e).__name__}"

    degraded = [name for name, status in checks.items() if status != "ok"]
    urgency = 0.0

    if degraded:
        urgency = min(1.0, len(degraded) / len(SERVICES) + 0.3)

    # Stimulus boost (before early return so external signals aren't missed)
    if ctx and ctx.stimuli_of_type("health.degraded"):
        urgency = max(urgency, 0.7)

    if urgency == 0.0:
        return DriveResult(
            name="maintain", priority=2, urgency=0.0,
            description="All services healthy",
            context={"checks": checks},
        )

    return DriveResult(
        name="maintain",
        priority=2,
        urgency=round(urgency, 2),
        description=f"Degraded: {', '.join(degraded)}" if degraded else "External health alert",
        proposed_action=f"Investigate {degraded[0]} health issue" if degraded else "Check health alert",
        context={"checks": checks, "degraded": degraded},
    )
