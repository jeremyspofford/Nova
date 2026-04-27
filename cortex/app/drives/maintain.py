"""Maintain drive — keep Nova healthy.

Urgency is based on:
- Service health check results
- health.degraded stimulus events

Side-effects:
- Triages newly-created goals (goal.created stimuli) and routes complex
  goals into the maturation pipeline by setting maturation_status='scoping'.
"""
from __future__ import annotations

import logging

from ..clients import get_orchestrator, get_llm, get_memory
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


async def _triage_new_goals(ctx: DriveContext) -> None:
    """Classify any goal.created stimuli and route complex goals into maturation."""
    for stim in ctx.stimuli_of_type(GOAL_CREATED):
        payload = stim.get("payload") or {}
        goal_id = payload.get("goal_id")
        if not goal_id:
            continue
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT title, description, maturation_status FROM goals WHERE id = $1::uuid",
                    goal_id,
                )
                if not row:
                    log.debug("Triage: goal %s not found", goal_id)
                    continue
                if row["maturation_status"] is not None:
                    # Already triaged or in a phase — skip
                    continue
                verdict = await triage_goal_complexity(row["title"], row["description"])
                # `scoping` is the first active phase — `triaging` is transient.
                # Simple goals stay at NULL maturation_status (legacy fast path).
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


async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Assess maintain drive urgency based on service health and stimuli."""
    # Side-effect: triage newly-created goals before health scoring
    if ctx:
        await _triage_new_goals(ctx)

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
