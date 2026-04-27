# Goal Maturation Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the missing forward-flow logic for the goal maturation pipeline so complex goals automatically progress through `triaging → scoping → speccing → review → verifying → completed` instead of sitting in active state with no executor advancing them.

**Architecture:** The schema, API endpoints, and partial cortex integration already exist. This plan adds the phase-execution logic to the cortex `serve` drive: when the drive picks up a goal in an active maturation phase, it dispatches phase-specific handler logic (LLM analysis, structured output, phase transition) instead of generic "execute the goal" planning. Phase 4 (`building`) is deferred — it depends on goal decomposition (separate ~2-3 week roadmap item). After spec approval, goals jump from `review` straight to `verifying` (manual implementation, then auto-verification).

**Tech Stack:** Python 3.11 (FastAPI, asyncpg, httpx), PyTorch is not needed; existing cortex/orchestrator/llm-gateway stack only.

**Spec:** `docs/superpowers/specs/2026-03-25-intelligence-and-goal-maturation-design.md` (Section 5)

**Out of scope (deferred):** Phase 4 (`building`) — spawns sub-goals per scope, depends on goal decomposition (`docs/roadmap.md` line 348).

**Current state on main (2026-04-27 — verified):**
- Migration `039_comments_and_goal_maturation.sql` adds `maturation_status`, `scope_analysis JSONB`, **`spec TEXT`**, `spec_approved_at`, `spec_approved_by` — NOTE: column is `spec`, not `spec_text`. This plan uses the existing `spec` column.
- Endpoints `POST /api/v1/goals/{id}/approve-spec` (line 359), `POST /:id/reject-spec` (line 381), `GET /:id/scope` (line 405) are wired
- Stimulus events in `cortex/app/stimulus.py`: `GOAL_CREATED = "goal.created"` (line 26), `GOAL_SPEC_APPROVED` (37), `GOAL_SPEC_REJECTED` (38), `GOAL_STUCK` (42), `GOAL_COMPLETED` (43) all exist
- Serve drive at `cortex/app/drives/serve.py:40-44` already accepts goals in active phases (excludes `review`) and enforces `iteration < max_iterations` + `cost_so_far_usd < max_cost_usd`
- Reflect logic in `cycle.py:935-947` reads `maturation_status`, records `maturation_phase` on every reflection; auto-escalates to `review` when stuck (`cycle.py:999`)
- LLM client in cortex: `from .clients import get_llm` (NOT `from .llm import get_llm` — there is no `llm.py`)
- Memory query in cortex: `from .memory import perceive_with_memory` — signature `perceive_with_memory(stimuli: list[dict], goal_context: str = "") -> dict[memory_context, engram_ids, retrieval_log_id]`. There is no `query_engrams_for_goal` function.
- `cortex/app/config.py:57` defines `settings.planning_model` (env: `CORTEX_PLANNING_MODEL`, defaults to `""`)
- llm-gateway `/complete` accepts `tier: "cheap" | "mid" | "best"` per existing usage in `cycle.py`
- Stimulus emission has TWO functions with different signatures:
  - `cortex/app/stimulus.py:91`: `async def emit(type, source, payload=None, priority=0)` — used inside cortex
  - `orchestrator/app/stimulus.py:50`: `async def emit_stimulus(type, payload=None, priority=0)` — used in orchestrator. Pick the right one per service.
- `orchestrator/app/goals_router.py:UpdateGoalRequest` (Pydantic model used by PATCH /goals/{id}) currently whitelists fields. It does **not** include `scope_analysis` or `spec`. This plan adds them in Task 4 Step 0 so tests can seed those fields via the PATCH endpoint.
- `manual_implementation_note` (migration 063) is **intentionally orphan** — schema is added now but no executor reads/writes it. It becomes load-bearing when goal decomposition lands and Phase 4 (`building`) is built. Documented as a known orphan, not a forgotten column.
- **Gap:** No code writes to `scope_analysis` or `spec`; no triage decides which goals enter the pipeline; no phase-specific logic runs when serve drive picks up a maturation goal in `triaging`/`scoping`/`speccing`/`verifying`

---

## File Map

### Tier 0 — Schema additions

| Action | File | Responsibility |
|---|---|---|
| Create | `orchestrator/app/migrations/063_goal_maturation_feedback_columns.sql` | Add `spec_rejection_feedback TEXT`, `manual_implementation_note TEXT` to `goals` (the `spec` column already exists from migration 039) |

### Tier 1 — Triage

| Action | File | Responsibility |
|---|---|---|
| Create | `cortex/app/maturation/__init__.py` | Maturation package marker |
| Create | `cortex/app/maturation/triage.py` | `triage_goal_complexity(goal) -> Literal["simple", "complex"]` — LLM-driven classifier with safe fallback |
| Modify | `orchestrator/app/goals_router.py:98-129` | On goal creation, call triage via Redis stimulus; set `maturation_status='triaging'` if classifier returns `complex` |
| Create | `tests/test_maturation_triage.py` | Triage classifier behavior, simple/complex cases, fallback when LLM unavailable |

### Tier 2 — Scoping (Phase 1)

