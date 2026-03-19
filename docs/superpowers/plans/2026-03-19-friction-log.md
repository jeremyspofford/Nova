# Friction Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an in-app friction log with Sprint Health metrics, auto-friction on pipeline failure, screenshot support, and a "Fix This" action that creates pipeline tasks.

**Architecture:** New `friction_router.py` on the orchestrator (CRUD + stats + "Fix This"), migration 030 for the `friction_log` table, auto-friction hook in `executor.py`, screenshot files on disk. Dashboard: new Friction page (Sprint Health header + entry list), Log Friction Sheet form, floating button on all pages.

**Tech Stack:** FastAPI + asyncpg (backend), React + TanStack Query + Tailwind (frontend), existing UI component library (Card, Badge, EmptyState, Sheet, Metric, Skeleton, Toast, RadioGroup)

**Design doc:** `docs/designs/hardening-sprint-friction-log.md` (all decisions from CEO, Eng, Design reviews)

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `orchestrator/app/migrations/031_friction_log.sql` | Create friction_log table + indexes |
| `orchestrator/app/friction_router.py` | CRUD endpoints, stats, "Fix This" action |
| `tests/test_friction.py` | Integration tests for friction log endpoints |
| `dashboard/src/pages/Friction.tsx` | Friction page: Sprint Health + entry list + filters |
| `dashboard/src/components/LogFrictionSheet.tsx` | Log Friction form (Sheet drawer) |
| `dashboard/src/components/LogFrictionButton.tsx` | Floating button (global, all pages) |

### Modified Files
| File | Change |
|------|--------|
| `orchestrator/app/main.py` | Mount friction_router |
| `orchestrator/app/pipeline/executor.py` | Auto-friction hook in `mark_task_failed()` |
| `orchestrator/app/pipeline_router.py` | Add `failed_this_week` + `submitted_today` to stats |
| `dashboard/src/api.ts` | Add friction API functions |
| `dashboard/src/types.ts` | Add FrictionEntry type |
| `dashboard/src/App.tsx` | Add /friction route |
| `dashboard/src/components/layout/Sidebar.tsx` | Add Friction nav item |
| `dashboard/src/components/layout/AppLayout.tsx` | Render LogFrictionButton |

---

## Task 1: Database Migration

**Files:**
- Create: `orchestrator/app/migrations/031_friction_log.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Friction log: lightweight issue tracker for dogfooding.
-- Entries track things that broke or felt wrong during usage.
-- "Fix This" creates a pipeline task from an entry.

CREATE TABLE IF NOT EXISTS friction_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description     TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'annoyance'
                    CHECK (severity IN ('blocker', 'annoyance', 'idea')),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_progress', 'fixed')),
    task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    screenshot_path TEXT,            -- full image file path on disk
    screenshot_thumb_path TEXT,      -- thumbnail file path on disk
    source          TEXT NOT NULL DEFAULT 'manual'
                    CHECK (source IN ('manual', 'auto')),
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_friction_log_status ON friction_log(status);
CREATE INDEX IF NOT EXISTS idx_friction_log_severity ON friction_log(severity);
CREATE INDEX IF NOT EXISTS idx_friction_log_created_at ON friction_log(created_at DESC);
```

- [ ] **Step 2: Restart orchestrator to run migration**

Run: `docker compose restart orchestrator && sleep 3 && docker compose logs orchestrator --tail 10 | grep -i migrat`
Expected: Log line showing migration 030 applied.

- [ ] **Step 3: Verify table exists**

