# Task & Goal Clarity + Artifact Viewing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Nova's task outputs understandable at a glance, goal progress readable as a timeline, and generated files viewable inline in the dashboard.

**Architecture:** Backend-first approach. Two migrations lay the schema foundation. Then backend changes (executor summary building, goal iteration recording, new API endpoints) followed by frontend components. Each component is independently testable.

**Tech Stack:** Python/FastAPI (orchestrator, cortex), React/TypeScript/TanStack Query (dashboard), asyncpg (DB), Tailwind CSS, react-markdown, rehype-highlight, mermaid

**Spec:** `docs/superpowers/specs/2026-03-30-task-goal-clarity-design.md`

---

## File Structure

### New Files
- `orchestrator/app/migrations/051_task_summary.sql` — summary column on tasks
- `orchestrator/app/migrations/052_goal_iterations.sql` — goal_iterations table + DocumentationAgent artifact_type update
- `orchestrator/app/workspace_router.py` — read-only workspace file endpoint
- `dashboard/src/components/FileViewer.tsx` — modal file viewer
- `dashboard/src/components/ArtifactRenderer.tsx` — renders artifacts by type

### Modified Files
- `orchestrator/app/pipeline/executor.py` — build summary JSONB in `_complete_task()`
- `orchestrator/app/pipeline/agents/post_pipeline.py` — improved DocumentationAgent prompt
- `orchestrator/app/goals_router.py` — iterations + artifacts endpoints
- `orchestrator/app/main.py` — mount workspace_router
- `cortex/app/cycle.py` — INSERT into goal_iterations
- `dashboard/src/api.ts` — new API functions
- `dashboard/src/pages/Tasks.tsx` — SummaryCard, restructured tabs, Artifacts tab
- `dashboard/src/pages/Goals.tsx` — GoalTimeline replacing raw JSON
- `dashboard/package.json` — add rehype-highlight, mermaid

---

## Task 1: Database Migrations

**Files:**
- Create: `orchestrator/app/migrations/051_task_summary.sql`
- Create: `orchestrator/app/migrations/052_goal_iterations.sql`

- [ ] **Step 1: Create migration 051 — task summary column**

```sql
-- 051_task_summary.sql
-- Add structured summary JSONB to tasks (populated at completion, no LLM call)
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS summary JSONB;

COMMENT ON COLUMN tasks.summary IS 'Structured summary: headline, files_created, files_modified, findings_count, review_verdict, cost_usd, duration_s';
```

- [ ] **Step 2: Create migration 052 — goal_iterations table + doc agent type**

```sql
-- 052_goal_iterations.sql
-- Track every goal attempt (success or failure) for timeline display
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

-- Update DocumentationAgent to produce task_summary artifacts
UPDATE pod_agents SET artifact_type = 'task_summary' WHERE role = 'documentation';
```

- [ ] **Step 3: Verify migrations are idempotent**

Run: `docker compose exec orchestrator python -c "print('migrations exist')"` — verify the orchestrator container picks them up on next restart. Migrations auto-run at startup from `orchestrator/app/migrations/*.sql`.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/migrations/051_task_summary.sql orchestrator/app/migrations/052_goal_iterations.sql
git commit -m "feat(db): add task summary column and goal_iterations table"
```

---

## Task 2: Task Executive Summary — Backend

**Files:**
- Modify: `orchestrator/app/pipeline/executor.py` — `_complete_task()` at line 1129

The summary is built inside `_complete_task()` where `completed_at`, `total_cost_usd`, and `output` are all available.

- [ ] **Step 1: Add summary builder function**

Add near the top of executor.py (after imports, around line 30):

```python
def _build_task_summary(
    output: str,
    state: "PipelineState",
    cost_usd: float,
    started_at: datetime | None,
) -> dict:
    """Build structured summary from pipeline output. No LLM call."""
    import re

    task_result = state.completed.get("task", {})
    files_changed = task_result.get("files_changed", [])
    commands_run = task_result.get("commands_run", [])
    review = state.completed.get("code_review", {})

    # Headline: first 1-2 sentences, max 200 chars
    text = (output or "").strip()
    sentences = re.split(r'(?<=[.!?])\s+', text[:500])
    headline = sentences[0] if sentences else text[:200]
    if len(headline) > 200:
        headline = headline[:197] + "..."

    duration_s = None
    if started_at:
        duration_s = round((datetime.now(timezone.utc) - started_at).total_seconds())

    return {
        "headline": headline,
        "files_created": [],  # TODO: distinguish from modified when pipeline tracks this
        "files_modified": files_changed,
        "commands_run": commands_run[:10],
        "findings_count": 0,  # Populated after query in _complete_task
        "review_verdict": review.get("verdict"),
        "cost_usd": round(cost_usd, 4) if cost_usd else 0,
        "duration_s": duration_s,
    }
