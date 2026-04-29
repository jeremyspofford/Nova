# Cortex Goal Decomposition + Maturation Executor (Phase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement goal decomposition (parent_goal_id tree) + the missing `building` maturation phase + multi-signal verification, so Cortex can break complex goals into recursive subgoals, materialize them, execute, verify, and recover from failures autonomously.

**Architecture:** Goals form a tree via the existing `goals.parent_goal_id`. Speccing now returns a JSON envelope: markdown narrative for humans plus structured `spec_children`/`verification_commands`/`success_criteria_structured` for machines. New `cortex/app/maturation/building.py` materializes the children — INSERTs subgoal rows for complex goals, task rows for simple goals — and advances the parent to a new `waiting` maturation phase. A parent in `waiting` resumes when all its children terminate. Verifying becomes multi-signal (commands + a Quartet code-review pass + structured criteria evaluator → PASS/FAIL/human-review). Failures re-spec once with reflection (`max_retries=2`), then escalate via the parent's `review_policy`. Reuses existing `reflections`, `check_approach_blocked`, stimulus, and journal infra. No parallel machinery.

**Tech Stack:** Python 3.11 (FastAPI + asyncpg + httpx), React + TypeScript + Tailwind for dashboard, Postgres 16, existing cortex/orchestrator/llm-gateway/memory-service stack. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-28-cortex-goal-decomposition-design.md`

**Builds on:** `docs/superpowers/plans/2026-04-27-goal-maturation-executor.md` (Phase 1-3 + 5 already delivered: triaging, scoping, speccing, health-check-only verifying). This plan adds Phase 4 (`building`) and rewrites the verifying executor to multi-signal.

**Out of scope (deferred to v2 per spec):** Rich nested tree visualization in dashboard, rich escalation reflection card, goal templates, cross-goal dependency, runtime auto-promotion, resource-aware concurrency.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `orchestrator/app/migrations/067_goal_decomposition.sql` | Create | Schema additions, `goal_verifications` table, `max_cost_usd` default+backfill, `maturation_status` constraint update. **Number is 067** because 064/065/066 are already taken by `brain_default_off`, `quality_v2`, `quality_loop_sessions`. Re-check at implementation time and bump if newer migrations have landed. |
| `orchestrator/app/goals_router.py` | Modify | Extend `UpdateGoalRequest` with new columns (spec_children, verification_commands, success_criteria_structured, review_policy, depth, max_depth, max_retries, retry_count) so tests can seed state. Extend `_row_to_goal` and `GoalResponse` to round-trip them. Add `parent_goal_id` query param to `list_goals`. Add `cascade` query param to `delete_goal`. |
| `cortex/app/maturation/building.py` | Create | Mechanical materializer; subgoals for complex, tasks for simple, depth wall, budget cascade |
| `cortex/app/maturation/verifying.py` | Rewrite | Multi-signal verifier replacing health-check stub |
| `cortex/app/maturation/aggregator.py` | Create | Pure-function aggregator combining (cmd_results, quartet_review, criteria_eval) → outcome |
| `cortex/app/maturation/commands.py` | Create | Verification command runner — async subprocess with timeout |
| `cortex/app/maturation/criteria.py` | Create | Structured criteria evaluator; check kinds: `command` / `engram_query` / `llm_judge` |
| `cortex/app/journal.py` | Modify | Add `emit_journal()` and `emit_notification()` helpers wrapping `write_entry` and websocket path |
| `cortex/app/stimulus.py` | Modify | Add `SUBGOAL_TERMINATED` stimulus and parent-wakeup handler |
| `cortex/app/cycle.py` | Modify | Add `building`+`waiting` routes in `_execute_serve`; child-readiness checker |
| `cortex/app/drives/serve.py` | Modify | Stale-goal query filters: skip `waiting` parents and dep-blocked children |
| `cortex/app/maturation/speccing.py` | Modify | Rewrite prompt to emit JSON envelope; preserve markdown narrative; backward-compat fallback |
| `cortex/app/router.py` | Modify | Add review comment endpoint (approve/reject already exist via orchestrator) |
| `dashboard/src/components/MaturationStages.tsx` | Create | New stepper component (referenced inline in Goals.tsx today) |
| `dashboard/src/components/GoalMaturationDetail.tsx` | Modify | Show review-policy reason + spec_children cards + verification commands |
| `dashboard/src/pages/Goals.tsx` | Modify | Spawned-children affordance line under parent goal cards |
| `tests/test_decomposition_lifecycle.py` | Create | E2E: complex goal → tree → execute → verify |
| `tests/test_decomposition_failure_recovery.py` | Create | Force verify failure → re-spec → escalate per policy |
| `tests/test_decomposition_simple_path.py` | Create | Simple goal flat-task path |
| `tests/test_review_policies.py` | Create | Policy variants cascade correctly |
| `tests/test_verification_aggregator.py` | Create | Aggregator unit tests |
| `tests/test_depth_limit.py` | Create | At max_depth-1, complex children forced flat |
| `tests/test_journal_completeness.py` | Create | Every documented transition emits the named event |

---

## Phase 1: Schema Foundation

### Task 1: Write migration 064

**Files:**
- Create: `orchestrator/app/migrations/067_goal_decomposition.sql`

The orchestrator runs all migrations idempotently at startup. This single file adds every schema change the rest of the plan depends on.

- [ ] **Step 1: Create the migration file**

```sql
-- Migration 067: goal decomposition + maturation executor
-- Builds on the latest sequential baseline (063 goal_maturation_feedback_columns,
-- 064 brain_default_off, 065 quality_v2, 066 quality_loop_sessions).
-- Re-verify the number at implementation time; bump if newer migrations have landed.
-- All ADDs are idempotent.

-- ── Structured artifacts produced by speccing ────────────────────────────────
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_children JSONB;
COMMENT ON COLUMN goals.spec_children IS
    'Immediate children planned by speccing. JSON array of '
    '{title, description, hint, depends_on:[indices], estimated_cost_usd, estimated_complexity}.';

ALTER TABLE goals ADD COLUMN IF NOT EXISTS verification_commands JSONB;
COMMENT ON COLUMN goals.verification_commands IS
    'Shell commands the verifier runs to prove this goal completed. '
    'JSON array of {cmd, cwd, timeout_s}.';

ALTER TABLE goals ADD COLUMN IF NOT EXISTS success_criteria_structured JSONB;
COMMENT ON COLUMN goals.success_criteria_structured IS
    'Machine-evaluable criteria. Array of {statement, check, check_arg} where '
    'check ∈ (''command'', ''engram_query'', ''llm_judge''). '
    'Legacy success_criteria TEXT remains; verifier reads structured first, falls back to TEXT.';

