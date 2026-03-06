# Task History Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add visible stage labels to pipeline progress checkmarks, single/bulk task deletion, and auto-cleanup retention setting.

**Architecture:** Backend gets two new DELETE endpoints in `pipeline_router.py` and a cleanup loop in `reaper.py`. Dashboard gets stage labels on the progress bar, delete buttons per-task and bulk, and a retention dropdown in Settings. All wired through the existing `apiFetch` + TanStack Query pattern.

**Tech Stack:** FastAPI (asyncpg), React + TypeScript, TanStack Query, Tailwind CSS, Lucide icons

---

## Task 1: Backend — DELETE Endpoints for Tasks

**Files:**
- Modify: `orchestrator/app/pipeline_router.py` (add after cancel endpoint ~line 249)
- Test: `tests/test_orchestrator.py`

### Step 1: Write the failing test

Add to the bottom of `tests/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_delete_single_task(client, admin_headers):
    """Delete a single terminal task."""
    # Submit a task to get one in the DB
    resp = await client.post(
        "/api/v1/pipeline/tasks",
        json={"user_input": "test task to delete"},
        headers=admin_headers,
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    # Cancel it so it becomes terminal
    await client.post(f"/api/v1/pipeline/tasks/{task_id}/cancel", headers=admin_headers)

    # Delete it
    resp = await client.delete(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
    assert resp.status_code == 204

    # Verify it's gone
    resp = await client.get(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_task_not_terminal_fails(client, admin_headers):
    """Cannot delete an active task — must cancel first."""
    resp = await client.post(
        "/api/v1/pipeline/tasks",
        json={"user_input": "active task"},
        headers=admin_headers,
    )
    task_id = resp.json()["task_id"]

    # Try to delete while still queued/active
    resp = await client.delete(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
    assert resp.status_code == 409

    # Cleanup: cancel it
    await client.post(f"/api/v1/pipeline/tasks/{task_id}/cancel", headers=admin_headers)
    await client.delete(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)


@pytest.mark.asyncio
async def test_bulk_delete_tasks(client, admin_headers):
    """Bulk delete terminal tasks by status filter."""
    # Create and cancel two tasks
    ids = []
    for i in range(2):
        resp = await client.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": f"bulk delete test {i}"},
            headers=admin_headers,
        )
        task_id = resp.json()["task_id"]
        await client.post(f"/api/v1/pipeline/tasks/{task_id}/cancel", headers=admin_headers)
        ids.append(task_id)

    # Bulk delete cancelled tasks
    resp = await client.delete(
        "/api/v1/pipeline/tasks?status=cancelled",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] >= 2
```

### Step 2: Run test to verify it fails

Run: `cd tests && uv run --with pytest --with pytest-asyncio --with httpx --with websockets --with python-dotenv pytest -v --tb=short -k "test_delete"`
Expected: FAIL — 404/405 because DELETE endpoint doesn't exist yet.

### Step 3: Write the implementation

Add to `orchestrator/app/pipeline_router.py` after the `cancel_pipeline_task` endpoint (after line 249):

```python
@router.delete("/api/v1/pipeline/tasks/{task_id}", status_code=204)
async def delete_pipeline_task(task_id: str, _admin: AdminDep) -> None:
    """
    Delete a single terminal task (complete/failed/cancelled) and all related records.
    FK CASCADE handles guardrail_findings, code_reviews, artifacts, agent_sessions.
    Admin-only.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM tasks
            WHERE id = $1::uuid
              AND status IN ('complete', 'failed', 'cancelled')
            """,
            task_id,
        )
    if result == "DELETE 0":
        raise HTTPException(
            status_code=409,
            detail="Task not found or not in a terminal state (complete/failed/cancelled)",
        )


@router.delete("/api/v1/pipeline/tasks")
async def bulk_delete_pipeline_tasks(
    _admin: AdminDep,
    status: str = Query(
        default="complete,failed,cancelled",
        description="Comma-separated terminal statuses to delete",
    ),
) -> dict:
    """
    Bulk delete terminal tasks matching the given statuses.
    Only allows terminal statuses (complete, failed, cancelled).
    Admin-only.
    """
    ALLOWED = {"complete", "failed", "cancelled"}
    requested = {s.strip() for s in status.split(",")}
    invalid = requested - ALLOWED
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Can only bulk-delete terminal statuses. Invalid: {invalid}",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM tasks
            WHERE status = ANY($1::text[])
            """,
            list(requested),
        )
    # result is like "DELETE 5"
    deleted = int(result.split()[-1])
    log.info("Bulk deleted %d tasks (statuses=%s)", deleted, requested)
    return {"deleted": deleted, "statuses": list(requested)}
```