```

- [ ] **Step 2: Wire summary into `_complete_task()`**

In `_complete_task()` (line 1129), after the cost rollup query (line 1157), add:

```python
    # Build and persist structured summary
    try:
        started_row = await conn.fetchrow(
            "SELECT started_at FROM tasks WHERE id = $1::uuid", task_id,
        )
        cost_row = await conn.fetchrow(
            "SELECT total_cost_usd FROM tasks WHERE id = $1::uuid", task_id,
        )
        findings_count = await conn.fetchval(
            "SELECT COUNT(*) FROM guardrail_findings WHERE task_id = $1::uuid", task_id,
        )
        summary = _build_task_summary(
            output, state,
            cost_usd=float(cost_row["total_cost_usd"] or 0),
            started_at=started_row["started_at"],
        )
        summary["findings_count"] = findings_count
        await conn.execute(
            "UPDATE tasks SET summary = $1::jsonb WHERE id = $2::uuid",
            json.dumps(summary), task_id,
        )
    except Exception as e:
        log.warning("Failed to build task summary for %s: %s", task_id, e)
```

Add `from datetime import datetime, timezone` to imports if not already present. Add `import json` if not already present.

- [ ] **Step 3: Verify summary appears in task API response**

After restarting orchestrator, submit a test task and verify `GET /api/v1/pipeline/tasks/{task_id}` includes the `summary` field.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/pipeline/executor.py
git commit -m "feat(orchestrator): build task executive summary at completion"
```

---

## Task 3: Improved DocumentationAgent Prompt

**Files:**
- Modify: `orchestrator/app/pipeline/agents/post_pipeline.py` — DocumentationAgent at line 16

- [ ] **Step 1: Update DEFAULT_SYSTEM prompt**

Replace lines 16-20 in post_pipeline.py:

```python
DEFAULT_SYSTEM = (
    "You are a Documentation agent. After a pipeline task completes, produce a structured summary.\n\n"
    "Use EXACTLY this Markdown format:\n\n"
    "## What was requested\n[1-2 sentences summarizing the user's original request]\n\n"
    "## What was done\n[2-4 sentences describing the work performed and outcome]\n\n"
    "## Key decisions\n[Bullet list of decisions made and why, or 'None']\n\n"
    "## Files touched\n[List each file created or modified with a brief description, or 'None']\n\n"
    "## Open questions\n[Any unresolved issues or follow-up items, or 'None']"
)
```

- [ ] **Step 2: Add dedup before artifact insert**

In the artifact storage path (where DocumentationAgent results are persisted), add a DELETE before INSERT. Find where artifacts are inserted for post-pipeline agents in executor.py's `_persist_stage_records()` (~line 917), add before the INSERT:

```python
if agent_role == "documentation":
    await conn.execute(
        "DELETE FROM artifacts WHERE task_id = $1::uuid AND artifact_type = 'task_summary'",
        task_id,
    )
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/pipeline/agents/post_pipeline.py orchestrator/app/pipeline/executor.py
git commit -m "feat(orchestrator): structured DocumentationAgent prompt + task_summary dedup"
```

---

## Task 4: Goal Iteration Recording — Cortex