| Action | File | Responsibility |
|---|---|---|
| Create | `cortex/app/maturation/scoping.py` | `run_scoping(goal_id) -> dict` — analyze description, query engrams, identify affected scopes; write to `goals.scope_analysis`; transition `scoping → speccing` |
| Modify | `cortex/app/cycle.py` | Branch in serve-drive planning: if `maturation_phase == 'scoping'`, call `run_scoping` instead of generic task dispatch |
| Create | `tests/test_maturation_scoping.py` | Goal in `scoping` phase produces `scope_analysis`, transitions to `speccing` |

### Tier 3 — Speccing (Phase 2)

| Action | File | Responsibility |
|---|---|---|
| Create | `cortex/app/maturation/speccing.py` | `run_speccing(goal_id) -> str` — generate engineering spec from scope; write to `goals.spec` (column from migration 039); transition `speccing → review` |
| Modify | `cortex/app/cycle.py` | Branch: if `maturation_phase == 'speccing'`, call `run_speccing` |
| Modify | `orchestrator/app/goals_router.py` | Add `spec` field to `GoalResponse` model; expose via `GET /goals/{id}` |
| Create | `tests/test_maturation_speccing.py` | Goal in `speccing` produces `spec`, transitions to `review`; reject_spec resets to `speccing` |

### Tier 4 — Verifying (Phase 5)

| Action | File | Responsibility |
|---|---|---|
| Create | `cortex/app/maturation/verifying.py` | `run_verifying(goal_id) -> dict` — run health checks + post-completion validation; transition `verifying → completed` (status, not maturation_status) |
| Modify | `cortex/app/cycle.py` | Branch: if `maturation_phase == 'verifying'`, call `run_verifying` |
| Modify | `orchestrator/app/goals_router.py:approve_spec` | Change destination from `building` to `verifying` (skip Phase 4 — flagged in plan header). Add a `manual_implementation_note` column write so the human can record what they did. |
| Create | `tests/test_maturation_verifying.py` | After approve-spec, goal jumps to `verifying`; verification runs health checks; transitions to `complete` status |

### Tier 5 — End-to-end + dashboard

| Action | File | Responsibility |
|---|---|---|
| Modify | `dashboard/src/pages/Goals.tsx` | Show maturation status badge on goal cards |
| Create | `dashboard/src/components/GoalMaturationDetail.tsx` | Expandable detail: scope analysis, spec preview, Approve/Reject buttons |
| (covered by Tier 0 migration) | `orchestrator/app/migrations/063_goal_maturation_feedback_columns.sql` | Already adds `manual_implementation_note TEXT` |
| Create | `tests/test_maturation_lifecycle.py` | Full e2e: create complex goal → triaging → scoping → speccing → (test API: approve-spec) → verifying → complete |

---

## Task 1: Schema additions

**Files:**
- Create: `orchestrator/app/migrations/063_goal_maturation_feedback_columns.sql`

- [ ] **Step 1: Write migration** (file: `orchestrator/app/migrations/063_goal_maturation_feedback_columns.sql`)

```sql
-- Migration 063: Goal maturation — rejection feedback + manual implementation note
-- The `spec` column already exists from migration 039.
-- Completes the schema for the goal maturation pipeline (executor logic in cortex).

ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_rejection_feedback TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS manual_implementation_note TEXT;
```

- [ ] **Step 2: Verify migration applies cleanly**

Run: `docker compose restart orchestrator && docker compose logs orchestrator --tail 20 | grep -i migration`
Expected: `Applied migration 063_goal_maturation_feedback_columns.sql`

- [ ] **Step 3: Verify columns exist**

Run: `docker compose exec postgres psql -U nova -d nova -c "\\d goals" | grep -E "spec_rejection|manual_impl"`
Expected: Both columns present with TEXT type.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/migrations/063_goal_maturation_feedback_columns.sql
git commit -m "feat(maturation): add rejection feedback + manual impl note columns"
```

---

## Task 2: Triage helper

**Files:**
- Create: `cortex/app/maturation/__init__.py`
- Create: `cortex/app/maturation/triage.py`
- Test: `tests/test_maturation_triage.py`

- [ ] **Step 1: Write failing test for triage classifier**

```python
# tests/test_maturation_triage.py
"""Tier 1 — triage classifier."""
import pytest
import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": ""}  # filled by fixture


@pytest.fixture(autouse=True)
def admin_headers():
    import os
    HEADERS["X-Admin-Secret"] = os.environ.get("NOVA_ADMIN_SECRET", "")


def test_simple_goal_does_not_enter_maturation():
    """A trivial goal stays in NULL maturation_status."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-simple",
            "description": "Add a print statement to log.py",
            "priority": 3, "max_iterations": 5, "max_cost_usd": 0.50,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    gid = resp.json()["id"]
    try:
        # Wait briefly for stimulus-driven triage
        import time; time.sleep(2)
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        assert detail.get("maturation_status") in (None, "simple")
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)


def test_complex_goal_enters_triaging():
    """A multi-service goal is classified complex and enters maturation."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-complex",
            "description": (
                "Build a new microservice that handles webhook delivery: "
                "receives HTTP POSTs from external systems, queues them in Redis, "
                "stores them in postgres, retries failed deliveries, exposes "
                "a dashboard page for monitoring, and integrates with the auth system."
            ),
            "priority": 3, "max_iterations": 50, "max_cost_usd": 5.00,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    gid = resp.json()["id"]
    try:
        # Wait for stimulus-driven triage (cortex cycle ~30s)
        import time; time.sleep(35)
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        assert detail.get("maturation_status") in ("triaging", "scoping")
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && uv run --with pytest --with pytest-asyncio --with httpx pytest -v --tb=short test_maturation_triage.py::test_complex_goal_enters_triaging`
Expected: FAIL — `maturation_status` is None (no triage yet).

- [ ] **Step 3: Implement triage classifier**

```python
# cortex/app/maturation/__init__.py
"""Goal maturation pipeline — phase executors."""
```

```python
# cortex/app/maturation/triage.py
"""Triage classifier — decides whether a goal enters the maturation pipeline."""
from __future__ import annotations

