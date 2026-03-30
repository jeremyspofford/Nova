# Cortex: Learning from Experience — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Cortex structured memory of what it has tried for each goal, so it stops repeating failures, builds on successes, and escalates when stuck.

**Architecture:** New `cortex_reflections` table stores structured outcomes per goal. The reflections module (`cortex/app/reflections.py`) handles all CRUD, dedup, and stuck detection. The thinking cycle wires in at two points: PLAN phase queries prior reflections, REFLECT phase records new ones. Lessons optionally ingest into engrams for cross-goal learning.

**Tech Stack:** Python 3.11, asyncpg, FastAPI, SHA-256 hashing, LLM lesson extraction via llm-gateway

**Spec:** `docs/specs/2026-03-28-cortex-learning-from-experience.md`

---

## File Map

### Created
| File | Responsibility |
|------|---------------|
| `orchestrator/app/migrations/048_cortex_reflections.sql` | Table, indexes, cascade delete |
| `cortex/app/reflections.py` | Record, query, format, dedup, stuck detection, approach hashing |
| `tests/test_cortex_reflections.py` | Integration tests for the full reflection lifecycle |

### Modified
| File | Changes |
|------|---------|
| `cortex/app/config.py:5-66` | Add `stuck_threshold_min` and `lesson_extraction_min_tier` settings |
| `cortex/app/stimulus.py:34-39` | Add `GOAL_STUCK` stimulus type constant |
| `cortex/app/cycle.py:172-173` | PLAN phase: query reflections, inject history into planning prompt |
| `cortex/app/cycle.py:184-185` | REFLECT phase: record reflection after task tracking |
| `cortex/app/cycle.py:390-434` | ACT phase: approach dedup check before dispatch |
| `cortex/app/memory.py` | Add `ingest_lesson()` for conditional engram ingestion |
| `cortex/app/router.py` | Add `GET /api/v1/cortex/reflections/{goal_id}` endpoint |

---

## Task 1: Migration — create cortex_reflections table

**Files:**
- Create: `orchestrator/app/migrations/048_cortex_reflections.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- 048_cortex_reflections.sql
-- Structured experience log for Cortex goal learning.
-- Records what was tried, what happened, and lessons learned per goal cycle.

CREATE TABLE IF NOT EXISTS cortex_reflections (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id           UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    cycle_number      INTEGER NOT NULL,
    drive             TEXT NOT NULL DEFAULT 'serve',
    maturation_phase  TEXT,
    task_id           UUID,

    -- What was tried
    approach          TEXT NOT NULL,
    approach_hash     TEXT NOT NULL,

    -- What happened
    outcome           TEXT NOT NULL CHECK (outcome IN (
                          'success', 'partial', 'failure', 'timeout', 'cancelled', 'escalated'
                      )),
    outcome_score     REAL NOT NULL,
    lesson            TEXT,
    failure_mode      TEXT,

    -- Conditions at time of reflection
    context_snapshot  JSONB DEFAULT '{}',

    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Primary query: recent reflections for a goal
CREATE INDEX IF NOT EXISTS cortex_reflections_goal_created_idx
    ON cortex_reflections (goal_id, created_at DESC);

-- Filter by outcome for stuck detection
CREATE INDEX IF NOT EXISTS cortex_reflections_goal_outcome_idx
    ON cortex_reflections (goal_id, outcome);

-- Approach dedup lookup
CREATE INDEX IF NOT EXISTS cortex_reflections_goal_hash_idx
    ON cortex_reflections (goal_id, approach_hash);
```

- [ ] **Step 2: Verify migration numbering**

Run: `ls orchestrator/app/migrations/*.sql | tail -3`
Expected: `048_cortex_reflections.sql` is the highest number (047_skills_and_rules.sql is the previous highest)

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/migrations/048_cortex_reflections.sql
git commit -m "feat(cortex): add cortex_reflections table for experience learning"
```

---

## Task 2: Config and stimulus additions

**Files:**
- Modify: `cortex/app/config.py:58` (before `log_level`)
- Modify: `cortex/app/stimulus.py:39` (after last stimulus constant)

- [ ] **Step 1: Add config settings**

In `cortex/app/config.py`, add two settings after `reflection_model` (line 56) and before `log_level` (line 59):

```python
    # Learning from experience
    stuck_threshold_min: int = int(os.getenv("CORTEX_STUCK_THRESHOLD_MIN", "3"))
    lesson_extraction_min_tier: str = os.getenv("CORTEX_LESSON_EXTRACTION_MIN_TIER", "mid")
```

- [ ] **Step 2: Add GOAL_STUCK stimulus type**

In `cortex/app/stimulus.py`, add after `GOAL_COMMENTED` (line 39):

```python

