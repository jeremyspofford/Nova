"""Serve drive — pursue user-set goals.

Urgency is based on:
- Number of active goals
- Whether any goals have pending tasks or need new work
- Time since last check
- Stimulus events (message received, goal created, schedule due)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..db import get_pool
from . import DriveContext, DriveResult

log = logging.getLogger(__name__)


async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Assess serve drive urgency based on active goals and stimuli."""
    pool = get_pool()
    async with pool.acquire() as conn:
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM goals WHERE status = 'active'"
        )

        stale_goals = await conn.fetch(
            """
            SELECT id, title, priority, progress, check_interval_seconds, last_checked_at,
                   maturation_status
            FROM goals
            WHERE status = 'active'
              AND (
                -- Normal stale check
                (last_checked_at IS NULL
                 OR last_checked_at < NOW() - (check_interval_seconds || ' seconds')::interval)
                -- OR has active maturation phase (not review — that waits for human)
                OR maturation_status IN ('scoping', 'speccing', 'building', 'verifying')
              )
              AND (maturation_status IS NULL OR maturation_status != 'review')
            ORDER BY priority DESC
            LIMIT 5
            """,
        )

        active_tasks = await conn.fetchval(
            """
            SELECT COUNT(*) FROM tasks t
            JOIN goals g ON t.goal_id = g.id
            WHERE g.status = 'active' AND t.status IN ('queued', 'running')
            """
        )

    if active_count == 0 and (ctx is None or not ctx.stimuli_of_type(
        "message.received", "goal.created", "goal.schedule_due",
        "goal.spec_approved", "recommendation.approved"
    )):
        return DriveResult(
            name="serve", priority=1, urgency=0.0,
            description="No active goals",
        )

    # Base urgency from stale goals
    stale_ratio = len(stale_goals) / max(active_count, 1) if active_count > 0 else 0
    urgency = min(1.0, 0.2 + stale_ratio * 0.6)

    # If tasks are already in-flight, reduce urgency
    if active_tasks > 0:
        urgency *= 0.5

    # Stimulus boosts
    if ctx:
        schedule_due = ctx.stimuli_of_type("goal.schedule_due")
        if schedule_due:
            urgency = max(urgency, 0.9)

        if ctx.stimuli_of_type("message.received"):
            urgency = min(1.0, urgency + 0.3)

        if ctx.stimuli_of_type("goal.created"):
            urgency = min(1.0, urgency + 0.2)

        if ctx.stimuli_of_type("goal.spec_approved"):
            urgency = max(urgency, 0.9)

        if ctx.stimuli_of_type("recommendation.approved"):
            urgency = min(1.0, urgency + 0.3)

    goal_summaries = [
        {"id": str(g["id"]), "title": g["title"], "priority": g["priority"],
         "progress": g["progress"], "maturation_status": g.get("maturation_status")}
        for g in stale_goals
    ]

    scheduled_goal_ids = []
    if ctx:
        for s in ctx.stimuli_of_type("goal.schedule_due"):
            gid = s.get("payload", {}).get("goal_id")
            if gid:
                scheduled_goal_ids.append(gid)

    return DriveResult(
        name="serve",
        priority=1,
        urgency=round(urgency, 2),
        description=f"{active_count} active goals, {len(stale_goals)} need attention",
        proposed_action=f"Work on goal: {stale_goals[0]['title']}" if stale_goals else None,
        context={
            "stale_goals": goal_summaries,
            "active_tasks": active_tasks,
            "scheduled_goal_ids": scheduled_goal_ids,
        },
    )
