"""Goal CRUD endpoints — used by dashboard and cortex."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import UserDep
from app.db import get_pool
from app.stimulus import emit_stimulus

log = logging.getLogger(__name__)

goals_router = APIRouter(tags=["goals"])


def _validate_and_compute_next(cron_expr: str) -> datetime:
    """Validate a cron expression and return the next fire time."""
    from croniter import croniter
    if not croniter.is_valid(cron_expr):
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {cron_expr}")
    return croniter(cron_expr, datetime.now(timezone.utc)).get_next(datetime)


# ── Request / Response models ─────────────────────────────────────────────────

class CreateGoalRequest(BaseModel):
    title: str
    description: str | None = None
    priority: int = 0
    max_iterations: int | None = 50
    max_cost_usd: float | None = None
    check_interval_seconds: int | None = 3600
    parent_goal_id: UUID | None = None
    schedule_cron: str | None = None
    max_completions: int | None = None
    created_via: str = "api"


class UpdateGoalRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: int | None = None
    progress: float | None = None
    max_iterations: int | None = None
    max_cost_usd: float | None = None
    check_interval_seconds: int | None = None
    schedule_cron: str | None = Field(default=None, description="Cron expression or None to clear")
    max_completions: int | None = None


class GoalResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    status: str
    priority: int
    progress: float
    current_plan: dict | list | None
    iteration: int
    max_iterations: int | None
    max_cost_usd: float | None
    cost_so_far_usd: float
    check_interval_seconds: int | None
    last_checked_at: datetime | None
    parent_goal_id: UUID | None
    schedule_cron: str | None
    schedule_next_at: datetime | None
    schedule_last_ran_at: datetime | None
    max_completions: int | None
    completion_count: int
    created_via: str
    created_by: str
    created_at: datetime
    updated_at: datetime


# ── Endpoints ─────────────────────────────────────────────────────────────────

@goals_router.post("/api/v1/goals", response_model=GoalResponse, status_code=201)
async def create_goal(req: CreateGoalRequest, user: UserDep):
    """Create a new goal."""
    pool = get_pool()
    schedule_next_at = None
    if req.schedule_cron:
        schedule_next_at = _validate_and_compute_next(req.schedule_cron)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO goals (title, description, priority, max_iterations,
                               max_cost_usd, check_interval_seconds, parent_goal_id,
                               created_by, schedule_cron, schedule_next_at,
                               max_completions, created_via)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING *
            """,
            req.title, req.description, req.priority, req.max_iterations,
            req.max_cost_usd, req.check_interval_seconds,
            req.parent_goal_id, user.email,
            req.schedule_cron, schedule_next_at,
            req.max_completions, req.created_via,
        )
    log.info("Goal created: %s — %s", row["id"], req.title)
    await emit_stimulus("goal.created", {
        "goal_id": str(row["id"]),
        "title": req.title,
        "schedule_cron": req.schedule_cron,
    })
    return _row_to_goal(row)


@goals_router.get("/api/v1/goals", response_model=list[GoalResponse])
async def list_goals(
    _user: UserDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    """List goals, optionally filtered by status."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                "SELECT * FROM goals WHERE status = $1 ORDER BY priority DESC, created_at DESC LIMIT $2",
                status, limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM goals ORDER BY priority DESC, created_at DESC LIMIT $1",
                limit,
            )
    return [_row_to_goal(r) for r in rows]


@goals_router.get("/api/v1/goals/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: UUID, _user: UserDep):
    """Get a single goal by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM goals WHERE id = $1", goal_id)
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
    return _row_to_goal(row)


@goals_router.patch("/api/v1/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(goal_id: UUID, req: UpdateGoalRequest, _user: UserDep):
    """Update a goal (title, status, priority, progress, etc.)."""
    # Build SET clause dynamically from non-None fields
    updates = req.model_dump(exclude_none=True)
    # If cron is being updated, recompute next_at
    if "schedule_cron" in updates:
        cron_val = updates["schedule_cron"]
        if cron_val:
            updates["schedule_next_at"] = _validate_and_compute_next(cron_val)
        else:
            updates["schedule_next_at"] = None
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_parts = []
    values = []
    for i, (key, val) in enumerate(updates.items(), start=1):
        set_parts.append(f"{key} = ${i}")
        values.append(val)

    values.append(goal_id)
    set_clause = ", ".join(set_parts)
    idx = len(values)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE goals SET {set_clause}, updated_at = NOW() WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
    log.info("Goal updated: %s", goal_id)
    return _row_to_goal(row)


@goals_router.delete("/api/v1/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: UUID, _user: UserDep):
    """Cancel and delete a goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM goals WHERE id = $1", goal_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Goal not found")
    log.info("Goal deleted: %s", goal_id)


def _row_to_goal(row) -> GoalResponse:
    return GoalResponse(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        priority=row["priority"],
        progress=row["progress"],
        current_plan=row["current_plan"],
        iteration=row["iteration"],
        max_iterations=row["max_iterations"],
        max_cost_usd=row["max_cost_usd"],
        cost_so_far_usd=row["cost_so_far_usd"],
        check_interval_seconds=row["check_interval_seconds"],
        last_checked_at=row["last_checked_at"],
        parent_goal_id=row["parent_goal_id"],
        schedule_cron=row["schedule_cron"],
        schedule_next_at=row["schedule_next_at"],
        schedule_last_ran_at=row["schedule_last_ran_at"],
        max_completions=row["max_completions"],
        completion_count=row["completion_count"],
        created_via=row["created_via"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