import logging
from typing import Literal

from ..clients import get_llm
from ..config import settings

log = logging.getLogger(__name__)

TRIAGE_PROMPT = """Classify this engineering goal as `simple` or `complex`.

Title: {title}
Description: {description}

A goal is COMPLEX if any apply:
- Touches multiple services (orchestrator, cortex, memory, dashboard, etc.)
- Requires database migrations
- Needs frontend AND backend changes
- Has security implications (auth, secrets, RBAC)
- Changes infrastructure (docker, networking, deployment)
- Estimates 3+ files changed

A goal is SIMPLE if it's a focused single-file or single-concern change.

Respond with exactly one word: `simple` or `complex`."""


async def triage_goal_complexity(
    title: str, description: str | None
) -> Literal["simple", "complex"]:
    """Classify a goal's complexity. Defaults to `complex` on any error (safer)."""
    try:
        llm = get_llm()
        prompt = TRIAGE_PROMPT.format(
            title=title or "(untitled)",
            description=description or "(no description)",
        )
        resp = await llm.post(
            "/complete",
            json={
                "model": settings.planning_model or "",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 10,
                "tier": "cheap",
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            log.warning("Triage LLM returned %d, defaulting to complex", resp.status_code)
            return "complex"
        text = resp.json().get("content", "").strip().lower()
        if "simple" in text and "complex" not in text:
            return "simple"
        return "complex"
    except Exception as e:
        log.warning("Triage failed (%s), defaulting to complex", e)
        return "complex"
```

- [ ] **Step 4: Wire triage into goal creation**

Modify `orchestrator/app/goals_router.py:create_goal` to emit a stimulus on creation that cortex picks up. Cortex on receiving the stimulus calls `triage_goal_complexity` and updates `maturation_status` accordingly.

```python
# In orchestrator/app/goals_router.py:create_goal, after the INSERT
from .stimulus import emit_stimulus, GOAL_CREATED
await emit_stimulus(GOAL_CREATED, {"goal_id": str(new_id)})
```

```python
# Add to cortex/app/cycle.py — locate the stimulus consumer loop. Stimuli are
# consumed via DriveContext.stimuli (see DriveContext.stimuli_of_type usage in
# cortex/app/drives/serve.py:60). The triage handler runs in the maintain
# drive's tick (which already runs every cycle). Add to cortex/app/drives/maintain.py:

from ..stimulus import GOAL_CREATED  # add to existing imports
from ..maturation.triage import triage_goal_complexity  # add

async def assess(ctx: DriveContext | None = None) -> DriveResult:
    # ... existing body ...
    # NEW: handle goal.created stimuli (triage)
    if ctx:
        for stim in ctx.stimuli_of_type(GOAL_CREATED):
            goal_id = stim["payload"]["goal_id"]
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT title, description, maturation_status FROM goals WHERE id = $1::uuid",
                    goal_id,
                )
                if row and row["maturation_status"] is None:
                    # Only triage goals that haven't been classified yet
                    verdict = await triage_goal_complexity(row["title"], row["description"])
                    new_status = "scoping" if verdict == "complex" else None
                    # `scoping` is the first active phase — triaging is transient
                    await conn.execute(
                        "UPDATE goals SET maturation_status = $1, updated_at = NOW() WHERE id = $2::uuid",
                        new_status, goal_id,
                    )
    # ... rest of existing body ...
```

If the existing maintain drive has no stimulus-handling code yet, the alternative is to add the handler to the main loop — search `cycle.py` for `ctx.stimuli` to find where stimuli are consumed and add the dispatch there. Use `DriveContext.stimuli_of_type(GOAL_CREATED)` for the lookup.

- [ ] **Step 5: Run tests to verify pass**

Run: `cd tests && pytest -v test_maturation_triage.py`
Expected: Both tests pass.

- [ ] **Step 6: Commit**

```bash
git add cortex/app/maturation/__init__.py cortex/app/maturation/triage.py orchestrator/app/goals_router.py cortex/app/cycle.py tests/test_maturation_triage.py
git commit -m "feat(maturation): triage classifier — complex goals enter pipeline"
```

---

## Task 3: Scoping phase executor

**Files:**
- Create: `cortex/app/maturation/scoping.py`
- Modify: `cortex/app/cycle.py` (add `scoping` branch in serve-drive planning)
- Test: `tests/test_maturation_scoping.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_maturation_scoping.py
"""Tier 2 — scoping phase produces scope_analysis."""
import os, time, httpx, pytest

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def test_scoping_produces_scope_analysis():
    """Goal entering scoping gets scope_analysis populated within ~60s."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-scoping",
            "description": "Add a webhook delivery service with auth, dashboard, and Redis queue",
            "priority": 5, "max_iterations": 10, "max_cost_usd": 1.00,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        # Force into scoping
        httpx.patch(
            f"{BASE}/goals/{gid}",
            json={"maturation_status": "scoping"},
            headers=HEADERS,
        )
        # Wait for cortex cycle (default 30s) plus scope analysis
        for _ in range(8):
            time.sleep(15)
            scope = httpx.get(f"{BASE}/goals/{gid}/scope", headers=HEADERS).json()
            if scope:
                break
        assert scope, "scope_analysis was never populated"
        # Should have identified backend + auth at minimum
        scopes_str = " ".join(str(scope.get(k, "")) for k in scope).lower()
        assert "backend" in scopes_str or "service" in scopes_str
        # Should have transitioned to speccing
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        assert detail.get("maturation_status") == "speccing"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && pytest -v test_maturation_scoping.py::test_scoping_produces_scope_analysis`
Expected: FAIL — scope_analysis stays empty, status stays at scoping.

- [ ] **Step 3: Implement scoping**

```python
# cortex/app/maturation/scoping.py
"""Scoping phase — analyze goal, identify affected areas, write scope_analysis."""
from __future__ import annotations

import json
import logging

from ..db import get_pool
from ..clients import get_llm
from ..memory import perceive_with_memory
from ..config import settings

log = logging.getLogger(__name__)

SCOPE_PROMPT = """Analyze this engineering goal. Identify all areas of the codebase affected.

Goal: {title}
Description: {description}

Related context from memory (top 5):
{memory_context}

Output JSON with these keys:
- "affected_scopes": list of strings from {{backend, frontend, data, security, infra, networking, ci_cd, testing}}
- "estimated_files_changed": integer
- "key_components": list of file paths or service names that will change
- "open_questions": list of clarifying questions for the human (empty list if none)
- "summary": one paragraph explaining what's affected and why

Respond with valid JSON only, no prose."""


async def run_scoping(goal_id: str) -> dict:
    """Execute the scoping phase for a goal. Writes scope_analysis, transitions to speccing."""
    pool = get_pool()
    async with pool.acquire() as conn:
        goal = await conn.fetchrow(
            "SELECT title, description FROM goals WHERE id = $1::uuid",
            goal_id,
        )
    if not goal:
        log.warning("Scoping called for missing goal %s", goal_id)
        return {}

    # Build a query stimulus from goal title + description, fetch via existing
    # cortex memory pathway (mirrors how the perceive phase works in cycle.py).
    perception = await perceive_with_memory(
        stimuli=[{"type": "goal.scoping", "payload": {"goal_id": goal_id}}],
        goal_context=f"{goal['title']} — {goal['description'] or ''}",
    )
    memory_str = perception.get("memory_context") or "(no relevant memories)"

    prompt = SCOPE_PROMPT.format(
        title=goal["title"],
        description=goal["description"] or "(no description)",
        memory_context=memory_str,
    )

    llm = get_llm()
    resp = await llm.post(
        "/complete",
        json={
            "model": settings.planning_model or "",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1500,
            "tier": "mid",
            "response_format": {"type": "json_object"},
        },
        timeout=120.0,
    )
    if resp.status_code != 200:
        log.warning("Scoping LLM returned %d for goal %s", resp.status_code, goal_id)
        return {}

    try:
        scope_data = json.loads(resp.json().get("content", "{}"))
    except json.JSONDecodeError as e:
        log.warning("Scoping LLM returned invalid JSON for goal %s: %s", goal_id, e)
        return {}

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET scope_analysis = $1::jsonb,
                                  maturation_status = 'speccing',
                                  updated_at = NOW()
               WHERE id = $2::uuid""",
            json.dumps(scope_data), goal_id,
        )
    log.info("Scoping complete for goal %s — transitioned to speccing", goal_id)
    return scope_data
