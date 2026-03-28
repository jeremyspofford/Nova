# Cortex: Learning from Experience

> Sub-project 1 of the Cortex Autonomy series. Foundation for all subsequent autonomy work.
>
> Date: 2026-03-28

## Problem

Cortex works on goals, succeeds or fails, writes a journal entry, and moves on. Next time it sees the same goal, it has no memory of what it already tried. It repeats the same mistakes because the thinking loop has no structured experience recall.

The journal exists (narrative text in `messages` table), and cycle outcomes are ingested into engrams. But neither is designed for the precise query: "What approaches have I tried for this specific goal, what happened, and what did I learn?"

## Solution

A dedicated experience log (the `cortex_reflections` table) that records structured outcomes for every Serve drive cycle. Before planning, Cortex reads this log to avoid past failures, build on successes, and know when to ask for help.

Five new behaviors:

1. **Check experience before planning** — PLAN phase queries prior reflections for the current goal
2. **Record structured outcomes** — After every Serve cycle, save what was tried, what happened, and why
3. **Don't repeat failed approaches** — Detect duplicate approaches via normalized text hashing
4. **Escalate when stuck** — After repeated failures, pause the goal and signal for human help
5. **Feed lessons to long-term memory** — Key lessons ingest into engrams for cross-goal pattern learning

## Detailed Design

### 1. Reflection Storage

New migration adds `cortex_reflections` table with:

- **Identity**: UUID primary key, linked to goal (`ON DELETE CASCADE` — reflections are meaningless without their goal. This differs from the tasks table which uses `ON DELETE SET NULL` because task records have independent audit value; reflections do not.)
- **Context**: cycle number, drive name, maturation phase at time of reflection, dispatched task ID
- **What was tried**: approach description (1-3 sentences), normalized approach hash (for dedup)
- **What happened**: outcome enum (`success | partial | failure | timeout | cancelled | escalated`), numeric score (0.0-1.0), lesson learned (1-2 sentences), failure mode category (free text, LLM-classified)
- **Conditions**: JSONB snapshot of budget tier, model used, memory hits, findings count, goal description hash (to detect goal modifications)

Indexes on `(goal_id, created_at DESC)`, `(goal_id, outcome)`, and `(goal_id, approach_hash)`.

**Phase scope**: Reflections are only recorded during active maturation phases (`scoping`, `speccing`, `building`, `verifying`) and for goals with null maturation_status (simple goals without maturation). The `triaging` phase exists in the schema but no pipeline tasks are dispatched during it, so no reflections are generated. The `review` phase is a human gate — Cortex doesn't work on it.

### 2. Check Experience Before Planning (PLAN Phase)

When the Serve drive wins and Cortex is about to plan work on a goal:

1. Query reflections for that goal, ordered by recency, limited to the current maturation phase
2. Limit to last 5 reflections (prompt budget constraint)
3. Format as a compact history block for the planning prompt:
   - Prior approaches and their outcomes
   - Failure modes encountered
   - Any lessons learned
   - Whether the goal description has changed since older reflections (flag for the planner)
4. Include this block in the LLM planning prompt alongside drive context, budget, stimuli, and memory context

The planner sees: "Here's what I've tried before for this goal. Approach A failed because of X. Approach B partially worked. Don't repeat A. Build on B or try something new."

**Prompt budget**: Each reflection entry is capped at ~40 tokens (approach + outcome + lesson compressed to one line). With up to 5 entries, the reflection block stays under ~200 tokens total. If a reflection's text exceeds the per-entry limit, truncate the approach and lesson fields. Never include raw task output — only the summarized fields.

### 3. Record Structured Outcomes (REFLECT Phase)

After every Serve drive cycle that dispatched a pipeline task:

1. **Always record** (zero LLM cost):
   - Approach: extracted from the plan text that was sent to the orchestrator
   - Approach hash: simple normalization (lowercase, strip excess whitespace, SHA-256). No LLM call. Word order is preserved — this catches exact and near-exact duplicates but not semantic equivalents. See Section 4 for LLM-powered dedup at dispatch time.
   - Outcome: mapped from task tracker results. Explicit mapping from `task_tracker.py` scores:
     - `complete` with 0 findings (score 0.8) → `success`
     - `complete` with findings (score 0.6) → `partial` (task finished but guardrails flagged issues)
     - `failed` (score 0.2) → `failure`
     - `cancelled` (score 0.1) → `cancelled` (external cancellation, not a failed approach)
     - `timed_out` (score 0.5) → `timeout`
   - Outcome score: raw numeric from task tracker
   - Context snapshot: budget tier, model, findings count, goal description hash
   - Maturation phase: current `maturation_status` of the goal

2. **LLM lesson extraction** (only at mid/best budget tier):
   - Additional call to extract: lesson learned, failure mode classification
   - Model: same as planning (tier-aware)
   - Max tokens: 100
   - If budget tier is `cheap` or `none`: skip extraction, leave `lesson` and `failure_mode` null
   - Null lessons are not backfilled in v1. If budget improves on a future cycle for the same goal, that cycle's reflection will have its own lesson. Historical null lessons stay null. (Backfill can be added in a later sub-project if needed.)

3. **Scope: Serve drive only.** Maintain, Improve, Learn, and Reflect drives don't dispatch goal-bound tasks and don't have the retry/learn pattern. No reflections recorded for them.

4. **Timeout handling**: If TRACK phase times out (task still running), record as `timeout` with score 0.5. Don't attempt to update later — the next cycle will either find the task complete (and record a new reflection) or dispatch new work.

### 4. Oscillation Prevention (Approach Dedup)

Before dispatching a task, check if the proposed approach has already been tried for this goal:

**Two-tier dedup**:

1. **At recording time** (zero cost): Simple hash (lowercase, strip whitespace, SHA-256). Catches exact and near-exact duplicates. Stored as `approach_hash` on the reflection.

2. **At dispatch time** (LLM-powered, when budget allows): Before dispatching, the planner receives the full reflection history and is explicitly instructed: "Do not propose an approach that is semantically equivalent to a prior failure." The LLM handles semantic dedup naturally during planning — it sees "Approach A: write Python code (failed)" and won't propose "generate Python code" because it understands these are the same thing. If budget doesn't allow a planning LLM call, fall back to the stored `approach_hash` for exact-match blocking only.

This avoids the contradiction of claiming "zero LLM cost" recording while requiring LLM normalization. Recording is always cheap; semantic dedup happens in the planning call that's already budgeted.

**Dedup rules** (applied to stored `approach_hash` matches):
- Same hash + prior outcome score **< 0.3** (true failure) = **block**. Don't try this again under similar conditions.
- Same hash + prior outcome score **>= 0.3** (partial success) = **allow**. Worth refining.
- Same hash + **conditions improved** since last attempt = **allow**. The approach might work now.

**Condition comparison**: Compare `context_snapshot.budget_tier` between the prior reflection and current state. Budget tiers are ordered (`best > mid > cheap > none`), so "improved" is well-defined. Model comparison is deferred from v1 — there's no reliable cross-provider model quality ranking. Budget tier alone is a strong enough signal for retry gating.

When the planner proposes an approach that's blocked, Cortex re-plans with an explicit instruction: "The following approaches have already failed for this goal under similar conditions: [list]. Propose a different strategy."

### 5. Stuck Detection and Escalation

**Threshold**: A goal is "stuck" after N consecutive failures, where N scales with the goal:
- `stuck_threshold = max(3, goal.max_iterations // 10)`
- Default max_iterations is 50, so default threshold is 5
- Minimum of 3 — even a small goal gets 3 tries

**Consecutive failure tracking**: Count reflections for this goal where `outcome IN ('failure', 'timeout')` and `created_at` is more recent than the last `success` or `partial` outcome. If no successes ever recorded, count from the first reflection. "Consecutive" means consecutive for this specific goal — not consecutive Cortex cycles. Cortex may bounce between goals across cycles; stuck detection only considers attempts on the same goal. `cancelled` outcomes don't count toward the stuck threshold (cancellation is external, not Cortex's fault).