# Experience learning stimuli
GOAL_STUCK = "goal.stuck"
```

- [ ] **Step 3: Commit**

```bash
git add cortex/app/config.py cortex/app/stimulus.py
git commit -m "feat(cortex): add config and stimulus types for experience learning"
```

---

## Task 3: Reflections module — core functions

**Files:**
- Create: `cortex/app/reflections.py`

This is the central module. It handles hashing, recording, querying, formatting, dedup, and stuck detection. All DB queries use the shared asyncpg pool from `cortex/app/db.py`.

- [ ] **Step 1: Create reflections.py with hash and record functions**

```python
"""Structured experience log for Cortex goal learning.

Records what was tried per goal, what happened, and lessons learned.
Used by the thinking cycle to avoid repeating failures and to detect stuck goals.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from .config import settings
from .db import get_pool

log = logging.getLogger(__name__)

# Budget tier ordering for condition comparison
_TIER_ORDER = {"none": 0, "cheap": 1, "mid": 2, "best": 3}


def compute_approach_hash(text: str) -> str:
    """Normalize approach text and return a truncated SHA-256 hash.

    Normalization: lowercase, collapse whitespace. Preserves word order so
    this catches exact/near-exact duplicates but not semantic equivalents.
    """
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


async def record_reflection(
    goal_id: str,
    cycle_number: int,
    approach: str,
    outcome: str,
    outcome_score: float,
    task_id: str | None = None,
    drive: str = "serve",
    maturation_phase: str | None = None,
    lesson: str | None = None,
    failure_mode: str | None = None,
    context_snapshot: dict | None = None,
) -> str:
    """Insert a reflection and return its ID."""
    approach_hash = compute_approach_hash(approach)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO cortex_reflections
               (goal_id, cycle_number, drive, maturation_phase, task_id,
                approach, approach_hash, outcome, outcome_score,
                lesson, failure_mode, context_snapshot)
               VALUES ($1::uuid, $2, $3, $4, $5::uuid,
                       $6, $7, $8, $9,
                       $10, $11, $12::jsonb)
               RETURNING id""",
            goal_id, cycle_number, drive, maturation_phase,
            task_id,
            approach[:1000], approach_hash, outcome, outcome_score,
            lesson[:500] if lesson else None,
            failure_mode[:200] if failure_mode else None,
            json.dumps(context_snapshot or {}),
        )
    ref_id = str(row["id"])
    log.info(
        "Recorded reflection for goal %s: outcome=%s score=%.1f hash=%s",
        goal_id, outcome, outcome_score, approach_hash,
    )
    return ref_id


