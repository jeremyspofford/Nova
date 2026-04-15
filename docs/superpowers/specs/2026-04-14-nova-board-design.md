# Nova Board — Phase 1 Design Spec

**Date:** 2026-04-14
**Phase:** 1
**Status:** Approved for implementation

---

## Overview

Nova Board is the human control surface for Nova Suite. It is an 8-column Kanban board where the operator can view tasks created by Nova-lite, approve or deny agent actions, monitor tool runs, and filter the task backlog by status, risk, and labels. It polls the Nova API every 5 seconds and is designed so that the polling transport can be replaced with WebSocket in a future phase without changing any components.

---

## Scope

### New service

- `services/board/` — React 18 + Vite 5 frontend, served by nginx in production

### API completions (services/api)

Four currently-stubbed endpoints are promoted to full implementations:

| Endpoint | Description |
| --- | --- |
| `GET /board` | Return 8 board columns and tasks grouped by column |
| `PATCH /board/tasks/{id}` | Move a task to a different board column |
| `GET /approvals/{id}` | Fetch a single approval request |
| `POST /approvals/{id}/respond` | Submit an approve/deny decision |

### Startup seeding

`services/api/app/tools/seed.py` gains a `seed_board_columns()` function that upserts the 8 canonical columns on every API startup.

---

## Tech Stack

| Concern | Choice | Reason |
|---|---|---|
| Framework | React 18 + Vite 5 | Component ecosystem, fast HMR, standard tooling |
| Server state | TanStack Query v5 | Built-in polling, caching, background refetch, error states |
| UI state | Zustand | Minimal boilerplate, no re-render on unrelated state changes |
| Styling | Plain CSS with `prefers-color-scheme` | No build-time dependency, two theme palettes |
| Testing | Vitest + React Testing Library | Co-located with Vite, fast, no Jest config overhead |
| Container | nginx:alpine (multi-stage build) | Minimal image, serves static files |

---

## Visual Design

Two palettes, selected automatically by `prefers-color-scheme`:

**Light mode — Light/Clean palette**
White cards, soft `box-shadow`, `#f8fafc` board background, `#1e293b` text, blue/amber/red accent chips, system-UI font stack.

**Dark mode — Dark/GitHub-style palette**
`#0d1117` background, `#161b22` cards, `#30363d` borders, `#e6edf3` text, `#58a6ff` blue accents, `#d29922` amber, `#ff7b72` red.

Status, priority, and risk are always communicated with both color and text — never color alone.

---

## Service Architecture

### Production

```txt
browser → board container (nginx:80, host:5173) → static files
browser → api container (:8000) → FastAPI
```

No reverse proxy required for local use. The browser talks directly to both services.

### Development

```txt
npm run dev → Vite dev server (:5173)
Vite proxy: /api/* → http://localhost:8000
```

Run `docker compose up db api` + `npm run dev` in `services/board/`. No CORS configuration needed.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_URL` | `""` (empty) | API base URL. Empty = same-origin. Set to `http://localhost:8000` in dev. |

---

## File Structure