**Escalation actions** (all happen in one cycle):
1. Record a reflection with `outcome = 'escalated'`, lesson = summary of all approaches tried
2. Set `goal.maturation_status = 'review'` — the existing human gate. Serve drive already skips goals in `review` phase.
3. Write a journal entry with `entry_type = 'escalation'` explaining what was tried, what failed, and why Cortex is stuck
4. Emit a new stimulus type: `goal.stuck` with payload `{goal_id, title, failure_count, approaches_tried}`. Note: this stimulus is not consumed by any drive in v1 — it exists as a hook for future features (e.g., dashboard notification badge, proactive chat message). The user-visible signals are the `review` maturation status on the Goals page and the escalation journal entry.

**Recovery**: When a user reviews a stuck goal and makes changes (edits description, adjusts parameters, adds context), they set the maturation status back to an active phase via the dashboard. The Serve drive picks it up on the next cycle. The planner sees prior reflections but also sees the goal description hash changed — it knows human intervention happened and prior failures may be less relevant.

**All goals stuck**: If every active goal is in `review`, Serve drive urgency drops to 0. Other drives take over (Maintain checks health, Learn looks for gaps, Reflect reviews patterns). Cortex doesn't halt — it shifts focus.

### 6. Long-Term Memory Ingestion

After recording a reflection, conditionally ingest the lesson into the engram network:

**What gets ingested**:
- Only reflections with a non-null `lesson` field (i.e., mid/best tier extractions)
- Format: "Working on goal '{title}' (phase: {maturation_phase}): tried {approach}. Result: {outcome}. Lesson: {lesson}."
- Metadata tags: `drive=serve`, `goal_id`, `outcome`, `failure_mode`

**What doesn't get ingested**:
- Reflections without lessons (cheap tier, no extraction)
- Routine successes with no surprising lesson
- Escalation summaries (these are about the goal, not general wisdom)

**Dedup**: The engram ingestion pipeline already has 0.90 cosine dedup. Combined with the structured format (goal title + approach + lesson), near-duplicate lessons across goals should be caught.

**Cross-goal value**: When Cortex later works on a different goal and runs memory retrieval in PERCEIVE, spreading activation may surface relevant lessons from past goals. "Last time I worked on a code generation goal with a vague description, it failed because..." This is organic — no special cross-goal query needed.

### 7. Migration from `current_plan`

Today, `goals.current_plan` JSONB stores the last task's outcome and gets overwritten each cycle. With the reflection table:

- **PLAN phase** reads from `cortex_reflections` (append-only, full history) instead of `current_plan` for experience context
- **`current_plan`** continues to be written (backward compatibility) but is no longer the source of truth for "what happened before"
- No schema changes to the goals table needed. `current_plan` becomes a convenience field for "last cycle's state" rather than the experience ledger.

## Dashboard Changes

Minimal for v1 — leverage existing pages:

- **Goals page**: A stuck goal shows as maturation status `review`. The existing Goals page already displays maturation status, so stuck goals are visible without new UI.
- **Cortex journal**: Already viewable at `/api/v1/cortex/journal`. Escalation entries appear here with full context of what was tried and why Cortex gave up.
- **No new pages or components in v1.** The `goal.stuck` stimulus is not surfaced in the dashboard yet — that's future work (notification badge, alert banner, etc.).
- **Future (v2)**: Dedicated reflection viewer showing the experience log per goal — approaches tried, outcomes over time, lesson timeline. This is Sub-project 3+ work.

## Files Changed

