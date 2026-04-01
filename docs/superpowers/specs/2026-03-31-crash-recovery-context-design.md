# Crash Recovery Context — Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Branch:** feature/crash-recovery

## Problem

When a pipeline task crashes mid-execution, completed stage outputs and agent session data survive in the database but are invisible. The dashboard shows nothing useful for failed tasks, and cortex only gets a truncated error string when re-planning — losing all knowledge of partial work that succeeded before the crash.

## Scope

Three interconnected parts:

1. **API** — Expose checkpoint and session data through existing patterns
2. **Dashboard** — Show stage-by-stage results for failed tasks
3. **Cortex** — Feed partial work into re-planning, dispatch smarter follow-up tasks

## Part 1: API Changes

### Add `checkpoint` to task detail endpoint

`GET /api/v1/pipeline/tasks/{task_id}` — add `t.checkpoint` to the SELECT query. Returns the JSONB object keyed by stage role:

```json
{
  "context": { "summary": "...", "tools_used": [...] },
  "task": { "content": "...", "files_changed": [...] }
}
```

Null for tasks that haven't started or have no completed stages. No change to the task list endpoint — checkpoint is only on the detail view.

### New sessions endpoint

`GET /api/v1/pipeline/tasks/{task_id}/sessions` — returns agent sessions for a task, ordered by `started_at`. Auth: `ApiKeyDep` (same as findings/reviews/artifacts).

Response shape per session:

```json
{
  "id": "uuid",
  "role": "context",
  "status": "complete",
  "output": { ... },
  "error": null,
  "traceback": null,
  "duration_ms": 1200,
  "model_used": "claude-sonnet-4-5-20250514",
  "cost_usd": 0.003,
  "started_at": "2026-03-31T14:00:00Z"
}
```

Fields: `id`, `role`, `status` (running/complete/failed), `output` (parsed result dict), `error`, `traceback`, `duration_ms`, `model_used`, `cost_usd`, `started_at`. Note: the DB column is `duration_ms` (migration 002).

### Add `checkpoint` to TaskOutcome (cortex)

`TaskOutcome` dataclass gains `checkpoint: dict | None = None`. `_score_task()` reads `task.get("checkpoint")` into it. No behavior change — just carrying the data for Part 3.

## Part 2: Dashboard — Failed Task Details

### Trigger condition

`TaskDetailsTab` adds a new rendering path: when the task is **failed** and has no output or task_summary artifact, render the checkpoint + sessions view.

### Layout

Vertical timeline of pipeline stages (same visual pattern as GoalTimeline):

- **Completed stages:** Green dot, stage name, collapsed by default. Expandable to show stage output (markdown-rendered). Duration from session data.
- **Failing stage:** Red dot, stage name. Error message displayed prominently. Traceback in a collapsible block (mono font, dimmed styling).
- **Stages not reached:** Grey dot, "Not reached" label. No card body.

### Data flow

