# Task & Goal Clarity + Artifact Viewing

**Date:** 2026-03-30
**Status:** Approved
**Problem:** Nova completes tasks and goals but the results are hard to understand. Task outputs are raw text walls. Goal progress is opaque JSON. Generated files require filesystem navigation — no way to view them in the dashboard.

---

## Components

Four components, ordered by dependency:

1. **Task Executive Summary** — synchronous structured summary at task completion
2. **Task Structured Breakdown** — improved DocumentationAgent post-pipeline output
3. **Goal Timeline with Plan Evolution** — iteration history replacing raw JSON
4. **Artifact Viewer & File Viewer** — inline content rendering in the dashboard

---

## Component 1: Task Executive Summary

**What:** When a task completes, the pipeline executor builds a `summary` JSONB from data already available — no LLM call.

**Schema change:** New migration adding `summary` JSONB column to `tasks` table.

```sql
ALTER TABLE tasks ADD COLUMN summary JSONB;
```

**Summary shape:**

```json
{
  "headline": "string — first 1-2 sentences of task output, truncated at ~200 chars",
  "files_created": ["path/to/file.md"],
  "files_modified": ["path/to/existing.py"],
  "commands_run": ["python -m pytest test_*.py"],
  "findings_count": 0,
  "review_verdict": "pass | needs_refactor | reject | null",
  "cost_usd": 0.12,
  "duration_s": 45
}
```

**Populated by:** `orchestrator/app/pipeline/executor.py` — in the task completion path, after `output` is composed (lines ~513-528). The `files_changed` list is already extracted from the agent result dict. `headline` is derived by splitting `output` on sentence boundaries and taking the first 200 characters. `findings_count` and `review_verdict` are already available from the pipeline state.

**API change:** `GET /api/v1/pipeline/tasks/{task_id}` already returns all task columns — `summary` will appear automatically.

**Dashboard change:** `dashboard/src/pages/Tasks.tsx` — new `SummaryCard` component rendered above the tabs in the task detail sheet. Shows:
- Headline text (teal accent border)
- File chips (created/modified) — each clickable (opens File Viewer)
- Stat row: findings count, review verdict, cost, duration

**Fallback:** If `summary` is null (tasks completed before this change), the detail sheet falls back to the current raw output display.

---

## Component 2: Task Structured Breakdown

**What:** Improve the existing DocumentationAgent post-pipeline prompt to produce a structured breakdown stored as a `task_summary` artifact.

**Prompt change:** `orchestrator/app/pipeline/agents/post_pipeline.py` — update `DocumentationAgent.DEFAULT_SYSTEM` to request structured markdown:

```markdown
## What was requested
[1-2 sentences summarizing the user's request]

## What was done
[2-4 sentences describing the work performed]

## Key decisions
[Bullet list of decisions made and why, if any]

## Files touched
[List of files created or modified with brief description of each]

## Open questions
[Any unresolved issues or follow-up items, or "None"]
```

**Artifact storage:** Artifact `artifact_type` = `task_summary`. One per task. If a `task_summary` artifact already exists for the task (retry), overwrite by content_hash dedup.

**Dashboard change:** The "Details" tab in task detail (replacing the current "Output" tab as default) renders the `task_summary` artifact as styled sections. If no `task_summary` artifact exists yet (post-pipeline still running or pre-change task), falls back to rendering `tasks.output` as plain text.

**Tab restructure:** Task detail tabs become:
1. **Details** (default) — structured breakdown or raw output fallback
2. **Artifacts** — all artifacts for this task (Component 4)
3. **Findings** — guardrail findings (existing)
4. **Pipeline** — per-stage outputs from checkpoint data (existing Code Review tab expanded to show all stages)

---

## Component 3: Goal Timeline with Plan Evolution

**What:** Preserve iteration history so the dashboard can show a chronological timeline of what cortex planned, what happened, and how the plan evolved.

### Schema

New migration:

```sql
CREATE TABLE goal_iterations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id         UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    iteration       INTEGER NOT NULL,
    cycle_number    INTEGER NOT NULL,
    plan_text       TEXT,
    task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
    task_status     TEXT,
    task_summary    TEXT,
    cost_usd        NUMERIC(10, 6) DEFAULT 0,
    files_touched   JSONB DEFAULT '[]',
    plan_adjustment TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(goal_id, iteration)
);

CREATE INDEX idx_goal_iterations_goal ON goal_iterations(goal_id);
```

### Population

**Where:** `cortex/app/cycle.py` — `_update_goal_progress()`, after the branch logic and before `_check_goal_limits()`.

```python
# Record iteration history
await conn.execute("""
    INSERT INTO goal_iterations (goal_id, iteration, cycle_number, plan_text,
        task_id, task_status, task_summary, cost_usd, files_touched, plan_adjustment)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    ON CONFLICT (goal_id, iteration) DO UPDATE SET
        task_status = EXCLUDED.task_status,
        task_summary = EXCLUDED.task_summary,
        cost_usd = EXCLUDED.cost_usd,
        files_touched = EXCLUDED.files_touched
""", goal_id, new_iteration, cycle, plan_text, task_id, outcome.status,
     headline, outcome.total_cost_usd, files_json, adjustment_note)
```

**Plan adjustment detection:** When the previous iteration failed and cortex re-planned, the `plan_adjustment` field captures the delta. Populated by comparing `current_plan.plan` (previous) with the new plan text. If they differ and the previous task failed, the adjustment is: "Re-planned after failure: {previous_error}. New approach: {new_plan_snippet}".

### API

New endpoint: `GET /api/v1/goals/{goal_id}/iterations`