Run: `docker compose exec postgres psql -U nova -d nova -c "\d friction_log"`
Expected: Table columns displayed.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/migrations/031_friction_log.sql
git commit -m "feat: migration 030 — friction_log table for dogfooding sprint"
```

---

## Task 2: Friction Router — CRUD Endpoints (TDD)

**Files:**
- Create: `tests/test_friction.py`
- Create: `orchestrator/app/friction_router.py`
- Modify: `orchestrator/app/main.py`

- [ ] **Step 1: Write integration tests (all will fail initially)**

```python
"""Integration tests for friction log CRUD endpoints."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

PREFIX = "nova-test-"


@pytest_asyncio.fixture
async def friction_entry(orchestrator: httpx.AsyncClient, admin_headers: dict):
    """Create a friction entry for tests, clean up after."""
    resp = await orchestrator.post(
        "/api/v1/friction",
        json={"description": f"{PREFIX}chat input resets on navigation", "severity": "blocker"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    entry = resp.json()
    yield entry
    # Cleanup
    await orchestrator.delete(f"/api/v1/friction/{entry['id']}", headers=admin_headers)


class TestFrictionCRUD:
    """Test friction log CRUD endpoints."""

    async def test_create_entry(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.post(
            "/api/v1/friction",
            json={"description": f"{PREFIX}pipeline timeout on large tasks", "severity": "annoyance"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["description"].startswith(PREFIX)
        assert data["severity"] == "annoyance"
        assert data["status"] == "open"
        assert data["source"] == "manual"
        assert data["id"]
        # Cleanup
        await orchestrator.delete(f"/api/v1/friction/{data['id']}", headers=admin_headers)

    async def test_create_entry_missing_description(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.post(
            "/api/v1/friction",
            json={"severity": "blocker"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_list_entries(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        ids = [e["id"] for e in data]
        assert friction_entry["id"] in ids

    async def test_list_filter_severity(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction?severity=blocker", headers=admin_headers)
        assert resp.status_code == 200
        for entry in resp.json():
            assert entry["severity"] == "blocker"

    async def test_list_filter_status(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction?status=open", headers=admin_headers)
        assert resp.status_code == 200
        for entry in resp.json():
            assert entry["status"] == "open"

    async def test_get_entry(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get(f"/api/v1/friction/{friction_entry['id']}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == friction_entry["id"]

    async def test_get_entry_not_found(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.get("/api/v1/friction/00000000-0000-0000-0000-000000000000", headers=admin_headers)
        assert resp.status_code == 404

    async def test_update_status(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.patch(
            f"/api/v1/friction/{friction_entry['id']}",
            json={"status": "fixed"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "fixed"

    async def test_update_invalid_status(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.patch(
            f"/api/v1/friction/{friction_entry['id']}",
            json={"status": "nonexistent"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_delete_entry(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        # Create one to delete
        create_resp = await orchestrator.post(
            "/api/v1/friction",
            json={"description": f"{PREFIX}delete-me", "severity": "idea"},
            headers=admin_headers,
        )
        entry_id = create_resp.json()["id"]
        resp = await orchestrator.delete(f"/api/v1/friction/{entry_id}", headers=admin_headers)
        assert resp.status_code == 204
        # Verify gone
        get_resp = await orchestrator.get(f"/api/v1/friction/{entry_id}", headers=admin_headers)
        assert get_resp.status_code == 404

    async def test_stats(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "open_count" in data
        assert "total_count" in data


class TestFrictionFixThis:
    """Test the 'Fix This' action that creates a pipeline task."""

    async def test_fix_creates_task(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.post(
            f"/api/v1/friction/{friction_entry['id']}/fix",
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "task_id" in data
        # Verify friction entry now has task_id
        entry_resp = await orchestrator.get(f"/api/v1/friction/{friction_entry['id']}", headers=admin_headers)
        assert entry_resp.json()["task_id"] == data["task_id"]
        assert entry_resp.json()["status"] == "in_progress"

    async def test_fix_not_found(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.post(
            "/api/v1/friction/00000000-0000-0000-0000-000000000000/fix",
            headers=admin_headers,
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/jeremy/workspace/nova && python -m pytest tests/test_friction.py -v --tb=short 2>&1 | head -40`
Expected: All tests FAIL (404 — endpoints don't exist yet).

- [ ] **Step 3: Create friction_router.py**

Create `orchestrator/app/friction_router.py` with all CRUD endpoints, stats, and "Fix This" action. Endpoints:
- `POST /api/v1/friction` — create entry
- `GET /api/v1/friction` — list with optional `severity`, `status`, `limit`, `offset` query params
- `GET /api/v1/friction/stats` — aggregate counts
- `GET /api/v1/friction/{entry_id}` — get single entry
- `PATCH /api/v1/friction/{entry_id}` — update status/severity
- `DELETE /api/v1/friction/{entry_id}` — delete entry
- `POST /api/v1/friction/{entry_id}/fix` — create pipeline task, update entry

Follow patterns from `auth_router.py`: Pydantic request/response models, `AdminDep` auth, `get_pool()` for DB, structured logging.

Key implementation details:
- "Fix This" internally calls `enqueue_task()` from `app.queue` with `metadata={"source": "friction_log", "friction_id": str(entry_id)}`
- Stats endpoint returns: `open_count`, `in_progress_count`, `fixed_count`, `total_count`, `blocker_count`
- List endpoint supports filtering by `severity`, `status`, and `source` query params
- List endpoint returns entries WITHOUT screenshot data (only `has_screenshot: bool`)
- GET single entry returns full `screenshot_path` (client fetches file separately)

- [ ] **Step 4: Mount router in main.py**

In `orchestrator/app/main.py`, add after the existing router imports:
```python
from app.friction_router import router as friction_router
```
And in the router mounting section:
```python
app.include_router(friction_router)
```

- [ ] **Step 5: Rebuild and run tests**

Run: `docker compose up --build orchestrator -d && sleep 5 && python -m pytest tests/test_friction.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_friction.py orchestrator/app/friction_router.py orchestrator/app/main.py
git commit -m "feat: friction log CRUD endpoints with integration tests"
```

---

## Task 3: Auto-Friction on Pipeline Failure

**Files:**
- Modify: `orchestrator/app/pipeline/executor.py`
- Modify: `tests/test_friction.py`

- [ ] **Step 1: Write test for auto-friction**

Add to `tests/test_friction.py`:

```python
class TestAutoFriction:
    """Test auto-friction creation on pipeline failure."""

    async def test_failed_task_creates_friction_entry(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Submit a task that will fail (no LLM configured), verify friction entry created."""
        # Submit a task to a pod that doesn't exist (will fail fast)
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": f"{PREFIX}auto-friction-test", "pod_id": "00000000-0000-0000-0000-000000000000"},
            headers=admin_headers,
        )
        if resp.status_code not in (200, 201, 202):
            pytest.skip(f"Could not submit task: {resp.status_code}")
        task_id = resp.json()["id"]

        # Wait briefly for pipeline to fail
        import asyncio
        await asyncio.sleep(3)

        # Check friction log for an auto-created entry referencing this task
        friction_resp = await orchestrator.get("/api/v1/friction?source=auto", headers=admin_headers)
        entries = friction_resp.json() if friction_resp.status_code == 200 else []
        auto_entries = [e for e in entries if e.get("metadata", {}).get("failed_task_id") == task_id]
        assert len(auto_entries) >= 1, f"Expected auto-friction entry for task {task_id}"
        assert auto_entries[0]["severity"] == "blocker"
        assert auto_entries[0]["source"] == "auto"

        # Cleanup
        for e in auto_entries:
            await orchestrator.delete(f"/api/v1/friction/{e['id']}", headers=admin_headers)

    async def test_friction_log_task_does_not_auto_create(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Tasks created from 'Fix This' (source=friction_log) should NOT auto-create friction entries."""
        # Create a friction entry
        create_resp = await orchestrator.post(
            "/api/v1/friction",
            json={"description": f"{PREFIX}loop-guard-test", "severity": "blocker"},
            headers=admin_headers,
        )
        entry = create_resp.json()

        # Use "Fix This" to create a task
        fix_resp = await orchestrator.post(f"/api/v1/friction/{entry['id']}/fix", headers=admin_headers)
        if fix_resp.status_code != 201:
            await orchestrator.delete(f"/api/v1/friction/{entry['id']}", headers=admin_headers)
            pytest.skip(f"Fix This failed: {fix_resp.status_code}")

        task_id = fix_resp.json()["task_id"]
        import asyncio
        await asyncio.sleep(3)

        # Verify NO auto-friction entry was created for this task
        friction_resp = await orchestrator.get("/api/v1/friction", headers=admin_headers)
        entries = friction_resp.json() if friction_resp.status_code == 200 else []
        auto_for_fix = [e for e in entries
                        if e.get("source") == "auto"
                        and e.get("metadata", {}).get("failed_task_id") == task_id]
        assert len(auto_for_fix) == 0, "Loop guard failed: auto-friction created for Fix-This task"

        # Cleanup
        await orchestrator.delete(f"/api/v1/friction/{entry['id']}", headers=admin_headers)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_friction.py::TestAutoFriction -v --tb=short`
Expected: FAIL — auto-friction hook doesn't exist yet.

- [ ] **Step 3: Add auto-friction hook to executor.py**

In `orchestrator/app/pipeline/executor.py`, inside `mark_task_failed()` after the existing `_publish_notification` call (~line 159), add:

```python
    # Auto-create friction log entry for pipeline failures (non-blocking)
    try:
        # Loop guard: skip tasks created from "Fix This" to prevent friction→task→friction chains
        task_meta = {}
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT metadata FROM tasks WHERE id = $1", task_id)
            if row:
                task_meta = row["metadata"] or {}
        if task_meta.get("source") != "friction_log":
            import json as _json
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO friction_log (description, severity, source, metadata)
                    VALUES ($1, 'blocker', 'auto', $2)
                    """,
                    f"Pipeline task failed: {error[:200]}",
                    _json.dumps({"failed_task_id": task_id, "error": error[:500]}),
                )
    except Exception:
        logger.warning(f"Auto-friction creation failed for task {task_id} (non-critical)")