```txt
services/board/
  Dockerfile
  nginx.conf
  index.html
  vite.config.ts
  package.json
  src/
    main.tsx                   — QueryClientProvider, App mount
    App.tsx                    — Board + TaskDetail layout root
    api/
      client.ts                — fetch wrapper (prepends VITE_API_URL, throws on non-2xx)
      board.ts                 — getBoard(filters?), moveTask(taskId, columnId)
      tasks.ts                 — getTasks(filters): TaskListResponse; getTask(id): TaskResponse;
                                  getRuns(taskId): { runs: Run[] }; patchTask(id, patch): TaskResponse
      approvals.ts             — getApproval(id): ApprovalRead; respondToApproval(id, decision, decidedBy, reason?): ApprovalRead
    stores/
      uiStore.ts               — Zustand: selectedTaskId, openModal, activeFilters
    hooks/
      useBoard.ts              — thin wrapper: useQuery(['board'], getBoard, { refetchInterval: 5000 })
      useTask.ts               — useQuery(['task', id], getTask) + useQuery(['runs', id])
      useApproval.ts           — useQuery(['approval', approvalId]) when task has pending approval
    components/
      Board/
        Board.tsx              — renders 8 Column components from useBoard data
        Column.tsx             — column header, WIP limit pill, TaskCard list
        TaskCard.tsx           — title, status/priority/risk badges, approval warning indicator
      TaskDetail/
        TaskDetail.tsx         — slide-out panel; always mounted, visible when selectedTaskId set
        RunList.tsx            — chronological run list: tool_name, status, timestamps
        ApprovalBanner.tsx     — summary, consequence, options buttons, inline error + retry
      shared/
        Badge.tsx              — reusable status/priority/risk/label chip
        FilterBar.tsx          — filter controls bound to uiStore.activeFilters
        Toast.tsx              — non-blocking error notification
    styles/
      tokens.css               — CSS custom properties for both themes (prefers-color-scheme)
      global.css               — reset, base typography, board layout
```

---

## Data Flow

### Board render cycle

1. `useBoard` fires `GET /board` on mount and every 5 000 ms
2. Response: `{ columns: BoardColumn[], tasks_by_column: { [columnId]: Task[] } }`
3. `Board.tsx` maps columns → `Column.tsx` → `TaskCard.tsx` per task
4. FilterBar state in Zustand is passed as query params to `getBoard()` (status, risk_class, labels, priority)
5. Changing a filter invalidates the board query → immediate refetch

### Task detail

1. Click TaskCard → `uiStore.setSelectedTask(id)`
2. `TaskDetail.tsx` becomes visible (CSS `transform` / `opacity`, not mount/unmount)
3. `useTask(id)` fetches `GET /tasks/{id}` and `GET /tasks/{id}/runs` (returns `{ runs: Run[] }` with `id`, `tool_name`, `status`, `started_at`, `finished_at`, `error` fields)
4. If `task.approval_required && task.status === 'needs_approval'`: `useApproval` fetches the pending approval
5. `ApprovalBanner` renders with summary, consequence, and option buttons

### Approval flow

1. User clicks Approve or Deny in `ApprovalBanner`
2. Optimistic: Zustand sets a `pendingDecision` flag, buttons disabled
3. `POST /approvals/{id}/respond` fires with `{ decision, decided_by: "user" }`
4. On success: invalidate `['board']` and `['task', id]` queries
5. On failure: clear `pendingDecision`, show inline error in banner with retry button

### Task column move

1. User drags or uses a "Move to…" menu on a TaskCard
2. Optimistic: update `tasks_by_column` in query cache immediately
3. `PATCH /board/tasks/{id}` fires with `{ board_column_id }`
4. On success: board query refetches in background (already up to date)
5. On failure: roll back query cache to previous state, show toast

---

## API Implementation Details

### GET /board

Returns columns in `order` ascending. Each column includes tasks whose `board_column_id` matches. Tasks without a `board_column_id` appear in the Inbox column (order = 1).

Response shape:

```json
{
  "columns": [
    {
      "id": "...",
      "name": "Inbox",
      "order": 1,
      "work_in_progress_limit": null,
      "status_filter": null,
      "description": null
    }
  ],
  "tasks_by_column": {
    "<column_id>": [ /* Task objects */ ]
  }
}
```

Supports the same query filters as `GET /tasks`: `status`, `risk_class`, `labels`, `priority`.

### PATCH /board/tasks/{id}

Accepts `{ "board_column_id": "<id>" }`. Updates `task.board_column_id`. Returns the updated `TaskResponse`. 404 if task or column not found.

This endpoint exists for semantic clarity as a dedicated "move" action. It does not replace `PATCH /tasks/{id}`, which remains the general-purpose task update endpoint. Both can update `board_column_id`; the board UI uses this endpoint for drag/move operations.

### GET /approvals/{id}

Returns the full `ApprovalRead` schema. 404 if not found.