**Files:**
- Modify: `cortex/app/cycle.py` — `_update_goal_progress()` at line 598

- [ ] **Step 1: Add iteration recording**

In `_update_goal_progress()`, right before the `_check_goal_limits` call (line 720), add:

```python
        # Record iteration history for goal timeline
        try:
            attempt = await conn.fetchval(
                "SELECT COALESCE(MAX(attempt), 0) + 1 FROM goal_iterations WHERE goal_id = $1::uuid",
                goal_id,
            )
            # Get plan text from current_plan
            plan_data = row["current_plan"] or {}
            plan_text = plan_data.get("plan", "") if isinstance(plan_data, dict) else ""

            # Detect plan adjustment (previous attempt failed, plan changed)
            adjustment = None
            if outcome.status != "complete" or (isinstance(plan_data, dict) and plan_data.get("last_task_status") == "failed"):
                prev_error = plan_data.get("last_task_error", "") if isinstance(plan_data, dict) else ""
                if prev_error:
                    adjustment = f"Re-planned after failure: {prev_error[:200]}"

            headline = (outcome.output or "")[:200].split("\n")[0] if outcome.output else outcome.status
            files = plan_data.get("files_changed", []) if isinstance(plan_data, dict) else []

            await conn.execute("""
                INSERT INTO goal_iterations
                    (goal_id, attempt, cycle_number, plan_text, task_id, task_status,
                     task_summary, cost_usd, files_touched, plan_adjustment)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            """,
                goal_id, attempt, cycle, plan_text,
                outcome.task_id if outcome.task_id != "unknown" else None,
                outcome.status, headline,
                outcome.total_cost_usd,
                json.dumps(files), adjustment,
            )
        except Exception as e:
            log.debug("Failed to record goal iteration: %s", e)
```

Ensure `import json` is at the top of cycle.py (it already is).

- [ ] **Step 2: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): record goal iterations for timeline display"
```

---

## Task 5: Goal Iterations + Artifacts API Endpoints

**Files:**
- Modify: `orchestrator/app/goals_router.py` — add after comments endpoints (~line 413)

- [ ] **Step 1: Add iterations endpoint**

After the `get_goal_scope` endpoint (~line 413):

```python
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
```

- [ ] **Step 2: Add goal-level artifacts endpoint**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/goals_router.py
git commit -m "feat(orchestrator): goal iterations and artifacts API endpoints"
```

---

## Task 6: Workspace File Reader Endpoint

**Files:**
- Create: `orchestrator/app/workspace_router.py`
- Modify: `orchestrator/app/main.py` — mount router

- [ ] **Step 1: Create workspace_router.py**

```python
"""Read-only workspace file access for the dashboard File Viewer."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from .config import settings

log = logging.getLogger(__name__)
workspace_router = APIRouter(tags=["workspace"])

MAX_FILE_SIZE = 1_000_000  # 1MB


@workspace_router.get("/api/v1/workspace/files")
async def read_workspace_file(path: str = Query(..., description="Relative path within workspace")):
    """Read a file from the Nova workspace. Read-only, path-traversal safe."""
    workspace = Path(settings.workspace_root).resolve()
    resolved = (workspace / path).resolve()

    # Path traversal prevention
    if not str(resolved).startswith(str(workspace)):
        raise HTTPException(403, "Path traversal blocked")
    if not resolved.is_file():
        raise HTTPException(404, "File not found")

    size = resolved.stat().st_size
    modified_at = datetime.fromtimestamp(resolved.stat().st_mtime, tz=timezone.utc).isoformat()

    if size > MAX_FILE_SIZE:
        return {
            "path": path,
            "content": None,
            "size_bytes": size,
            "modified_at": modified_at,
            "truncated": True,
            "error": f"File too large to display ({size:,} bytes, limit {MAX_FILE_SIZE:,})",
        }

    content = resolved.read_text(errors="replace")
    return {
        "path": path,
        "content": content,
        "size_bytes": size,
        "modified_at": modified_at,
    }
```