```

- [ ] **Step 4: Wire into cycle.py**

In `cycle.py`, find the serve-drive dispatch logic (where it currently calls `_dispatch_task` or similar). Add a branch:

```python
# Inside serve drive planning, after fetching goal with maturation_phase
if maturation_phase == "scoping":
    from .maturation.scoping import run_scoping
    await run_scoping(state.goal_id)
    state.action_taken = "serve"
    return  # Skip generic task dispatch this cycle
```

- [ ] **Step 5: Run test to verify pass**

Run: `cd tests && pytest -v test_maturation_scoping.py`
Expected: Test passes within ~2 min (cortex cycle interval).

- [ ] **Step 6: Commit**

```bash
git add cortex/app/maturation/scoping.py cortex/app/cycle.py tests/test_maturation_scoping.py
git commit -m "feat(maturation): scoping phase — LLM analyzes goal scope"
```

---

## Task 4: Speccing phase executor

**Files:**
- Create: `cortex/app/maturation/speccing.py`
- Modify: `cortex/app/cycle.py` (add `speccing` branch alongside the `scoping` branch from Task 3)
- Modify: `orchestrator/app/goals_router.py` — (a) widen `UpdateGoalRequest` so tests can seed `scope_analysis`/`spec` via PATCH; (b) add `spec` field to `GoalResponse` and `_row_to_goal()` mapper
- Test: `tests/test_maturation_speccing.py`

- [ ] **Step 0: Widen UpdateGoalRequest so tests can seed maturation fields**

In `orchestrator/app/goals_router.py`, find `class UpdateGoalRequest(BaseModel)`. Add two fields:

```python
class UpdateGoalRequest(BaseModel):
    # ... existing fields ...
    maturation_status: str | None = None
    scope_analysis: dict | None = None  # NEW — admin-only seeding for maturation tests
    spec: str | None = None              # NEW — admin-only seeding for maturation tests