### Step 4: Run test to verify it passes

Run: `cd tests && uv run --with pytest --with pytest-asyncio --with httpx --with websockets --with python-dotenv pytest -v --tb=short -k "test_delete"`
Expected: 3 tests PASS

### Step 5: Rebuild and restart orchestrator

Run: `docker compose build orchestrator && docker compose up -d orchestrator`

### Step 6: Commit

```bash
git add orchestrator/app/pipeline_router.py tests/test_orchestrator.py
git commit -m "feat: add DELETE endpoints for single and bulk task deletion"
```

---

## Task 2: Backend — Auto-Cleanup in Reaper

**Files:**
- Modify: `orchestrator/app/reaper.py` (add cleanup function + call from loop)
- Modify: `orchestrator/app/main.py` (no changes needed — reaper already runs)

### Step 1: Add the cleanup function to reaper.py

Add to the bottom of `orchestrator/app/reaper.py` (before the `_audit` helper):

```python
# ── Auto-cleanup expired task history ─────────────────────────────────────────

async def _cleanup_expired_tasks() -> None:
    """
    Delete terminal tasks older than the configured retention period.
    Reads `task_history_retention_days` from platform config.
    0 or missing = disabled (keep forever).
    Runs every reaper cycle (~60s) but only acts hourly via a simple modulo check.
    """
    from .db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM platform_config WHERE key = 'task_history_retention_days'"
        )
        if not row:
            return
        try:
            days = int(row["value"].strip('"'))
        except (ValueError, TypeError, AttributeError):
            return
        if days <= 0:
            return

        result = await conn.execute(
            """
            DELETE FROM tasks
            WHERE status IN ('complete', 'failed', 'cancelled')
              AND completed_at < now() - ($1 || ' days')::interval
            """,
            str(days),
        )
        deleted = int(result.split()[-1])
        if deleted > 0:
            logger.info("Auto-cleanup: deleted %d tasks older than %d days", deleted, days)
            await _audit(conn, "task_history_cleanup", "info",
                         data={"deleted": deleted, "retention_days": days})
```

### Step 2: Wire it into the reaper loop

In `orchestrator/app/reaper.py`, modify the `reaper_loop` function to call `_cleanup_expired_tasks`. Add it after the existing reap calls inside the `try` block:

```python
async def reaper_loop() -> None:
    logger.info("Reaper started")
    _cycle = 0
    while True:
        try:
            await asyncio.sleep(settings.reaper_interval_seconds)
            await _reap_stale_running_tasks()
            await _reap_stuck_queued_tasks()
            await _reap_timed_out_sessions()
            # Run cleanup once per ~60 cycles (~hourly at 60s interval)
            _cycle += 1
            if _cycle % 60 == 0:
                await _cleanup_expired_tasks()
        except asyncio.CancelledError:
            logger.info("Reaper shutting down")
            break
        except Exception:
            logger.exception("Reaper cycle error — will retry next interval")
```

### Step 3: Rebuild and restart

Run: `docker compose build orchestrator && docker compose up -d orchestrator`

### Step 4: Commit

```bash
git add orchestrator/app/reaper.py
git commit -m "feat: add auto-cleanup of expired task history in reaper loop"
```

---

## Task 3: Dashboard — API Functions for Task Deletion

**Files:**
- Modify: `dashboard/src/api.ts` (add after `getQueueStats` ~line 96)

### Step 1: Add the delete functions

Add to `dashboard/src/api.ts` after line 96 (after `getQueueStats`):

```typescript
export const deletePipelineTask = (task_id: string) =>
  apiFetch<void>(`/api/v1/pipeline/tasks/${task_id}`, { method: 'DELETE' })

export const bulkDeletePipelineTasks = (statuses = 'complete,failed,cancelled') =>
  apiFetch<{ deleted: number; statuses: string[] }>(
    `/api/v1/pipeline/tasks?status=${encodeURIComponent(statuses)}`,
    { method: 'DELETE' },
  )
```

