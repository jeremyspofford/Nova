# Cortex Goal Decomposition + Maturation Executor

**Status:** Design
**Date:** 2026-04-28
**Author:** Jeremy Spofford (with Claude)
**Effort estimate:** 2–3 weeks
**Roadmap entry:** [Self-Directed Autonomy → No goal decomposition](../../../roadmap.md) and Maturation pipeline executor stub

## Motivation

Cortex's autonomous loop runs but cannot break a goal like "build feature X" into a subtask DAG. Today every goal is one blob per cycle: speccing produces a markdown spec with "sub-tasks in dependency order" but nothing parses or executes that list. The `goals.maturation_status` check constraint includes a `building` value that no code path uses, and `verifying.py` only checks service health (not goal completion).

Without decomposition + a real building/verifying executor, autonomy level 6 ("self-directed") stays partial: Cortex can plan, but can't actually break work down, can't recurse on complexity, and can't verify what shipped.

## Decisions

These are the decisions made during the brainstorm — listed up front so reviewers can disagree before reading the rest.

| # | Decision | Choice |
|---|---|---|
| 1 | **Shape of decomposed work** | Goal tree — recursive subgoals via existing `goals.parent_goal_id` |
| 2 | **Recursion strategy** | Hybrid — parent's speccing outlines immediate children with hints; each child re-enters its own maturation |
| 3 | **Verification semantics** | Multi-signal — `verification_commands` + Quartet code-review pass + structured `success_criteria` aggregated to PASS / FAIL / human-review |
| 4 | **Review gates** | Policy-driven — `goals.review_policy` column cascades down the tree (`top-only` / `cost-above-N` / `scopes-sensitive` / `all`) |
| 5 | **Failure recovery** | Smart retry → escalate — failed subgoal re-specs once with reflection (max_retries=2), then escalates via parent's `review_policy` |
| 6 | **UX scope (v1)** | Review modal + journal entries + thin "spawned N subgoals" affordance + escalation notification. **Deferred:** rich tree view, rich escalation reflection card |

## Architecture

The hot path stays unchanged: Cortex's thinking loop (`cycle.py`) picks stale goals, evaluates drives, dispatches work. New behavior all lives in:

1. **Maturation phase routing in `cycle.py:_execute_serve`** — already routes to `run_scoping`/`run_speccing`/`run_verifying`. Adds routing for `building` and `waiting`.
2. **Speccing output format** — switches from free-text markdown to a structured JSON envelope (markdown narrative still emitted for human review).
3. **New `building` phase executor** — mechanical materializer, no LLM call. Reads `goals.spec_children`, creates child `goals` rows (or `tasks` rows for simple leaves), advances parent to `waiting`.
4. **New `waiting` phase** — terminal-but-passive: parent goal sits idle until all children resolve, then advances to `verifying`. The cycle's stale-goal query treats `waiting` parents as un-pickable until at least one child terminates.
5. **`verifying` rewrite** — multi-signal: runs commands, spawns a verification Quartet task, evaluates structured criteria, aggregates outcomes.
6. **Failure recovery in `cycle.py` and `verifying.py`** — wraps `goals.retry_count`, `check_approach_blocked()` from existing reflections, escalation via `review_policy`.

Reused infra (no parallel machinery):
- `cortex.reflections` table + `check_approach_blocked()` — already used by `serve.py` to dedup failed approaches
- `goal_tasks` mapping — used for leaf goals (those with `complexity='simple'` or whose triage said simple)
- `tasks.goal_id` FK — connects executable tasks to their owning goal
- `comments` table — already wired for `entity_type='goal'` review feedback
- `MaturationBadge`, `MaturationStages`, `GoalMaturationDetail` dashboard components

## Data Model

Single migration, additive and idempotent. No destructive changes.

