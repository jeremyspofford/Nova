# Crash Recovery Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface partial pipeline results when tasks crash — to the dashboard UI and to cortex for smarter re-planning.

**Architecture:** Three layers: (1) orchestrator exposes checkpoint + sessions via API, (2) dashboard renders a stage timeline for failed tasks, (3) cortex stores partial work context and injects it into re-dispatch prompts. Data flows from DB through existing patterns — no new tables or pipeline changes.

**Tech Stack:** Python/FastAPI (orchestrator, cortex), React/TypeScript/TanStack Query (dashboard), asyncpg, PostgreSQL JSONB.

**Spec:** `docs/superpowers/specs/2026-03-31-crash-recovery-context-design.md`

---

### Task 1: Add `checkpoint` to task detail API

**Files:**
- Modify: `orchestrator/app/pipeline_router.py:209-236` (get_pipeline_task endpoint)
- Test: `tests/test_crash_recovery.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_crash_recovery.py`:

```python
"""Integration tests for crash recovery context endpoints."""
import pytest

pytestmark = pytest.mark.asyncio


class TestCheckpointExposure:
    """Verify checkpoint data is returned in task detail."""

    async def test_task_detail_includes_checkpoint(self, orchestrator, test_api_key):
        """GET /tasks/{id} should include a checkpoint field."""
        headers = test_api_key["headers"]
        # Submit a task
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-checkpoint: say hello"},
            headers=headers,
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        # Fetch detail immediately — checkpoint should exist (possibly empty)
        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}", headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "checkpoint" in data, "Task detail must include checkpoint field"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_crash_recovery.py::TestCheckpointExposure::test_task_detail_includes_checkpoint -v`
Expected: FAIL — `"checkpoint" not in data`

- [ ] **Step 3: Add `t.checkpoint` to the SELECT in `get_pipeline_task`**

In `orchestrator/app/pipeline_router.py`, modify the `get_pipeline_task` endpoint's SQL query (line ~216) to add `t.checkpoint` after `t.total_cost_usd`:

```python
        row = await conn.fetchrow(
            """
            SELECT t.id, t.status, t.pod_id, p.name AS pod_name,
                   t.user_input, t.output, t.error, t.current_stage,
                   t.retry_count, t.max_retries,
                   t.queued_at, t.started_at, t.completed_at, t.metadata,
                   t.total_cost_usd, t.checkpoint,
                   (SELECT COUNT(*) FROM guardrail_findings gf WHERE gf.task_id = t.id) AS findings_count,
                   (SELECT COUNT(*) FROM code_reviews cr WHERE cr.task_id = t.id) AS reviews_count,
                   (SELECT COUNT(*) FROM artifacts a WHERE a.task_id = t.id) AS artifacts_count
            FROM tasks t
            LEFT JOIN pods p ON p.id = t.pod_id
            WHERE t.id = $1::uuid
            """,
            task_id,
        )
```

No changes to `_task_dict` needed — asyncpg includes all selected columns in the row dict, and `_row_to_dict` passes through any keys not in uuid_fields/dt_fields as-is. JSONB columns are automatically decoded by asyncpg's codec.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_crash_recovery.py::TestCheckpointExposure -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/pipeline_router.py tests/test_crash_recovery.py
git commit -m "feat(orchestrator): expose checkpoint in task detail endpoint"
```

---

### Task 2: New sessions endpoint

**Files:**
- Modify: `orchestrator/app/pipeline_router.py` (add endpoint after reviews endpoint, ~line 452)
- Test: `tests/test_crash_recovery.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_crash_recovery.py`:

```python
class TestSessionsEndpoint:
    """Verify the new /tasks/{id}/sessions endpoint."""

    async def test_sessions_returns_list(self, orchestrator, test_api_key):
        """GET /tasks/{id}/sessions should return a list of agent sessions."""
        headers = test_api_key["headers"]
        # Submit a task
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-sessions: say hello"},
            headers=headers,
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}/sessions", headers=headers
        )
        assert resp.status_code == 200
        sessions = resp.json()
        assert isinstance(sessions, list)

    async def test_sessions_have_expected_fields(self, orchestrator, test_api_key):
        """Each session should have role, status, error, traceback, duration_ms."""
        headers = test_api_key["headers"]
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-session-fields: say hello"},
            headers=headers,
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        # Wait briefly for at least one session to be created
        import asyncio
        await asyncio.sleep(3)

        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}/sessions", headers=headers
        )
        assert resp.status_code == 200
        sessions = resp.json()
        if sessions:  # May be empty if task hasn't started yet
            s = sessions[0]
            for field in ("id", "role", "status", "error", "traceback", "duration_ms", "started_at"):
                assert field in s, f"Session missing field: {field}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_crash_recovery.py::TestSessionsEndpoint::test_sessions_returns_list -v`