-- ── Review + retry policy ────────────────────────────────────────────────────
ALTER TABLE goals ADD COLUMN IF NOT EXISTS review_policy TEXT NOT NULL DEFAULT 'cost-above-2'
    CHECK (review_policy IN ('top-only', 'all', 'cost-above-2', 'cost-above-5', 'scopes-sensitive'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS max_depth INTEGER NOT NULL DEFAULT 5;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS depth INTEGER NOT NULL DEFAULT 0;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 2;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;

-- ── Maturation phase: add 'waiting' (parent blocked on children) ─────────────
ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_maturation_status_check;
ALTER TABLE goals ADD CONSTRAINT goals_maturation_status_check
    CHECK (maturation_status IS NULL OR maturation_status IN
        ('triaging', 'scoping', 'speccing', 'review', 'building', 'waiting', 'verifying'));

-- ── Per-attempt verification record ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS goal_verifications (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id        UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    attempt        INTEGER NOT NULL,
    cmd_results    JSONB,    -- [{cmd, exit_code, stdout_tail, stderr_tail, duration_ms}]
    quartet_review JSONB,    -- {confidence, verdict, summary, task_id}
    criteria_eval  JSONB,    -- [{statement, pass, evidence}]
    aggregate      TEXT NOT NULL CHECK (aggregate IN ('pass', 'fail', 'human-review')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS goal_verifications_goal_idx ON goal_verifications(goal_id);

-- ── Index for cycle's "find parent ready to verify" query ───────────────────
CREATE INDEX IF NOT EXISTS goals_parent_status_idx
    ON goals(parent_goal_id, status) WHERE parent_goal_id IS NOT NULL;

-- ── max_cost_usd: default + backfill so building.py cascade can't NoneType ──
ALTER TABLE goals ALTER COLUMN max_cost_usd SET DEFAULT 5.00;
UPDATE goals SET max_cost_usd = 5.00 WHERE max_cost_usd IS NULL AND status = 'active';
```

- [ ] **Step 2: Restart orchestrator to run the migration**

Run: `docker compose restart orchestrator && docker compose logs --tail 50 orchestrator | grep -i migration`
Expected: log line `Applied migration 067_goal_decomposition.sql` (or "already applied" on a re-run).

- [ ] **Step 3: Verify schema**

Run:
```bash
docker compose exec postgres psql -U nova -d nova -c "\d goals" | grep -E "spec_children|verification_commands|review_policy|max_depth|retry_count"
docker compose exec postgres psql -U nova -d nova -c "\dt goal_verifications"
docker compose exec postgres psql -U nova -d nova -c "SELECT COUNT(*) FROM goals WHERE max_cost_usd IS NULL AND status = 'active';"
```
Expected: 5 rows for the column grep, 1 row showing `goal_verifications` exists, count = 0.

- [ ] **Step 4: Commit**

```bash
git add -f orchestrator/app/migrations/067_goal_decomposition.sql
git commit -m "feat(migrations): 067 — goal decomposition + maturation executor schema"
```

---

## Phase 2: Journal + Notification Helpers

### Task 2: Add `emit_journal` and `emit_notification` helpers

**Files:**
- Modify: `cortex/app/journal.py`
- Test: `tests/test_journal_completeness.py` (created later in Task 25; placeholder for now)

These are thin wrappers that the rest of the code calls. Centralising the shape lets us filter journal entries by event in queries.

- [ ] **Step 1: Read existing journal.py to find `write_entry`**

Run: `grep -n "def write_entry\|def read_user_replies" cortex/app/journal.py`
Note the signature of `write_entry` (the existing journal writer).

- [ ] **Step 2: Add `emit_journal` helper at the bottom of journal.py**

```python
async def emit_journal(
    goal_id: str | None,
    event: str,
    payload: dict | None = None,
) -> None:
    """Structured journal entry for goal-lifecycle events.

    Wraps write_entry so journal queries can filter by event/goal_id.
    Body shape: 'event=<event> goal=<id> payload=<json>'
    Metadata: {event, goal_id, payload}
    """
    content = f"event={event} goal={goal_id or '-'}"
    if payload:
        content += f" payload={json.dumps(payload, default=str)}"
    metadata = {"event": event, "goal_id": str(goal_id) if goal_id else None}
    if payload:
        metadata["payload"] = payload
    try:
        # write_entry signature (cortex/app/journal.py:17):
        #   write_entry(content: str, entry_type: str = "narration", metadata: dict | None = None)
        await write_entry(content=content, entry_type="goal_event", metadata=metadata)
    except Exception as e:
        # Journal failures must never break the maturation pipeline.
        log.warning("emit_journal failed (event=%s goal=%s): %s", event, goal_id, e)
```

- [ ] **Step 3: Add `emit_notification` helper**

```python
async def emit_notification(
    goal_id: str,
    kind: str,
    title: str,
    link: str | None = None,
) -> None:
    """Publish a goal notification to the existing nova:notifications Redis pub/sub channel.

    Existing consumers:
      - orchestrator/app/pipeline_router.py:1232 — SSE stream subscribes to nova:notifications
      - orchestrator/app/auto_friction.py:28 — friction logger subscribes to the same channel

    Dashboard reads the SSE stream at GET /api/v1/pipeline/notifications/stream.
    No new HTTP endpoint or websocket plumbing required.
    """
    from .clients import get_redis
    payload = {
        "kind": kind,
        "goal_id": str(goal_id),
        "title": title,
        "link": link or f"/goals/{goal_id}",
    }
    try:
        redis = await get_redis()
        await redis.publish("nova:notifications", json.dumps(payload))
    except Exception as e:
        log.warning("emit_notification failed (kind=%s goal=%s): %s", kind, goal_id, e)
```

- [ ] **Step 4: Add `import json` if not present**

Run: `head -10 cortex/app/journal.py | grep "import json"` — if absent, add it.

- [ ] **Step 5: Commit**

```bash
git add -f cortex/app/journal.py
git commit -m "feat(cortex): emit_journal + emit_notification helpers for maturation events"
```

---

## Phase 3: Speccing JSON Envelope Rewrite

### Task 3: Failing test — speccing produces structured output

**Files:**
- Create: `tests/test_decomposition_speccing.py`

- [ ] **Step 1: Write the failing test**

```python
"""Speccing produces a JSON envelope with spec_children + verification_commands + criteria."""
import asyncio
import os
import pytest
import httpx

ORCH = os.getenv("NOVA_ORCH_URL", "http://localhost:8000")
ADMIN = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
HEADERS = {"X-Admin-Secret": ADMIN}


@pytest.mark.asyncio
async def test_speccing_produces_structured_output():
    """A goal advanced past speccing has spec_children populated with the right shape."""
    # Create a complex goal manually parked at 'speccing' phase
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ORCH}/api/v1/goals", headers=HEADERS, json={
            "title": "nova-test-decomp speccing structured output",
            "description": "Add a /healthz alias on orchestrator next to /health/ready",
            "max_cost_usd": 5.00,
        })
        r.raise_for_status()
        goal_id = r.json()["id"]

        # Force into speccing phase via PATCH (test-only path; speccing.py picks up next cycle)
        await c.patch(f"{ORCH}/api/v1/goals/{goal_id}", headers=HEADERS,
            json={"maturation_status": "speccing",
                  "scope_analysis": {"affected_scopes": ["backend"], "estimated_files_changed": 1}})

        # Wait for a cortex cycle to advance it (speccing → review on success)
        for _ in range(60):
            await asyncio.sleep(2)
            g = (await c.get(f"{ORCH}/api/v1/goals/{goal_id}", headers=HEADERS)).json()
            if g.get("maturation_status") in ("review", None) or g.get("status") == "failed":
                break

        # Cleanup happens via fixture teardown; for now just delete
        try:
            assert g.get("spec_children") is not None, \
                "speccing should populate spec_children with structured JSON"
            children = g["spec_children"]
            assert isinstance(children, list) and len(children) >= 1
            for c_item in children:
                assert "title" in c_item and "description" in c_item
                assert "depends_on" in c_item and isinstance(c_item["depends_on"], list)
                assert "estimated_cost_usd" in c_item
            assert g.get("verification_commands") is not None, \
                "speccing should produce verification_commands"
            assert isinstance(g["verification_commands"], list)
            assert g.get("success_criteria_structured") is not None
        finally:
            await c.delete(f"{ORCH}/api/v1/goals/{goal_id}", headers=HEADERS)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_decomposition_speccing.py -v -m "not slow"`
Expected: FAIL — `spec_children` is None (speccing doesn't populate it yet).

### Task 4: Rewrite speccing.py to emit JSON envelope

**Files:**
- Modify: `cortex/app/maturation/speccing.py`

The current `SPEC_PROMPT` returns markdown. We replace it with a JSON-envelope prompt while preserving the markdown narrative inside the envelope for the human review modal.

- [ ] **Step 1: Replace `SPEC_PROMPT`**

Replace the existing `SPEC_PROMPT` constant in `cortex/app/maturation/speccing.py` with:

```python
SPEC_PROMPT = """Generate an engineering plan for this goal.

Goal: {title}
Description: {description}

Scope analysis (already produced):
{scope_analysis}

Parent goal hint (if any, treat as starting context, not a constraint):
{parent_hint}

You are at depth {depth} of {max_depth}. If you're close to max_depth, prefer flat task-sized
children (single-file changes) over deep recursion.

Respond with a single JSON object exactly matching this shape (no markdown fences, no preamble):

{{
  "spec_markdown": "<2-page markdown narrative for human review: architecture, file changes table, sub-tasks in dependency order, cost estimate, open questions>",
  "spec_children": [
    {{
      "title": "<short imperative>",
      "description": "<2-3 sentences>",
      "hint": "<one-line nudge for the child's own scoping>",
      "depends_on": [<int indices into spec_children>],
      "estimated_cost_usd": <float>,
      "estimated_complexity": "<simple|complex>"
    }}
  ],
  "verification_commands": [
    {{"cmd": "<shell command>", "cwd": null, "timeout_s": <int>}}
  ],
  "success_criteria_structured": [
    {{"statement": "<plain english>", "check": "<command|engram_query|llm_judge>", "check_arg": "<command-or-query-or-prompt>"}}
  ]
}}

Rules:
- Sum of children.estimated_cost_usd MUST be ≤ 0.85 × parent_max_cost (you have ${max_cost} parent budget).
- depends_on indices must reference valid earlier entries in spec_children.
- estimated_complexity='simple' children get materialized as flat tasks (no further recursion).
- Verification commands should be runnable with no human in the loop (no interactive prompts).
- Keep spec_markdown under 1500 words.
"""
```

- [ ] **Step 2: Replace `run_speccing` body**

Replace the existing `run_speccing` function with:

```python
async def run_speccing(goal_id: str) -> dict | None:
    """Generate spec, write spec_markdown + spec_children + verification_commands + criteria.

    Transitions: speccing → review on success.
    On hard failure: writes minimal markdown-only envelope and forces complexity='simple' so
    building can flat-materialize in a recovery path.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        goal = await conn.fetchrow(
            """SELECT title, description, scope_analysis, max_cost_usd, depth, max_depth, current_plan
               FROM goals WHERE id = $1::uuid""",
            goal_id,
        )
    if not goal or not goal["scope_analysis"]:
        log.warning("Speccing called without scope_analysis for goal %s", goal_id)
        return None

    scope_raw = goal["scope_analysis"]
    if isinstance(scope_raw, str):
        try:
            scope_str = json.dumps(json.loads(scope_raw), indent=2)
        except json.JSONDecodeError:
            scope_str = scope_raw
    else:
        scope_str = json.dumps(scope_raw, indent=2)

    parent_hint = ""
    plan = goal["current_plan"] or {}
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            plan = {}
    if isinstance(plan, dict):
        parent_hint = plan.get("hint", "") or "(none)"

    prompt = SPEC_PROMPT.format(
        title=goal["title"],
        description=goal["description"] or "(no description)",
        scope_analysis=scope_str,
        parent_hint=parent_hint,
        depth=goal["depth"],
        max_depth=goal["max_depth"],
        max_cost=f"{goal['max_cost_usd']:.2f}",
    )

    llm = get_llm()
    envelope: dict | None = None
    for attempt, temp in enumerate((0.2, 0.4, 0.6), start=1):
        resp = await llm.post(
            "/complete",
            json={
                "model": settings.planning_model or "",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp,
                "max_tokens": 4000,
                "tier": "best",
                "response_format": {"type": "json_object"},
            },
            timeout=240.0,
        )
        if resp.status_code != 200:
            log.warning("Speccing LLM returned %d for goal %s (attempt %d)",
                        resp.status_code, goal_id, attempt)
            continue
        content = resp.json().get("content", "").strip()
        if not content:
            log.warning("Speccing returned empty for goal %s (attempt %d)", goal_id, attempt)
            continue
        try:
            parsed = json.loads(content)
            # Validate envelope shape minimally
            if (isinstance(parsed, dict)
                and parsed.get("spec_markdown")
                and isinstance(parsed.get("spec_children"), list)):
                envelope = parsed
                break
            log.warning("Speccing envelope malformed for goal %s (attempt %d)", goal_id, attempt)
        except json.JSONDecodeError as e:
            log.warning("Speccing JSON decode failed for goal %s (attempt %d): %s",
                        goal_id, attempt, e)

    if envelope is None:
        # Hard fallback — write minimal envelope so the goal can still advance.
        # Mark complexity='simple' so building treats it as a flat-task leaf,
        # bypassing further LLM rounds that would presumably also fail.
        log.warning("Speccing exhausted retries for goal %s; writing minimal envelope", goal_id)
        envelope = {
            "spec_markdown": (
                f"## Speccing Deferred\n\n"
                f"LLM returned no usable structured output after 3 retries for goal "
                f"`{goal['title']}`.\n\n"
                f"Description: {goal['description'] or '(none)'}\n\n"
                f"Action: review manually before approving."
            ),
            "spec_children": [],
            "verification_commands": [],
            "success_criteria_structured": [],
            "_fallback": True,
        }

    # Persist all four artifacts + advance to review
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET
                  spec = $1,
                  spec_children = $2::jsonb,
                  verification_commands = $3::jsonb,
                  success_criteria_structured = $4::jsonb,
                  complexity = COALESCE(complexity, CASE WHEN $5 THEN 'simple' ELSE 'complex' END),
                  maturation_status = 'review',
                  updated_at = NOW()
               WHERE id = $6::uuid""",
            envelope["spec_markdown"],
            json.dumps(envelope.get("spec_children") or []),
            json.dumps(envelope.get("verification_commands") or []),
            json.dumps(envelope.get("success_criteria_structured") or []),
            envelope.get("_fallback", False),
            goal_id,
        )

    from ..journal import emit_journal
    await emit_journal(goal_id, "speccing.complete",
        {"children_count": len(envelope.get("spec_children") or []),
         "fallback": envelope.get("_fallback", False)})
    log.info("Speccing complete for goal %s — transitioned to review (children=%d)",
             goal_id, len(envelope.get("spec_children") or []))
    return envelope
