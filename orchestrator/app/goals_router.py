"""Goal CRUD endpoints — used by dashboard and cortex."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import UserDep
from app.db import get_pool
from app.intel_router import CreateCommentRequest
from app.stimulus import GOAL_COMMENTED, GOAL_SPEC_APPROVED, GOAL_SPEC_REJECTED, emit_stimulus

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
    success_criteria: str | None = None
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
    success_criteria: str | None = None
    status: str | None = None
    priority: int | None = None
    progress: float | None = None
    max_iterations: int | None = None
    max_cost_usd: float | None = None
    check_interval_seconds: int | None = None
    schedule_cron: str | None = Field(default=None, description="Cron expression or None to clear")
    max_completions: int | None = None
    complexity: str | None = None
    maturation_status: str | None = None


class GoalResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    success_criteria: str | None
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
    maturation_status: str | None = None
    complexity: str | None = None
    scope_analysis: dict | None = None
    spec: str | None = None
    spec_approved_at: datetime | None = None
    spec_approved_by: str | None = None
    source_recommendation_id: UUID | None = None


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
            INSERT INTO goals (title, description, success_criteria, priority,
                               max_iterations, max_cost_usd, check_interval_seconds,
                               parent_goal_id, created_by, schedule_cron,
                               schedule_next_at, max_completions, created_via)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING *
            """,
            req.title, req.description, req.success_criteria, req.priority,
            req.max_iterations, req.max_cost_usd, req.check_interval_seconds,
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


@goals_router.get("/api/v1/goals/stats")
async def goal_stats(_user: UserDep) -> dict:
    """Aggregate goal statistics for the dashboard."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE status = 'active') AS active,
              COUNT(*) FILTER (WHERE status = 'completed') AS completed,
              COUNT(*) FILTER (WHERE status = 'failed') AS failed,
              COUNT(*) FILTER (WHERE status = 'paused') AS paused,
              COALESCE(AVG(iteration) FILTER (WHERE status IN ('completed','failed')), 0) AS avg_iterations,
              COALESCE(AVG(cost_so_far_usd) FILTER (WHERE status IN ('completed','failed')), 0)::float AS avg_cost_usd,
              COALESCE(SUM(cost_so_far_usd), 0)::float AS total_cost_usd
            FROM goals
            """
        )
    total_terminal = (row["completed"] or 0) + (row["failed"] or 0)
    success_rate = (
        round((row["completed"] or 0) / total_terminal, 4)
        if total_terminal > 0 else 0.0
    )
    return {
        "active": row["active"] or 0,
        "completed": row["completed"] or 0,
        "failed": row["failed"] or 0,
        "paused": row["paused"] or 0,
        "success_rate": success_rate,
        "avg_iterations": round(float(row["avg_iterations"]), 1),
        "avg_cost_usd": round(row["avg_cost_usd"], 6),
        "total_cost_usd": round(row["total_cost_usd"], 6),
    }


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
    updates = req.model_dump(exclude_unset=True)
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

    # Emit activity event on status changes
    if "status" in updates:
        try:
            from app.activity import emit_activity
            new_status = updates["status"]
            severity = "warning" if new_status == "failed" else "info"
            await emit_activity(
                pool, "goal_status_changed", "orchestrator",
                f"Goal '{row['title'][:60]}' status changed to {new_status}",
                severity=severity,
                metadata={"goal_id": str(goal_id), "status": new_status},
            )
        except Exception:
            pass

    return _row_to_goal(row)