### POST /approvals/{id}/respond

Accepts `{ "decision": "approve"|"deny"|<custom>, "decided_by": string, "reason": string|null }`.

- Sets `approval.status` to `"approved"` or `"denied"` — always one of these two enum values regardless of the custom option string chosen. The raw custom string is stored in `approval.decision` only. (Full status enum: `pending | approved | denied | cancelled`; `cancelled` is set by task cancellation, not this endpoint — the 409 guard fires on any non-`pending` status including `cancelled`.)
- Sets `approval.decided_by`, `approval.decided_at`, `approval.decision`, `approval.reason`
- Updates `task.status`: approve → `"ready"`, deny → `"cancelled"`
- Returns updated `ApprovalRead`
- 409 if approval is not in `pending` status
- 404 if approval not found

### Board column seeding

`seed_board_columns(db)` upserts 8 columns on startup:

| Order | Name | Description |
|---|---|---|
| 1 | Inbox | New tasks not yet triaged |
| 2 | Ready | Approved and ready to execute |
| 3 | Running | Currently executing |
| 4 | Waiting | Paused, waiting on external signal |
| 5 | Needs Approval | Requires human decision before proceeding |
| 6 | Done | Completed successfully |
| 7 | Failed | Terminated with error |
| 8 | Cancelled | Denied or explicitly cancelled |

Called from `main.py` lifespan alongside existing `seed_tools` and `seed_llm_providers`.

---

## Docker + Build

### Dockerfile (multi-stage)

- Note: VITE_API_URL is a *build arg*, not runtime env. Dev uses `npm run dev` + Vite proxy

- Prod assumes same-origin (nginx → api via docker network) or reverse proxy

```txt
Stage 1 (build): node:20-alpine — npm ci, npm run build → /app/dist
Stage 2 (serve): nginx:alpine — copy dist, copy nginx.conf
```

### nginx.conf

- Serves static files from `/usr/share/nginx/html`
- `try_files $uri $uri/ /index.html` for client-side routing
- Listens on port 80 (mapped to host 5173 in docker-compose)

### docker-compose.yml additions

```yaml
board:
  build:
    context: ../services/board
    args:
      VITE_API_URL: ""   # empty = same-origin; override for non-localhost API
  ports:
    - "5173:80"
```

`VITE_API_URL` is a build-time variable (Vite inlines it at `npm run build`). It must be passed as a Docker build arg (`ARG VITE_API_URL` in the Dockerfile), not as a runtime environment variable — nginx does not read it. For local development, run `npm run dev` instead of the container; Vite's dev proxy handles API routing transparently.

---

## Testing

### Frontend (Vitest + React Testing Library)

- Mock `api/client.ts` at module boundary — no network calls in tests
- **TaskCard:** renders title, correct badge for each status/priority/risk value, approval warning indicator when `approval_required` is true
- **ApprovalBanner:** calls `respondToApproval` with correct args on button click, shows retry on error, disables buttons while pending
- **FilterBar:** updating a filter calls `uiStore` correctly
- **useBoard:** polling interval fires refetch, query key includes active filters

### API (pytest)

New test files:

- `test_board.py` — GET /board returns columns and grouped tasks; PATCH /board/tasks/{id} updates column; 404 on unknown task/column; tasks without board_column_id appear in Inbox column
- `test_approvals_respond.py` — POST /approvals/{id}/respond sets decision fields, updates task status; 409 on non-pending approval; 404 on unknown approval

---

## Success Criteria

- `docker compose up` starts all three services (db, api, board) cleanly
- Board shows 8 columns with tasks populated from seeded data
- Clicking a task opens the detail panel; clicking outside closes it
- Tasks in `needs_approval` status show the ApprovalBanner with working Approve/Deny
- Approving a task moves it to Ready column within one poll cycle (≤5s)
- Denying a task moves it to the Cancelled column (order 8)
- FilterBar filters update the board without page reload
- Both light and dark mode render correctly
- All Vitest and pytest tests pass