```

Note: executor.py uses `import json as _json` locally, NOT at module level. Either add `import json` at the top of `mark_task_failed`, or use `_json` alias pattern consistent with the rest of the file. The snippet below uses a local import.

- [ ] **Step 4: Rebuild and run tests**

Run: `docker compose up --build orchestrator -d && sleep 5 && python -m pytest tests/test_friction.py::TestAutoFriction -v`
Expected: Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/pipeline/executor.py tests/test_friction.py
git commit -m "feat: auto-friction on pipeline failure with loop guard"
```

---

## Task 4: Extend Pipeline Stats

**Files:**
- Modify: `orchestrator/app/pipeline_router.py`

- [ ] **Step 1: Add `failed_this_week` and `submitted_today` to the existing stats query**

In `orchestrator/app/pipeline_router.py`, find the `pipeline_stats` function (~line 1057). Add two more FILTER clauses to the query:

```sql
COUNT(*) FILTER (WHERE status = 'failed' AND completed_at >= NOW() - INTERVAL '7 days') AS failed_this_week,
COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS submitted_today
```

And add them to the response dict:
```python
"failed_this_week": counts["failed_this_week"],
"submitted_today": counts["submitted_today"],
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python -m pytest tests/test_orchestrator.py -v --tb=short -k stats`
Expected: PASS (no regressions).

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/pipeline_router.py
git commit -m "feat: extend pipeline stats with failed_this_week and submitted_today"
```

---

## Task 5: Dashboard — API + Types

**Files:**
- Modify: `dashboard/src/api.ts`
- Modify: `dashboard/src/types.ts`

- [ ] **Step 1: Add FrictionEntry type to types.ts**

```typescript
export interface FrictionEntry {
  id: string
  description: string
  severity: 'blocker' | 'annoyance' | 'idea'
  status: 'open' | 'in_progress' | 'fixed'
  source: 'manual' | 'auto'
  task_id: string | null
  user_id: string | null
  screenshot_path: string | null
  screenshot_thumb_path: string | null
  has_screenshot: boolean
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface FrictionStats {
  open_count: number
  in_progress_count: number
  fixed_count: number
  total_count: number
  blocker_count: number
}
```

- [ ] **Step 2: Add friction API functions to api.ts**

```typescript
// ── Friction Log ──────────────────────────────────────────────────────
export const getFrictionEntries = (params?: { severity?: string; status?: string; limit?: number; offset?: number }) => {
  const query = new URLSearchParams()
  if (params?.severity) query.set('severity', params.severity)
  if (params?.status) query.set('status', params.status)
  if (params?.limit) query.set('limit', String(params.limit))
  if (params?.offset) query.set('offset', String(params.offset))
  const qs = query.toString()
  return apiFetch<FrictionEntry[]>(`/api/v1/friction${qs ? `?${qs}` : ''}`)
}

export const getFrictionEntry = (id: string) =>
  apiFetch<FrictionEntry>(`/api/v1/friction/${id}`)

export const createFrictionEntry = (data: { description: string; severity: string; screenshot?: string; screenshot_thumb?: string }) =>
  apiFetch<FrictionEntry>('/api/v1/friction', { method: 'POST', body: JSON.stringify(data) })

export const updateFrictionEntry = (id: string, data: { status?: string; severity?: string }) =>
  apiFetch<FrictionEntry>(`/api/v1/friction/${id}`, { method: 'PATCH', body: JSON.stringify(data) })

export const deleteFrictionEntry = (id: string) =>
  apiFetch<void>(`/api/v1/friction/${id}`, { method: 'DELETE' })

export const fixFrictionEntry = (id: string) =>
  apiFetch<{ task_id: string }>(`/api/v1/friction/${id}/fix`, { method: 'POST' })

export const getFrictionStats = () =>
  apiFetch<FrictionStats>('/api/v1/friction/stats')
```

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/api.ts dashboard/src/types.ts
git commit -m "feat(dashboard): friction log API functions and types"
```

---

## Task 6: Friction Page — Sprint Health + Entry List

**Files:**
- Create: `dashboard/src/pages/Friction.tsx`

- [ ] **Step 1: Create the Friction page component**

Build `Friction.tsx` with:
- `PageHeader` with title "Friction Log" and inline "Log Friction" button
- Sprint Health section: 4x `Metric` in `grid-cols-2 md:grid-cols-4`:
  - **Success Rate** — `getPipelineStats().completed_this_week / (completed_this_week + failed_this_week)` as percentage
  - **Submitted Today** — `getPipelineStats().submitted_today`
  - **Failed Today** — `getPipelineStats().failed_today`
  - **Open Friction** — `getFrictionStats().open_count`
- Filter bar: `Select` for severity (all/blocker/annoyance/idea) + `Select` for status (all/open/in_progress/fixed)
- Entry list: `Card` per entry with `StatusDot`, severity `Badge`, source `Badge` ("auto" if auto), description, timestamp (`formatDistanceToNow`), thumbnail if has_screenshot, action buttons
- Actions per entry: "Fix This" `Button` (disabled if task_id set or status=fixed), "Mark Fixed" `Button` (disabled if fixed), "Delete" with `ConfirmDialog`
- `EmptyState` with `ClipboardX` icon when no entries
- `Skeleton` loading states for metrics and cards
- TanStack Query: `useQuery` for entries + stats, `useMutation` for fix/update/delete with `queryClient.invalidateQueries`

Use existing page patterns from Tasks.tsx: same import style, same query patterns, same component composition.

- [ ] **Step 2: Verify build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/Friction.tsx
git commit -m "feat(dashboard): Friction page with Sprint Health header and entry list"
```

---

## Task 7: Log Friction Sheet

**Files:**
- Create: `dashboard/src/components/LogFrictionSheet.tsx`

- [ ] **Step 1: Create the Log Friction Sheet component**

Build `LogFrictionSheet.tsx` with:
- `Sheet` component (right drawer) — follows existing `Sheet` usage patterns
- Form: `Textarea` (4 rows, auto-focused on open, placeholder "What went wrong?")
- `RadioGroup` for severity: blocker (default), annoyance, idea
- Screenshot drop zone: `div` with `border-dashed`, accepts paste (Ctrl+V) and drag-drop
  - On paste/drop: validate MIME type (image/*), validate size (<5MB), resize to thumbnail (~50KB JPEG via Canvas API), show preview
  - Preview: `rounded-md` image with `x` remove button
- Submit `Button` (disabled during mutation, shows Loader2 spinner)
- Cancel `Button` (closes sheet)
- `useMutation` with `createFrictionEntry`, invalidates friction queries on success
- Success: `Toast` "Friction logged" + close sheet
- Error: `Toast` "Failed to save. Try again."
- Props: `open: boolean`, `onOpenChange: (open: boolean) => void`

Screenshot resize utility (inline or small helper):
```typescript
function resizeImage(file: File, maxWidth = 200): Promise<{ full: string; thumb: string }> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        // Thumbnail
        const canvas = document.createElement('canvas')
        const scale = Math.min(maxWidth / img.width, maxWidth / img.height, 1)
        canvas.width = img.width * scale
        canvas.height = img.height * scale
        canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
        resolve({
          full: reader.result as string,
          thumb: canvas.toDataURL('image/jpeg', 0.7),
        })
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  })
}
```

- [ ] **Step 2: Verify build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/LogFrictionSheet.tsx
git commit -m "feat(dashboard): Log Friction sheet with screenshot paste/drop"
```