```

Also extend the PATCH handler (`update_goal` at line 200) to apply these fields if present. Look for the existing field-by-field update pattern and add the two new ones following the same shape. The endpoint is already admin-gated via `UserDep`, so this is safe.

- [ ] **Step 1: Write failing test**

```python
# tests/test_maturation_speccing.py
"""Tier 3 — speccing phase produces spec."""
import os, time, httpx, json

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def test_speccing_produces_spec_and_transitions_to_review():
    """Goal in speccing phase gets spec populated and transitions to review within ~90s."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-speccing",
            "description": "Add webhook delivery service with auth and dashboard",
            "priority": 5, "max_iterations": 10, "max_cost_usd": 1.00,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        # Force into speccing with a pre-populated scope_analysis
        scope_seed = {"affected_scopes": ["backend", "frontend", "security"],
                      "estimated_files_changed": 6,
                      "summary": "Adds a webhook service touching auth and dashboard."}
        # Use orchestrator's PATCH to set both columns
        httpx.patch(
            f"{BASE}/goals/{gid}",
            json={"maturation_status": "speccing", "scope_analysis": scope_seed},
            headers=HEADERS,
        )
        # Wait for cortex cycle (default 30s) plus speccing LLM call
        for _ in range(8):
            time.sleep(15)
            detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
            if detail.get("spec"):
                break
        assert detail.get("spec"), "spec was never populated"
        assert len(detail["spec"]) > 100, "spec too short to be a real spec"
        assert detail.get("maturation_status") == "review"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && pytest -v test_maturation_speccing.py::test_speccing_produces_spec_and_transitions_to_review`
Expected: FAIL — `spec` stays NULL because no executor writes to it.

- [ ] **Step 3: Implement speccing**

```python
# cortex/app/maturation/speccing.py
"""Speccing phase — generate engineering spec from scope, write to goals.spec."""
from __future__ import annotations

import json
import logging

from ..clients import get_llm
from ..config import settings
from ..db import get_pool

log = logging.getLogger(__name__)

SPEC_PROMPT = """Generate an engineering spec for this goal.

Goal: {title}
Description: {description}

Scope analysis (already produced):
{scope_analysis}

Produce a markdown spec with these sections:
1. **Architecture** — 2-3 sentences on the approach
2. **File changes** — markdown table: Action | Path | Responsibility
3. **Sub-tasks in dependency order** — numbered list, each one a 1-day-or-less unit
4. **Cost/complexity estimate** — rough hours or days
5. **Open questions** — list, empty if none

Keep total spec under 1500 words. Be concrete; reference real file paths and known
services. The reader is an engineer who will execute this plan tomorrow.

Respond with the markdown spec only, no preamble."""


async def run_speccing(goal_id: str) -> str:
    """Generate spec, write to goals.spec, transition speccing → review."""
    pool = get_pool()
    async with pool.acquire() as conn:
        goal = await conn.fetchrow(
            "SELECT title, description, scope_analysis FROM goals WHERE id = $1::uuid",
            goal_id,
        )
    if not goal or not goal["scope_analysis"]:
        log.warning("Speccing called without scope_analysis for goal %s", goal_id)
        return ""

    scope_str = json.dumps(goal["scope_analysis"], indent=2) if isinstance(
        goal["scope_analysis"], dict
    ) else str(goal["scope_analysis"])

    prompt = SPEC_PROMPT.format(
        title=goal["title"],
        description=goal["description"] or "(no description)",
        scope_analysis=scope_str,
    )

    llm = get_llm()
    resp = await llm.post(
        "/complete",
        json={
            "model": settings.planning_model or "",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 3000,
            "tier": "best",
        },
        timeout=180.0,
    )
    if resp.status_code != 200:
        log.warning("Speccing LLM returned %d for goal %s", resp.status_code, goal_id)
        return ""

    spec = resp.json().get("content", "").strip()
    if len(spec) < 50:
        log.warning("Speccing returned too-short spec for goal %s", goal_id)
        return ""

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET spec = $1,
                                  maturation_status = 'review',
                                  updated_at = NOW()
               WHERE id = $2::uuid""",
            spec, goal_id,
        )

    # Dashboard surfaces "review" state via the existing goals-list refresh
    # (TanStack Query staleTime=5s in dashboard/src/api.ts). No extra stimulus
    # needed — the visible badge transition is the notification.

    log.info("Speccing complete for goal %s — transitioned to review", goal_id)
    return spec
```

- [ ] **Step 4: Wire into cycle.py**

Find the `maturation_phase == "scoping"` branch added in Task 3. Add a sibling branch:

```python
elif maturation_phase == "speccing":
    from .maturation.speccing import run_speccing
    await run_speccing(state.goal_id)
    state.action_taken = "serve"
    return  # Skip generic task dispatch
```

- [ ] **Step 5: Add `spec` field to GoalResponse**

In `orchestrator/app/goals_router.py`, find the `GoalResponse` Pydantic model (line 87 area — confirm via `grep -n "class GoalResponse" goals_router.py`). Add:

```python
class GoalResponse(BaseModel):
    # ... existing fields ...
    spec: str | None = None
    spec_rejection_feedback: str | None = None