Expected: FAIL — 404 (endpoint doesn't exist)

- [ ] **Step 3: Add the sessions endpoint**

In `orchestrator/app/pipeline_router.py`, add after the `list_task_reviews` endpoint (~line 452):

```python
@router.get("/api/v1/pipeline/tasks/{task_id}/sessions")
async def list_task_sessions(task_id: str, _key: ApiKeyDep) -> list[dict]:
    """List agent sessions for a pipeline task, ordered by execution sequence."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, task_id, role, status, output, error, traceback,
                   duration_ms, model_used, cost_usd, started_at
            FROM agent_sessions
            WHERE task_id = $1::uuid
            ORDER BY started_at
            """,
            task_id,
        )
    return [
        _row_to_dict(r, uuid_fields=("id", "task_id"),
                     dt_fields=("started_at",))
        for r in rows
    ]
```

Note: migration 044 added `model_used` as a dedicated column. The older `model` column (migration 002) is not used.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_crash_recovery.py::TestSessionsEndpoint -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/pipeline_router.py tests/test_crash_recovery.py
git commit -m "feat(orchestrator): add sessions endpoint for task agent sessions"
```

---

### Task 3: Add `checkpoint` to cortex TaskOutcome

**Files:**
- Modify: `cortex/app/task_tracker.py:22-33` (TaskOutcome dataclass)
- Modify: `cortex/app/task_tracker.py:36-85` (_score_task function)

- [ ] **Step 1: Add `checkpoint` field to `TaskOutcome` dataclass**

In `cortex/app/task_tracker.py`, add after the `total_cost_usd` field (line 33):

```python
@dataclass
class TaskOutcome:
    """Result of waiting for a dispatched task."""
    task_id: str
    status: str  # complete | failed | cancelled | running | unknown
    score: float  # 0.0–1.0 outcome score
    confidence: float  # how confident we are in the score
    output: str | None = None
    error: str | None = None
    findings_count: int = 0
    timed_out: bool = False
    total_cost_usd: float = 0.0
    checkpoint: dict | None = None
    current_stage: str | None = None
```

- [ ] **Step 2: Wire `checkpoint` and `current_stage` into every `_score_task` return path**

In `_score_task`, read checkpoint and current_stage from the task dict (line ~42) and pass them through **all 6** return paths (timed_out, complete with findings, complete clean, failed, cancelled, unknown fallback):

```python
def _score_task(task: dict, timed_out: bool) -> TaskOutcome:
    """Derive an outcome score from a task's terminal state."""
    task_id = task.get("id", "unknown")
    status = task.get("status", "unknown")
    output = task.get("output")
    error = task.get("error")
    findings_count = task.get("findings_count", 0)
    total_cost_usd = float(task.get("total_cost_usd") or 0)
    checkpoint = task.get("checkpoint")
    current_stage = task.get("current_stage")
```

Then add `checkpoint=checkpoint, current_stage=current_stage` to every `TaskOutcome(...)` constructor call in the function — all 6 return paths, including the final unknown fallback at the bottom.

- [ ] **Step 3: Verify cortex container still starts**

Run: `docker compose up -d cortex && docker compose logs cortex --tail 5`
Expected: Container starts, no import errors.

- [ ] **Step 4: Commit**

```bash
git add cortex/app/task_tracker.py
git commit -m "feat(cortex): carry checkpoint data through TaskOutcome"
```

---

### Task 4: Cortex stores partial work context on failure

**Files:**
- Modify: `cortex/app/cycle.py:653-675` (_update_goal_progress failed branch)

- [ ] **Step 1: Enrich the failed branch with checkpoint fields**

In `cortex/app/cycle.py`, replace the `elif outcome.status == "failed":` branch (~line 653):

```python
        elif outcome.status == "failed":
            # Failed task — store error context + partial work for re-planning
            plan_update = {
                **current_plan,
                "last_task_id": outcome.task_id,
                "last_task_status": "failed",
                "last_task_error": (outcome.error or "unknown")[:500],
                "cycle": cycle,
            }
            # Enrich with partial work from checkpoint
            if outcome.checkpoint and isinstance(outcome.checkpoint, dict):
                plan_update["last_completed_stages"] = list(outcome.checkpoint.keys())
                # The "task" stage output is the actual work product
                task_output = outcome.checkpoint.get("task", {})
                if isinstance(task_output, dict):
                    content = task_output.get("content") or task_output.get("output") or str(task_output)
                    plan_update["last_stage_output"] = content[:1000]
                # Identify failing stage from current_stage (carried via TaskOutcome)
                plan_update["failed_at_stage"] = outcome.current_stage or "unknown"
            await conn.execute(
                """UPDATE goals
                   SET current_plan = $1::jsonb,
                       cost_so_far_usd = $3,
                       updated_at = NOW()
                   WHERE id = $2::uuid""",
                json.dumps(plan_update),
                goal_id,
                new_cost,
            )
            log.info(
                "Goal %s: task %s failed at %s — partial work stored for re-planning "
                "(stages: %s)",
                goal_id, outcome.task_id,
                plan_update.get("failed_at_stage", "unknown"),
                plan_update.get("last_completed_stages", []),
            )
```

Note: `failed_at_stage` uses `outcome.current_stage` which was added to `TaskOutcome` in Task 3 and populated from the task detail API's `current_stage` field.

- [ ] **Step 2: Verify cortex container restarts cleanly**

Run: `docker compose restart cortex && docker compose logs cortex --tail 10`
Expected: Clean startup, no errors.

- [ ] **Step 3: Commit**

```bash
git add cortex/app/cycle.py cortex/app/task_tracker.py
git commit -m "feat(cortex): store partial work context from failed tasks in goal plan"
```

---

### Task 5: Cortex injects prior work context into planner prompt

**Files:**
- Modify: `cortex/app/cycle.py:336-365` (goal_context_block assembly in _plan_action)

- [ ] **Step 1: Add prior work context block to goal context assembly**

In `cortex/app/cycle.py`, in the `_plan_action` function inside the `if drive.name == "serve":` block, find the section that builds `goal_context_block` (around line 340-360). After the existing block that handles `last_task_status == "failed"` (~line 347), replace it with an expanded version:

```python
        if plan_data and isinstance(plan_data, dict):
            if plan_data.get("last_task_status") == "failed":
                parts.append(f"Last attempt FAILED: {plan_data.get('last_task_error', 'unknown')[:200]}")
                # Inject prior work context if partial stages completed
                completed_stages = plan_data.get("last_completed_stages")
                if completed_stages:
                    failed_stage = plan_data.get("failed_at_stage", "unknown")
                    parts.append(f"Completed stages before failure: {', '.join(completed_stages)}")
                    parts.append(f"Failed at stage: {failed_stage}")
                    stage_output = plan_data.get("last_stage_output")
                    if stage_output:
                        parts.append(
                            "Prior work output (use as starting point, do not redo):\n"
                            f"{stage_output[:500]}"
                        )
            elif plan_data.get("last_task_output"):
                parts.append(f"Last result: {plan_data['last_task_output'][:200]}")
            if plan_data.get("plan"):
                parts.append(f"Previous plan: {plan_data['plan'][:200]}")
```

- [ ] **Step 2: Verify cortex restarts cleanly**

Run: `docker compose restart cortex && docker compose logs cortex --tail 10`
Expected: Clean startup.

- [ ] **Step 3: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): inject prior work context into re-planning prompt"
```

---

### Task 6: Dashboard — API client + types for sessions

**Files:**
- Modify: `dashboard/src/types.ts` (add AgentSession interface, add checkpoint to PipelineTask)
- Modify: `dashboard/src/api.ts` (add getTaskSessions)

- [ ] **Step 1: Add `AgentSession` interface to types.ts**

In `dashboard/src/types.ts`, after the `CodeReviewVerdict` interface (~line 108):

```typescript
export interface AgentSession {
  id: string
  task_id: string
  role: string
  status: 'running' | 'complete' | 'failed' | 'skipped'
  output: Record<string, unknown> | null
  error: string | null
  traceback: string | null
  duration_ms: number | null
  model_used: string | null
  cost_usd: number
  started_at: string | null
}
```

- [ ] **Step 2: Add `checkpoint` to `PipelineTask` interface**

In `dashboard/src/types.ts`, add after the `summary` field in `PipelineTask`:

```typescript
  checkpoint: Record<string, Record<string, unknown>> | null
```

- [ ] **Step 3: Add `getTaskSessions` to api.ts**

In `dashboard/src/api.ts`, after `getTaskReviews` (~line 181):

```typescript
export const getTaskSessions = (task_id: string) =>
  apiFetch<AgentSession[]>(`/api/v1/pipeline/tasks/${task_id}/sessions`)
```

Add `AgentSession` to the import from `'./types'`.

- [ ] **Step 4: Build check**

Run: `cd dashboard && npm run build 2>&1 | tail -3`
Expected: `built in Xs` with no type errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/types.ts dashboard/src/api.ts
git commit -m "feat(dashboard): add AgentSession type and sessions API client"
```

---

### Task 7: Dashboard — FailedTaskStagesView component

**Files:**
- Modify: `dashboard/src/pages/Tasks.tsx` (add FailedTaskStagesView, update TaskDetailsTab)

- [ ] **Step 1: Add the PIPELINE_STAGES constant**

In `dashboard/src/pages/Tasks.tsx`, after the `HELP_ENTRIES` array (~line 55):

```typescript
/** Full 7-stage pipeline order (from checkpoint.py PIPELINE_STAGE_ORDER). */
const PIPELINE_STAGES = [
  { role: 'context', label: 'Context' },
  { role: 'task', label: 'Task' },
  { role: 'critique_direction', label: 'Critique' },
  { role: 'guardrail', label: 'Guardrail' },
  { role: 'code_review', label: 'Code Review' },
  { role: 'critique_acceptance', label: 'Acceptance' },
  { role: 'decision', label: 'Decision' },
]
```

- [ ] **Step 2: Add the FailedTaskStagesView component**

In `dashboard/src/pages/Tasks.tsx`, before `TaskDetailsTab` (~line 483):

```typescript
function FailedTaskStagesView({ taskId, checkpoint, error: taskError }: {
  taskId: string
  checkpoint: Record<string, Record<string, unknown>> | null
  error: string | null
}) {
  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ['task-sessions', taskId],
    queryFn: () => getTaskSessions(taskId),
    staleTime: Infinity,  // terminal task — data won't change
  })

  if (isLoading) return <Skeleton lines={5} />

  const sessionByRole = new Map(sessions.map(s => [s.role, s]))
  const completedRoles = new Set(checkpoint ? Object.keys(checkpoint) : [])
  const failedSession = sessions.find(s => s.status === 'failed')

  return (
    <div className="space-y-0">
      {PIPELINE_STAGES.map((stage, i) => {
        const session = sessionByRole.get(stage.role)
        const isCompleted = completedRoles.has(stage.role)
        const isFailed = session?.status === 'failed' || (failedSession?.role === stage.role)
        const isNotReached = !isCompleted && !isFailed && !session

        const dotColor = isCompleted ? 'bg-success'
          : isFailed ? 'bg-danger'
          : 'bg-content-tertiary'

        return (
          <div key={stage.role} className="relative pb-3 pl-6">
            {/* Connector line */}
            {i < PIPELINE_STAGES.length - 1 && (
              <div className="absolute left-[9px] top-5 h-full w-0.5 bg-border" />
            )}
            {/* Status dot */}
            <div className={`absolute left-1 top-1.5 h-3 w-3 rounded-full border-2 border-surface ${dotColor}`} />

            {isNotReached ? (
              <div className="py-1 text-caption text-content-tertiary">
                {stage.label} — <span className="italic">not reached</span>
              </div>
            ) : (
              <StageCard
                stage={stage}
                session={session}
                checkpoint={isCompleted ? checkpoint![stage.role] : null}
                isFailed={isFailed}
              />
            )}
          </div>
        )
      })}

      {/* Task-level error fallback (if no specific session failed) */}
      {taskError && !failedSession && (
        <div className="mt-3 rounded-sm bg-danger-dim p-3">
          <p className="text-caption font-medium text-danger mb-1">Pipeline Error</p>
          <pre className="whitespace-pre-wrap break-words text-mono-sm text-danger">
            {taskError}
          </pre>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Add the StageCard sub-component**

Directly above `FailedTaskStagesView`:

```typescript
function StageCard({ stage, session, checkpoint, isFailed }: {
  stage: { role: string; label: string }
  session?: AgentSession
  checkpoint: Record<string, unknown> | null
  isFailed: boolean
}) {
  const [expanded, setExpanded] = useState(false)

  const duration = session?.duration_ms
    ? `${(session.duration_ms / 1000).toFixed(1)}s`
    : null
  const model = session?.model_used?.split('/').pop() ?? null
  const cost = session?.cost_usd ? `$${session.cost_usd.toFixed(3)}` : null

  return (
    <div className={clsx(
      'rounded-md border p-2.5',
      isFailed ? 'border-danger/30 bg-danger-dim/10' : 'border-border bg-surface-elevated',
    )}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-content-tertiary hover:text-content-primary text-xs"
        >
          {expanded ? '\u25BE' : '\u25B8'}
        </button>
        <span className={clsx(
          'text-compact font-medium',
          isFailed ? 'text-danger' : 'text-content-primary',
        )}>
          {stage.label}
        </span>
        <span className="flex-1" />
        {duration && <span className="text-caption text-content-tertiary">{duration}</span>}
        {model && <span className="text-caption text-content-tertiary">{model}</span>}
        {cost && <span className="text-caption text-content-tertiary">{cost}</span>}
      </div>

      {/* Error for failed stage */}
      {isFailed && session?.error && (
        <div className="mt-2">
          <pre className="whitespace-pre-wrap break-words rounded-sm bg-danger-dim p-2 text-mono-sm text-danger">
            {session.error}
          </pre>
          {session.traceback && (
            <details className="mt-1">
              <summary className="text-caption text-content-tertiary cursor-pointer hover:text-content-secondary">
                Traceback
              </summary>
              <pre className="mt-1 whitespace-pre-wrap break-words text-mono-sm text-content-tertiary max-h-48 overflow-y-auto">
                {session.traceback}
              </pre>
            </details>
          )}
        </div>
      )}

      {/* Expanded checkpoint output */}
      {expanded && checkpoint && (
        <div className="mt-2 rounded-sm bg-surface-card p-2 markdown-body text-compact text-content-secondary">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {typeof checkpoint.content === 'string'
              ? checkpoint.content
              : JSON.stringify(checkpoint, null, 2)}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Add imports**

At the top of `Tasks.tsx`, add `AgentSession` to the type imports from `'../types'` and `getTaskSessions` to the API imports.

- [ ] **Step 5: Build check**

Run: `cd dashboard && npm run build 2>&1 | tail -3`
Expected: `built in Xs` — no errors.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/Tasks.tsx
git commit -m "feat(dashboard): add FailedTaskStagesView component for crash recovery"
```

---

### Task 8: Wire FailedTaskStagesView into TaskDetailsTab

**Files:**
- Modify: `dashboard/src/pages/Tasks.tsx` (TaskDetailsTab, ~line 485)

- [ ] **Step 1: Update TaskDetailsTab to accept task status and checkpoint**

Change the `TaskDetailsTab` signature and add the failed-task rendering path:

```typescript
function TaskDetailsTab({ taskId, taskStatus, checkpoint, fallbackOutput, fallbackError }: {
  taskId: string
  taskStatus: string
  checkpoint: Record<string, Record<string, unknown>> | null
  fallbackOutput: string | null
  fallbackError: string | null
}) {
  const { data: artifacts = [] } = useQuery({
    queryKey: ['task-artifacts', taskId],
    queryFn: () => getTaskArtifacts(taskId),
    staleTime: 10_000,
  })
  const summary = artifacts.find(a => a.artifact_type === 'task_summary')

  if (summary) {
    return (
      <div className="prose prose-invert max-w-none rounded-sm bg-surface-elevated p-3 text-compact markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{summary.content}</ReactMarkdown>
      </div>
    )
  }

  // Failed task with no summary — show stage-by-stage recovery view
  if (taskStatus === 'failed' && !fallbackOutput) {
    return <FailedTaskStagesView taskId={taskId} checkpoint={checkpoint} error={fallbackError} />
  }

  return (
    <div className="space-y-3">
      {fallbackOutput ? (
        <div className="rounded-sm bg-surface-elevated p-3 text-compact text-content-secondary markdown-body">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{fallbackOutput}</ReactMarkdown>
        </div>
      ) : (
        <p className="text-compact text-content-tertiary">No output yet.</p>
      )}
      {fallbackError && (
        <div>
          <p className="mb-1 text-caption font-medium text-danger">Error</p>
          <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-sm bg-danger-dim p-3 text-mono-sm text-danger">
            {fallbackError}
          </pre>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Update the TaskDetailsTab call site in TaskDetailSheet**

Find the `TaskDetailsTab` usage in `TaskDetailSheet` (~line 654) and pass the new props:

```typescript
          {detailTab === 'details' && (
            <TaskDetailsTab
              taskId={task.id}
              taskStatus={task.status}
              checkpoint={task.checkpoint}
              fallbackOutput={task.output}
              fallbackError={task.error}
            />
          )}
```

- [ ] **Step 3: Build check**

Run: `cd dashboard && npm run build 2>&1 | tail -3`
Expected: `built in Xs` — no errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/Tasks.tsx
git commit -m "feat(dashboard): wire crash recovery view into failed task details tab"
```

---

### Task 9: Integration verification

**Files:**
- Test: `tests/test_crash_recovery.py`

- [ ] **Step 1: Add a combined checkpoint + sessions test**

Append to `tests/test_crash_recovery.py`:

```python
class TestCrashRecoveryIntegration:
    """End-to-end: checkpoint appears in task detail, sessions are queryable."""

    async def test_checkpoint_and_sessions_available(self, orchestrator, test_api_key):
        """After submitting a task, both checkpoint and sessions should be accessible."""
        headers = test_api_key["headers"]
        import asyncio

        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-recovery-e2e: say hello"},
            headers=headers,
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        # Wait for task to progress past at least one stage
        await asyncio.sleep(5)

        # Verify checkpoint exists in task detail
        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}", headers=headers
        )
        assert resp.status_code == 200
        assert "checkpoint" in resp.json()

        # Verify sessions endpoint works
        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}/sessions", headers=headers
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest tests/test_crash_recovery.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Run dashboard build as final check**

Run: `cd dashboard && npm run build 2>&1 | tail -3`
Expected: Clean build.

- [ ] **Step 4: Commit test**

```bash
git add tests/test_crash_recovery.py
git commit -m "test: add crash recovery integration tests"
```

---

### Task 10: Clean up checkpoint file

**Files:**
- Delete: `.claude/checkpoints/crash-recovery-context.md`

- [ ] **Step 1: Remove the checkpoint file (work is complete)**

```bash
rm .claude/checkpoints/crash-recovery-context.md
```

- [ ] **Step 2: Final commit with all changes on feature branch**

Verify all work is committed:

```bash
git log --oneline feature/crash-recovery ^main
```

Expected: ~9 commits covering API, cortex, dashboard, and tests.