### Step 2: Commit

```bash
git add dashboard/src/api.ts
git commit -m "feat: add delete task API functions to dashboard"
```

---

## Task 4: Dashboard — Stage Labels on Progress Bar

**Files:**
- Modify: `dashboard/src/pages/Tasks.tsx` (StageProgress component, lines 62-94)

### Step 1: Update StageProgress to show labels

Replace lines 62-94 in `dashboard/src/pages/Tasks.tsx` with:

```typescript
function StageProgress({ task }: { task: PipelineTask }) {
  const { completedUpTo, activeIndex } = resolveStageState(task)

  return (
    <div className="flex items-center gap-0">
      {STAGES.map((stage, i) => {
        const done    = i < completedUpTo
        const active  = i === activeIndex
        const failed  = task.status === 'failed' && i === activeIndex

        return (
          <div key={stage} className="flex items-center">
            {i > 0 && (
              <div className={clsx('h-px w-3 sm:w-5', done ? 'bg-emerald-500' : 'bg-neutral-200 dark:bg-neutral-700')} />
            )}
            <div className="flex flex-col items-center gap-0.5" title={STAGE_LABELS[stage]}>
              <div
                className={clsx(
                  'flex size-5 sm:size-6 items-center justify-center rounded-full text-[10px] font-bold border transition-all',
                  done   && 'bg-emerald-100 dark:bg-emerald-900/30 border-emerald-600 text-emerald-700 dark:text-emerald-400',
                  active && !failed && 'border-amber-400 text-amber-700 dark:text-amber-400 animate-pulse bg-amber-50 dark:bg-amber-900/30',
                  failed && 'border-red-500 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30',
                  !done && !active && 'border-neutral-300 dark:border-neutral-600 text-neutral-500 dark:text-neutral-400 bg-card dark:bg-neutral-900',
                )}
              >
                {done ? '✓' : i + 1}
              </div>
              <span className={clsx(
                'text-[9px] leading-none font-medium hidden sm:block',
                done   && 'text-emerald-600 dark:text-emerald-400',
                active && !failed && 'text-amber-600 dark:text-amber-400',
                failed && 'text-red-500 dark:text-red-400',
                !done && !active && 'text-neutral-400 dark:text-neutral-500',
              )}>
                {STAGE_LABELS[stage]}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
```

### Step 2: Verify the dashboard builds

Run: `cd dashboard && npm run build`
Expected: No TypeScript errors

### Step 3: Commit

```bash
git add dashboard/src/pages/Tasks.tsx
git commit -m "feat: show stage labels below pipeline progress checkmarks"
```

---

## Task 5: Dashboard — Delete Buttons on Task Cards + Clear All History

**Files:**
- Modify: `dashboard/src/pages/Tasks.tsx` (imports, TaskCard, Tasks main component)

### Step 1: Update imports

At line 4, add `Trash2` to the Lucide imports:

```typescript
import {
  Send, RefreshCw, X, CheckCircle, AlertCircle, Clock,
  ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, Loader2, Trash2,
} from 'lucide-react'
```

Update the api imports at line 10-12 to include the new functions:

```typescript
import {
  getPipelineTasks, submitPipelineTask, cancelPipelineTask,
  reviewPipelineTask, getQueueStats, getPods, getModels,
  deletePipelineTask, bulkDeletePipelineTasks,
} from '../api'
```

### Step 2: Add delete button to TaskCard

In the `TaskCard` component (starts at line 145), add a delete mutation after the cancel mutation (~line 153):

```typescript
  const deleteMutation = useMutation({
    mutationFn: () => deletePipelineTask(task.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pipeline-tasks'] }),
  })
```

Then in the header buttons area (the `<div className="flex shrink-0 items-center gap-1">` block), add a trash icon button for terminal tasks. Add this right before the expand/collapse button:

```typescript
          {isTerminal && (
            <button
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              title="Delete task"
              className="rounded-md p-1 text-neutral-400 dark:text-neutral-500 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-40"
            >
              <Trash2 size={14} />
            </button>
          )}
```

### Step 3: Add "Clear All History" button