```

And in `_row_to_goal(row)` (line 266 area):

```python
def _row_to_goal(row) -> GoalResponse:
    return GoalResponse(
        # ... existing mappings ...
        spec=row.get("spec"),
        spec_rejection_feedback=row.get("spec_rejection_feedback"),
    )
```

- [ ] **Step 6: Run test to verify pass**

Run: `cd tests && pytest -v test_maturation_speccing.py`
Expected: Test passes within ~3 min.

- [ ] **Step 7: Commit**

```bash
git add cortex/app/maturation/speccing.py cortex/app/cycle.py orchestrator/app/goals_router.py tests/test_maturation_speccing.py
git commit -m "feat(maturation): speccing phase — LLM generates spec, transitions to review"
```

---

## Task 5: Approve-spec routes to verifying (Phase 4 skip)

**Files:**
- Modify: `orchestrator/app/goals_router.py:359-374` (approve_spec endpoint)
- Test: `tests/test_maturation_approve.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/test_maturation_approve.py
"""Verify approve-spec routes directly to verifying (Phase 4 building deferred)."""
import os, httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def test_approve_spec_routes_to_verifying():
    """approve-spec sets maturation_status to 'verifying', not 'building'."""
    # Create goal and force into review
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-approve-spec",
            "description": "Test approve-spec routing",
            "priority": 3, "max_iterations": 5, "max_cost_usd": 0.50,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        # Force into review state with seeded scope + spec
        httpx.patch(
            f"{BASE}/goals/{gid}",
            json={
                "maturation_status": "review",
                "scope_analysis": {"affected_scopes": ["backend"]},
                "spec": "## Architecture\\nMinimal change.",
            },
            headers=HEADERS,
        )
        resp = httpx.post(f"{BASE}/goals/{gid}/approve-spec", headers=HEADERS)
        assert resp.status_code == 200
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        assert detail["maturation_status"] == "verifying", \
            f"Expected verifying (Phase 4 deferred), got {detail['maturation_status']}"
        assert detail.get("spec_approved_at"), "spec_approved_at should be set"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && pytest -v test_maturation_approve.py`
Expected: FAIL — currently routes to `building`.

- [ ] **Step 3: Update goals_router.py**

Edit `orchestrator/app/goals_router.py:359-374`. Change the SQL string in the approve_spec function from `'building'` to `'verifying'` and add an inline comment explaining the deferral:

```python
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
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd tests && pytest -v test_maturation_approve.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/goals_router.py tests/test_maturation_approve.py
git commit -m "feat(maturation): approve-spec routes to verifying (Phase 4 deferred)"
```

---

## Task 6: Verifying phase executor

**Files:**
- Create: `cortex/app/maturation/verifying.py`
- Modify: `cortex/app/cycle.py` — add `verifying` branch alongside `scoping`/`speccing`
- Test: `tests/test_maturation_verifying.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_maturation_verifying.py
"""Tier 4 — verifying phase runs health checks, transitions to completed."""
import os, time, httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def test_verifying_completes_goal_when_services_healthy():
    """Goal in verifying transitions to status='completed' once health checks pass."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-verifying",
            "description": "Test verifying phase",
            "priority": 3, "max_iterations": 5, "max_cost_usd": 0.50,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        httpx.patch(
            f"{BASE}/goals/{gid}",
            json={"maturation_status": "verifying"},
            headers=HEADERS,
        )
        # Wait for cortex cycle (default 30s)
        for _ in range(6):
            time.sleep(15)
            detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
            if detail.get("status") == "completed":
                break
        assert detail.get("status") == "completed", \
            f"Goal should be completed after verifying, got status={detail.get('status')}"
        assert detail.get("maturation_status") is None, \
            "maturation_status should be cleared after completion"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && pytest -v test_maturation_verifying.py`
Expected: FAIL — no executor advances the goal from verifying.

- [ ] **Step 3: Implement verifying**

```python
# cortex/app/maturation/verifying.py
"""Verifying phase — run health checks, mark goal complete (or back to review on failure)."""
from __future__ import annotations

import logging
import httpx

from ..config import settings
from ..db import get_pool

log = logging.getLogger(__name__)

# Service health endpoints to probe. Ports match docker-compose service names
# from the Nova stack — use the docker-internal hostnames since cortex runs in
# the same compose network.
HEALTH_ENDPOINTS = [
    ("orchestrator", "http://orchestrator:8000/health/ready"),
    ("llm-gateway", "http://llm-gateway:8001/health/ready"),
    ("memory-service", "http://memory-service:8002/health/ready"),
]


async def run_verifying(goal_id: str) -> bool:
    """Run health checks. Returns True if goal completed successfully, False otherwise."""
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
                                   updated_at = NOW(),
                                   completed_at = NOW()
               WHERE id = $1::uuid""",
            goal_id,
        )
    from ..stimulus import emit, GOAL_COMPLETED
    await emit(GOAL_COMPLETED, "cortex", payload={"goal_id": goal_id})
    log.info("Verification passed for goal %s — marked completed", goal_id)
    return True
```

- [ ] **Step 4: Wire into cycle.py**

Add to the maturation branch chain (alongside `scoping` and `speccing`):

```python
elif maturation_phase == "verifying":
    from .maturation.verifying import run_verifying
    await run_verifying(state.goal_id)
    state.action_taken = "serve"
    return
