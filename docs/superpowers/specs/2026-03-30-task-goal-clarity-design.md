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

**Schema change:** Migration `051_task_summary.sql`:

```sql
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS summary JSONB;
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

**Populated by:** `orchestrator/app/pipeline/executor.py` — inside `_complete_task()` (line ~1129), where `completed_at` is being set. This is the only location where all required data is available:

- `headline`: first 200 chars of `output`, split on sentence boundaries
- `files_created` / `files_modified`: from task agent result dict `files_changed` (already extracted during pipeline)
- `commands_run`: from task agent result dict `commands_run`
- `findings_count`: query `SELECT COUNT(*) FROM guardrail_findings WHERE task_id = $1` (not available on PipelineState — must be queried)
- `review_verdict`: `state.completed.get("code_review", {}).get("verdict")` — nullable when code review was skipped (run_condition not met)
- `cost_usd`: `total_cost_usd` already computed by `_complete_task`
- `duration_s`: `(now - started_at).total_seconds()` — both values available inside `_complete_task`

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

**Artifact type change:** Migration to update the DocumentationAgent pod_agents config:

```sql
UPDATE pod_agents SET artifact_type = 'task_summary' WHERE role = 'documentation';
```

This distinguishes new structured summaries from old-format documentation artifacts.

**Artifact dedup:** Before inserting, delete any existing `task_summary` artifact for the task:

```sql
DELETE FROM artifacts WHERE task_id = $1 AND artifact_type = 'task_summary';
```

This handles retries cleanly without needing a UNIQUE constraint change.

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

Migration `052_goal_iterations.sql`:

```sql
CREATE TABLE IF NOT EXISTS goal_iterations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id         UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    attempt         INTEGER NOT NULL,
    cycle_number    INTEGER NOT NULL,
    plan_text       TEXT,
    task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
    task_status     TEXT,
    task_summary    TEXT,
    cost_usd        NUMERIC(10, 6) DEFAULT 0,
    files_touched   JSONB DEFAULT '[]',
    plan_adjustment TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(goal_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_goal_iterations_goal ON goal_iterations(goal_id);
```

**Key design decision — `attempt` vs `iteration`:** The column is named `attempt` (not `iteration`) and uses its own monotonically-increasing counter, separate from `goals.iteration` which only increments on success. Every task dispatch (success or failure) gets a new `attempt` number. This avoids the UNIQUE constraint violation that would occur with consecutive failures at the same `goals.iteration` value.

**Note:** Cortex connects to the same Postgres instance as orchestrator. This is the existing pattern — cortex already writes directly to `goals`, `cortex_state`, and other orchestrator-owned tables.

### Population

**Where:** `cortex/app/cycle.py` — `_update_goal_progress()`, after the branch logic and before `_check_goal_limits()`.

```python
# Record iteration history — attempt always increments (unlike goals.iteration which only increments on success)
attempt = await conn.fetchval(
    "SELECT COALESCE(MAX(attempt), 0) + 1 FROM goal_iterations WHERE goal_id = $1::uuid",
    goal_id,
)
await conn.execute("""
    INSERT INTO goal_iterations (goal_id, attempt, cycle_number, plan_text,
        task_id, task_status, task_summary, cost_usd, files_touched, plan_adjustment)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
""", goal_id, attempt, cycle, plan_text, task_id, outcome.status,
     headline, outcome.total_cost_usd, files_json, adjustment_note)
```

**Plan adjustment detection:** When the previous attempt failed and cortex re-planned, the `plan_adjustment` field captures the delta. Populated by comparing `current_plan.plan` (previous) with the new plan text. If they differ and the previous task failed, the adjustment is: "Re-planned after failure: {previous_error}. New approach: {new_plan_snippet}".

### API

New endpoint: `GET /api/v1/goals/{goal_id}/iterations`

Returns:
```json
[
  {
    "attempt": 3,
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
    "attempt": 2,
    "cycle_number": 848,
    "plan_text": "Review platform capabilities and identify gaps",
    "task_id": "7b1e...03af",
    "task_status": "failed",
    "task_summary": "Failed: missing test fixtures",
    "cost_usd": 0.04,
    "files_touched": [],
    "plan_adjustment": "Re-planned after failure: test_fixtures directory not found. New approach: fix boolean type handling directly.",
    "created_at": "2026-03-30T14:15:00Z"
  }
]
```

### Dashboard

**GoalTimeline component** in `dashboard/src/pages/Goals.tsx`:

1. **Progress narrative** — top card with teal accent. Text generated client-side from iteration history: takes the last 3-5 attempts and composes "Completed X. Y failed (reason). Retried with Z. Next: W." Simple template logic, no LLM call.

2. **Timeline view** — vertical timeline, newest first. Each node shows:
   - Attempt number and timestamp
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
| `documentation`, `task_summary`, `decision_record`, `api_contract` | Markdown via `react-markdown` + `remark-gfm` (already in project) |
| `code`, `test`, `config`, `schema` | Syntax-highlighted via `rehype-highlight` (new dep, pairs with existing react-markdown) |
| `diagram` | Mermaid rendering via `mermaid` library (new dep) |
| `context_package` | Collapsible JSON tree viewer |

**New npm dependencies:** `rehype-highlight`, `mermaid` (or `react-mermaid2`).

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
    workspace = Path(settings.workspace_root)
    resolved = (workspace / path).resolve()
    if not str(resolved).startswith(str(workspace.resolve())):
        raise HTTPException(403, "Path traversal blocked")
    if not resolved.is_file():
        raise HTTPException(404, "File not found")
    size = resolved.stat().st_size
    if size > 1_000_000:  # 1MB limit for text viewer
        return {
            "path": path,
            "content": None,
            "size_bytes": size,
            "modified_at": datetime.fromtimestamp(resolved.stat().st_mtime).isoformat(),
            "truncated": True,
            "error": "File too large to display (>1MB)",
        }
    content = resolved.read_text(errors="replace")
    return {
        "path": path,
        "content": content,
        "size_bytes": size,
        "modified_at": datetime.fromtimestamp(resolved.stat().st_mtime).isoformat(),
    }
```

**Rendering:** Same logic as artifact types — detect by extension, render markdown or syntax-highlight code.

**Security:** Path traversal prevention via `resolve()` + prefix check. Read-only. No directory listing. Scoped to `NOVA_WORKSPACE` / `workspace_root`. The TOCTOU race between `is_file()` and `read_text()` is accepted risk given the single-user containerized deployment model.

### Goal-Level Artifact Rollup

New endpoint: `GET /api/v1/goals/{goal_id}/artifacts`

Single query joining `tasks` and `artifacts` on `goal_id`:

```sql
SELECT a.*, t.goal_id,
       (SELECT gi.attempt FROM goal_iterations gi WHERE gi.task_id = a.task_id LIMIT 1) as attempt
FROM artifacts a
JOIN tasks t ON a.task_id = t.id
WHERE t.goal_id = $1
ORDER BY a.created_at DESC
```

Goal detail page gets an "Artifacts" expandable section below the timeline, showing all artifacts grouped by attempt number.

---

## Migration Summary

1. `051_task_summary.sql` — `ALTER TABLE tasks ADD COLUMN IF NOT EXISTS summary JSONB`
2. `052_goal_iterations.sql` — `CREATE TABLE goal_iterations`, update DocumentationAgent artifact_type

## Files Modified

### Backend (orchestrator)
- `orchestrator/app/migrations/051_task_summary.sql` — summary column
- `orchestrator/app/migrations/052_goal_iterations.sql` — iterations table + pod_agents update
- `orchestrator/app/pipeline/executor.py` — build summary JSONB in `_complete_task()`
- `orchestrator/app/pipeline/agents/post_pipeline.py` — improved DocumentationAgent prompt
- `orchestrator/app/goals_router.py` — new `GET /goals/{goal_id}/iterations`, `GET /goals/{goal_id}/artifacts`
- `orchestrator/app/workspace_router.py` (new) — file read endpoint
- `orchestrator/app/router.py` — mount workspace_router

### Backend (cortex)
- `cortex/app/cycle.py` — INSERT into goal_iterations in `_update_goal_progress()`

### Dashboard
- `dashboard/src/pages/Tasks.tsx` — SummaryCard, restructured tabs, Artifacts tab
- `dashboard/src/pages/Goals.tsx` — GoalTimeline component replacing raw JSON
- `dashboard/src/components/FileViewer.tsx` (new) — modal file viewer
- `dashboard/src/components/ArtifactRenderer.tsx` (new) — renders artifacts by type
- `dashboard/src/api.ts` — new API functions: `getGoalIterations`, `getGoalArtifacts`, `getWorkspaceFile`
- `package.json` — add `rehype-highlight`, `mermaid` (or `react-mermaid2`)

## Verification

1. Complete a pipeline task → verify summary card appears with correct headline, files, cost
2. Wait for post-pipeline → verify Details tab shows structured breakdown
3. Create a goal, let cortex run 2+ attempts → verify timeline shows attempt history with plan evolution
4. Fail a task deliberately → verify timeline shows failure and plan adjustment on retry
5. Click a file path in any summary → verify File Viewer opens with rendered content
6. Check Artifacts tab → verify all artifact types render correctly
7. Existing tasks (pre-migration) → verify fallback to raw output display works
8. Large file (>1MB) → verify File Viewer shows truncation message
9. Path traversal attempt → verify 403 response