```

- [ ] **Step 3: Run the test from Task 3**

Run: `pytest tests/test_decomposition_speccing.py::test_speccing_produces_structured_output -v`
Expected: PASS (assuming a working LLM).

- [ ] **Step 4: Commit**

```bash
git add -f cortex/app/maturation/speccing.py tests/test_decomposition_speccing.py
git commit -m "feat(cortex): speccing emits JSON envelope (markdown + spec_children + verification + criteria)"
```

---

## Phase 4: Building Executor

### Task 5: Failing test — building creates subgoals from spec_children

**Files:**
- Create: `tests/test_decomposition_simple_path.py` (extended later)
- Create: `tests/test_decomposition_lifecycle.py`

- [ ] **Step 1: Write the failing test**

```python
"""Building materializes spec_children as subgoal rows for complex goals."""
import asyncio, os, pytest, httpx, json

ORCH = os.getenv("NOVA_ORCH_URL", "http://localhost:8000")
ADMIN = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
HEADERS = {"X-Admin-Secret": ADMIN}


@pytest.mark.asyncio
async def test_building_spawns_subgoals_for_complex_goal():
    """A complex goal with spec_children advances from review→building, spawning child rows."""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ORCH}/api/v1/goals", headers=HEADERS, json={
            "title": "nova-test-decomp building spawns",
            "description": "test parent",
            "max_cost_usd": 10.00,
        })
        goal_id = r.json()["id"]

        # Seed the goal with spec_children (skip the LLM round)
        children_json = json.dumps([
            {"title": "child A", "description": "do A", "hint": "fast", "depends_on": [],
             "estimated_cost_usd": 2.0, "estimated_complexity": "complex"},
            {"title": "child B", "description": "do B", "hint": "after A", "depends_on": [0],
             "estimated_cost_usd": 3.0, "estimated_complexity": "complex"},
        ])
        await c.patch(f"{ORCH}/api/v1/goals/{goal_id}", headers=HEADERS, json={
            "complexity": "complex",
            "spec": "irrelevant for this test",
            "spec_children": json.loads(children_json),
            "maturation_status": "building",
            "spec_approved_at": "2026-04-28T00:00:00Z",
            "spec_approved_by": "test",
        })

        # Wait for cortex cycle to run building
        for _ in range(60):
            await asyncio.sleep(2)
            g = (await c.get(f"{ORCH}/api/v1/goals/{goal_id}", headers=HEADERS)).json()
            if g.get("maturation_status") == "waiting":
                break

        try:
            assert g["maturation_status"] == "waiting", f"parent should advance to waiting, got {g}"

            # Verify two child rows exist with parent_goal_id pointing to us
            r = await c.get(f"{ORCH}/api/v1/goals?parent_goal_id={goal_id}", headers=HEADERS)
            children = r.json()
            assert len(children) == 2
            titles = sorted(ch["title"] for ch in children)
            assert titles == ["child A", "child B"]
            for ch in children:
                assert ch["depth"] == 1
                assert ch["maturation_status"] == "triaging"
        finally:
            await c.delete(f"{ORCH}/api/v1/goals/{goal_id}?cascade=true", headers=HEADERS)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_decomposition_lifecycle.py::test_building_spawns_subgoals_for_complex_goal -v`
Expected: FAIL — building isn't routed yet, parent stays in `building` indefinitely.

### Task 6: Implement `building.py`

**Files:**
- Create: `cortex/app/maturation/building.py`

- [ ] **Step 1: Create the file**

```python
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
```

- [ ] **Step 2: Run the test from Task 5 — still fails (cycle hasn't routed)**

Continue to Task 7 to wire routing; this task's test passes only after Task 8.

- [ ] **Step 3: Commit**

```bash
git add -f cortex/app/maturation/building.py tests/test_decomposition_lifecycle.py
git commit -m "feat(cortex): building.py — mechanical materializer for goal decomposition"
```

---

## Phase 5: Cycle Integration

### Task 7: Failing tests — cycle routes building + waiting

These tests already exist (Task 5's parent-spawning test); we just need the cycle to actually route them. No new tests required for this task.

### Task 8: Add building + waiting routing to cycle.py

**Files:**
- Modify: `cortex/app/cycle.py` around lines 503-527 where existing maturation routing lives

- [ ] **Step 1: Locate the existing maturation routing block**

Run: `grep -n "maturation_phase ==" cortex/app/cycle.py`
Note the lines (currently routes scoping/speccing/verifying).

- [ ] **Step 2: Add `_all_children_terminated` helper FIRST (must exist before it's called)**

Below `_select_goal` near top of cycle.py:

```python
async def _all_children_terminated(parent_goal_id: str) -> bool:
    """True when every child goal has terminal status (completed | failed | cancelled)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE status IN ('completed', 'failed', 'cancelled')) AS done
               FROM goals WHERE parent_goal_id = $1::uuid""",
            parent_goal_id,
        )
    return row["total"] > 0 and row["total"] == row["done"]
```

- [ ] **Step 3: Add building + waiting cases (now references the helper defined in Step 2)**

Insert after the `verifying` branch (before `# Check if this approach has already failed`):

```python
    elif maturation_phase == "building":
        from .maturation.building import run_building
        msg = await run_building(goal_id)
        return msg

    elif maturation_phase == "waiting":
        # Parent waiting on children. Don't dispatch new work for this goal directly;
        # instead check if all children have terminated, and if so advance to verifying.
        ready = await _all_children_terminated(goal_id)
        if ready:
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE goals SET maturation_status = 'verifying', updated_at = NOW() WHERE id = $1::uuid",
                    goal_id,
                )
            from .journal import emit_journal
            await emit_journal(goal_id, "waiting.children_complete", {})
            return f"Children all terminated → goal {goal_id} advancing to verifying"
        return f"Waiting on children for goal {goal_id} (no-op cycle)"
```

- [ ] **Step 4: Run building test from Task 5**

Run: `pytest tests/test_decomposition_lifecycle.py::test_building_spawns_subgoals_for_complex_goal -v`
Expected: PASS — parent advances `building → waiting`, two children created.

- [ ] **Step 5: Commit**

```bash
git add -f cortex/app/cycle.py
git commit -m "feat(cortex): cycle.py routes building + waiting maturation phases"
```

### Task 9: Sibling-deps filter in stale-goal query

**Files:**
- Modify: `cortex/app/drives/serve.py`

A child goal whose `current_plan.depends_on` references a sibling that hasn't completed should be filtered out of the stale list — otherwise Cortex picks it up and burns cycles.

- [ ] **Step 1: Find the existing stale-query in serve.py**

Run: `grep -n "stale_goals\|FROM goals\|status = 'active'" cortex/app/drives/serve.py`

- [ ] **Step 2: Add a sibling-deps filter**

After the existing stale query loads goals, filter in Python (cleaner than SQL with JSONB array probing):

```python
async def _filter_dep_blocked(goals: list[dict]) -> list[dict]:
    """Remove children whose depends_on siblings haven't completed."""
    pool = get_pool()
    out = []
    for g in goals:
        plan = g.get("current_plan") or {}
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except json.JSONDecodeError:
                plan = {}
        deps = plan.get("depends_on") if isinstance(plan, dict) else None
        if not deps or not g.get("parent_goal_id"):
            out.append(g)
            continue
        # Find sibling spawn_indices among completed siblings
        async with pool.acquire() as conn:
            done = await conn.fetch(
                """SELECT (current_plan->>'spawn_index')::int AS idx
                   FROM goals
                   WHERE parent_goal_id = $1::uuid
                     AND status IN ('completed','cancelled')
                     AND current_plan ? 'spawn_index'""",
                g["parent_goal_id"],
            )
        done_idx = {r["idx"] for r in done if r["idx"] is not None}
        if all(d in done_idx for d in deps):
            out.append(g)
    return out
```

Then call it in the stale path:

```python
stale_goals = await _filter_dep_blocked(stale_goals)
```

- [ ] **Step 3: Verify with a deps-blocked scenario**

Run a quick manual test:
```bash
docker compose restart cortex
docker compose logs --tail 100 -f cortex | grep -i "Waiting on children\|filtered"
```
Expected: when a parent waits on multiple children, deps-blocked children stay paused.

- [ ] **Step 4: Commit**

```bash
git add -f cortex/app/drives/serve.py
git commit -m "feat(cortex): stale-goal filter for sibling-deps blocked children"
```

---

## Phase 6: Multi-Signal Verification

### Task 10: Failing test — verification aggregator

**Files:**
- Create: `tests/test_verification_aggregator.py`

- [ ] **Step 1: Write aggregator unit tests**