```

- [ ] **Step 5: Run test to verify pass**

Run: `cd tests && pytest -v test_maturation_verifying.py`
Expected: PASS — goal transitions to `completed` once cortex picks it up (~30-60s).

- [ ] **Step 6: Commit**

```bash
git add cortex/app/maturation/verifying.py cortex/app/cycle.py tests/test_maturation_verifying.py
git commit -m "feat(maturation): verifying phase — health checks complete goal"
```

---

## Task 7: End-to-end lifecycle test

**Files:**
- Create: `tests/test_maturation_lifecycle.py`

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_maturation_lifecycle.py
"""End-to-end goal maturation lifecycle: create → triage → scope → spec → review → verify → complete.

Skips Phase 4 (building) — handled separately when goal decomposition lands.
"""
import os, time, httpx, pytest

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def _wait_for_status(gid: str, predicate, timeout: int = 180) -> dict:
    """Poll goal until predicate(detail) is true or timeout."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        if predicate(last):
            return last
        time.sleep(15)
    raise AssertionError(
        f"Timed out waiting for goal {gid}; last state: maturation_status="
        f"{last.get('maturation_status')}, status={last.get('status')}"
    )


@pytest.mark.slow
def test_full_maturation_lifecycle():
    """A complex goal flows triaging → scoping → speccing → review → verifying → complete."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-lifecycle",
            "description": (
                "Build a webhook delivery microservice with auth, dashboard page, "
                "Redis queue, postgres storage, retry policy, and security review."
            ),
            "priority": 5, "max_iterations": 10, "max_cost_usd": 2.00,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        # Triage should kick in within ~30s and produce maturation_status='scoping'
        # (since the goal is clearly complex)
        d = _wait_for_status(gid, lambda x: x.get("maturation_status") in ("scoping", "speccing", "review"))
        assert d.get("maturation_status") in ("scoping", "speccing", "review")

        # Scoping should populate scope_analysis and transition to speccing
        d = _wait_for_status(gid, lambda x: x.get("maturation_status") in ("speccing", "review"))
        scope = httpx.get(f"{BASE}/goals/{gid}/scope", headers=HEADERS).json()
        assert scope, "scope_analysis should be populated by now"

        # Speccing should populate spec and transition to review
        d = _wait_for_status(gid, lambda x: x.get("maturation_status") == "review")
        assert d.get("spec"), "spec should be populated"
        assert len(d["spec"]) > 100

        # Human approves
        resp = httpx.post(f"{BASE}/goals/{gid}/approve-spec", headers=HEADERS)
        assert resp.status_code == 200

        # Verifying runs and transitions to completed
        d = _wait_for_status(gid, lambda x: x.get("status") == "completed", timeout=120)
        assert d.get("status") == "completed"
        assert d.get("maturation_status") is None
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
```

- [ ] **Step 2: Register the `slow` marker** (if not already present)

Add to `tests/conftest.py` `pytest_configure`:

```python
config.addinivalue_line("markers", "slow: marker for long-running e2e tests (~3-5 min)")
```

- [ ] **Step 3: Run the test**

Run: `cd tests && pytest -v --tb=short -m slow test_maturation_lifecycle.py`
Expected: PASS within ~5 min.

- [ ] **Step 4: Commit**

```bash
git add tests/test_maturation_lifecycle.py tests/conftest.py
git commit -m "test(maturation): end-to-end lifecycle covering triage→complete"
```

---

## Task 8: Dashboard UI

**Files:**
- Create: `dashboard/src/components/MaturationBadge.tsx` — colored pill for maturation_status
- Create: `dashboard/src/components/GoalMaturationDetail.tsx` — expandable detail with scope, spec, Approve/Reject buttons
- Modify: `dashboard/src/pages/Goals.tsx` — show MaturationBadge on each goal, render GoalMaturationDetail when expanded

**Badge color mapping** (per `DESIGN.md` — restrained palette: teal primary, amber for cognitive states, stone for neutrals):

| maturation_status | Color | Rationale |
|---|---|---|
| `triaging` | stone-400 / stone-600 dark | Pre-cognitive, not yet active |
| `scoping` | amber-400 (text) on amber-950/30 (bg) | Active cognition |
| `speccing` | amber-500 (text) on amber-950/30 (bg) | Deeper active cognition |
| `review` | teal-400 (text) on teal-900/30 (bg) | Awaiting human — primary accent |
| `verifying` | amber-400 with pulse animation | Cognition + uncertainty |
| `completed` (status, badge fades) | stone-500 | Terminal |

- [ ] **Step 1: Create MaturationBadge component**

```tsx
// dashboard/src/components/MaturationBadge.tsx
import { ReactElement } from 'react';

type MaturationStatus = 'triaging' | 'scoping' | 'speccing' | 'review' | 'verifying' | null | undefined;

const STYLES: Record<NonNullable<MaturationStatus>, string> = {
  triaging:  'bg-stone-200/50 text-stone-600 dark:bg-stone-800/50 dark:text-stone-400',
  scoping:   'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400',
  speccing:  'bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-500',
  review:    'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400',
  verifying: 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 animate-pulse',
};

const LABELS: Record<NonNullable<MaturationStatus>, string> = {
  triaging:  'Triaging',
  scoping:   'Scoping',
  speccing:  'Speccing',
  review:    'Awaiting Review',
  verifying: 'Verifying',
};

export function MaturationBadge({ status }: { status: MaturationStatus }): ReactElement | null {
  if (!status) return null;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STYLES[status]}`}>
      {LABELS[status]}
    </span>
  );
}
```

- [ ] **Step 2: Create GoalMaturationDetail component**

```tsx
// dashboard/src/components/GoalMaturationDetail.tsx
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../api';

