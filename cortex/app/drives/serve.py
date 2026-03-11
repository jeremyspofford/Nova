"""Serve drive — pursue user-set goals.

Urgency is based on:
- Number of active goals
- Whether any goals have pending tasks or need new work
- Time since last check
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..db import get_pool
from . import DriveResult

log = logging.getLogger(__name__)


async def assess() -> DriveResult:
    """Assess serve drive urgency based on active goals."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Count active goals
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM goals WHERE status = 'active'"
        )

        # Find goals needing attention (not checked recently)
        stale_goals = await conn.fetch(
            """
            SELECT id, title, priority, progress, check_interval_seconds, last_checked_at
            FROM goals
            WHERE status = 'active'
              AND (last_checked_at IS NULL
                   OR last_checked_at < NOW() - (check_interval_seconds || ' seconds')::interval)
            ORDER BY priority DESC
            LIMIT 5
            """,
        )

        # Count in-flight tasks for active goals
        active_tasks = await conn.fetchval(
            """
            SELECT COUNT(*) FROM tasks t
            JOIN goals g ON t.goal_id = g.id
            WHERE g.status = 'active' AND t.status IN ('queued', 'running')
            """
        )

    if active_count == 0:
        return DriveResult(
            name="serve", priority=1, urgency=0.0,
            description="No active goals",
        )

    # Urgency increases with stale goals
    stale_ratio = len(stale_goals) / max(active_count, 1)
    urgency = min(1.0, 0.2 + stale_ratio * 0.6)

    # If tasks are already in-flight, reduce urgency (work is happening)
    if active_tasks > 0:
        urgency *= 0.5

    goal_summaries = [
        {"id": str(g["id"]), "title": g["title"], "priority": g["priority"],
         "progress": g["progress"]}
        for g in stale_goals
    ]

    return DriveResult(
        name="serve",
        priority=1,
        urgency=round(urgency, 2),
        description=f"{active_count} active goals, {len(stale_goals)} need attention",
        proposed_action=f"Work on goal: {stale_goals[0]['title']}" if stale_goals else None,
        context={"stale_goals": goal_summaries, "active_tasks": active_tasks},
    )