@goals_router.delete("/api/v1/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: UUID, _user: UserDep):
    """Cancel and delete a goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        created_via = await conn.fetchval("SELECT created_via FROM goals WHERE id = $1", goal_id)
        if created_via == "system":
            raise HTTPException(status_code=403, detail="System goals cannot be deleted")
        result = await conn.execute("DELETE FROM goals WHERE id = $1", goal_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Goal not found")
    log.info("Goal deleted: %s", goal_id)


def _row_to_goal(row) -> GoalResponse:
    plan = row["current_plan"]
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except (json.JSONDecodeError, TypeError):
            plan = None
    return GoalResponse(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        success_criteria=row.get("success_criteria"),
        status=row["status"],
        priority=row["priority"],
        progress=row["progress"],
        current_plan=plan,
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
        maturation_status=row.get("maturation_status"),
        complexity=row.get("complexity"),
        scope_analysis=row.get("scope_analysis"),
        spec=row.get("spec"),
        spec_approved_at=row.get("spec_approved_at"),
        spec_approved_by=row.get("spec_approved_by"),
        source_recommendation_id=row.get("source_recommendation_id"),
    )


# ── Goal Comments ─────────────────────────────────────────────────────────────

@goals_router.get("/api/v1/goals/{goal_id}/comments")
async def list_goal_comments(
    goal_id: UUID, _user: UserDep,
    limit: int = Query(default=50),
    offset: int = Query(default=0),
):
    """List comments on a goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM comments
               WHERE entity_type = 'goal' AND entity_id = $1
               ORDER BY created_at ASC LIMIT $2 OFFSET $3""",
            goal_id, limit, offset,
        )
    return [dict(r) for r in rows]


@goals_router.post("/api/v1/goals/{goal_id}/comments", status_code=201)
async def create_goal_comment(goal_id: UUID, req: CreateCommentRequest, _user: UserDep):
    """Add a comment to a goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO comments (entity_type, entity_id, author_type, author_name, body)
               VALUES ('goal', $1, $2, $3, $4)
               RETURNING *""",
            goal_id, req.author_type, req.author_name, req.body,
        )
    if req.author_type == "human":
        await emit_stimulus(GOAL_COMMENTED, {"goal_id": str(goal_id), "comment_id": str(row["id"])})
    return dict(row)


@goals_router.delete("/api/v1/goals/{goal_id}/comments/{comment_id}", status_code=204)
async def delete_goal_comment(goal_id: UUID, comment_id: UUID, _user: UserDep):
    """Delete a comment from a goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM comments WHERE id = $1 AND entity_type = 'goal' AND entity_id = $2",
            comment_id, goal_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Comment not found")


# ── Goal Maturation ──────────────────────────────────────────────────────────

@goals_router.post("/api/v1/goals/{goal_id}/approve-spec")
async def approve_spec(goal_id: UUID, _user: UserDep):
    """Approve a goal's spec, advancing maturation to 'building'."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE goals SET maturation_status = 'building',
                   spec_approved_at = NOW(), spec_approved_by = $1, updated_at = NOW()
               WHERE id = $2 AND maturation_status = 'review'
               RETURNING *""",
            _user.email, goal_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found or not in review status")
    await emit_stimulus(GOAL_SPEC_APPROVED, {"goal_id": str(goal_id)})
    return _row_to_goal(row)


class RejectSpecRequest(BaseModel):
    feedback: str


@goals_router.post("/api/v1/goals/{goal_id}/reject-spec")
async def reject_spec(goal_id: UUID, req: RejectSpecRequest, _user: UserDep):
    """Reject a goal's spec, sending it back to speccing with feedback."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE goals SET maturation_status = 'speccing', updated_at = NOW()
               WHERE id = $1 AND maturation_status = 'review'
               RETURNING *""",
            goal_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found or not in review status")
    # Post the feedback as a comment
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO comments (entity_type, entity_id, author_type, author_name, body)
               VALUES ('goal', $1, 'human', $2, $3)""",
            goal_id, _user.email, f"Spec rejected: {req.feedback}",
        )
    await emit_stimulus(GOAL_SPEC_REJECTED, {"goal_id": str(goal_id), "feedback": req.feedback})
    return _row_to_goal(row)


@goals_router.get("/api/v1/goals/{goal_id}/scope")
async def get_goal_scope(goal_id: UUID, _user: UserDep):
    """Get scope analysis for a goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT scope_analysis FROM goals WHERE id = $1", goal_id)
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
    return row["scope_analysis"] or {}