```python
"""Aggregator combines (cmd_results, quartet_review, criteria_eval) → outcome string."""
import pytest
from cortex.app.maturation.aggregator import aggregate


def _r(*exit_codes): return [{"cmd": f"c{i}", "exit_code": e} for i, e in enumerate(exit_codes)]


def test_all_green_passes():
    assert aggregate(_r(0, 0), {"confidence": 0.9}, [{"pass": True}]*3) == "pass"


def test_command_fail_with_quartet_agreement_fails():
    assert aggregate(_r(0, 1), {"confidence": 0.85}, [{"pass": True}]*2) == "fail"


def test_command_fail_with_low_quartet_confidence_human_review():
    assert aggregate(_r(0, 1), {"confidence": 0.4}, [{"pass": True}]*2) == "human-review"


def test_all_green_but_quartet_low_confidence_human_review():
    assert aggregate(_r(0, 0), {"confidence": 0.3}, [{"pass": True}]*4) == "human-review"


def test_no_commands_passes_when_quartet_high():
    assert aggregate([], {"confidence": 0.9}, [{"pass": True}]*2) == "pass"


def test_no_commands_human_review_when_quartet_low():
    assert aggregate([], {"confidence": 0.6}, [{"pass": True}]) == "human-review"


def test_majority_criteria_fail_blocks_pass():
    assert aggregate(_r(0), {"confidence": 0.9},
                     [{"pass": True}, {"pass": False}, {"pass": False}, {"pass": False}]) == "fail"
```