In the main `Tasks` component, add a state variable and mutation for bulk delete. Inside the component, after the `isFetching` destructure (~line 376):

```typescript
  const [confirmClear, setConfirmClear] = useState(false)

  const bulkDelete = useMutation({
    mutationFn: () => bulkDeletePipelineTasks(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })
      setConfirmClear(false)
    },
  })
```

Then, in the History tab's empty state or task list section, add the clear button. Replace the task list `<div>` block (lines ~448-458) with:

```typescript
      {/* Task list */}
      <div className="space-y-3">
        {tab === 'history' && historyTasks.length > 0 && (
          <div className="flex justify-end">
            {confirmClear ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-neutral-500 dark:text-neutral-400">Delete all history?</span>
                <button
                  onClick={() => bulkDelete.mutate()}
                  disabled={bulkDelete.isPending}
                  className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50"
                >
                  {bulkDelete.isPending ? 'Deleting…' : 'Confirm'}
                </button>
                <button
                  onClick={() => setConfirmClear(false)}
                  className="rounded-md px-3 py-1.5 text-xs text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmClear(true)}
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-neutral-500 dark:text-neutral-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 dark:hover:text-red-400"
              >
                <Trash2 size={12} /> Clear All History
              </button>
            )}
          </div>
        )}

        {tabTasks[tab].length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-16 text-neutral-500 dark:text-neutral-400">
            {tab === 'active'  && <><Clock size={24} /><p className="text-sm">No active tasks</p></>}
            {tab === 'review'  && <><CheckCircle size={24} /><p className="text-sm">No tasks awaiting review</p></>}
            {tab === 'history' && <><AlertCircle size={24} /><p className="text-sm">No completed tasks yet</p></>}
          </div>
        ) : (
          tabTasks[tab].map(task => <TaskCard key={task.id} task={task} />)
        )}
      </div>
```

### Step 4: Verify the dashboard builds

Run: `cd dashboard && npm run build`
Expected: No TypeScript errors

### Step 5: Commit

```bash
git add dashboard/src/pages/Tasks.tsx
git commit -m "feat: add per-task delete and clear all history buttons"
```

---

## Task 6: Dashboard — Task Retention Setting in Settings Page

**Files:**
- Modify: `dashboard/src/pages/Settings.tsx` (Platform Defaults section, ~line 1227-1236)

### Step 1: Add retention config field

In `dashboard/src/pages/Settings.tsx`, find the Platform Defaults `<Section>` block (line 1222). We need to read the current retention value from the config entries. Find where `defaultModel` is read from entries (search for `nova.default_model` in the `entries.find(...)` calls near the top of the `Settings` component).

Add alongside the existing config value reads:

```typescript
  const retentionDays = entries.find(e => e.key === 'task_history_retention_days')?.value ?? ''
```

Then add a new `ConfigField` inside the Platform Defaults section, after the `Default model override` field (after line 1235):

```typescript
        <ConfigField
          label="Task history retention"
          configKey="task_history_retention_days"
          value={String(retentionDays)}
          placeholder="0 (keep forever)"
          description="Automatically delete completed/failed/cancelled tasks older than this many days. Set to 0 or leave blank to keep forever. Common values: 7, 30, 60, 90."
          onSave={handleSave}
          saving={saveMutation.isPending}
        />
```

### Step 2: Verify the dashboard builds

Run: `cd dashboard && npm run build`
Expected: No TypeScript errors

### Step 3: Commit

```bash
git add dashboard/src/pages/Settings.tsx
git commit -m "feat: add task history retention setting to Platform Defaults"
```

---

## Task 7: Integration Test — Full Delete Flow

**Files:**
- Modify: `tests/test_orchestrator.py`

### Step 1: Verify all existing tests still pass

Run: `cd tests && uv run --with pytest --with pytest-asyncio --with httpx --with websockets --with python-dotenv pytest -v --tb=short`
Expected: All tests PASS

### Step 2: Commit all remaining changes and push

```bash
git add -A tests/
git commit -m "test: add task deletion integration tests"
```

---

## Task 8: Final Build + Push

### Step 1: Rebuild everything

Run:
```bash
docker compose build orchestrator
cd dashboard && npm run build && cd ..
```
Expected: Both build successfully.

### Step 2: Push

```bash
git push origin main
```