Returns:
```json
[
  {
    "iteration": 2,
    "cycle_number": 849,
    "plan_text": "Fix boolean type handling in validate_type()",
    "task_id": "a3f2...c91e",
    "task_status": "complete",
    "task_summary": "Updated validation_helpers.py to reject bool. All 287 tests pass.",
    "cost_usd": 0.08,
    "files_touched": ["workspace/validation_helpers.py"],
    "plan_adjustment": null,
    "created_at": "2026-03-30T14:22:00Z"
  },
  {
    "iteration": 1,
    "cycle_number": 847,
    "plan_text": "Review platform capabilities and identify gaps",
    "task_id": "7b1e...03af",
    "task_status": "failed",
    "task_summary": "Failed: missing test fixtures",
    "cost_usd": 0.04,
    "files_touched": [],
    "plan_adjustment": null,
    "created_at": "2026-03-30T14:15:00Z"
  }
]
```

### Dashboard

**GoalTimeline component** in `dashboard/src/pages/Goals.tsx`:

1. **Progress narrative** — top card with teal accent. Text generated client-side from iteration history: takes the last 3-5 iterations and composes "Completed X. Y failed (reason). Retried with Z. Next: W." Simple template logic, no LLM call.

2. **Timeline view** — vertical timeline, newest first. Each node shows:
   - Iteration number and timestamp
   - Plan text (what cortex intended)
   - Task outcome (status badge, headline)
   - Files touched (clickable, opens File Viewer)
   - Cost
   - Plan adjustment note (if present, shown as a yellow callout: "Adjusted plan: ...")

3. **Replaces** the current "Last Plan" raw JSON display and bare task list.

---

## Component 4: Artifact Viewer & File Viewer

### Artifacts Tab

**New tab** on task detail sheet. Fetches `GET /api/v1/pipeline/tasks/{task_id}/artifacts` (endpoint exists, unwired).

**Rendering by artifact_type:**

| Type | Rendering |
|------|-----------|
| `documentation`, `task_summary`, `decision_record`, `api_contract` | Markdown → HTML (use existing `react-markdown` or add it) |
| `code`, `test`, `config`, `schema` | Syntax-highlighted code block (detect language from `name` or `file_path` extension) |
| `diagram` | Mermaid diagram rendering |
| `context_package` | Collapsible JSON tree viewer |

Each artifact card shows: name, type badge, created_at, file_path (if set, clickable). "Copy content" button.

### File Viewer Modal

**New shared component:** `dashboard/src/components/FileViewer.tsx`

Opens as a modal when any file path is clicked anywhere in the dashboard (task summary, goal timeline, artifact list).

**Backend endpoint:** `GET /api/v1/workspace/files?path=<relative_path>`

```python
# orchestrator/app/workspace_router.py (new)
@router.get("/api/v1/workspace/files")
async def read_workspace_file(path: str):
    """Read a file from the Nova workspace. Read-only, path-traversal safe."""
    workspace = settings.nova_workspace
    resolved = (Path(workspace) / path).resolve()
    if not str(resolved).startswith(str(Path(workspace).resolve())):
        raise HTTPException(403, "Path traversal blocked")
    if not resolved.is_file():
        raise HTTPException(404, "File not found")
    content = resolved.read_text(errors="replace")
    return {
        "path": path,
        "content": content,
        "size_bytes": resolved.stat().st_size,
        "modified_at": datetime.fromtimestamp(resolved.stat().st_mtime).isoformat(),
    }
```

**Rendering:** Same logic as artifact types — detect by extension, render markdown or syntax-highlight code.

**Security:** Path traversal prevention via `resolve()` + prefix check. Read-only. No directory listing. Scoped to `NOVA_WORKSPACE`.

### Goal-Level Artifact Rollup

Goal detail page gets an "Artifacts" expandable section below the timeline. Fetches artifacts for all tasks associated with the goal (via `goal_id` on tasks table). Grouped by iteration number.

---

## Migration Summary

1. `ALTER TABLE tasks ADD COLUMN summary JSONB` — task executive summary
2. `CREATE TABLE goal_iterations (...)` — iteration history for timeline

## Files Modified

### Backend (orchestrator)
- `orchestrator/app/migrations/0XX_task_summary.sql` — summary column
- `orchestrator/app/migrations/0XX_goal_iterations.sql` — iterations table
- `orchestrator/app/pipeline/executor.py` — build summary JSONB at task completion
- `orchestrator/app/pipeline/agents/post_pipeline.py` — improved DocumentationAgent prompt
- `orchestrator/app/goals_router.py` — new GET `/goals/{goal_id}/iterations` endpoint
- `orchestrator/app/workspace_router.py` (new) — file read endpoint
- `orchestrator/app/router.py` — mount workspace_router

### Backend (cortex)
- `cortex/app/cycle.py` — INSERT into goal_iterations in `_update_goal_progress()`

### Dashboard
- `dashboard/src/pages/Tasks.tsx` — SummaryCard, restructured tabs, Artifacts tab
- `dashboard/src/pages/Goals.tsx` — GoalTimeline component replacing raw JSON
- `dashboard/src/components/FileViewer.tsx` (new) — modal file viewer
- `dashboard/src/components/ArtifactRenderer.tsx` (new) — renders artifacts by type
- `dashboard/src/api.ts` — new API functions: `getGoalIterations`, `getWorkspaceFile`

## Verification

1. Complete a pipeline task → verify summary card appears with correct headline, files, cost
2. Wait for post-pipeline → verify Details tab shows structured breakdown
3. Create a goal, let cortex run 2+ iterations → verify timeline shows iteration history with plan evolution
4. Fail a task deliberately → verify timeline shows failure and plan adjustment on retry
5. Click a file path in any summary → verify File Viewer opens with rendered content
6. Check Artifacts tab → verify all artifact types render correctly
7. Existing tasks (pre-migration) → verify fallback to raw output display works