```sql
-- Migration 064: goal decomposition + maturation executor

-- Structured children list (machine-readable companion to goals.spec)
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_children JSONB;
-- Shape: [
--   {
--     "title": "Schema work",
--     "description": "Migration + backfill for users.tenant_id",
--     "hint": "DDL is small; backfill is the risk",
--     "depends_on": [],                 -- indices into spec_children
--     "estimated_cost_usd": 1.20,
--     "estimated_complexity": "complex" -- triage prediction; child still re-triages
--   },
--   ...
-- ]

-- Verification artifacts produced by speccing
ALTER TABLE goals ADD COLUMN IF NOT EXISTS verification_commands JSONB;
-- Shape: [{"cmd": "make test-quick", "cwd": null, "timeout_s": 60}, ...]

ALTER TABLE goals ADD COLUMN IF NOT EXISTS success_criteria_structured JSONB;
-- Shape: [
--   {"statement": "tsc passes", "check": "command", "check_arg": "cd dashboard && npx tsc --noEmit"},
--   {"statement": "API returns 200 for new route", "check": "command", "check_arg": "curl -sf …"},
--   {"statement": "engram for 'tenant migration' exists", "check": "engram_query", "check_arg": "tenant migration"},
--   {"statement": "feature feels intuitive", "check": "llm_judge", "check_arg": "<prompt>"}
-- ]
-- The legacy success_criteria TEXT column stays for back-compat; new code reads structured first, falls back to TEXT.

-- Review + retry policy
ALTER TABLE goals ADD COLUMN IF NOT EXISTS review_policy TEXT NOT NULL DEFAULT 'cost-above-2'
    CHECK (review_policy IN ('top-only', 'all', 'cost-above-2', 'cost-above-5', 'scopes-sensitive'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS max_depth INTEGER NOT NULL DEFAULT 5;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS depth INTEGER NOT NULL DEFAULT 0;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 2;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;

-- New maturation phase: 'waiting' (parent blocked on children)
ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_maturation_status_check;
ALTER TABLE goals ADD CONSTRAINT goals_maturation_status_check
    CHECK (maturation_status IS NULL OR maturation_status IN
        ('triaging', 'scoping', 'speccing', 'review', 'building', 'waiting', 'verifying'));

-- Per-attempt verification record (audit trail; one row per verify run)
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

-- Index for the cycle's "find a parent ready to verify" query
CREATE INDEX IF NOT EXISTS goals_parent_status_idx
    ON goals(parent_goal_id, status) WHERE parent_goal_id IS NOT NULL;
```

The `depth` column lets the speccing prompt warn the LLM when it's getting close to `max_depth` (encouraging flatter decomposition near the floor).

## Speccing Rewrite

Speccing already exists (`cortex/app/maturation/speccing.py`) and produces a markdown spec via LLM. The rewrite changes its output contract while keeping markdown for the review modal.

**New prompt instructs the LLM to return both:**

1. A `spec` markdown narrative (current behavior — for the review modal)
2. A `spec_children` JSON array (immediate children with hints; not a full deep tree per the hybrid recursion decision)
3. A `verification_commands` JSON array
4. A `success_criteria_structured` JSON array

The LLM returns one JSON envelope:

```json
{
  "spec_markdown": "## Architecture\n…",
  "spec_children": [
    {
      "title": "Schema work",
      "description": "…",
      "hint": "DDL + backfill",
      "depends_on": [],
      "estimated_cost_usd": 1.20,
      "estimated_complexity": "complex"
    },
    {
      "title": "API surface",
      "description": "…",
      "hint": "…",
      "depends_on": [0],
      "estimated_cost_usd": 1.50,
      "estimated_complexity": "complex"
    }
  ],
  "verification_commands": [
    {"cmd": "make test-quick", "timeout_s": 30},
    {"cmd": "cd dashboard && npx tsc --noEmit", "timeout_s": 60}
  ],
  "success_criteria_structured": [
    {"statement": "All test commands exit 0", "check": "command", "check_arg": "(see verification_commands)"},
    {"statement": "Code review confidence ≥ 0.7", "check": "llm_judge", "check_arg": "<prompt>"}
  ]
}
```