---

## Task 8: Floating Button + Navigation + Route

**Files:**
- Create: `dashboard/src/components/LogFrictionButton.tsx`
- Modify: `dashboard/src/components/layout/AppLayout.tsx`
- Modify: `dashboard/src/components/layout/Sidebar.tsx`
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Create LogFrictionButton component**

```typescript
// Floating "Log Friction" button — rendered globally in AppLayout.
// Fixed bottom-right, opens the LogFrictionSheet.
import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from './ui'
import { LogFrictionSheet } from './LogFrictionSheet'

export function LogFrictionButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        variant="accent"
        className="fixed bottom-6 right-6 z-40 shadow-lg"
        onClick={() => setOpen(true)}
        aria-label="Log friction"
      >
        <AlertTriangle className="h-4 w-4" />
        <span className="hidden md:inline ml-2">Log Friction</span>
      </Button>
      <LogFrictionSheet open={open} onOpenChange={setOpen} />
    </>
  )
}
```

- [ ] **Step 2: Add to AppLayout**

In `dashboard/src/components/layout/AppLayout.tsx`, import and render `LogFrictionButton` inside the layout (after the main content area, so it floats above):
```typescript
import { LogFrictionButton } from '../LogFrictionButton'
// ... inside the return, after {children}:
<LogFrictionButton />
```

