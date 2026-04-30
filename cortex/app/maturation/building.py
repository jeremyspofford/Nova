"""Building phase — mechanical materializer. No LLM call.

Reads goals.spec_children (set by speccing). For complex goals, INSERTs subgoal rows
under parent_goal_id and advances parent to 'waiting'. For simple goals, creates flat
tasks under goal_tasks and advances directly to 'verifying'.
"""
from __future__ import annotations

import json
import logging

from ..clients import get_orchestrator
from ..config import settings
from ..db import get_pool
from ..journal import emit_journal

log = logging.getLogger(__name__)


async def run_building(goal_id: str) -> str:
    """Materialize spec_children. Returns a one-line outcome description for cycle journal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        goal = await conn.fetchrow(
            """SELECT id, title, description, complexity, depth, max_depth,
                      max_cost_usd, cost_so_far_usd, max_retries, review_policy,
                      scope_analysis, spec_children, parent_goal_id
               FROM goals WHERE id = $1::uuid""",
            goal_id,
        )
    if not goal:
        return f"Building: goal {goal_id} not found"

    children = _decode_jsonb(goal["spec_children"]) or []

    # Depth wall: at max_depth-1, force flat tasks regardless of complexity claim
    at_depth_wall = goal["depth"] >= goal["max_depth"] - 1
    is_simple = goal["complexity"] == "simple" or len(children) == 0 or at_depth_wall

    # Enforce budget cascade. Sum of children.estimated_cost_usd ≤ 0.85 × parent remaining.
    if children and not is_simple:
        children = _cap_children_budget(children, goal)

    if is_simple:
        return await _materialize_as_tasks(goal, children)
    return await _materialize_as_subgoals(goal, children)


def _decode_jsonb(raw):
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _cap_children_budget(children: list[dict], goal) -> list[dict]:
    """Scale children proportionally so sum ≤ 0.85 × parent remaining."""
    parent_remaining = max(0.0, (goal["max_cost_usd"] or 5.0) - (goal["cost_so_far_usd"] or 0.0))
    cap = parent_remaining * 0.85
    total = sum(float(c.get("estimated_cost_usd") or 0.0) for c in children)
    if total <= 0 or total <= cap:
        return children
    ratio = cap / total
    log.warning("Goal %s: child budgets sum to $%.2f > cap $%.2f; scaling by %.2f",
                goal["id"], total, cap, ratio)
    out = []
    for c in children:
        c2 = dict(c)
        c2["estimated_cost_usd"] = float(c.get("estimated_cost_usd") or 0.0) * ratio
        out.append(c2)
    return out


def _inherited_policy(parent, child) -> str:
    """Cascade review_policy with auto-upgrade for security/infra/data scopes.

    Reads the parent's scope_analysis (the child has not been scoped yet — when it
    re-enters maturation it will re-scope and may further upgrade its own policy).
    """
    base = parent["review_policy"]
    if base == "scopes-sensitive":
        return base
    scope = _decode_jsonb(parent["scope_analysis"]) or {}
    affected = scope.get("affected_scopes") or []
    if any(s in affected for s in ("security", "infra", "data")):
        return "scopes-sensitive"
    return base


async def _materialize_as_subgoals(goal, children: list[dict]) -> str:
    """Create child goal rows; advance parent → waiting. Emits journal entries."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for idx, c in enumerate(children):
                hint = c.get("hint") or c.get("description")
                child_plan = {
                    "hint": hint,
                    "depends_on": c.get("depends_on") or [],
                    "spawn_index": idx,
                }
                policy = _inherited_policy(goal, c)
                await conn.execute(
                    """INSERT INTO goals (
                          title, description, parent_goal_id, depth, max_depth,
                          review_policy, max_cost_usd, max_retries,
                          maturation_status, status, created_by, current_plan
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'triaging','active','cortex',$9::jsonb)""",
                    c.get("title") or f"subgoal {idx + 1}",
                    c.get("description") or "",
                    goal["id"],
                    goal["depth"] + 1,
                    goal["max_depth"],
                    policy,
                    float(c.get("estimated_cost_usd") or 0.0) or None,
                    goal["max_retries"],
                    json.dumps(child_plan),
                )
            await conn.execute(
                "UPDATE goals SET maturation_status = 'waiting', updated_at = NOW() WHERE id = $1::uuid",
                goal["id"],
            )

    await emit_journal(str(goal["id"]), "building.complete", {"children_count": len(children)})
    for idx, c in enumerate(children):
        await emit_journal(str(goal["id"]), "subgoal.spawned",
            {"index": idx, "title": c.get("title"), "estimated_cost_usd": c.get("estimated_cost_usd")})
    return f"Building: spawned {len(children)} subgoals → waiting"


async def _materialize_as_tasks(goal, children: list[dict]) -> str:
    """For simple/leaf goals: create pipeline tasks; advance to verifying."""
    pool = get_pool()
    orch = get_orchestrator()

    # If children list is empty, fall back to a single task representing the whole goal.
    if not children:
        children = [{"title": goal["title"], "description": goal["description"] or "",
                     "hint": "(simple goal — single task)"}]

    task_ids = []
    for idx, c in enumerate(children):
        body = (
            f"[Cortex goal] {c.get('title') or goal['title']}: "
            f"{c.get('hint') or c.get('description') or '(no detail)'}"
        )
        try:
            r = await orch.post(
                "/api/v1/tasks",
                json={"user_input": body, "goal_id": str(goal["id"]),
                      "metadata": {"source": "cortex.building", "child_index": idx}},
                headers={"Authorization": f"Bearer {settings.cortex_api_key}"},
            )
            r.raise_for_status()
            task_ids.append(r.json().get("task_id"))
        except Exception as e:
            log.warning("Task dispatch failed for goal %s child %d: %s", goal["id"], idx, e)

    async with pool.acquire() as conn:
        async with conn.transaction():
            for idx, task_id in enumerate(task_ids):
                if task_id is None:
                    continue
                await conn.execute(
                    """INSERT INTO goal_tasks (goal_id, task_id, sequence, status)
                       VALUES ($1::uuid, $2::uuid, $3, 'pending')
                       ON CONFLICT (goal_id, task_id) DO NOTHING""",
                    goal["id"], task_id, idx,
                )
            await conn.execute(
                "UPDATE goals SET maturation_status = 'verifying', updated_at = NOW() WHERE id = $1::uuid",
                goal["id"],
            )

    await emit_journal(str(goal["id"]), "building.tasks_dispatched", {"task_count": len(task_ids)})
    return f"Building: dispatched {len(task_ids)} tasks → verifying"