Same retry-on-empty-content discipline as today (3 attempts at temperatures 0.2, 0.4, 0.6). On total failure: hard fallback writes a minimal markdown-only spec with `spec_children=null` and forces `complexity='simple'` so the goal advances as a flat-task leaf rather than looping.

When `goals.complexity='simple'` (set by triage), speccing produces only `verification_commands` + `success_criteria_structured` and a flat task list inside `spec_children` with all entries marked `estimated_complexity='simple'` — building will materialize them as `tasks` rows, not subgoal rows.

The sub-budget sum constraint: speccing's prompt instructs the LLM that ∑(child.estimated_cost_usd) ≤ 0.85 × parent.max_cost_usd (15% buffer for verification + retries). If the LLM violates this, building reduces each child proportionally and logs a warning.

## Building Executor

New file: `cortex/app/maturation/building.py`. No LLM call.

```python
async def run_building(goal_id: str) -> str:
    """Materialize spec_children into rows. Mechanical."""
    goal = await fetch_goal(goal_id)
    if goal["depth"] >= goal["max_depth"]:
        # Force flat tasks at the depth wall regardless of complexity
        return await _materialize_as_tasks(goal)

    children = goal["spec_children"] or []

    # Enforce budget allocation
    total_estimated = sum(c.get("estimated_cost_usd", 0) for c in children)
    parent_remaining = (goal["max_cost_usd"] or 0) - goal["cost_so_far_usd"]
    cap = parent_remaining * 0.85
    if total_estimated > cap and total_estimated > 0:
        ratio = cap / total_estimated
        for c in children:
            c["estimated_cost_usd"] *= ratio

    if goal["complexity"] == "simple":
        return await _materialize_as_tasks(goal)
    return await _materialize_as_subgoals(goal, children)


async def _materialize_as_subgoals(goal, children):
    """Create child goal rows and advance parent → waiting."""
    async with pool.acquire() as conn, conn.transaction():
        for idx, c in enumerate(children):
            await conn.execute(
                """INSERT INTO goals
                   (title, description, parent_goal_id, depth, max_depth,
                    review_policy, max_cost_usd, max_retries,
                    maturation_status, status, created_by, current_plan)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'triaging','active','cortex',$9::jsonb)""",
                c["title"], c["description"], goal["id"], goal["depth"] + 1,
                goal["max_depth"], _inherited_policy(goal, c),
                c.get("estimated_cost_usd"), goal["max_retries"],
                json.dumps({"hint": c.get("hint"), "depends_on": c.get("depends_on", []),
                            "spawn_index": idx}),
            )
        await conn.execute(
            "UPDATE goals SET maturation_status = 'waiting', updated_at = NOW() WHERE id = $1::uuid",
            goal["id"],
        )
    await emit_journal(goal["id"], "building.complete", {"children_count": len(children)})
    return f"Building: spawned {len(children)} subgoals → waiting"


async def _materialize_as_tasks(goal):
    """For simple/leaf goals: create tasks under goal_tasks and advance to verifying."""
    children = goal["spec_children"] or []
    async with pool.acquire() as conn, conn.transaction():
        for idx, c in enumerate(children):
            task_id = await create_pipeline_task(
                user_input=f"[Cortex goal] {c['title']}: {c.get('hint') or c.get('description')}",
                goal_id=goal["id"],
            )
            await conn.execute(
                """INSERT INTO goal_tasks (goal_id, task_id, sequence, status)
                   VALUES ($1, $2, $3, 'pending')""",
                goal["id"], task_id, idx,
            )
        await conn.execute(
            "UPDATE goals SET maturation_status = 'verifying', updated_at = NOW() WHERE id = $1::uuid",
            goal["id"],
        )
    await emit_journal(goal["id"], "building.tasks_dispatched", {"task_count": len(children)})
    return f"Building: dispatched {len(children)} tasks → verifying"


def _inherited_policy(parent, child):
    """Cascade review_policy with auto-upgrade for security/infra/data scopes."""
    base = parent["review_policy"]
    if base == "scopes-sensitive":
        # Already strictest; cascade unchanged
        return base
    scope = parent.get("scope_analysis", {}).get("affected_scopes", [])
    if any(s in scope for s in ("security", "infra", "data")):
        return "scopes-sensitive"
    return base
```

