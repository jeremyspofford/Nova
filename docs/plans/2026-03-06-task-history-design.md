# Task History Improvements Design

## Goal

Improve the dashboard Tasks page: show meaningful stage labels on pipeline
progress checkmarks, and add task history cleanup (manual delete + auto-retention).

## 1. Stage Labels on Progress Bar

Each of the 5 pipeline stages gets a short label, always visible:

```
 ✓ Context  →  ✓ Task  →  ✓ Guardrail  →  ✓ Review  →  ✓ Decision
```

- Completed: teal checkmark + label
- Running: amber spinner + label
- Pending: gray circle + label

Tooltip on hover shows detail from existing API data:
- Context: summary from checkpoint
- Guardrail: finding count + max severity
- Code Review: verdict + iteration count
- Decision: outcome

## 2. Manual Task Deletion

Backend:
- `DELETE /api/v1/pipeline/tasks/{task_id}` — single task (admin auth)
- `DELETE /api/v1/pipeline/tasks?status=complete,failed,cancelled` — bulk delete (admin auth)
- FK CASCADE handles findings, reviews, artifacts

Dashboard:
- Trash icon per task card in History tab
- "Clear All History" button with confirmation dialog

## 3. Auto-Cleanup Setting

Dashboard Settings (Platform Defaults section):
- "Task History Retention" dropdown: Never (default), 7, 30, 60, 90 days
- Stored as `task_history_retention_days` in platform config

Backend:
- Orchestrator background loop checks hourly
- Deletes terminal tasks older than configured retention
- Logs cleanup count

## 4. Files to Change

- `orchestrator/app/pipeline_router.py` — add DELETE endpoints
- `orchestrator/app/reaper.py` or new `cleanup.py` — auto-cleanup loop
- `dashboard/src/pages/Tasks.tsx` — stage labels, tooltips, delete buttons
- `dashboard/src/pages/Settings.tsx` — retention dropdown
- `dashboard/src/api.ts` — delete task API calls
- `tests/test_orchestrator.py` — delete task integration test