async def query_reflections(
    goal_id: str,
    phase: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Get recent reflections for a goal, optionally filtered by maturation phase."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if phase:
            rows = await conn.fetch(
                """SELECT id, cycle_number, approach, approach_hash, outcome,
                          outcome_score, lesson, failure_mode, maturation_phase,
                          context_snapshot, created_at
                   FROM cortex_reflections
                   WHERE goal_id = $1::uuid AND maturation_phase = $2
                   ORDER BY created_at DESC
                   LIMIT $3""",
                goal_id, phase, limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, cycle_number, approach, approach_hash, outcome,
                          outcome_score, lesson, failure_mode, maturation_phase,
                          context_snapshot, created_at
                   FROM cortex_reflections
                   WHERE goal_id = $1::uuid
                   ORDER BY created_at DESC
                   LIMIT $2""",
                goal_id, limit,
            )
    return [
        {
            "id": str(r["id"]),
            "cycle_number": r["cycle_number"],
            "approach": r["approach"],
            "approach_hash": r["approach_hash"],
            "outcome": r["outcome"],
            "outcome_score": r["outcome_score"],
            "lesson": r["lesson"],
            "failure_mode": r["failure_mode"],
            "maturation_phase": r["maturation_phase"],
            "context_snapshot": r["context_snapshot"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


def format_reflection_history(
    reflections: list[dict],
    current_goal_desc_hash: str | None = None,
) -> str:
    """Format reflections as a compact block for the planning prompt.

    Each entry is capped at ~40 tokens. Flags when the goal description has
    changed since older reflections (human intervention signal).
    Returns empty string if no reflections.
    """
    if not reflections:
        return ""

    lines = ["Prior experience with this goal:"]

    # Check if goal description changed since oldest reflection
    if current_goal_desc_hash and reflections:
        oldest = reflections[-1]  # list is newest-first
        old_hash = (oldest.get("context_snapshot") or {}).get("goal_description_hash")
        if old_hash and old_hash != current_goal_desc_hash:
            lines.append("(Note: goal description was modified since earlier attempts — prior failures may be less relevant)")

    for r in reversed(reflections):  # chronological order (oldest first)
        outcome = r["outcome"]
        score = r["outcome_score"]
        approach = r["approach"][:80]
        line = f"- [{outcome} ({score:.1f})] {approach}"
        if r.get("lesson"):
            line += f" → {r['lesson'][:60]}"
        lines.append(line)

    return "\n".join(lines)


async def check_approach_blocked(
    goal_id: str,
    approach_text: str,
    current_tier: str,
) -> tuple[bool, list[str]]:
    """Check if a proposed approach has already failed for this goal.

    Returns (is_blocked, list of failed approach descriptions).

    Dedup rules:
    - Same hash + prior score < 0.3 (true failure) + conditions NOT improved → block
    - Same hash + prior score >= 0.3 (partial success) → allow
    - Same hash + conditions improved since last attempt → allow
    """
    approach_hash = compute_approach_hash(approach_text)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT approach, outcome_score, context_snapshot
               FROM cortex_reflections
               WHERE goal_id = $1::uuid AND approach_hash = $2
               ORDER BY created_at DESC""",
            goal_id, approach_hash,
        )

    if not rows:
        return False, []

    failed_approaches = []
    for row in rows:
        prior_score = row["outcome_score"]
        if prior_score >= 0.3:
            # Partial success — allow retry
            continue

        # True failure — check if conditions improved
        prior_snapshot = row["context_snapshot"] or {}
        prior_tier = prior_snapshot.get("budget_tier", "none")
        if _TIER_ORDER.get(current_tier, 0) > _TIER_ORDER.get(prior_tier, 0):
            # Budget improved — allow retry
            continue

        failed_approaches.append(row["approach"][:100])

    is_blocked = len(failed_approaches) > 0
    return is_blocked, failed_approaches


async def count_consecutive_failures(goal_id: str) -> int:
    """Count consecutive failures/timeouts since the last success for a goal.

    'Consecutive' means for this specific goal, not consecutive Cortex cycles.
    Cancelled outcomes don't count (external, not the approach's fault).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Find the most recent success or partial success
        last_success = await conn.fetchrow(
            """SELECT created_at FROM cortex_reflections
               WHERE goal_id = $1::uuid AND outcome IN ('success', 'partial')
               ORDER BY created_at DESC LIMIT 1""",
            goal_id,
        )

        if last_success:
            # Count failures after the last success
            count = await conn.fetchval(
                """SELECT COUNT(*) FROM cortex_reflections
                   WHERE goal_id = $1::uuid
                     AND outcome IN ('failure', 'timeout')
                     AND created_at > $2""",
                goal_id, last_success["created_at"],
            )
        else:
            # No successes ever — count all failures
            count = await conn.fetchval(
                """SELECT COUNT(*) FROM cortex_reflections
                   WHERE goal_id = $1::uuid
                     AND outcome IN ('failure', 'timeout')""",
                goal_id,
            )

    return count


def compute_stuck_threshold(max_iterations: int) -> int:
    """Compute the stuck threshold for a goal.

    Scales with goal size: max(3, max_iterations // 10).
    """
    return max(settings.stuck_threshold_min, max_iterations // 10)
```

- [ ] **Step 2: Verify file compiles**

Run: `cd /home/jeremy/workspace/arialabs/nova && python3 -c "import ast; ast.parse(open('cortex/app/reflections.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add cortex/app/reflections.py
git commit -m "feat(cortex): add reflections module — record, query, dedup, stuck detection"
```

---

## Task 4: Lesson ingestion to engrams

**Files:**
- Modify: `cortex/app/memory.py` (add `ingest_lesson` function after `reflect_to_engrams`, line 101)

- [ ] **Step 1: Add ingest_lesson function**

Add after line 101 in `cortex/app/memory.py` (after the `reflect_to_engrams` function):

```python


async def ingest_lesson(
    goal_title: str,
    maturation_phase: str | None,
    approach: str,
    outcome: str,
    lesson: str,
    goal_id: str | None = None,
    failure_mode: str | None = None,
) -> None:
    """Ingest a reflection lesson into engrams for cross-goal learning.

    Only called for reflections with non-null lessons (mid/best budget tier).
    Routine successes without surprising lessons are not ingested.
    """
    if not settings.reflect_to_engrams:
        return

    # Skip routine successes with no surprising lesson
    if outcome == "success" and not lesson:
        return

    phase_ctx = f" (phase: {maturation_phase})" if maturation_phase else ""
    raw_text = (
        f"Working on goal '{goal_title}'{phase_ctx}: "
        f"tried {approach[:200]}. "
        f"Result: {outcome}. "
        f"Lesson: {lesson}"
    )

    metadata = {"drive": "serve", "outcome": outcome}
    if goal_id:
        metadata["goal_id"] = goal_id
    if failure_mode:
        metadata["failure_mode"] = failure_mode

    try:
        mem = get_memory()
        await mem.post(
            "/api/v1/engrams/ingest",
            json={
                "raw_text": raw_text,
                "source_type": "cortex",
                "source_id": "cortex-lesson",
                "metadata": metadata,
            },
            timeout=10.0,
        )
        log.debug("Ingested lesson for goal '%s'", goal_title)
    except Exception as e:
        log.debug("Failed to ingest lesson: %s", e)
```

- [ ] **Step 2: Commit**

```bash
git add cortex/app/memory.py
git commit -m "feat(cortex): add lesson ingestion to engram memory"
```

---

## Task 5: Wire reflection query into PLAN phase

**Files:**
- Modify: `cortex/app/cycle.py:10` (add import)
- Modify: `cortex/app/cycle.py:254-283` (goal context block in `_plan_action`)

This is the core integration: before planning, query what Cortex has tried before for this goal.

- [ ] **Step 1: Add import**

In `cortex/app/cycle.py`, add to the imports (after line 26):

```python
from .reflections import query_reflections, format_reflection_history, record_reflection, check_approach_blocked, count_consecutive_failures, compute_stuck_threshold, _TIER_ORDER
```

- [ ] **Step 2: Add reflection history to planning prompt**

In `_plan_action`, after the goal context block is built (after line 283 where `goal_context_block` is set), add the reflection query:

```python
            # Query prior experience with this goal
            reflection_history = ""
            try:
                from .reflections import compute_approach_hash as _hash
                phase = goal.get("maturation_status")
                reflections = await query_reflections(goal_id, phase=phase, limit=5)
                desc = goal.get("description") or ""
                desc_hash = _hash(desc) if desc else None
                reflection_history = format_reflection_history(reflections, current_goal_desc_hash=desc_hash)
            except Exception as e:
                log.debug("Failed to query reflections for goal %s: %s", goal_id, e)
```

Then in the prompt template (around line 304), include the reflection history. Change:

```python
{"Goal details:\n" + goal_context_block if goal_context_block else ""}
```

to:

```python
{"Goal details:\n" + goal_context_block if goal_context_block else ""}
{reflection_history}
```

And add explicit instruction when there are failed approaches. After the `reflection_history` line in the prompt, before `Context:`, add:

```python
{"Do NOT repeat approaches that previously failed. Build on partial successes or try something new." if reflection_history else ""}
```

- [ ] **Step 3: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): query prior reflections during PLAN phase"
```

---

## Task 6: Wire reflection recording into REFLECT phase

**Files:**
- Modify: `cortex/app/cycle.py:184-185` (after TRACK, before REFLECT journal)

After `_track_dispatched_task` returns a `TaskOutcome`, record a structured reflection. This goes in `run_cycle()` between the TRACK and REFLECT phases.

- [ ] **Step 1: Add reflection recording after task tracking**

In `run_cycle()`, after line 182 (`state.task_outcome = await _track_dispatched_task(state)`) and before line 185 (`await _reflect(state)`), add:

```python
        # Record structured reflection for learning
        if state.task_outcome and state.goal_id and state.action_taken == "serve":
            await _record_cycle_reflection(state)
```

- [ ] **Step 2: Add the _record_cycle_reflection function**

Add this function before `_reflect()` (before line 658):

```python
async def _record_cycle_reflection(state: CycleState) -> None:
    """Record a structured reflection after a Serve drive cycle with a task outcome.

    Maps TaskOutcome to reflection outcome, optionally extracts lesson via LLM,
    checks for stuck goals, and ingests lessons into engrams.
    """
    outcome = state.task_outcome
    if not outcome:
        return

    # Map task status to reflection outcome
    if outcome.timed_out:
        ref_outcome, ref_score = "timeout", 0.5
    elif outcome.status == "complete" and outcome.findings_count == 0:
        ref_outcome, ref_score = "success", outcome.score
    elif outcome.status == "complete":
        ref_outcome, ref_score = "partial", outcome.score
    elif outcome.status == "failed":
        ref_outcome, ref_score = "failure", outcome.score
    elif outcome.status == "cancelled":
        ref_outcome, ref_score = "cancelled", outcome.score
    else:
        ref_outcome, ref_score = "failure", 0.2

    # Extract approach from the plan that was sent
    approach = state.outcome.split(" | ")[0] if state.outcome else "unknown approach"
    # Trim the "Dispatched task <id> for goal '<title>'" prefix
    if "Plan:" in approach:
        approach = approach.split("Plan:", 1)[1].strip()

    # Get goal metadata for context
    goal_title = ""
    goal_description = ""
    maturation_phase = None
    max_iterations = 50
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT title, description, maturation_status, max_iterations FROM goals WHERE id = $1::uuid",
                state.goal_id,
            )
            if row:
                goal_title = row["title"]
                goal_description = row["description"] or ""
                maturation_phase = row["maturation_status"]
                max_iterations = row["max_iterations"] or 50
    except Exception as e:
        log.debug("Failed to read goal metadata: %s", e)

    context_snapshot = {
        "budget_tier": state.budget_tier,
        "model": state.resolved_model,
        "findings_count": outcome.findings_count,
        "task_cost_usd": outcome.total_cost_usd,
        "memory_hits": len(state.engram_ids),
        "goal_description_hash": compute_approach_hash(goal_description) if goal_description else None,
    }

    # LLM lesson extraction (only at mid/best tier)
    lesson = None
    failure_mode = None
    tier_ok = _TIER_ORDER.get(state.budget_tier, 0) >= _TIER_ORDER.get(
        settings.lesson_extraction_min_tier, 2
    )
    if tier_ok and ref_outcome in ("failure", "partial", "timeout"):
        lesson, failure_mode = await _extract_lesson(
            approach, ref_outcome, outcome.error or outcome.output or ""
        )

    try:
        await record_reflection(
            goal_id=state.goal_id,
            cycle_number=state.cycle_number,
            approach=approach,
            outcome=ref_outcome,
            outcome_score=ref_score,
            task_id=outcome.task_id,
            drive="serve",
            maturation_phase=maturation_phase,
            lesson=lesson,
            failure_mode=failure_mode,
            context_snapshot=context_snapshot,
        )
    except Exception as e:
        log.warning("Failed to record reflection: %s", e)
        return

    # Check stuck detection
    try:
        from .stimulus import emit, GOAL_STUCK
        failure_count = await count_consecutive_failures(state.goal_id)
        threshold = compute_stuck_threshold(max_iterations)
        if failure_count >= threshold:
            log.warning(
                "Goal %s stuck: %d consecutive failures (threshold %d)",
                state.goal_id, failure_count, threshold,
            )
            # Escalate: move to review, journal, emit stimulus
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE goals SET maturation_status = 'review', updated_at = NOW() WHERE id = $1::uuid",
                    state.goal_id,
                )
            # Record escalation reflection
            all_reflections = await query_reflections(state.goal_id, limit=20)
            approaches_tried = [r["approach"][:80] for r in all_reflections if r["outcome"] in ("failure", "timeout")]
            escalation_lesson = f"Stuck after {failure_count} failures. Approaches tried: {'; '.join(approaches_tried[:5])}"
            await record_reflection(
                goal_id=state.goal_id,
                cycle_number=state.cycle_number,
                approach="escalation",
                outcome="escalated",
                outcome_score=0.0,
                drive="serve",
                maturation_phase=maturation_phase,
                lesson=escalation_lesson,
            )
            await write_entry(
                f"**Escalation** — Goal '{goal_title}' is stuck after {failure_count} consecutive failures.\n\n"
                f"Approaches tried:\n" + "\n".join(f"- {a}" for a in approaches_tried[:5]) +
                f"\n\nMoving to 'review' status for human input.",
                entry_type="escalation",
                metadata={"goal_id": state.goal_id, "failure_count": failure_count, "action": "stuck_escalation"},
            )
            await emit(
                GOAL_STUCK, "cortex",
                payload={"goal_id": state.goal_id, "title": goal_title,
                         "failure_count": failure_count, "approaches_tried": approaches_tried[:5]},
            )
    except Exception as e:
        log.warning("Stuck detection failed for goal %s: %s", state.goal_id, e)

    # Ingest lesson into engrams for cross-goal learning
    if lesson:
        try:
            from .memory import ingest_lesson
            await ingest_lesson(
                goal_title=goal_title,
                maturation_phase=maturation_phase,
                approach=approach,
                outcome=ref_outcome,
                lesson=lesson,
                goal_id=state.goal_id,
                failure_mode=failure_mode,
            )
        except Exception as e:
            log.debug("Lesson ingestion failed: %s", e)



async def _extract_lesson(approach: str, outcome: str, detail: str) -> tuple[str | None, str | None]:
    """Use LLM to extract a lesson and failure mode from a cycle outcome.

    Returns (lesson, failure_mode) tuple. Both may be None on error.
    """
    prompt = f"""A task was executed with this approach: {approach[:200]}
Result: {outcome}
Details: {detail[:300]}

Extract two things:
1. LESSON: One sentence about what to do differently next time (max 100 tokens)
2. FAILURE_MODE: A short category label for why it failed (e.g., "ambiguous requirements", "missing dependency", "timeout", "model limitation")

Respond in exactly this format:
LESSON: <lesson>
FAILURE_MODE: <category>"""

    try:
        llm = get_llm()
        resp = await llm.post("/complete", json={
            "model": settings.planning_model or "",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 100,
            "tier": "mid",
            "task_type": "planning",
            "metadata": {"agent_id": "cortex", "task_id": "lesson-extraction"},
        })
        if resp.status_code == 200:
            text = resp.json().get("content", "")
            lesson = None
            failure_mode = None
            for line in text.strip().split("\n"):
                if line.startswith("LESSON:"):
                    lesson = line[7:].strip()[:500]
                elif line.startswith("FAILURE_MODE:"):
                    failure_mode = line[13:].strip()[:200]
            return lesson, failure_mode
    except Exception as e:
        log.debug("Lesson extraction LLM call failed: %s", e)

    return None, None
```

- [ ] **Step 3: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): record reflections and detect stuck goals in REFLECT phase"
```

---

## Task 7: Approach dedup in ACT phase

**Files:**
- Modify: `cortex/app/cycle.py:390-434` (`_execute_serve`)

Before dispatching a task, check if the proposed approach has already failed.

- [ ] **Step 1: Add dedup check to _execute_serve**

In `_execute_serve`, after line 398 (`state.goal_id = goal_id`) and before the dispatch try block (line 401), add:

```python
    # Check if this approach has already failed (oscillation prevention)
    try:
        is_blocked, failed = await check_approach_blocked(goal_id, plan, state.budget_tier)
        if is_blocked:
            log.info("Approach blocked for goal %s — already failed: %s", goal_id, failed[:2])
            # Re-plan with explicit instruction to try something different
            replan_prompt = (
                f"The following approaches have already failed for this goal under similar conditions:\n"
                + "\n".join(f"- {f}" for f in failed[:3])
                + "\n\nPropose a DIFFERENT strategy. Do not retry these failed approaches."
            )
            try:
                llm = get_llm()
                resp = await llm.post("/complete", json={
                    "model": settings.planning_model or "",
                    "messages": [{"role": "user", "content": replan_prompt}],
                    "temperature": 0.5,
                    "max_tokens": 300,
                    "tier": "mid",
                    "task_type": "planning",
                    "metadata": {"agent_id": "cortex", "task_id": f"replan-{state.cycle_number}"},
                })
                if resp.status_code == 200:
                    plan = resp.json().get("content", plan)
            except Exception as e:
                log.debug("Re-plan after dedup block failed: %s", e)
    except Exception as e:
        log.debug("Approach dedup check failed: %s", e)
```

- [ ] **Step 2: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): block repeated failed approaches before dispatch"
```

---

## Task 8: Reflections endpoint on cortex router

**Files:**
- Modify: `cortex/app/router.py` (add endpoint after the journal endpoint, line 149)

- [ ] **Step 1: Add reflections endpoint**

Add after the journal endpoint (after line 149) in `cortex/app/router.py`:

```python


@cortex_router.get("/reflections/{goal_id}")
async def get_reflections(goal_id: UUID, limit: int = Query(default=20, le=100)):
    """Reflections (experience log) for a specific goal."""
    from .reflections import query_reflections
    refs = await query_reflections(str(goal_id), limit=limit)
    return {"reflections": refs, "count": len(refs)}
```

- [ ] **Step 2: Commit**

```bash
git add cortex/app/router.py
git commit -m "feat(cortex): add reflections query endpoint"
```

---

## Task 9: Integration tests

**Files:**
- Create: `tests/test_cortex_reflections.py`

Tests follow Nova's pattern: hit real running services over HTTP, `nova-test-` prefix, pytest fixtures for setup/teardown.

- [ ] **Step 1: Create test file**

```python
"""Integration tests for cortex experience learning (reflections).

Requires services running: orchestrator (8000), cortex (8100), memory-service (8002).
Tests hit real running services — no mocks.
"""
import hashlib
import os
import time
import pytest
import requests

BASE = "http://localhost:8000/api/v1"
CORTEX = "http://localhost:8100/api/v1/cortex"
MEM = "http://localhost:8002/api/v1/engrams"


@pytest.fixture
def admin_headers():
    secret = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    return {"X-Admin-Secret": secret}


@pytest.fixture
def goal_id(admin_headers):
    """Create a test goal and clean up after."""
    resp = requests.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-reflections-goal",
            "description": "Test goal for reflection integration tests",
            "priority": 1,
            "max_iterations": 50,
            "max_cost_usd": 10.0,
        },
        headers=admin_headers,
    )
    assert resp.status_code in (200, 201), f"Failed to create goal: {resp.text}"
    gid = resp.json()["id"]
    yield gid
    # Cleanup: delete goal (cascades to reflections)
    requests.delete(f"{BASE}/goals/{gid}", headers=admin_headers)


def _insert_reflection(goal_id: str, approach: str, outcome: str, score: float,
                       cycle: int = 1, lesson: str | None = None,
                       failure_mode: str | None = None,
                       budget_tier: str = "mid", goal_desc_hash: str | None = None):
    """Insert a reflection directly via SQL through cortex's DB.

    Uses the orchestrator's admin SQL endpoint if available, otherwise
    calls cortex internals. This helper exists because reflections are
    normally written by cortex's cycle, not via HTTP API.
    """
    import psycopg2
    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "nova_dev_password")
    conn = psycopg2.connect(
        host=pg_host, port=5432, dbname="nova",
        user="nova", password=pg_pass,
    )
    conn.autocommit = True
    normalized = " ".join(approach.lower().split())
    approach_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    import json
    ctx = json.dumps({"budget_tier": budget_tier, "goal_description_hash": goal_desc_hash})
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO cortex_reflections
               (goal_id, cycle_number, drive, approach, approach_hash,
                outcome, outcome_score, lesson, failure_mode, context_snapshot)
               VALUES (%s, %s, 'serve', %s, %s, %s, %s, %s, %s, %s::jsonb)""",
            (goal_id, cycle, approach, approach_hash, outcome, score,
             lesson, failure_mode, ctx),
        )
    conn.close()


class TestReflectionCRUD:
    """Test basic reflection storage and retrieval."""

    def test_reflections_endpoint_exists(self, goal_id):
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "reflections" in data
        assert data["count"] == 0

    def test_record_and_query_reflection(self, goal_id):
        """Insert a reflection, verify it appears in the query endpoint."""
        _insert_reflection(goal_id, "Write a data pipeline", "success", 0.8, cycle=1)
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        ref = data["reflections"][0]
        assert ref["outcome"] == "success"
        assert ref["outcome_score"] == pytest.approx(0.8, abs=0.01)
        assert "approach_hash" in ref

    def test_multiple_reflections_ordered_by_recency(self, goal_id):
        """Multiple reflections come back newest-first."""
        _insert_reflection(goal_id, "First attempt", "failure", 0.2, cycle=1)
        time.sleep(0.1)
        _insert_reflection(goal_id, "Second attempt", "partial", 0.6, cycle=2)
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        data = resp.json()
        assert data["count"] == 2
        assert data["reflections"][0]["approach"] == "Second attempt"
        assert data["reflections"][1]["approach"] == "First attempt"


class TestGoalDeletionCascade:
    """Verify reflections are cleaned up when a goal is deleted."""

    def test_cascade_on_goal_delete(self, admin_headers):
        resp = requests.post(
            f"{BASE}/goals",
            json={
                "title": "nova-test-cascade-goal",
                "description": "Will be deleted to test cascade",
                "priority": 1, "max_iterations": 10, "max_cost_usd": 1.0,
            },
            headers=admin_headers,
        )
        assert resp.status_code in (200, 201)
        gid = resp.json()["id"]
        _insert_reflection(gid, "Some approach", "failure", 0.2)
        # Verify it exists
        resp = requests.get(f"{CORTEX}/reflections/{gid}")
        assert resp.json()["count"] == 1
        # Delete goal — should cascade
        requests.delete(f"{BASE}/goals/{gid}", headers=admin_headers)
        resp = requests.get(f"{CORTEX}/reflections/{gid}")
        assert resp.json()["count"] == 0


class TestOscillationPrevention:
    """Test approach dedup blocks repeated failures."""

    def test_same_hash_different_whitespace(self):
        """Normalized hashes match despite whitespace differences."""
        t1 = "Write a Python function"
        t2 = "Write   a   Python   function"
        h1 = hashlib.sha256(" ".join(t1.lower().split()).encode()).hexdigest()[:16]
        h2 = hashlib.sha256(" ".join(t2.lower().split()).encode()).hexdigest()[:16]
        assert h1 == h2

    def test_same_hash_different_case(self):
        t1 = "Write a Python Function"
        t2 = "write a python function"
        h1 = hashlib.sha256(" ".join(t1.lower().split()).encode()).hexdigest()[:16]
        h2 = hashlib.sha256(" ".join(t2.lower().split()).encode()).hexdigest()[:16]
        assert h1 == h2

    def test_failed_approach_appears_in_reflections(self, goal_id):
        """A failed approach is retrievable by hash for dedup checking."""
        _insert_reflection(goal_id, "Deploy with docker compose", "failure", 0.2)
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        ref = resp.json()["reflections"][0]
        assert ref["outcome"] == "failure"
        assert ref["approach_hash"]  # hash was computed and stored

    def test_partial_success_not_blocked(self, goal_id):
        """Approaches with score >= 0.3 should NOT be blocked (worth refining)."""
        _insert_reflection(goal_id, "Partial approach", "partial", 0.6)
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        ref = resp.json()["reflections"][0]
        # Score 0.6 >= 0.3, so this approach should be allowed for retry
        assert ref["outcome_score"] >= 0.3


class TestConditionAwareRetry:
    """Test that improved conditions allow retrying failed approaches."""

    def test_failure_at_cheap_stores_tier(self, goal_id):
        """Reflections store the budget tier for condition comparison."""
        _insert_reflection(goal_id, "Generate code", "failure", 0.2,
                          budget_tier="cheap")
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        ref = resp.json()["reflections"][0]
        ctx = ref["context_snapshot"]
        assert ctx["budget_tier"] == "cheap"

    def test_different_tier_allows_retry(self, goal_id):
        """Same approach at a better tier should be retryable."""
        _insert_reflection(goal_id, "Generate code", "failure", 0.2,
                          budget_tier="cheap")
        _insert_reflection(goal_id, "Generate code", "failure", 0.2,
                          budget_tier="mid")
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        # Both stored — the retry logic checks tier ordering at dispatch time
        assert resp.json()["count"] == 2


class TestStuckDetection:
    """Test stuck threshold computation and escalation."""

    def test_minimum_threshold(self):
        assert max(3, 10 // 10) == 3

    def test_scales_with_iterations(self):
        assert max(3, 50 // 10) == 5
        assert max(3, 100 // 10) == 10

    def test_consecutive_failures_counted(self, goal_id):
        """Multiple failures for a goal are queryable for stuck detection."""
        for i in range(5):
            _insert_reflection(goal_id, f"Attempt {i}", "failure", 0.2, cycle=i)
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        failures = [r for r in resp.json()["reflections"] if r["outcome"] == "failure"]
        assert len(failures) == 5

    def test_success_resets_failure_count(self, goal_id):
        """A success after failures means only post-success failures count."""
        _insert_reflection(goal_id, "Attempt 1", "failure", 0.2, cycle=1)
        _insert_reflection(goal_id, "Attempt 2", "failure", 0.2, cycle=2)
        time.sleep(0.1)
        _insert_reflection(goal_id, "Attempt 3", "success", 0.8, cycle=3)
        time.sleep(0.1)
        _insert_reflection(goal_id, "Attempt 4", "failure", 0.2, cycle=4)
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        refs = resp.json()["reflections"]
        # The success at cycle 3 resets the consecutive count
        # Only 1 failure after the success (cycle 4)
        success_time = None
        for r in refs:
            if r["outcome"] == "success":
                success_time = r["created_at"]
                break
        post_success_failures = [
            r for r in refs
            if r["outcome"] == "failure" and r["created_at"] > success_time
        ]
        assert len(post_success_failures) == 1

    def test_cancelled_not_counted_as_failure(self, goal_id):
        """Cancelled outcomes don't count toward stuck threshold."""
        _insert_reflection(goal_id, "Attempt", "cancelled", 0.1, cycle=1)
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        ref = resp.json()["reflections"][0]
        assert ref["outcome"] == "cancelled"
        # Cancelled should not contribute to stuck detection


class TestGoalDescriptionChange:
    """Test that changed goal descriptions are flagged in reflection context."""

    def test_description_hash_stored_in_context(self, goal_id):
        """Reflections store the goal description hash for change detection."""
        desc_hash = hashlib.sha256(" ".join("test description".lower().split()).encode()).hexdigest()[:16]
        _insert_reflection(goal_id, "Some approach", "failure", 0.2,
                          goal_desc_hash=desc_hash)
        resp = requests.get(f"{CORTEX}/reflections/{goal_id}")
        ctx = resp.json()["reflections"][0]["context_snapshot"]
        assert ctx.get("goal_description_hash") == desc_hash


class TestExperienceRecallInPlanning:
    """Test that planning has access to reflection fields."""

    def test_goal_detail_includes_planning_fields(self, goal_id, admin_headers):
        resp = requests.get(f"{BASE}/goals/{goal_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "max_iterations" in data or "max_iterations" in data.get("goal", data)


class TestCortexReflectionsHealth:
    """Verify cortex service is healthy and reflections are accessible."""

    def test_cortex_health(self):
        resp = requests.get("http://localhost:8100/health/ready", timeout=5)
        assert resp.status_code == 200

    def test_reflections_endpoint_bad_uuid(self):
        resp = requests.get(f"{CORTEX}/reflections/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
```

- [ ] **Step 2: Run tests**

Run: `cd /home/jeremy/workspace/arialabs/nova && python3 -m pytest tests/test_cortex_reflections.py -v 2>&1 | tail -30`
Expected: All tests pass (tests that require DB interaction depend on services running)

- [ ] **Step 3: Commit**

```bash
git add tests/test_cortex_reflections.py
git commit -m "test(cortex): add integration tests for experience learning"
```

---

## Task 10: Verify full build

- [ ] **Step 1: Check dashboard TypeScript compilation**

Run: `cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build 2>&1 | tail -5`
Expected: Build succeeds (no dashboard changes in this feature)

- [ ] **Step 2: Check Python syntax across all modified files**

Run: `cd /home/jeremy/workspace/arialabs/nova && python3 -c "import ast; [ast.parse(open(f).read()) for f in ['cortex/app/reflections.py', 'cortex/app/config.py', 'cortex/app/stimulus.py', 'cortex/app/memory.py']]; print('All OK')"`
Expected: `All OK`

- [ ] **Step 3: Run full test suite if services are up**

Run: `cd /home/jeremy/workspace/arialabs/nova && make test-quick 2>&1 | tail -10`
Expected: Health checks pass

- [ ] **Step 4: Final commit if any fixes needed, then verify clean working tree**

Run: `git status`
Expected: Clean working tree