- [ ] **Step 2: Run — fails (module doesn't exist)**

Run: `pytest tests/test_verification_aggregator.py -v`
Expected: collection error / ImportError.

### Task 11: Implement aggregator

**Files:**
- Create: `cortex/app/maturation/aggregator.py`

- [ ] **Step 1: Create file**

```python
"""Pure-function aggregator: (cmd_results, quartet_review, criteria_eval) → outcome.

Outcomes: 'pass', 'fail', 'human-review'.
"""
from __future__ import annotations


def aggregate(cmd_results: list[dict], quartet_review: dict | None, criteria_eval: list[dict]) -> str:
    """Combine signals into a single outcome.

    Rules:
      - All cmds exit 0, quartet ≥ 0.7, criteria ≥ 75% pass → pass
      - Any cmd non-zero AND quartet ≥ 0.7 (LLM agrees it failed) → fail
      - Any cmd non-zero AND quartet < 0.7 (LLM uncertain) → human-review
      - All cmds pass AND criteria majority pass AND quartet < 0.5 → human-review
      - 0 commands AND only LLM signals: pass if quartet ≥ 0.85 else human-review
      - Criteria majority FAIL blocks pass even if commands+quartet green → fail
    """
    quartet_conf = float((quartet_review or {}).get("confidence") or 0.0)
    cmd_pass = all(int(c.get("exit_code") or 0) == 0 for c in cmd_results)
    criteria_pass_ratio = (
        sum(1 for x in criteria_eval if x.get("pass")) / len(criteria_eval)
        if criteria_eval else 1.0
    )

    if not cmd_results and not criteria_eval:
        # Degenerate: no signals at all — escalate
        return "human-review"

    # No commands: rely on quartet + criteria
    if not cmd_results:
        if quartet_conf >= 0.85 and criteria_pass_ratio >= 0.75:
            return "pass"
        return "human-review"

    # Have commands
    if not cmd_pass:
        return "fail" if quartet_conf >= 0.7 else "human-review"

    # All commands green
    if criteria_pass_ratio < 0.5:
        return "fail"  # criteria majority fail blocks pass
    if quartet_conf < 0.5:
        return "human-review"  # quartet disagrees with green tests
    if quartet_conf >= 0.7 and criteria_pass_ratio >= 0.75:
        return "pass"
    return "human-review"
```

- [ ] **Step 2: Run aggregator tests — pass**

Run: `pytest tests/test_verification_aggregator.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add -f cortex/app/maturation/aggregator.py tests/test_verification_aggregator.py
git commit -m "feat(cortex): verification aggregator (commands + Quartet + criteria)"
```

### Task 12: Implement command runner

**Files:**
- Create: `cortex/app/maturation/commands.py`

- [ ] **Step 1: Create file**

```python
"""Run verification commands. Captures stdout/stderr tails + exit codes."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

_TAIL_LIMIT = 4000  # bytes per stream


async def run_commands(cmd_specs: list[dict]) -> list[dict]:
    """Execute each cmd spec and return per-command result dicts.

    Each spec: {"cmd": str, "cwd": str|None, "timeout_s": int|None}
    Each result: {"cmd": str, "exit_code": int, "stdout_tail": str, "stderr_tail": str, "duration_ms": int}
    """
    results = []
    for spec in cmd_specs or []:
        cmd = spec.get("cmd") or ""
        cwd = spec.get("cwd") or None
        timeout = float(spec.get("timeout_s") or 60)
        if not cmd:
            results.append({"cmd": "", "exit_code": -1,
                            "stdout_tail": "", "stderr_tail": "empty cmd", "duration_ms": 0})
            continue

        start = asyncio.get_event_loop().time()
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                exit_code = proc.returncode
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                stdout, stderr = b"", b"timed out"
                exit_code = -2
        except Exception as e:
            log.warning("Command '%s' failed to launch: %s", cmd, e)
            stdout, stderr = b"", str(e).encode()
            exit_code = -3

        duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)
        results.append({
            "cmd": cmd,
            "exit_code": exit_code,
            "stdout_tail": stdout[-_TAIL_LIMIT:].decode("utf-8", errors="replace"),
            "stderr_tail": stderr[-_TAIL_LIMIT:].decode("utf-8", errors="replace"),
            "duration_ms": duration_ms,
        })
    return results
```

- [ ] **Step 2: Commit**

```bash
git add -f cortex/app/maturation/commands.py
git commit -m "feat(cortex): verification command runner (subprocess + timeout + tails)"
```

### Task 13: Implement criteria evaluator

**Files:**
- Create: `cortex/app/maturation/criteria.py`

- [ ] **Step 1: Create file**

```python
"""Evaluate structured success_criteria against signals collected during verification.

Each criterion is one of:
  {"check": "command", "check_arg": "<shell>"}
      → look up the cmd in cmd_results; pass = exit_code == 0
  {"check": "engram_query", "check_arg": "<query string>"}
      → memory-service /context query; pass = ≥1 engram with importance ≥ 0.5
  {"check": "llm_judge", "check_arg": "<prompt>"}
      → ask a tier=cheap LLM yes/no with criterion + cmd_results + quartet_review as evidence
"""
from __future__ import annotations

import logging
from ..clients import get_llm

log = logging.getLogger(__name__)


async def evaluate_criteria(
    criteria: list[dict],
    cmd_results: list[dict],
    quartet_review: dict | None,
) -> list[dict]:
    out = []
    for crit in criteria or []:
        kind = (crit.get("check") or "").strip().lower()
        arg = crit.get("check_arg") or ""
        statement = crit.get("statement") or "(unstated)"
        try:
            if kind == "command":
                passed, evidence = _eval_command(arg, cmd_results)
            elif kind == "engram_query":
                passed, evidence = await _eval_engram(arg)
            elif kind == "llm_judge":
                passed, evidence = await _eval_llm(arg, statement, cmd_results, quartet_review)
            else:
                passed, evidence = False, f"unknown check kind: {kind}"
        except Exception as e:
            log.warning("Criteria eval failed (%s): %s", kind, e)
            passed, evidence = False, f"eval error: {e}"
        out.append({"statement": statement, "pass": bool(passed), "evidence": evidence})
    return out


def _eval_command(arg: str, cmd_results: list[dict]) -> tuple[bool, str]:
    for r in cmd_results or []:
        if r.get("cmd") == arg:
            ok = int(r.get("exit_code") or 0) == 0
            return ok, f"exit={r.get('exit_code')}"
    return False, "command not found in run set"


async def _eval_engram(arg: str) -> tuple[bool, str]:
    from ..clients import get_memory
    mem = get_memory()
    try:
        r = await mem.post("/api/v1/engrams/context", json={"query": arg, "k": 5})
        if r.status_code != 200:
            return False, f"memory http {r.status_code}"
        engs = r.json().get("engrams") or []
        good = [e for e in engs if (e.get("importance") or 0.0) >= 0.5]
        return len(good) >= 1, f"matches={len(good)}"
    except Exception as e:
        return False, f"engram err: {e}"


async def _eval_llm(prompt_template: str, statement: str,
                    cmd_results: list[dict], quartet_review: dict | None) -> tuple[bool, str]:
    llm = get_llm()
    body = (
        f"Criterion: {statement}\n"
        f"Custom prompt: {prompt_template}\n"
        f"Verification command exits: {[r.get('exit_code') for r in cmd_results]}\n"
        f"Code-review verdict: {(quartet_review or {}).get('verdict', 'unknown')} "
        f"(confidence {(quartet_review or {}).get('confidence', 0)})\n\n"
        f"Did this criterion pass? Reply with one word: yes or no."
    )
    r = await llm.post(
        "/complete",
        json={"messages": [{"role": "user", "content": body}],
              "max_tokens": 10, "temperature": 0.0, "tier": "cheap"},
        timeout=30.0,
    )
    if r.status_code != 200:
        return False, f"llm http {r.status_code}"
    text = (r.json().get("content") or "").strip().lower()
    return text.startswith("yes"), f"llm: {text[:40]}"
```

- [ ] **Step 2: Commit**

```bash
git add -f cortex/app/maturation/criteria.py
git commit -m "feat(cortex): structured success-criteria evaluator (command/engram/llm)"
```

### Task 14: Rewrite verifying.py with multi-signal logic

**Files:**
- Modify: `cortex/app/maturation/verifying.py`

- [ ] **Step 1: Replace contents**

Replace the entire file:

```python
"""Verifying phase — multi-signal: commands + Quartet code-review + structured criteria.

Spec: docs/superpowers/specs/2026-04-28-cortex-goal-decomposition-design.md
"""
from __future__ import annotations

import json
import logging

from ..clients import get_orchestrator
from ..config import settings
from ..db import get_pool
from ..journal import emit_journal, emit_notification
from ..reflections import record_reflection, check_approach_blocked
from ..stimulus import emit, GOAL_COMPLETED
from .aggregator import aggregate
from .commands import run_commands
from .criteria import evaluate_criteria

log = logging.getLogger(__name__)


async def run_verifying(goal_id: str) -> str:
    """Multi-signal verification. Returns a one-line outcome description."""
    goal = await _load_goal(goal_id)
    if not goal:
        return f"Verifying: goal {goal_id} not found"

    cmd_specs = _decode(goal["verification_commands"]) or []
    criteria = _decode(goal["success_criteria_structured"]) or []

    cmd_results = await run_commands(cmd_specs)
    quartet_review = await _quartet_verify(goal)
    criteria_eval = await evaluate_criteria(criteria, cmd_results, quartet_review)
    outcome = aggregate(cmd_results, quartet_review, criteria_eval)

    attempt = await _record_attempt(goal_id, cmd_results, quartet_review, criteria_eval, outcome)

    if outcome == "pass":
        await _mark_complete(goal_id)
        await emit_journal(goal_id, "verify.pass", {"attempt": attempt})
        await emit(GOAL_COMPLETED, "cortex", payload={"goal_id": goal_id})
        return f"Verification passed → completed (attempt {attempt})"

    if outcome == "fail":
        return await _on_verify_fail(goal_id, goal, attempt,
                                     cmd_results, quartet_review, criteria_eval)

    # human-review
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE goals SET maturation_status = 'review', updated_at = NOW() WHERE id = $1::uuid",
            goal_id,
        )
        await conn.execute(
            """INSERT INTO comments (entity_type, entity_id, author_type, author_name, body)
               VALUES ('goal', $1::uuid, 'nova', 'cortex',
                       'Verification mixed — needs human review. See goal_verifications.')""",
            goal_id,
        )
    await emit_journal(goal_id, "verify.human_review", {"attempt": attempt})
    return f"Verification mixed → review queue (attempt {attempt})"


# ── Helpers ────────────────────────────────────────────────────────────────
async def _load_goal(goal_id: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT id, title, description, spec, verification_commands,
                      success_criteria_structured, success_criteria,
                      retry_count, max_retries, review_policy, parent_goal_id,
                      cost_so_far_usd
               FROM goals WHERE id = $1::uuid""",
            goal_id,
        )


def _decode(raw):
    if raw is None: return None
    if isinstance(raw, (list, dict)): return raw
    if isinstance(raw, str):
        try: return json.loads(raw)
        except json.JSONDecodeError: return None
    return None


def _first_failure_mode(cmd_results, quartet_review, criteria_eval) -> str | None:
    """Pick a short failure label for reflections.failure_mode (truncated to 200 chars by record_reflection)."""
    for r in cmd_results or []:
        if int(r.get("exit_code") or 0) != 0:
            return f"cmd_fail: {r.get('cmd', '')[:120]} exit={r.get('exit_code')}"
    qv = (quartet_review or {}).get("verdict")
    if qv and qv != "complete":
        return f"quartet_verdict: {qv}"
    for c in criteria_eval or []:
        if not c.get("pass"):
            return f"criterion_fail: {(c.get('statement') or '')[:120]}"
    return None


async def _quartet_verify(goal) -> dict:
    """Spawn a Quartet pipeline task whose Code Review agent verdicts the goal."""
    orch = get_orchestrator()
    prompt = (
        f"[Verification task — read the goal, then assess whether it appears completed.]\n"
        f"Goal: {goal['title']}\n"
        f"Description: {goal['description'] or '(none)'}\n"
        f"Spec excerpt: {(goal['spec'] or '')[:1500]}\n\n"
        f"Inspect the codebase. Render a verdict on whether this goal is complete. "
        f"Reply ONLY with JSON: "
        f'{{"verdict": "complete|partial|incomplete", "confidence": 0.0-1.0, "summary": "<one sentence>"}}'
    )
    try:
        r = await orch.post(
            "/api/v1/tasks",
            json={"user_input": prompt, "goal_id": str(goal["id"]),
                  "metadata": {"source": "cortex.verifying", "kind": "verification"}},
            headers={"Authorization": f"Bearer {settings.cortex_api_key}"},
            timeout=300.0,
        )
        r.raise_for_status()
        task_id = r.json().get("task_id")
        # Poll for completion (verification task should be fast)
        for _ in range(90):  # up to 3 min
            import asyncio
            await asyncio.sleep(2)
            tr = await orch.get(f"/api/v1/tasks/{task_id}",
                                headers={"Authorization": f"Bearer {settings.cortex_api_key}"})
            if tr.status_code != 200:
                continue
            td = tr.json()
            if td.get("status") in ("complete", "failed", "cancelled"):
                result_text = td.get("result") or td.get("output") or "{}"
                try:
                    parsed = json.loads(result_text) if isinstance(result_text, str) else result_text
                except json.JSONDecodeError:
                    parsed = {"verdict": "incomplete", "confidence": 0.0, "summary": "non-JSON output"}
                parsed["task_id"] = task_id
                return parsed
        return {"verdict": "incomplete", "confidence": 0.0, "summary": "verification task timeout", "task_id": task_id}
    except Exception as e:
        log.warning("Quartet verify failed for goal %s: %s", goal["id"], e)
        return {"verdict": "incomplete", "confidence": 0.0, "summary": f"error: {e}"}


async def _record_attempt(goal_id, cmd_results, quartet_review, criteria_eval, outcome) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        attempt_row = await conn.fetchrow(
            "SELECT COALESCE(MAX(attempt), 0) + 1 AS next FROM goal_verifications WHERE goal_id = $1::uuid",
            goal_id,
        )
        attempt = attempt_row["next"]
        await conn.execute(
            """INSERT INTO goal_verifications
                  (goal_id, attempt, cmd_results, quartet_review, criteria_eval, aggregate)
               VALUES ($1::uuid, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6)""",
            goal_id, attempt,
            json.dumps(cmd_results), json.dumps(quartet_review), json.dumps(criteria_eval),
            outcome,
        )
    return attempt


async def _mark_complete(goal_id):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET status = 'completed',
                                  maturation_status = NULL,
                                  progress = 1.0,
                                  updated_at = NOW()
               WHERE id = $1::uuid""",
            goal_id,
        )


async def _on_verify_fail(goal_id, goal, attempt, cmd_results, quartet_review, criteria_eval):
    """Re-spec or escalate. Returns one-line outcome."""
    # Reflection.
    # record_reflection signature (cortex/app/reflections.py:31):
    #   (goal_id, cycle_number, approach, outcome, outcome_score,
    #    task_id=None, drive='serve', maturation_phase=None,
    #    lesson=None, failure_mode=None, context_snapshot=None)
    # approach_hash is computed internally; failure detail goes in context_snapshot.
    try:
        await record_reflection(
            goal_id=goal_id,
            cycle_number=0,  # 0 signals a verify-time reflection (not from a cortex cycle)
            approach=goal["spec"] or "(no spec)",
            outcome="verify_failed",
            outcome_score=0.2,
            maturation_phase="verifying",
            failure_mode=_first_failure_mode(cmd_results, quartet_review, criteria_eval),
            context_snapshot={
                "cmd_failures": [r for r in cmd_results if int(r.get("exit_code") or 0) != 0],
                "quartet": quartet_review,
                "criteria_failures": [c for c in criteria_eval if not c.get("pass")],
            },
        )
    except Exception as e:
        log.warning("record_reflection failed for goal %s: %s", goal_id, e)

    # Retry budget exhausted?
    if goal["retry_count"] >= goal["max_retries"]:
        return await _escalate(goal_id, goal, attempt, reason="retries_exhausted")

    # Approach blocked (already failed N times before)?
    try:
        is_blocked, _ = await check_approach_blocked(goal_id, goal["spec"] or "", "best")
        if is_blocked:
            return await _escalate(goal_id, goal, attempt, reason="approach_blocked")
    except Exception as e:
        log.debug("check_approach_blocked failed: %s", e)

    # Re-spec: bump retry_count, transition back to scoping
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET retry_count = retry_count + 1,
                                  maturation_status = 'scoping',
                                  updated_at = NOW()
               WHERE id = $1::uuid""",
            goal_id,
        )
    await emit_journal(goal_id, "verify.retry",
        {"attempt": attempt, "next_retry": goal["retry_count"] + 1})
    return f"Verification failed → re-spec (retry {goal['retry_count'] + 1}/{goal['max_retries']})"


async def _escalate(goal_id, goal, attempt, reason: str) -> str:
    """Escalate per goal.review_policy. Three branches: human / propagate / terminal."""
    policy = goal["review_policy"]
    pool = get_pool()

    if policy in ("all", "scopes-sensitive", "cost-above-2", "cost-above-5"):
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE goals SET maturation_status = 'review', updated_at = NOW()
                   WHERE id = $1::uuid""",
                goal_id,
            )
            await conn.execute(
                """INSERT INTO comments (entity_type, entity_id, author_type, author_name, body)
                   VALUES ('goal', $1::uuid, 'nova', 'cortex',
                           'Goal stuck after ' || $2 || ' retries (' || $3 || '). '
                           || 'See goal_verifications. Approve a re-spec, edit spec, or abort.')""",
                goal_id, goal["max_retries"], reason,
            )
        await emit_notification(goal_id, "goal_stuck",
            title=f"Goal '{goal['title']}' stuck — needs review")
        await emit_journal(goal_id, "verify.escalate.human", {"reason": reason, "attempt": attempt})
        return f"Verification exhausted → escalated to human ({reason})"

    # policy = 'top-only' AND not top → propagate
    if goal["parent_goal_id"]:
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE goals SET retry_count = retry_count + 1,
                                      maturation_status = 'scoping',
                                      updated_at = NOW()
                   WHERE id = $1::uuid""",
                goal["parent_goal_id"],
            )
            await conn.execute(
                """UPDATE goals SET status = 'failed', updated_at = NOW()
                   WHERE id = $1::uuid""",
                goal_id,
            )
        await emit_journal(goal_id, "verify.escalate.parent",
            {"reason": reason, "parent_goal_id": str(goal["parent_goal_id"])})
        return f"Verification exhausted → propagated to parent ({reason})"

    # Top-level + top-only + retries exhausted → terminal failure
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE goals SET status = 'failed', updated_at = NOW() WHERE id = $1::uuid",
            goal_id,
        )
    await emit_journal(goal_id, "verify.fail.terminal", {"reason": reason})
    return f"Verification exhausted → goal failed (autonomous policy)"
```

- [ ] **Step 2: Run aggregator tests + smoke-test full verify**

Run: `pytest tests/test_verification_aggregator.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add -f cortex/app/maturation/verifying.py
git commit -m "feat(cortex): rewrite verifying.py — multi-signal verification with retry+escalate"
```

---

## Phase 7: Failure Recovery Tests

### Task 15: Failing test — verify failure → re-spec

**Files:**
- Create: `tests/test_decomposition_failure_recovery.py`

- [ ] **Step 1: Write the test**

```python
"""Force a verification failure; assert goal re-enters scoping with retry_count=1."""
import asyncio, os, json, pytest, httpx

ORCH = os.getenv("NOVA_ORCH_URL", "http://localhost:8000")
ADMIN = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
HEADERS = {"X-Admin-Secret": ADMIN}


@pytest.mark.asyncio
async def test_verify_failure_triggers_respec():
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ORCH}/api/v1/goals", headers=HEADERS, json={
            "title": "nova-test-failure-respec",
            "description": "force verify failure to test re-spec",
            "max_cost_usd": 10.0,
        })
        gid = r.json()["id"]
        # Seed goal directly in 'verifying' with a guaranteed-failing command
        await c.patch(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS, json={
            "complexity": "simple",
            "spec": "test spec",
            "verification_commands": [{"cmd": "false", "timeout_s": 5}],
            "success_criteria_structured": [
                {"statement": "false exits 0", "check": "command", "check_arg": "false"},
            ],
            "maturation_status": "verifying",
        })

        # Wait for cortex cycle to verify and re-spec
        for _ in range(60):
            await asyncio.sleep(2)
            g = (await c.get(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)).json()
            if g.get("retry_count", 0) >= 1 and g.get("maturation_status") == "scoping":
                break

        try:
            assert g["retry_count"] == 1, f"retry_count should be 1, got {g}"
            assert g["maturation_status"] == "scoping", f"should re-enter scoping, got {g['maturation_status']}"
        finally:
            await c.delete(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)


@pytest.mark.asyncio
async def test_retry_exhaustion_escalates():
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ORCH}/api/v1/goals", headers=HEADERS, json={
            "title": "nova-test-failure-escalate",
            "description": "force two failures to test escalation",
            "max_cost_usd": 10.0,
        })
        gid = r.json()["id"]
        # Start at retry_count=2 (already at max_retries) so the next failure escalates
        await c.patch(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS, json={
            "complexity": "simple",
            "spec": "test spec",
            "verification_commands": [{"cmd": "false", "timeout_s": 5}],
            "success_criteria_structured": [{"statement": "false exits 0", "check": "command", "check_arg": "false"}],
            "max_retries": 2,
            "retry_count": 2,
            "review_policy": "cost-above-2",
            "maturation_status": "verifying",
        })

        for _ in range(60):
            await asyncio.sleep(2)
            g = (await c.get(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)).json()
            if g.get("maturation_status") == "review":
                break
        try:
            assert g["maturation_status"] == "review", \
                f"after retry exhaustion, should be in 'review' (escalated), got {g['maturation_status']}"
        finally:
            await c.delete(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Run — expects PASS once verifying.py is in place**

Run: `pytest tests/test_decomposition_failure_recovery.py -v`
Expected: PASS (verifying.py from Task 14 already implements re-spec + escalate).

- [ ] **Step 3: Commit**

```bash
git add -f tests/test_decomposition_failure_recovery.py
git commit -m "test: failure recovery — verify→respec→escalate"
```

---

## Phase 8: Stimulus + Parent Wakeup

### Task 16: Add SUBGOAL_TERMINATED stimulus

**Files:**
- Modify: `cortex/app/stimulus.py`

- [ ] **Step 1: Add the constant**

After existing `GOAL_COMPLETED`:

```python
SUBGOAL_TERMINATED = "subgoal.terminated"  # any terminal: completed | failed | cancelled
```

- [ ] **Step 2: Emit on terminal transitions**

In `cortex/app/maturation/verifying.py` `_mark_complete`, add (alongside the existing `GOAL_COMPLETED`):

```python
# inside _mark_complete after the UPDATE:
goal = await _load_goal(goal_id)
if goal and goal["parent_goal_id"]:
    from ..stimulus import SUBGOAL_TERMINATED
    await emit(SUBGOAL_TERMINATED, "cortex",
               payload={"goal_id": goal_id, "parent_goal_id": str(goal["parent_goal_id"]),
                        "outcome": "completed"})
```

Similarly in `_escalate` after the parent-propagate path and the terminal-failure path.

- [ ] **Step 3: Add a stimulus subscriber that wakes parents**

In `cortex/app/cycle.py` (or wherever stimulus consumers live — check `grep -n "stimulus\|drain\|subscribe" cortex/app/*.py`):

When SUBGOAL_TERMINATED fires for parent_goal_id P, mark P's `last_checked_at = NULL` so the next cycle's stale query picks it up immediately rather than waiting 30s:

```python
# in stimulus drain / handler
async def _on_subgoal_terminated(payload: dict):
    parent_id = payload.get("parent_goal_id")
    if not parent_id:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE goals SET last_checked_at = NULL WHERE id = $1::uuid",
            parent_id,
        )
```

- [ ] **Step 4: Commit**

```bash
git add -f cortex/app/stimulus.py cortex/app/cycle.py cortex/app/maturation/verifying.py
git commit -m "feat(cortex): SUBGOAL_TERMINATED stimulus + parent wakeup on child terminal"
```

---

## Phase 9: Goals Router Extensions

The dashboard UX (Phase 10) and integration tests (Phase 11) depend on
`UpdateGoalRequest` round-tripping the new columns. The notification helper
already publishes to the existing `nova:notifications` Redis channel
(see Task 2), so no new HTTP endpoint is required. The comment endpoint
already exists at `POST /api/v1/goals/{id}/comments` (`goals_router.py:351`,
`create_goal_comment`) — reuse it.

### Task 17: Extend `UpdateGoalRequest` + `GoalResponse` + `_row_to_goal`

**Files:**
- Modify: `orchestrator/app/goals_router.py:51` (UpdateGoalRequest), `:70` (GoalResponse), `_row_to_goal` helper

- [ ] **Step 1: Add new fields to `UpdateGoalRequest`**

After existing fields:

```python
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
```

- [ ] **Step 2: Add the same fields to `GoalResponse`**

```python
    spec_children: list[dict] | None = None
    verification_commands: list[dict] | None = None
    success_criteria_structured: list[dict] | None = None
    review_policy: str | None = None
    depth: int | None = None
    max_depth: int | None = None
    max_retries: int | None = None
    retry_count: int | None = None
```

- [ ] **Step 3: Update `_row_to_goal` to include the new columns**

Find `_row_to_goal` (search the file). For each new column, add the equivalent of:

```python
        spec_children=row.get("spec_children"),
        verification_commands=row.get("verification_commands"),
        success_criteria_structured=row.get("success_criteria_structured"),
        review_policy=row.get("review_policy"),
        depth=row.get("depth"),
        max_depth=row.get("max_depth"),
        max_retries=row.get("max_retries"),
        retry_count=row.get("retry_count"),
```

JSONB columns come back as Python dict/list directly (asyncpg auto-decodes), but
in some configurations they arrive as strings — match the existing pattern in
`_row_to_goal` for `current_plan`/`scope_analysis` if it does string-to-dict coercion.

- [ ] **Step 4: Update the PATCH endpoint to actually write new fields**

Find `update_goal` (the PATCH handler) — its body currently builds a dynamic SQL
update. Add the new fields to the column allowlist. JSONB fields need
`::jsonb` casting and `json.dumps()` on the Python value:

```python
JSONB_FIELDS = {"spec_children", "verification_commands", "success_criteria_structured"}
# In the loop building SET clauses:
if field in JSONB_FIELDS and value is not None:
    set_clauses.append(f"{field} = ${param_idx}::jsonb")
    params.append(json.dumps(value))
else:
    set_clauses.append(f"{field} = ${param_idx}")
    params.append(value)
```

- [ ] **Step 5: Add `parent_goal_id` query param to `list_goals` (line 141)**

```python
@goals_router.get("/api/v1/goals", response_model=list[GoalResponse])
async def list_goals(
    _user: UserDep,
    status: str | None = Query(default=None),
    parent_goal_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    pool = get_pool()
    where = []
    args = []
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
```

- [ ] **Step 6: Add `cascade` query param to `delete_goal` (line 269)**

```python
@goals_router.delete("/api/v1/goals/{goal_id}")
async def delete_goal(goal_id: UUID, _user: UserDep, cascade: bool = Query(default=False)):
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if cascade:
                # Recursive subgoal deletion (one level — repeat until no children remain).
                # Children of children are caught by ON DELETE CASCADE on goal_tasks/etc., but
                # parent_goal_id is ON DELETE SET NULL — so we explicitly recurse.
                while True:
                    deleted = await conn.execute(
                        "DELETE FROM goals WHERE parent_goal_id = $1::uuid", goal_id,
                    )
                    if deleted == "DELETE 0":
                        break
            r = await conn.execute("DELETE FROM goals WHERE id = $1::uuid", goal_id)
    if r == "DELETE 0":
        raise HTTPException(404, "goal not found")
    return {"ok": True}
```

- [ ] **Step 7: Type-check and smoke**

```bash
docker compose restart orchestrator
curl -sS -X PATCH -H "X-Admin-Secret: $NOVA_ADMIN_SECRET" -H "Content-Type: application/json" \
     -d '{"review_policy":"top-only","max_depth":3}' \
     http://localhost:8000/api/v1/goals/<some-id> | jq '.review_policy, .max_depth'
```
Expected: `"top-only"` and `3`.

- [ ] **Step 8: Commit**

```bash
git add -f orchestrator/app/goals_router.py
git commit -m "feat(orchestrator): goals_router round-trips decomposition columns + parent filter + cascade delete"
```

---

## Phase 10: Dashboard UX

### Task 19: Build MaturationStages component

**Files:**
- Create: `dashboard/src/components/MaturationStages.tsx`

- [ ] **Step 1: Create the file**

```tsx
import clsx from 'clsx'
import { Check } from 'lucide-react'

const STAGES = ['triaging', 'scoping', 'speccing', 'review', 'building', 'waiting', 'verifying'] as const
type Stage = typeof STAGES[number]

interface Props {
  current: Stage | null | undefined
  compact?: boolean
}

const LABEL: Record<Stage, string> = {
  triaging: 'Triage',
  scoping: 'Scope',
  speccing: 'Spec',
  review: 'Review',
  building: 'Build',
  waiting: 'Wait',
  verifying: 'Verify',
}

export function MaturationStages({ current, compact = false }: Props) {
  const currentIdx = current ? STAGES.indexOf(current) : -1

  return (
    <div className={clsx('flex items-center gap-1', compact ? 'text-[10px]' : 'text-xs')}>
      {STAGES.map((stage, idx) => {
        const done = idx < currentIdx
        const active = idx === currentIdx
        return (
          <div key={stage} className="flex items-center gap-1">
            <span
              className={clsx(
                'inline-flex items-center justify-center rounded-full',
                compact ? 'h-3 w-3 text-[8px]' : 'h-5 w-5 text-[10px]',
                done && 'bg-emerald-500 text-white',
                active && 'bg-amber-400 text-stone-900 animate-pulse',
                !done && !active && 'bg-stone-700 text-stone-400',
              )}
            >
              {done ? <Check className="h-2.5 w-2.5" /> : idx + 1}
            </span>
            {!compact && <span className={clsx(active ? 'text-content-primary font-medium' : 'text-content-tertiary')}>{LABEL[stage]}</span>}
            {idx < STAGES.length - 1 && <span className="text-stone-700">{compact ? '·' : '→'}</span>}
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add -f dashboard/src/components/MaturationStages.tsx
git commit -m "feat(dashboard): MaturationStages stepper component"
```

### Task 20: Extend GoalMaturationDetail with policy reasons + spec_children

**Files:**
- Modify: `dashboard/src/components/GoalMaturationDetail.tsx`

- [ ] **Step 1: Add a "Why is this in review?" section to the modal**

Around the existing review-state branch, add:

```tsx
{goal.maturation_status === 'review' && (
  <div className="space-y-3">
    <div className="text-xs text-content-tertiary">
      <strong className="text-content-secondary">Why review?</strong>{' '}
      {explainPolicy(goal)}
    </div>

    {goal.spec_children && goal.spec_children.length > 0 && (
      <div>
        <div className="text-xs uppercase text-content-tertiary tracking-wide mb-2">Children Cortex plans to spawn</div>
        <div className="space-y-1.5">
          {goal.spec_children.map((c: any, i: number) => (
            <div key={i} className="rounded-md bg-surface-card-hover px-3 py-2 text-xs">
              <div className="font-mono font-medium text-content-primary">
                {i + 1}. {c.title}
              </div>
              <div className="text-content-tertiary mt-0.5">hint: {c.hint || c.description}</div>
              <div className="flex items-center gap-2 mt-1 text-content-tertiary">
                <span>${(c.estimated_cost_usd || 0).toFixed(2)}</span>
                <span>·</span>
                <span>{c.estimated_complexity || 'unknown'}</span>
                {c.depends_on?.length > 0 && (
                  <>
                    <span>·</span>
                    <span>depends on: {c.depends_on.map((d: number) => `#${d + 1}`).join(', ')}</span>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    )}

    {goal.verification_commands && goal.verification_commands.length > 0 && (
      <div>
        <div className="text-xs uppercase text-content-tertiary tracking-wide mb-2">Verification commands</div>
        <ul className="text-xs font-mono space-y-1">
          {goal.verification_commands.map((v: any, i: number) => (
            <li key={i} className="text-content-secondary">• {v.cmd}</li>
          ))}
        </ul>
      </div>
    )}
  </div>
)}
```

- [ ] **Step 2: Add `explainPolicy` helper at the bottom of the file**

```tsx
function explainPolicy(goal: any): string {
  const policy = goal.review_policy || 'cost-above-2'
  if (policy === 'all') return 'Review policy: every level requires approval.'
  if (policy === 'scopes-sensitive')
    return `Review policy: scopes-sensitive — affects ${(goal.scope_analysis?.affected_scopes || []).join(', ')}.`
  if (policy.startsWith('cost-above-')) {
    const threshold = policy.split('-').pop()
    const cost = goal.spec_children?.reduce((a: number, c: any) => a + (c.estimated_cost_usd || 0), 0) || 0
    return `Review policy: cost-above-$${threshold} — estimated $${cost.toFixed(2)} ≥ $${threshold}.`
  }
  if (policy === 'top-only') return 'Review policy: top-only — top-level approval, autonomous below.'
  return `Review policy: ${policy}`
}
```

- [ ] **Step 3: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add -f dashboard/src/components/GoalMaturationDetail.tsx
git commit -m "feat(dashboard): GoalMaturationDetail — policy reasons + spec_children + verification commands"
```

### Task 21: Spawned-children affordance on Goals.tsx

**Files:**
- Modify: `dashboard/src/pages/Goals.tsx`

- [ ] **Step 1: Add a sub-line under the goal card**

Inside the goal card render (find the area near maturation badge):

```tsx
{goal.spec_children && goal.spec_children.length > 0 && (
  <SpawnedChildrenLine goalId={goal.id} count={goal.spec_children.length} />
)}
```

Add the component:

```tsx
function SpawnedChildrenLine({ goalId, count }: { goalId: string; count: number }) {
  const [open, setOpen] = useState(false)
  const { data: children } = useQuery({
    queryKey: ['goal-children', goalId],
    queryFn: () => apiFetch<any[]>(`/api/v1/goals?parent_goal_id=${goalId}`),
    enabled: open,
    staleTime: 10_000,
  })

  const summary = children
    ? `Spawned ${count} subgoals → ${children.filter(c => c.status === 'completed').length} done · ${children.filter(c => c.status === 'active').length} active · ${children.filter(c => c.maturation_status === 'review').length} need review`
    : `Spawned ${count} subgoals (click to load)`

  return (
    <div>
      <button onClick={() => setOpen(v => !v)} className="text-caption text-accent hover:underline">
        {summary}
      </button>
      {open && children && (
        <ul className="mt-1 ml-4 space-y-0.5">
          {children.map(c => (
            <li key={c.id}>
              <Link to={`/goals/${c.id}`} className="text-caption hover:underline">
                {c.title} · {c.status}
                {c.maturation_status && ` (${c.maturation_status})`}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check + smoke test in browser**

Run: `cd dashboard && npx tsc --noEmit`
Expected: clean. Open `/goals` and verify a parent with children shows the spawned line.

- [ ] **Step 3: Commit**

```bash
git add -f dashboard/src/pages/Goals.tsx
git commit -m "feat(dashboard): spawned-children affordance under parent goal cards"
```

### Task 22: Wire goal_stuck notification to toast

**Files:**
- Modify: `dashboard/src/hooks/useNotifications.ts` (extend `PipelineNotification` type to also accept goal-shaped messages)
- Modify: `dashboard/src/App.tsx:161` (`handleNotification` dispatch)

The dashboard already consumes the SSE stream at `/api/v1/pipeline/notifications/stream`
(`useNotifications.ts:26`). The cortex `emit_notification` helper from Task 2
publishes to the `nova:notifications` Redis channel with `{kind, goal_id, title, link}`,
so we just need to teach the dashboard to handle that shape alongside the existing
task-shaped messages.

- [ ] **Step 1: Extend the notification type in `useNotifications.ts`**

Replace the `PipelineNotification` interface and add a discriminated union:

```typescript
export interface TaskNotification {
  type: string;        // "complete" | "failed" | "error" | "warning" | ...
  task_id: string;
  title: string;
  body: string;
  timestamp: string;
}

export interface GoalNotification {
  kind: string;        // "goal_stuck" | ...
  goal_id: string;
  title: string;
  link?: string;
}

export type PipelineNotification = TaskNotification | GoalNotification;

export function isGoalNotification(n: PipelineNotification): n is GoalNotification {
  return "kind" in n && "goal_id" in n;
}
```

- [ ] **Step 2: Dispatch goal notifications in `App.tsx`**

Find `handleNotification` (around `App.tsx:161`). Add a branch:

```tsx
import { isGoalNotification } from './hooks/useNotifications'

const handleNotification = useCallback((n: PipelineNotification) => {
  if (isGoalNotification(n)) {
    if (n.kind === 'goal_stuck') {
      toast.warning(n.title, {
        action: { label: 'View', onClick: () => navigate(n.link || `/goals/${n.goal_id}`) },
      })
    }
    return
  }
  // Existing task-notification path follows…
}, [navigate])
```

(Match the toast library actually in use — sonner per `grep "toast\." App.tsx`. The
existing handler already calls `toast.<variant>(...)`; reuse that.)

- [ ] **Step 3: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add -f dashboard/src/hooks/useNotifications.ts dashboard/src/App.tsx
git commit -m "feat(dashboard): goal_stuck notification dispatch + toast with View action"
```

---

## Phase 11: Integration Tests + Smoke

### Task 23a: Test simple-goal path (flat tasks, no subgoals)

**Files:**
- Create: `tests/test_decomposition_simple_path.py`

The simple-goal path bypasses subgoal recursion and materializes tasks under
`goal_tasks` directly. Verify a goal with `complexity='simple'` advances
`building → verifying` (skipping `waiting`) and creates rows in `goal_tasks`
rather than spawning child goals.

- [ ] **Step 1: Write test**

```python
import asyncio, os, json, pytest, httpx

ORCH = os.getenv("NOVA_ORCH_URL", "http://localhost:8000")
ADMIN = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
HEADERS = {"X-Admin-Secret": ADMIN}


@pytest.mark.asyncio
async def test_simple_goal_materializes_flat_tasks():
    """Simple goal: building creates tasks (not subgoals); maturation advances to verifying."""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ORCH}/api/v1/goals", headers=HEADERS, json={
            "title": "nova-test-simple-flat",
            "description": "single-file change",
            "max_cost_usd": 5.0,
        })
        gid = r.json()["id"]
        await c.patch(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS, json={
            "complexity": "simple",
            "spec": "test spec",
            "spec_children": [
                {"title": "single task", "description": "do the thing", "hint": "h",
                 "depends_on": [], "estimated_cost_usd": 1.0, "estimated_complexity": "simple"},
            ],
            "maturation_status": "building",
            "spec_approved_at": "2026-04-28T00:00:00Z",
            "spec_approved_by": "test",
        })

        for _ in range(60):
            await asyncio.sleep(2)
            g = (await c.get(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)).json()
            if g.get("maturation_status") in ("verifying", None):
                break

        try:
            assert g["maturation_status"] == "verifying", \
                f"simple goal should advance building → verifying, got {g['maturation_status']}"
            # No subgoals spawned
            children_resp = await c.get(f"{ORCH}/api/v1/goals?parent_goal_id={gid}", headers=HEADERS)
            assert len(children_resp.json()) == 0, "simple goal must not spawn subgoals"
            # Tasks materialized via goal_tasks (verify by looking at tasks endpoint)
            # If no tasks endpoint with goal_id filter exists, this assertion can be skipped;
            # the verifying-status assertion already proves building.tasks_dispatched ran.
        finally:
            await c.delete(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Run + commit**

Run: `pytest tests/test_decomposition_simple_path.py -v`
Expected: PASS.

```bash
git add -f tests/test_decomposition_simple_path.py
git commit -m "test: simple-goal path materializes flat tasks instead of subgoals"
```

### Task 23: Test depth_limit forces flat tasks at the wall

**Files:**
- Create: `tests/test_depth_limit.py`

- [ ] **Step 1: Write test**

```python
import asyncio, os, json, pytest, httpx

ORCH = os.getenv("NOVA_ORCH_URL", "http://localhost:8000")
ADMIN = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
HEADERS = {"X-Admin-Secret": ADMIN}


@pytest.mark.asyncio
async def test_depth_wall_forces_flat_tasks():
    """A goal at depth=max_depth-1 with 'complex' children gets flat-task-materialized anyway."""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ORCH}/api/v1/goals", headers=HEADERS, json={
            "title": "nova-test-depth-wall",
            "description": "depth wall test",
            "max_cost_usd": 10.0,
        })
        gid = r.json()["id"]
        # Force depth = 4 (max=5 - 1)
        await c.patch(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS, json={
            "depth": 4, "max_depth": 5,
            "complexity": "complex",
            "spec": "test",
            "spec_children": [
                {"title": "complex child", "description": "desc", "hint": "h", "depends_on": [],
                 "estimated_cost_usd": 1.0, "estimated_complexity": "complex"},
            ],
            "maturation_status": "building",
            "spec_approved_at": "2026-04-28T00:00:00Z", "spec_approved_by": "test",
        })
        for _ in range(60):
            await asyncio.sleep(2)
            g = (await c.get(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)).json()
            if g.get("maturation_status") == "verifying":
                break
        try:
            assert g["maturation_status"] == "verifying", \
                f"at depth wall, building should advance to verifying (flat tasks), got {g['maturation_status']}"
            # No subgoals should have been spawned
            r = await c.get(f"{ORCH}/api/v1/goals?parent_goal_id={gid}", headers=HEADERS)
            assert len(r.json()) == 0, "depth wall hit but subgoals spawned anyway"
        finally:
            await c.delete(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Run + commit**

Run: `pytest tests/test_depth_limit.py -v`
Expected: PASS.

```bash
git add -f tests/test_depth_limit.py
git commit -m "test: depth_wall forces flat tasks at max_depth-1"
```

### Task 24: Test review_policy variants

**Files:**
- Create: `tests/test_review_policies.py`

- [ ] **Step 1: Write tests**

```python
import asyncio, os, json, pytest, httpx

ORCH = os.getenv("NOVA_ORCH_URL", "http://localhost:8000")
ADMIN = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
HEADERS = {"X-Admin-Secret": ADMIN}


@pytest.mark.parametrize("parent_policy,parent_scope,expected_child", [
    ("top-only", ["backend"], "top-only"),
    ("cost-above-2", ["backend"], "cost-above-2"),
    ("cost-above-2", ["security"], "scopes-sensitive"),  # auto-upgrade
    ("scopes-sensitive", ["backend"], "scopes-sensitive"),
    ("all", ["backend"], "all"),
])
@pytest.mark.asyncio
async def test_policy_cascades(parent_policy, parent_scope, expected_child):
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ORCH}/api/v1/goals", headers=HEADERS, json={
            "title": f"nova-test-policy-{parent_policy}-{parent_scope[0]}",
            "description": "policy cascade",
            "max_cost_usd": 10.0,
        })
        gid = r.json()["id"]
        await c.patch(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS, json={
            "complexity": "complex",
            "spec": "test",
            "spec_children": [
                {"title": "ch1", "description": "d", "hint": "h", "depends_on": [],
                 "estimated_cost_usd": 1.0, "estimated_complexity": "complex"},
            ],
            "review_policy": parent_policy,
            "scope_analysis": {"affected_scopes": parent_scope},
            "maturation_status": "building",
            "spec_approved_at": "2026-04-28T00:00:00Z", "spec_approved_by": "test",
        })

        for _ in range(60):
            await asyncio.sleep(2)
            g = (await c.get(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)).json()
            if g.get("maturation_status") == "waiting":
                break

        try:
            r = await c.get(f"{ORCH}/api/v1/goals?parent_goal_id={gid}", headers=HEADERS)
            children = r.json()
            assert len(children) == 1
            assert children[0]["review_policy"] == expected_child, \
                f"{parent_policy}+{parent_scope} expected {expected_child}, got {children[0]['review_policy']}"
        finally:
            await c.delete(f"{ORCH}/api/v1/goals/{gid}?cascade=true", headers=HEADERS)
```

- [ ] **Step 2: Run + commit**

Run: `pytest tests/test_review_policies.py -v`
Expected: 5 tests PASS.

```bash
git add -f tests/test_review_policies.py
git commit -m "test: review_policy cascade with auto-upgrade for sensitive scopes"
```

### Task 25: Test journal completeness

**Files:**
- Create: `tests/test_journal_completeness.py`

- [ ] **Step 1: Write test**

```python
"""Run a complex goal lifecycle and assert every documented journal event fires."""
import asyncio, os, pytest, httpx

ORCH = os.getenv("NOVA_ORCH_URL", "http://localhost:8000")
ADMIN = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
HEADERS = {"X-Admin-Secret": ADMIN}

EXPECTED_EVENTS = {
    "speccing.complete",
    "building.complete",
    "subgoal.spawned",
    "verify.pass",
}  # baseline; failure paths covered by failure recovery tests


@pytest.mark.slow
@pytest.mark.asyncio
async def test_complex_goal_emits_all_documented_events():
    """End-to-end: create complex goal with no review_policy gating, observe journal."""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ORCH}/api/v1/goals", headers=HEADERS, json={
            "title": "nova-test-journal-complete",
            "description": "Add a comment to README — trivially-passing verification",
            "max_cost_usd": 5.0,
            "review_policy": "top-only",
        })
        gid = r.json()["id"]

        # Auto-approve when it lands in review
        for _ in range(180):
            await asyncio.sleep(2)
            g = (await c.get(f"{ORCH}/api/v1/goals/{gid}", headers=HEADERS)).json()
            if g.get("maturation_status") == "review":
                await c.post(f"{ORCH}/api/v1/goals/{gid}/approve-spec", headers=HEADERS, json={"approved_by": "test"})
            if g.get("status") in ("completed", "failed"):
                break

        try:
            # Pull journal events filtered to this goal
            j = (await c.get(f"{ORCH}/api/v1/journal?goal_id={gid}", headers=HEADERS)).json()
            seen = {e.get("event") for e in (j or [])}
            missing = EXPECTED_EVENTS - seen
            assert not missing, f"missing journal events: {missing}; saw: {seen}"
        finally:
            await c.delete(f"{ORCH}/api/v1/goals/{gid}?cascade=true", headers=HEADERS)
```

- [ ] **Step 2: Run + commit**

Run: `pytest tests/test_journal_completeness.py -v -m slow`
Expected: PASS (slow test — wait for full lifecycle).

```bash
git add -f tests/test_journal_completeness.py
git commit -m "test: complex goal lifecycle emits all documented journal events"
```

### Task 26: Manual smoke test

**Steps:**

- [ ] **Step 1: Restart everything**

Run: `docker compose restart cortex orchestrator memory-service llm-gateway`

- [ ] **Step 2: Create a real complex goal via dashboard**

In the Goals page, create:
- Title: "Add /healthz alias on orchestrator"
- Description: "Add a route /healthz that returns the same response as /health/ready, so external monitors that expect /healthz work."
- max_cost_usd: 5.00
- review_policy: cost-above-2

- [ ] **Step 3: Observe the lifecycle in the journal**

Watch the Cortex Journal in dashboard. Expect: triaging → scoping → speccing → review (modal fires per cost-above-2). Approve. → building → waiting → child completes → verifying → completed.

- [ ] **Step 4: Force a failure path and observe escalation**

Create a goal whose verification_commands include `false`. Observe re-spec → re-spec → escalate notification → review modal in dashboard.

- [ ] **Step 5: If everything works, mark plan complete**

```bash
git tag -a "cortex-decomposition-v1" -m "Cortex goal decomposition + maturation executor v1 complete"
git push --tags
```

---

## Done

When all 26 tasks are checked, this plan is complete. Roadmap items closed:
- "No goal decomposition" (Self-Directed Autonomy gap)
- "Maturation pipeline stub" — building phase implemented
- Verifying.py is no longer just a health check

Open spec items remain as documented in the spec — `success_criteria_structured.engram_query` predicate, max_cost defaults for chat-created goals, notification durability — all addressed minimally in this plan and revisitable post-ship if usage demands.
