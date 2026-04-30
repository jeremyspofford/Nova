"""Goal CRUD endpoints — used by dashboard and cortex."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from app.auth import UserDep
from app.db import get_pool
from app.intel_router import CreateCommentRequest
from app.stimulus import (
    GOAL_COMMENTED,
    GOAL_CREATED,
    GOAL_SPEC_APPROVED,
    GOAL_SPEC_REJECTED,
    emit_stimulus,
)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
    scope_analysis: dict | None = None  # admin-only seeding for maturation tests
    spec: str | None = None              # admin-only seeding for maturation tests
    spec_rejection_feedback: str | None = None  # admin-only seeding for maturation tests
    # New fields for goal decomposition (migration 067)
    spec_children: list[dict] | None = None
    verification_commands: list[dict] | None = None
    success_criteria_structured: list[dict] | None = None
    review_policy: str | None = None
    depth: int | None = None
    max_depth: int | None = None
    max_retries: int | None = None
    retry_count: int | None = None
    spec_approved_at: datetime | None = None
    spec_approved_by: str | None = None


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
    spec_rejection_feedback: str | None = None
    spec_approved_at: datetime | None = None
    spec_approved_by: str | None = None
    source_recommendation_id: UUID | None = None
    spec_children: list[dict] | None = None
    verification_commands: list[dict] | None = None
    success_criteria_structured: list[dict] | None = None
    review_policy: str | None = None
    depth: int | None = None
    max_depth: int | None = None
    max_retries: int | None = None
    retry_count: int | None = None


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
    await emit_stimulus(GOAL_CREATED, {
        "goal_id": str(row["id"]),
        "title": req.title,
        "schedule_cron": req.schedule_cron,
    })
    return _row_to_goal(row)


@goals_router.get("/api/v1/goals", response_model=list[GoalResponse])
async def list_goals(
    _user: UserDep,
    status: str | None = Query(default=None),
    parent_goal_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    """List goals, optionally filtered by status and/or parent_goal_id."""
    pool = get_pool()
    where: list[str] = []
    args: list = []
    if status:
        where.append(f"status = ${len(args) + 1}")
        args.append(status)
    if parent_goal_id:
        where.append(f"parent_goal_id = ${len(args) + 1}::uuid")
        args.append(parent_goal_id)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    args.append(limit)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM goals{where_clause} ORDER BY priority DESC, created_at DESC LIMIT ${len(args)}",
            *args,
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
    # Columns stored as JSONB need explicit cast + JSON-serialized text so asyncpg
    # doesn't reject dict/list values.
    JSONB_COLUMNS = {
        "scope_analysis",
        "spec_children",
        "verification_commands",
        "success_criteria_structured",
    }
    for i, (key, val) in enumerate(updates.items(), start=1):
        if key in JSONB_COLUMNS and isinstance(val, (dict, list)):
            set_parts.append(f"{key} = ${i}::jsonb")
            values.append(json.dumps(val))
        else:
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
async def delete_goal(
    goal_id: UUID,
    _user: UserDep,
    cascade: bool = Query(default=False),
):
    """Cancel and delete a goal.

    When cascade=true, recursively delete all subgoals. The parent_goal_id
    foreign key uses NO ACTION (Postgres default — neither CASCADE nor
    SET NULL), so we explicitly recurse to clean the subtree.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        created_via = await conn.fetchval("SELECT created_via FROM goals WHERE id = $1", goal_id)
        if created_via == "system":
            raise HTTPException(status_code=403, detail="System goals cannot be deleted")
        async with conn.transaction():
            if cascade:
                # Repeatedly delete leaves under the subtree until none remain.
                while True:
                    deleted = await conn.execute(
                        """DELETE FROM goals WHERE id IN (
                               WITH RECURSIVE descendants AS (
                                   SELECT id FROM goals WHERE parent_goal_id = $1
                                   UNION ALL
                                   SELECT g.id FROM goals g
                                   JOIN descendants d ON g.parent_goal_id = d.id
                               )
                               SELECT id FROM descendants
                           )""",
                        goal_id,
                    )
                    if deleted == "DELETE 0":
                        break
            result = await conn.execute("DELETE FROM goals WHERE id = $1", goal_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Goal not found")
    log.info("Goal deleted: %s (cascade=%s)", goal_id, cascade)


def _row_to_goal(row) -> GoalResponse:
    plan = row["current_plan"]
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except (json.JSONDecodeError, TypeError):
            plan = None
    scope = row.get("scope_analysis")
    if isinstance(scope, str):
        try:
            scope = json.loads(scope)
        except (json.JSONDecodeError, TypeError):
            scope = None
    spec_children = row.get("spec_children")
    if isinstance(spec_children, str):
        try:
            spec_children = json.loads(spec_children)
        except (json.JSONDecodeError, TypeError):
            spec_children = None
    verification_commands = row.get("verification_commands")
    if isinstance(verification_commands, str):
        try:
            verification_commands = json.loads(verification_commands)
        except (json.JSONDecodeError, TypeError):
            verification_commands = None
    success_criteria_structured = row.get("success_criteria_structured")
    if isinstance(success_criteria_structured, str):
        try:
            success_criteria_structured = json.loads(success_criteria_structured)
        except (json.JSONDecodeError, TypeError):
            success_criteria_structured = None
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
        scope_analysis=scope,
        spec=row.get("spec"),
        spec_rejection_feedback=row.get("spec_rejection_feedback"),
        spec_approved_at=row.get("spec_approved_at"),
        spec_approved_by=row.get("spec_approved_by"),
        source_recommendation_id=row.get("source_recommendation_id"),
        spec_children=spec_children,
        verification_commands=verification_commands,
        success_criteria_structured=success_criteria_structured,
        review_policy=row.get("review_policy"),
        depth=row.get("depth"),
        max_depth=row.get("max_depth"),
        max_retries=row.get("max_retries"),
        retry_count=row.get("retry_count"),
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
    """Approve a goal's spec.

    Routes directly to 'verifying' — the building phase (sub-goal spawn) is
    deferred until goal decomposition lands. Until then, humans implement the
    approved spec manually, then 'verifying' kicks in to validate the result.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE goals SET maturation_status = 'verifying',
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
    """Get scope analysis for a goal.

    asyncpg returns JSONB as a string by default (no codec registered), so we
    decode it here to ensure callers get a dict — mirroring _row_to_goal()'s
    defensive decoding for the same column.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT scope_analysis FROM goals WHERE id = $1", goal_id)
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
    raw = row["scope_analysis"]
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return raw  # already a dict (asyncpg may return dict if codec registered later)


# ── Goal Iterations & Artifacts ──────────────────────────────────────────────

@goals_router.get("/api/v1/goals/{goal_id}/iterations")
async def list_goal_iterations(
    goal_id: UUID, _user: UserDep,
    limit: int = Query(default=50),
    offset: int = Query(default=0),
):
    """List goal iteration history for timeline display."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, goal_id, attempt, cycle_number, plan_text,
                      task_id, task_status, task_summary, cost_usd,
                      files_touched, plan_adjustment, created_at
               FROM goal_iterations
               WHERE goal_id = $1
               ORDER BY attempt DESC
               LIMIT $2 OFFSET $3""",
            goal_id, limit, offset,
        )
    return [dict(r) for r in rows]


@goals_router.get("/api/v1/goals/{goal_id}/artifacts")
async def list_goal_artifacts(goal_id: UUID, _user: UserDep):
    """List all artifacts across all tasks for a goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT a.*,
                      (SELECT gi.attempt FROM goal_iterations gi
                       WHERE gi.task_id = a.task_id LIMIT 1) as attempt
               FROM artifacts a
               JOIN tasks t ON a.task_id = t.id
               WHERE t.goal_id = $1
               ORDER BY a.created_at DESC""",
            goal_id,
        )
    return [dict(r) for r in rows]