The `depends_on` encoded into `current_plan` JSONB is what the cycle's stale-query reads to determine which children are unblocked.

## Verification (Multi-Signal)

`verifying.py` rewrite. Spawns a Quartet code-review task, runs verification commands, evaluates structured criteria, aggregates.

```python
async def run_verifying(goal_id: str) -> str:
    goal = await fetch_goal(goal_id)

    # 1. Run verification_commands (skip for goals without any)
    cmd_results = await _run_commands(goal["verification_commands"] or [])

    # 2. Spawn Quartet verification task (Code Review agent re-reads spec + outputs)
    quartet_review = await _quartet_verify(goal_id, goal)

    # 3. Evaluate structured criteria
    criteria_eval = await _evaluate_criteria(
        goal["success_criteria_structured"] or [],
        cmd_results=cmd_results,
        quartet_review=quartet_review,
    )

    # 4. Aggregate
    aggregate = _aggregate(cmd_results, quartet_review, criteria_eval)

    # 5. Persist verification record
    attempt = await _next_attempt_number(goal_id)
    await record_verification(goal_id, attempt, cmd_results, quartet_review, criteria_eval, aggregate)

    if aggregate == "pass":
        await _mark_complete(goal_id)
        await emit_journal(goal_id, "verify.pass", {"attempt": attempt})
        # If this goal had a parent, the parent's stale-query will pick it up
        # to check if all siblings are done → advance parent to verifying.
        return "Verification passed → completed"

    if aggregate == "fail":
        return await _on_verify_fail(goal_id, goal, attempt, cmd_results, quartet_review, criteria_eval)

    # human-review aggregate
    await _set_status(goal_id, maturation_status="review")
    await _add_comment(goal_id, "nova", "Verification mixed — needs human eyes (see goal_verifications row)")
    await emit_journal(goal_id, "verify.human_review", {"attempt": attempt})
    return "Verification mixed → review queue"
```

`_aggregate()` thresholds:
- All commands exit 0 AND quartet confidence ≥ 0.7 AND ≥75% structured criteria pass → `pass`
- Any command non-zero AND quartet confidence ≥ 0.7 (LLM agrees it failed) → `fail`
- Any command non-zero AND quartet confidence < 0.7 (LLM uncertain) → `human-review`
- All commands pass AND ≥75% criteria pass AND quartet confidence < 0.5 → `human-review` (LLM disagrees with green tests — investigate)
- 0 commands AND only LLM signals → `pass` if quartet ≥ 0.85, else `human-review`

## Failure Recovery

When `_on_verify_fail` fires (or a leaf task fails terminally):