- [ ] **Step 2: Mount router in main.py**

In `orchestrator/app/main.py`, add import and include after existing routers (~line 187):

```python
from .workspace_router import workspace_router
```

```python
app.include_router(workspace_router)
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/workspace_router.py orchestrator/app/main.py
git commit -m "feat(orchestrator): read-only workspace file endpoint for File Viewer"
```

---

## Task 7: Dashboard API Functions + Dependencies

**Files:**
- Modify: `dashboard/src/api.ts`
- Modify: `dashboard/package.json`

- [ ] **Step 1: Add type definitions to api.ts**

Add near the other interfaces:

```typescript
export interface Artifact {
  id: string
  task_id: string
  agent_session_id: string | null
  artifact_type: string
  name: string
  content: string
  content_hash: string
  file_path: string | null
  metadata: Record<string, unknown> | null
  created_at: string
  attempt?: number
}

export interface GoalIteration {
  id: string
  goal_id: string
  attempt: number
  cycle_number: number
  plan_text: string | null
  task_id: string | null
  task_status: string | null
  task_summary: string | null
  cost_usd: number
  files_touched: string[]
  plan_adjustment: string | null
  created_at: string
}

export interface WorkspaceFile {
  path: string
  content: string | null
  size_bytes: number
  modified_at: string
  truncated?: boolean
  error?: string
}

export interface TaskSummary {
  headline: string
  files_created: string[]
  files_modified: string[]
  commands_run: string[]
  findings_count: number
  review_verdict: string | null
  cost_usd: number
  duration_s: number | null
}
```

- [ ] **Step 2: Add API functions**

After the existing `getTaskReviews` function (~line 181):

```typescript
export const getTaskArtifacts = (task_id: string) =>
  apiFetch<Artifact[]>(`/api/v1/pipeline/tasks/${task_id}/artifacts`)

export const getGoalIterations = (goal_id: string) =>
  apiFetch<GoalIteration[]>(`/api/v1/goals/${goal_id}/iterations`)

export const getGoalArtifacts = (goal_id: string) =>
  apiFetch<Artifact[]>(`/api/v1/goals/${goal_id}/artifacts`)

export const getWorkspaceFile = (path: string) =>
  apiFetch<WorkspaceFile>(`/api/v1/workspace/files?path=${encodeURIComponent(path)}`)
```

- [ ] **Step 3: Install new npm dependencies**

```bash
cd dashboard && npm install rehype-highlight mermaid
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/api.ts dashboard/package.json dashboard/package-lock.json
git commit -m "feat(dashboard): API functions and types for task/goal clarity"
```

---

## Task 8: FileViewer Component

**Files:**
- Create: `dashboard/src/components/FileViewer.tsx`

- [ ] **Step 1: Create FileViewer component**

A modal that opens when any file path is clicked. Renders markdown or syntax-highlighted code based on file extension. Fetches content via the workspace file endpoint.

Key behaviors:
- Click backdrop or X to close
- Markdown files rendered via `react-markdown`
- Code files displayed in a `<pre>` block with language class for highlighting
- Shows file size, copy path button
- Handles truncated files (>1MB) with a warning message
- Handles loading and error states

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/components/FileViewer.tsx
git commit -m "feat(dashboard): FileViewer modal for inline file viewing"
```

---

## Task 9: ArtifactRenderer Component

**Files:**
- Create: `dashboard/src/components/ArtifactRenderer.tsx`

- [ ] **Step 1: Create ArtifactRenderer component**

An expandable card for displaying a single artifact. Renders content differently by artifact_type:
- Markdown types (documentation, task_summary, decision_record, api_contract) → rendered markdown
- Code types (code, test, config, schema) → syntax-highlighted code block
- Diagram → Mermaid rendering (import mermaid dynamically, render to SVG, sanitize with DOMPurify or use mermaid's built-in sanitization before inserting)
- context_package → formatted JSON viewer

Each card shows: name, type badge, expand/collapse toggle, copy button, clickable file_path.

**Security note:** For Mermaid diagram rendering, use mermaid's `securityLevel: 'strict'` configuration to prevent script injection in diagram definitions. Do not use raw innerHTML with untrusted content — mermaid's render API produces sanitized SVG output when configured with strict security.

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/components/ArtifactRenderer.tsx
git commit -m "feat(dashboard): ArtifactRenderer for inline artifact display"
```