- [ ] **Step 3: Add Friction to Sidebar nav**

In `dashboard/src/components/layout/Sidebar.tsx`, add to the Core section items (after Tasks):
```typescript
import { AlertTriangle } from 'lucide-react'  // add to imports

// In navSections[0].items, after the Tasks entry:
{ to: '/friction', label: 'Friction', icon: AlertTriangle, minRole: 'member' },
```

- [ ] **Step 4: Add route in App.tsx**

```typescript
import Friction from './pages/Friction'  // add to imports

// Add route after /tasks:
<Route path="/friction" element={<AppLayout><Friction /></AppLayout>} />
```

- [ ] **Step 5: Verify build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/LogFrictionButton.tsx dashboard/src/components/layout/AppLayout.tsx dashboard/src/components/layout/Sidebar.tsx dashboard/src/App.tsx
git commit -m "feat(dashboard): floating Log Friction button, nav entry, /friction route"
```

---

## Task 9: Screenshot File Storage

**Files:**
- Modify: `orchestrator/app/friction_router.py`

- [ ] **Step 1: Add screenshot file handling to the create endpoint**

In `friction_router.py`, when creating an entry with screenshot data (base64 in the request body):
1. Create upload directory: `/workspace/.nova/uploads/friction/` (create on first use)
2. Decode base64, write full image to `{entry_id}_full.{ext}`
3. Write thumbnail to `{entry_id}_thumb.jpg`
4. Store file paths in DB columns `screenshot_path` and `screenshot_thumb_path`
5. On delete: remove both files (try/except, log warning on failure)

Add a GET endpoint for serving screenshots:
```python
@router.get("/api/v1/friction/{entry_id}/screenshot")
async def get_friction_screenshot(entry_id: str, thumb: bool = False, _admin: AdminDep = None):
    """Serve a friction entry's screenshot file."""
    # ... fetch path from DB, serve with FileResponse
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python -m pytest tests/test_friction.py -v`
Expected: All PASS (screenshots are optional — existing tests don't send them).

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/friction_router.py
git commit -m "feat: screenshot file storage for friction entries"
```