```python
async def _on_verify_fail(goal_id, goal, attempt, cmd_results, quartet_review, criteria_eval):
    # 1. Log the reflection — what was tried, what failed
    await record_reflection(
        goal_id=goal_id,
        approach_hash=compute_approach_hash(goal),
        outcome="failed",
        evidence={"cmd_failures": _failed_cmds(cmd_results),
                  "quartet": quartet_review,
                  "criteria_failures": _failed_criteria(criteria_eval)},
    )

    # 2. Check retry budget
    if goal["retry_count"] >= goal["max_retries"]:
        return await _escalate(goal_id, goal, attempt)

    # 3. Check if this approach is permanently blocked (already failed N times before)
    is_blocked, _ = await check_approach_blocked(goal_id, goal["spec"], "best")
    if is_blocked:
        return await _escalate(goal_id, goal, attempt, reason="approach_blocked")

    # 4. Re-spec: bump retry_count, set maturation_status back to 'scoping'.
    #    Existing scoping → speccing will read reflections via perceive_with_memory.
    await bump_retry_and_rescope(goal_id)
    await emit_journal(goal_id, "verify.retry", {"attempt": attempt, "next_retry": goal["retry_count"] + 1})
    return f"Verification failed → re-spec (retry {goal['retry_count'] + 1}/{goal['max_retries']})"


async def _escalate(goal_id, goal, attempt, reason="retries_exhausted"):
    """Escalate per parent's review_policy."""
    policy = goal["review_policy"]

    if policy in ("all", "scopes-sensitive", "cost-above-2", "cost-above-5"):
        # Human gate it
        await _set_status(goal_id, status="active", maturation_status="review")
        await _add_comment(goal_id, "nova",
            f"Goal stuck after {goal['max_retries']} retries ({reason}). "
            f"See goal_verifications for diagnostics. Approve a re-spec, edit the spec, or abort.")
        await emit_notification(goal_id, "goal_stuck",
            title=f"Goal '{goal['title']}' stuck — needs review")
        await emit_journal(goal_id, "verify.escalate.human", {"reason": reason})
        return "Verification exhausted → escalated to human"

    # policy = 'top-only' AND we're not the top → propagate failure to parent
    if goal["parent_goal_id"]:
        await _propagate_failure(goal["parent_goal_id"], child_id=goal_id, reason=reason)
        await _set_status(goal_id, status="failed")
        await emit_journal(goal_id, "verify.escalate.parent", {"reason": reason})
        return "Verification exhausted → propagated to parent"

    # Top-level + top-only policy + retries exhausted → just fail (matches autonomy contract)
    await _set_status(goal_id, status="failed")
    await emit_journal(goal_id, "verify.fail.terminal", {"reason": reason})
    return "Verification exhausted → goal failed (autonomous policy)"
```

`_propagate_failure` increments parent's `retry_count` and re-enters parent at `scoping` so it can re-plan with the failed child as new context. Parent's own retry budget still applies.

## Cortex Loop Integration

`cycle.py` changes are surgical. The `_execute_serve` maturation routing already exists for scoping/speccing/verifying — adds two cases:

```python
elif maturation_phase == "building":
    from .maturation.building import run_building
    msg = await run_building(goal_id)
    return msg

elif maturation_phase == "waiting":
    # Parent is waiting on children. Don't dispatch anything new for this goal.
    # Check if all children have terminated; if so, advance to verifying.
    ready = await _all_children_terminated(goal_id)
    if ready:
        await _set_status(goal_id, maturation_status="verifying")
        return f"Children all terminated → goal {goal_id} advancing to verifying"
    return f"Waiting on children for goal {goal_id} (no-op cycle)"
```