---

## Task 10: Task Detail — SummaryCard + Restructured Tabs

**Files:**
- Modify: `dashboard/src/pages/Tasks.tsx`

This is the largest frontend change. Adds the SummaryCard above the tabs, restructures tabs (Details/Artifacts/Findings/Pipeline), and wires up the Artifacts tab and FileViewer.

- [ ] **Step 1: Add SummaryCard component**

A card rendered above the tabs showing: headline, file chips (clickable), findings count, review verdict, cost, duration. Only shown when `task.summary` exists. Styled with teal accent border matching the dashboard's existing design system.

- [ ] **Step 2: Add TaskDetailsTab and TaskArtifactsTab components**

`TaskDetailsTab`: tries to find and render the `task_summary` artifact, falls back to raw output.
`TaskArtifactsTab`: fetches and renders all artifacts using ArtifactCard.

- [ ] **Step 3: Update tab structure**

Replace tabs from `['output', 'findings', 'reviews']` to `['details', 'artifacts', 'findings', 'pipeline']`.

- [ ] **Step 4: Wire FileViewer**

Add `viewingFile` state. Render `<FileViewer>` modal when set. Pass `setViewingFile` to SummaryCard and artifact components.

- [ ] **Step 5: Verify build**

Run: `cd dashboard && npm run build`
Expected: TypeScript compilation succeeds

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/Tasks.tsx
git commit -m "feat(dashboard): task detail SummaryCard, restructured tabs, artifacts + file viewer"
```

---

## Task 11: Goal Timeline — Dashboard

**Files:**
- Modify: `dashboard/src/pages/Goals.tsx`

- [ ] **Step 1: Add GoalTimeline component**

Contains:
- Progress narrative card (teal accent) — client-side text from last 5 attempts
- Vertical timeline with connected dots (green=complete, red=failed, gray=other)
- Each node: attempt number, timestamp, plan text, task summary, files (clickable), cost
- Plan adjustment callouts in yellow/warning style
- `buildNarrative()` helper — takes chronological attempts, builds "Did X. Y failed. Retried with Z." prose

- [ ] **Step 2: Replace raw JSON display**

Find the "Last Plan" display (lines ~625-635) and recent tasks section (lines ~637-674). Replace both with `<GoalTimeline goalId={goal.id} onFileClick={setViewingFile} />`.

- [ ] **Step 3: Wire FileViewer**

Add `viewingFile` state and `<FileViewer>` modal to the Goals page.

- [ ] **Step 4: Verify build**

Run: `cd dashboard && npm run build`
Expected: TypeScript compilation succeeds

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/Goals.tsx
git commit -m "feat(dashboard): goal timeline with progress narrative and plan evolution"
```

---

## Task 12: Integration Verification

- [ ] **Step 1: Check Vite proxy covers workspace endpoint**

The dashboard's Vite config should already proxy `/api` to the orchestrator. Verify `/api/v1/workspace/files` is covered.

- [ ] **Step 2: End-to-end verification**

Restart services: `make dev`

1. Submit a test task via chat → verify SummaryCard appears in task detail
2. Wait for post-pipeline → verify Details tab shows structured breakdown
3. Click a file path → verify FileViewer opens with content
4. Check Artifacts tab → verify artifacts are listed
5. Navigate to Goals → verify timeline shows for goals with iterations
6. Check a pre-migration task → verify fallback to raw output works
7. Try a path traversal → verify 403 response
8. Try a large file → verify truncation message

- [ ] **Step 3: Final commit if needed**

```bash
git add -A
git commit -m "feat: task & goal clarity — integration fixes"
```