| File | Change |
|---|---|
| `orchestrator/app/migrations/0XX_cortex_reflections.sql` | New table, indexes |
| `cortex/app/reflections.py` | New module: record, query, dedup, stuck detection |
| `cortex/app/cycle.py` | PLAN phase calls reflection query; REFLECT phase calls reflection recording |
| `cortex/app/drives/serve.py` | Pass maturation_status to cycle state for reflection context |
| `cortex/app/memory.py` | Conditional lesson ingestion into engrams |
| `cortex/app/stimulus.py` | Add `GOAL_STUCK` stimulus type |
| `cortex/app/config.py` | Add `CORTEX_STUCK_THRESHOLD_MIN` (default 3), `CORTEX_LESSON_EXTRACTION_MIN_TIER` (default "mid"). Both are .env-configurable; dashboard-configurable via Redis is deferred to when other Cortex settings get a dashboard section. |

## Testing Strategy

| Test | What it validates |
|---|---|
| **Reflection CRUD** | Record a reflection, query by goal_id, verify fields |
| **Experience recall in planning** | Create goal + 3 reflections, verify planning prompt includes history |
| **Oscillation prevention** | Record a failed approach, propose same approach, verify it's blocked |
| **Condition-aware retry** | Record failure at cheap tier, verify same approach allowed at best tier |
| **Partial success retry** | Record 0.5-score approach, verify retry is allowed |
| **Stuck detection** | Create 5 consecutive failures, verify goal moves to `review` + stimulus emitted |
| **Stuck recovery** | After escalation, change goal description, verify Cortex resumes |
| **Lesson ingestion** | Record reflection at mid tier, verify engram ingested; at cheap tier, verify no ingestion |
| **Goal deletion cascade** | Delete goal, verify reflections deleted |

Tests hit real running services (consistent with Nova's integration test pattern). Resources created with `nova-test-` prefix.

## What This Doesn't Cover

- **Cross-goal pattern learning** — Addressed by Sub-project 3 (Reflect drive completion). This spec handles per-goal experience; cross-goal patterns emerge organically through engram consolidation.
- **Intel recommendation generation** — Addressed by Sub-project 3 (Improve/Learn drive completion).
- **Dashboard reflection viewer** — Deferred to a later sub-project. Journal and goal status are sufficient for v1 visibility.
- **Self-modification** — Sub-project 5. Separate safety model.
- **Non-Serve drive learning** — Other drives don't have the goal-bound retry pattern. If they need learning later, the reflection table can be extended.
- **Cross-goal approach_hash index** — A standalone index on `approach_hash` (without goal_id) would enable cross-goal pattern queries ("what approaches have I tried across all goals?"). Deferred to Sub-project 3 when the Reflect drive needs this.
- **Lesson backfill** — Reflections recorded at cheap tier have null `lesson` and `failure_mode`. These are not backfilled in v1. Can be added later if the gap proves problematic.
- **Model quality comparison** — Retry gating uses budget tier only, not model identity. Adding a model quality ranking table would enable smarter retry decisions but is out of scope.

## Design Notes

**Why a dedicated table instead of using engrams or journal?** The engram network is associative memory — great for "what do I vaguely know about X?" but poor for the precise query "what exact approaches did I try for goal Y?" The journal is narrative text in the messages table, not indexed for structured queries. A purpose-built table gives exact goal-scoped queries, structured dedup, and clean stuck detection without fighting the wrong abstraction.

**Why Cortex writes directly to the goals table (not via orchestrator API)?** Cortex already has direct DB access to the shared Postgres and writes to goals directly in the existing code (`cycle.py` does `UPDATE goals SET ...`). This is a deliberate architectural choice — Cortex is a privileged internal service, not an external consumer. Adding an HTTP round-trip through the orchestrator for goal status updates would add latency and failure modes with no security benefit.

**Why `cancelled` is a separate outcome, not a failure.** A cancelled task was stopped externally (user cancelled, system restarted, etc.). It doesn't indicate the approach was wrong. Treating it as a failure would pollute stuck detection and block valid approaches from being retried.

## Dependencies

- Cortex service running with DB access
- Orchestrator pipeline task dispatch working
- Memory service ingestion pipeline working
- No new external dependencies

## Effort Estimate

~1 week: 2 days for reflection storage + query + recording, 1 day for oscillation prevention + stuck detection, 1 day for planning prompt integration + lesson ingestion, 1 day for integration tests.