The stale-goal query in `serve.py` adds two filters:
1. Skip goals where `maturation_status='waiting'` AND not all children terminated (so we don't burn cycles polling a parent every 30s — children's completion will mark parent's `last_checked_at` via stimulus)
2. For child goals, skip those whose `current_plan->depends_on` refers to siblings that haven't completed yet

Stimulus emission already exists in `cortex.stimulus`:
- `GOAL_COMPLETED` is emitted by `verifying.py` on pass → stimulus listener can wake parent's `waiting` cycle immediately
- New stimulus `SUBGOAL_TERMINATED` (completed OR failed OR escalated) — subscribers: parent's stale check

## Review Modal (UX, v1)

Surfaced when `goals.maturation_status='review'`. Built on top of existing `GoalMaturationDetail` component.

**Trigger paths:**
- Speccing completes AND `_should_review(parent)` is True (per `review_policy`)
- Subgoal escalation per failure recovery
- Verification aggregate = `human-review`

**Modal contents:**
- Goal title + maturation badge (existing)
- Why this is in review (policy match shown explicitly: "scopes touch security" / "cost $1.80 ≥ $2.00 cap" / "verification mixed")
- For pre-execution review: `spec_children` rendered as cards with hints + estimated cost + depends_on
- For escalation review: link to `goal_verifications` rows showing what was tried (no rich card — just link to journal)
- Verification commands list
- Buttons: **Approve** / **Approve + lower budget…** / **Reject (require manual)** / **Comment**

API additions to `cortex.router`:
- `POST /api/v1/goals/{id}/review/approve` — sets `spec_approved_at`/`spec_approved_by`, advances `maturation_status`
- `POST /api/v1/goals/{id}/review/reject` — sets `spec_rejection_feedback`, marks `status='paused'`
- `POST /api/v1/goals/{id}/review/comment` — appends to `comments` table

## Journal Entries (UX, v1)

Existing `cortex.journal` already writes structured entries to the Cortex Journal conversation. Decomposition emits new entries at every transition (already shown in pseudocode):

| Event | Emitted by |
|---|---|
| `speccing.complete` | speccing.py |
| `review.fired` | building.py before transitioning, conditional on policy |
| `review.approved` / `review.rejected` | router approve/reject endpoints |
| `building.complete` | building.py (subgoal mode) |
| `building.tasks_dispatched` | building.py (leaf mode) |
| `subgoal.spawned` | building.py per child |
| `verify.pass` / `verify.fail` / `verify.human_review` | verifying.py |
| `verify.retry` | verifying.py on re-spec |
| `verify.escalate.human` / `verify.escalate.parent` / `verify.fail.terminal` | verifying.py escalation |

Dashboard surfaces journal entries in two places:
- Existing Cortex chat view (Journal conversation) — no change needed
- Goal detail panel: filtered journal entries for that goal (`WHERE metadata->>'goal_id' = $1`) rendered as a timeline below `GoalMaturationDetail`

## Thin "Spawned N subgoals" Affordance (UX, v1)

In `Goals.tsx` goal cards, when `goal.spec_children` is populated, render a single line under the maturation badge:

> Spawned 3 subgoals → 1 done · 1 retrying · 1 needs review

Click expands a flat list of children (title + status badge + cost). No tree expansion, no nesting. Click a child to navigate to its goal detail page. This is the v1 "show the user something happened" affordance — defers full tree view until usage proves it's needed.

## Notification on Escalation (UX, v1)

When `_escalate` fires with `policy IN ('all', 'scopes-sensitive', 'cost-above-*')`, emit a notification via the existing notification path (websocket + dashboard top-bar badge). Notification payload:

```json
{
  "kind": "goal_stuck",
  "goal_id": "...",
  "title": "Goal 'Backfill' stuck — needs review",
  "link": "/goals/<parent_id>?subgoal=<this_id>"
}
```

Click navigates to goal detail with the escalated subgoal scrolled into view; the journal timeline shows the failure history. No rich reflection-chain card — that's deferred to v2 once we see real escalation patterns.

## Out of Scope / Deferred to v2

- **Rich tree view** — full nested tree visualization in dashboard. Existing per-goal cards + thin spawned-children affordance + journal timeline cover v1 needs. Add when deep trees in production make flat lists insufficient.
- **Rich escalation reflection card** — purpose-built UI showing reflection chain, side-by-side attempts, recommended-next-action. v1 just notifies + links to journal.
- **Goal templates** — pre-defined decomposition patterns ("authentication change", "data migration") that bias speccing.
- **Cross-goal dependency** — sibling goals at different parts of the tree depending on each other. Today: only `depends_on` within siblings of the same parent.
- **Auto-promotion** — leaf task at runtime detected as too complex → promote to subgoal mid-execution. (Original brainstorm option C of "shape" was rejected; only design-time decomposition.)
- **Resource-aware concurrency** — bounded parallelism is currently implicit (Cortex round-robins through stale goals; max 1 LLM call per cycle). Real budget-aware concurrency limits across the tree are deferred.

## Testing Strategy

Per project rule (CLAUDE.md): integration tests against real services, no mocks.

**New test files in `tests/`:**

| File | Covers |
|---|---|
| `test_decomposition_lifecycle.py` | Create complex goal → triage → scope → spec → review (admin auto-approve) → build → children spawn → child completes → parent verifies → completes |
| `test_decomposition_failure_recovery.py` | Force a child verify failure; assert re-spec; force a second failure; assert escalate per policy |
| `test_decomposition_simple_path.py` | Simple goal: triage→spec→build (tasks not subgoals)→verify→complete in single goal lifecycle |
| `test_review_policies.py` | Each policy variant (top-only / cost-above-2 / scopes-sensitive / all) cascades correctly to children |
| `test_verification_aggregator.py` | Fixture-based: feed (cmd_results, quartet_review, criteria_eval) tuples, assert aggregate result |
| `test_depth_limit.py` | Goal at max_depth-1 spawning complex children → forced to flat tasks at the wall |
| `test_journal_completeness.py` | Run a complex lifecycle; assert every transition emits the documented journal event |

Existing tests must continue to pass — particularly `test_cortex_goals.py` and `test_cortex_loop.py`. Backward compatibility:
- Goals created before this migration have `spec_children=NULL` → speccing rewrite produces structured output on next run; goals already past speccing are unaffected.
- The legacy `success_criteria` TEXT column stays. New verifier reads `success_criteria_structured` first, falls back to TEXT (treats whole text as one `llm_judge` criterion).

## Open Questions

These are real questions that the spec deliberately defers — calling them out so they're not buried later.

1. **What does `success_criteria_structured.check='engram_query'` actually evaluate?** Spec assumes "engram with this content exists at importance > 0.5" — needs concrete predicate during implementation.
2. **Quartet verification task budget** — adds an LLM call per goal completion. Cost analysis: ~$0.05–$0.15 per goal at typical token counts. Acceptable for v1; revisit if volume grows.
3. **Notification durability** — existing notification path is best-effort websocket. For escalations, do we need persistence so they're recoverable across dashboard restarts? Likely yes; deferred to UX implementation pass.
4. **Top-level goal max_cost defaults** — today Cortex creates goals with `max_cost_usd=NULL`. Decomposition needs a non-null cap to do budget cascading; default should probably be tier-based (cheap/mid/best maps to $1/$5/$20). Not yet decided.

## Effort Estimate

| Phase | Effort | Includes |
|---|---|---|
| Schema + speccing rewrite | 3 days | Migration 064, speccing prompt + JSON envelope, retry/fallback |
| Building executor | 2 days | `building.py`, both subgoal and task materialization paths, depth wall |
| Verifying rewrite | 3 days | Multi-signal aggregator, command runner, Quartet verification task wiring, `goal_verifications` table |
| Failure recovery + escalation | 2 days | `_on_verify_fail`, `_escalate`, `_propagate_failure`, reflection integration |
| Cycle.py integration + waiting state | 1 day | New maturation routes, sibling-dependency check, stimulus subscriber |
| Review API + modal UX | 2 days | 3 endpoints, modal additions to existing GoalMaturationDetail |
| Spawned-children affordance | 0.5 day | Goals.tsx card line + flat list expand |
| Journal events + notification | 0.5 day | Wire emit_journal + emit_notification calls |
| Tests | 3 days | All 7 test files above |
| Buffer / iteration | 2 days | Bug fixes, schema iteration, performance |

**Total: ~19 days (~3 weeks of focused work)**

## References

- Roadmap: `docs/roadmap.md` — Self-Directed Autonomy section, "No goal decomposition" gap (~roadmap line 352) and "Maturation pipeline stub" (line 353)
- Existing maturation code: `cortex/app/maturation/{triage,scoping,speccing,verifying}.py`
- Existing thinking loop: `cortex/app/cycle.py` (`_execute_serve` maturation routing at line 503)
- Existing reflection system: `cortex/app/reflections.py`, `check_approach_blocked()`
- Schema baseline: migrations 021 (goals), 036 (success_criteria), 039 (maturation columns), 063 (rejection feedback)
- Dashboard components: `dashboard/src/components/{MaturationBadge,GoalMaturationDetail}.tsx`