- New `getTaskSessions(taskId)` TanStack Query, only enabled when task status is `failed`
- Checkpoint data comes from the existing task detail response (add to `PipelineTask` type)
- Sessions provide error/traceback for the failing stage and timing for all stages
- Stage order derived from `PIPELINE_STAGE_ORDER` in `checkpoint.py`: context, task, critique_direction, guardrail, code_review, critique_acceptance, decision (7 stages, not 5 — the dashboard's existing `STAGES` constant only shows 5, which is a pre-existing gap this feature corrects)

### Matching completed stages to sessions

Checkpoint keys are stage roles. Sessions have a `role` field. Match by role to pair checkpoint output (what the stage produced) with session metadata (timing, cost, model). If a checkpoint key exists without a matching session (edge case), show the checkpoint output alone.

## Part 3: Cortex — Partial Work for Re-planning

### Storing partial work context

In `_update_goal_progress`, the **failed** branch enriches `current_plan` with fields derived from `outcome.checkpoint`:

| Field | Source | Purpose |
|-------|--------|---------|
| `last_completed_stages` | List of keys from checkpoint dict | Which stages succeeded |
| `prior_checkpoint` | Full checkpoint dict | All completed stage outputs for re-planning |
| `failed_at_stage` | First stage in pipeline order not in checkpoint keys, fallback to `current_stage` | Where it broke |

These fields only exist in `current_plan` when the prior task failed with partial work. Complete tasks and tasks that failed before any stage completed don't set them.

### Smart re-dispatch

When the planner builds the next iteration's task input and `current_plan` contains prior work fields, a **prior work context block** is appended to the goal context assembly in `_plan_action` (the `serve` drive path in `cycle.py` — the planner uses a user message, not a system prompt):

```
Completed stages before failure: context, task
Failed at stage: guardrail
Prior work from completed stages (use as starting point, do not redo):
  [context]: <stage output, 500 chars max>
  [task]: <stage output, 500 chars max>
```

Each completed stage's output is included with a per-stage cap of 500 chars. This gives the planner structured context from ALL completed stages, not just the task stage. With 7 stages max, worst case is ~3500 chars.

Legacy fallback: if `prior_checkpoint` is absent but `last_stage_output` exists (from plans stored before this revision), the old single-output format is used.

This injection is conditional — only when prior work fields exist. ~20 lines in the dispatch prompt builder.

The planner then generates task input that references the prior output. The pipeline runs its full stage sequence, but the Context and Task agents execute faster because the input already contains the answer. No pipeline modifications, no checkpoint copying between tasks, no "start at stage X" mode.

## What This Does NOT Include

- **Raw LLM message recovery** — The crashing stage shows its error only, not partial LLM responses. Clean and simple.
- **Checkpoint copying between tasks** — Each task runs its own pipeline. Prior context flows through the task input, not internal state.
- **Pipeline "start at stage X" mode** — The full pipeline always runs. Smart input makes early stages fast, not skipped.
- **Session data on the task list endpoint** — Only the detail view gets checkpoint/sessions. List stays lean.

## Files to Change

### Orchestrator
- `orchestrator/app/pipeline_router.py` — Add checkpoint to task detail SELECT, new sessions endpoint
- `orchestrator/app/pipeline/executor.py` — No changes needed (checkpoint already saved)

### Dashboard
- `dashboard/src/api.ts` — Add `getTaskSessions()`, update `PipelineTask` type
- `dashboard/src/types.ts` — Add `AgentSession` interface
- `dashboard/src/pages/Tasks.tsx` — New `FailedTaskStagesView` component in `TaskDetailsTab`

### Cortex
- `cortex/app/task_tracker.py` — Add `checkpoint` field to `TaskOutcome`, read in `_score_task()`
- `cortex/app/cycle.py` — Enrich failed branch of `_update_goal_progress` with partial work fields
- `cortex/app/cycle.py` — Inject prior work context block in dispatch prompt builder

## Eng Review Decisions (2026-03-31)

1. **Sessions dedup:** Endpoint uses `DISTINCT ON (role) ORDER BY started_at DESC` — one session per stage, latest wins
2. **Stage constants:** Keep existing 5-stage `STAGES` for progress bar; new `PIPELINE_STAGES` (7 stages) scoped to `FailedTaskStagesView` only
3. **Tests:** 5 API schema tests (always run) + 2 cortex integration tests (opt-in, LLM-dependent) in `tests/test_crash_recovery.py`
4. **Full checkpoint:** `prior_checkpoint` stores the entire checkpoint dict, not a truncated snippet. Per-stage cap of 500 chars on injection.
5. **Failed stage detection:** Inferred from checkpoint gaps (first stage in pipeline order not in checkpoint keys), not `current_stage`
6. **Sessions payload:** `output` column excluded from sessions endpoint (dashboard uses checkpoint data instead)
7. **TODO update:** "Learning from Failures" effort reduced from 1 week to 3 days (checkpoint data now provides failed task context)