type Goal = {
  id: string;
  maturation_status: string | null;
  scope_analysis: Record<string, unknown> | null;
  spec: string | null;
};

export function GoalMaturationDetail({ goal }: { goal: Goal }) {
  const qc = useQueryClient();
  const [feedback, setFeedback] = useState('');

  const approve = useMutation({
    mutationFn: () => apiFetch(`/api/v1/goals/${goal.id}/approve-spec`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  });
  const reject = useMutation({
    mutationFn: () =>
      apiFetch(`/api/v1/goals/${goal.id}/reject-spec`, {
        method: 'POST',
        body: JSON.stringify({ feedback }),
      }),
    onSuccess: () => {
      setFeedback('');
      qc.invalidateQueries({ queryKey: ['goals'] });
    },
  });

  return (
    <div className="border-t border-stone-200 dark:border-stone-800 p-4 space-y-4">
      {goal.scope_analysis && (
        <section>
          <h4 className="text-xs uppercase text-stone-500 mb-1">Scope Analysis</h4>
          <pre className="text-xs bg-stone-50 dark:bg-stone-900 p-2 rounded overflow-auto">
            {JSON.stringify(goal.scope_analysis, null, 2)}
          </pre>
        </section>
      )}
      {goal.spec && (
        <section>
          <h4 className="text-xs uppercase text-stone-500 mb-1">Spec</h4>
          <pre className="text-sm whitespace-pre-wrap font-sans">{goal.spec}</pre>
        </section>
      )}
      {goal.maturation_status === 'review' && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => approve.mutate()}
            disabled={approve.isPending}
            className="px-3 py-1.5 rounded bg-teal-500 text-white text-sm font-medium hover:bg-teal-600 disabled:opacity-50"
          >
            {approve.isPending ? 'Approving…' : 'Approve Spec'}
          </button>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Feedback for revision (required to reject)"
            className="px-3 py-2 rounded border border-stone-300 dark:border-stone-700 bg-transparent text-sm"
            rows={3}
          />
          <button
            type="button"
            onClick={() => reject.mutate()}
            disabled={reject.isPending || !feedback.trim()}
            className="px-3 py-1.5 rounded border border-stone-300 dark:border-stone-700 text-sm font-medium hover:bg-stone-100 dark:hover:bg-stone-800 disabled:opacity-50"
          >
            Reject &amp; Revise
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Wire into Goals.tsx**

In `dashboard/src/pages/Goals.tsx`, locate the goal row/card render. Add:

```tsx
import { MaturationBadge } from '../components/MaturationBadge';
import { GoalMaturationDetail } from '../components/GoalMaturationDetail';

// In the goal card rendering, next to title/status:
<MaturationBadge status={goal.maturation_status} />

// Below the row, when expanded:
{expandedGoalId === goal.id && goal.maturation_status && (
  <GoalMaturationDetail goal={goal} />
)}
```

If `Goals.tsx` doesn't already track an expanded-row state, add it at the top of the component:

```tsx
const [expandedGoalId, setExpandedGoalId] = useState<string | null>(null);

// On the goal row's onClick:
onClick={() => setExpandedGoalId(prev => prev === goal.id ? null : goal.id)}
```

- [ ] **Step 4: Verify TypeScript build**

Run: `cd dashboard && npm run build`
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 5: Manual smoke test**

1. `make dev` (if not running)
2. Open dashboard at http://localhost:5173/goals
3. Create a complex goal via the dashboard UI
4. Refresh after ~30s — should see "Scoping" badge
5. Refresh after ~60s — should see "Speccing" then "Awaiting Review"
6. Click row to expand; verify scope analysis + spec render
7. Click "Approve Spec" — should transition to "Verifying" then "completed"

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/MaturationBadge.tsx dashboard/src/components/GoalMaturationDetail.tsx dashboard/src/pages/Goals.tsx
git commit -m "feat(dashboard): goal maturation badges + approve/reject UI"
```

---

## Verification of full plan

After all 8 tasks complete:

- [ ] `make test` shows new maturation tests passing (~6-8 added tests, all green)
- [ ] Dashboard Goals page shows maturation badges and approve/reject flow works end-to-end
- [ ] Cortex logs show `outcome=Scoping complete`, `outcome=Speccing complete`, `outcome=Verifying complete` for goals progressing through phases
- [ ] `SELECT id, title, maturation_status, scope_analysis IS NOT NULL AS has_scope, spec IS NOT NULL AS has_spec FROM goals WHERE maturation_status IS NOT NULL` shows goals at all phases with appropriate state
- [ ] Roadmap entry "Maturation pipeline executor" can be marked Delivered

**Total estimated effort:** 2-3 days (1 person, focused).

**Dependency check:** This plan does NOT depend on goal decomposition. Phase 4 (`building`) is intentionally skipped — `approve-spec` routes directly to `verifying`. When goal decomposition lands later, a follow-up plan re-routes approve-spec to `building` and adds the sub-goal-spawn logic.