---

## Task 10: Create TODOS.md

**Files:**
- Create: `TODOS.md`

- [ ] **Step 1: Create TODOS.md with deferred items from reviews**

```markdown
# TODOS

Deferred work tracked from plan reviews and implementation.

---

### Friction Log -> GitHub Issue Export
**Priority:** P3 | **Effort:** S | **Depends on:** friction log feature

One-click to create a GitHub issue from a friction entry. Pre-populates title, description, severity label. Requires GITHUB_TOKEN in .env. Bridges internal tracking to external visibility.

**Context:** Deferred from CEO review (2026-03-19). Friction log IS the issue tracker during the dogfooding sprint. This becomes valuable when preparing for external users or open-source.

---

### Screenshot File Cleanup Tooling
**Priority:** P3 | **Effort:** S | **Depends on:** friction log with file storage

Orphan detection + disk usage monitoring for friction screenshot files. Files can become orphaned after DB restores or manual deletes.

**Context:** Deferred from eng review (2026-03-19). Trivial volume during the dogfooding sprint. Only matters at scale or after DB restore operations.
```

- [ ] **Step 2: Commit**

```bash
git add TODOS.md
git commit -m "docs: create TODOS.md with deferred friction log items"
```

---

## Task 11: End-to-End Verification

- [ ] **Step 1: Run full integration test suite**

Run: `python -m pytest tests/test_friction.py -v`
Expected: All tests PASS.

- [ ] **Step 2: Verify dashboard builds**

Run: `cd dashboard && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 3: Manual smoke test**

1. Open dashboard at http://localhost:5173
2. Verify "Friction" appears in sidebar nav (Core section, after Tasks)
3. Click it — see empty state with "No friction yet" message
4. Click floating "Log Friction" button (bottom-right)
5. Fill form: description, severity=blocker, paste screenshot
6. Submit — verify toast + entry appears in list
7. Verify Sprint Health shows metrics
8. Click "Fix This" — verify task created (check Tasks page)
9. Submit a pipeline task that fails — verify auto-friction entry appears
10. Click "Mark Fixed" — verify status badge changes to green

- [ ] **Step 4: Final commit if any fixups needed**

Stage only the files changed during fixups (never `git add -A` — pre-existing unstaged changes exist):
```bash
git add <specific-files-changed> && git commit -m "fix: friction log smoke test fixups"
```
