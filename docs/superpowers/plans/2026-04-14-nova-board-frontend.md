# Nova Board: Frontend Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `services/board/` React+Vite frontend that renders the 8-column Nova Board, shows task detail with run history, and lets operators approve or deny pending agent actions — all polling the Nova API every 5 seconds.

**Architecture:** Static SPA served by nginx in production (multi-stage Docker build). In dev, `npm run dev` starts a Vite dev server with a proxy that forwards API calls to localhost:8000 — no CORS config needed. TanStack Query owns all server state and polling. Zustand holds UI-only state (selected task, toast message, active filters). The API layer is a thin typed wrapper over `fetch` with a single `apiFetch` helper. All components are tested with Vitest + React Testing Library, mocking `api/client.ts` at the module boundary.

**Tech Stack:** React 18, TypeScript, Vite 5, TanStack Query v5, Zustand v4, Vitest, React Testing Library, nginx:alpine

**Prerequisite:** The nova-board-api plan is complete and all API tests pass. Run `cd services/api && python3 -m pytest tests/ -v` to verify.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `services/api/app/routers/approvals.py` | Modify | Add `GET /tasks/{task_id}/approvals` endpoint |
| `services/api/tests/test_approvals_respond.py` | Modify | Add test for new endpoint |
| `services/board/package.json` | Create | Dependencies and scripts |
| `services/board/tsconfig.json` | Create | TypeScript config |
| `services/board/vite.config.ts` | Create | Vite + Vitest config with dev proxy |
| `services/board/index.html` | Create | HTML entry point |
| `services/board/.env.development` | Create | VITE_API_URL="" (proxy handles routing) |
| `services/board/src/test/setup.ts` | Create | jest-dom matchers setup |
| `services/board/src/api/types.ts` | Create | Shared TypeScript types matching API schemas |
| `services/board/src/api/client.ts` | Create | fetch wrapper: prepends VITE_API_URL, throws on non-2xx |
| `services/board/src/api/board.ts` | Create | getBoard(filters?), moveTask(taskId, columnId) |
| `services/board/src/api/tasks.ts` | Create | getTasks, getTask, getRuns, patchTask |
| `services/board/src/api/approvals.ts` | Create | getApproval, getTaskApprovals, respondToApproval |
| `services/board/src/stores/uiStore.ts` | Create | Zustand: selectedTaskId, toast, activeFilters |
| `services/board/src/hooks/useBoard.ts` | Create | useQuery(['board', filters], refetchInterval: 5000 |
| `services/board/src/hooks/useTask.ts` | Create | task + runs + pendingApprovalId queries |
| `services/board/src/hooks/useApproval.ts` | Create | useQuery(['approval', approvalId]) |
| `services/board/src/styles/tokens.css` | Create | CSS custom properties for light + dark themes |
| `services/board/src/styles/global.css` | Create | Reset, base typography, board layout |
| `services/board/src/components/shared/Badge.tsx` | Create | Status/priority/risk/label chip |
| `services/board/src/components/shared/Toast.tsx` | Create | Non-blocking error notification |
| `services/board/src/components/shared/FilterBar.tsx` | Create | Filter controls bound to uiStore.activeFilters |
| `services/board/src/components/Board/TaskCard.tsx` | Create | Title, badges, approval warning indicator |
| `services/board/src/components/Board/Column.tsx` | Create | Column header, WIP pill, TaskCard list |
| `services/board/src/components/Board/Board.tsx` | Create | Maps 8 Column components from useBoard data |
| `services/board/src/components/TaskDetail/RunList.tsx` | Create | Chronological run list: tool_name, status, timestamps |
| `services/board/src/components/TaskDetail/ApprovalBanner.tsx` | Create | Summary, consequence, option buttons, error + retry |
| `services/board/src/components/TaskDetail/TaskDetail.tsx` | Create | Slide-out panel; always mounted, CSS-toggled visibility |
| `services/board/src/App.tsx` | Create | Board + TaskDetail layout root, QueryClient, style imports |
| `services/board/src/main.tsx` | Create | React root mount |
| `services/board/Dockerfile` | Create | Multi-stage: node:20-alpine build → nginx:alpine serve |
| `services/board/nginx.conf` | Create | Static files + try_files for SPA routing |
| `infra/docker-compose.yml` | Modify | Add `board` service |

---

### Task 1: API extension — GET /tasks/{task_id}/approvals

The frontend's `useTask` hook needs a way to find the pending approval ID for a task in `needs_approval` status. `TaskResponse` does not include it, so we add a simple list endpoint.

**Files:**
- Modify: `services/api/app/routers/approvals.py`
- Modify: `services/api/tests/test_approvals_respond.py`

- [ ] **Step 1: Write failing test**

Add to `services/api/tests/test_approvals_respond.py`:

```python
def test_get_task_approvals_returns_list(client):
    task, approval = _create_task_with_approval(client)
    response = client.get(f"/tasks/{task['id']}/approvals")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == approval["id"]
    assert data[0]["status"] == "pending"


def test_get_task_approvals_empty_for_unknown_task(client):
    response = client.get("/tasks/nonexistent/approvals")
    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd services/api
python3 -m pytest tests/test_approvals_respond.py::test_get_task_approvals_returns_list -v
```

Expected: FAIL — 404 or 405 (route does not exist).

- [ ] **Step 3: Add endpoint to approvals router**

In `services/api/app/routers/approvals.py`, add this route before `get_approval`:

```python
@router.get("/tasks/{task_id}/approvals", response_model=list[ApprovalRead])
def list_task_approvals(task_id: str, db: Session = Depends(get_db)):
    approvals = db.query(Approval).filter(Approval.task_id == task_id).all()
    return [ApprovalRead.model_validate(a) for a in approvals]
```

Also add `Session` and `get_db` to the imports if they are not already present (they are added by the nova-board-api plan's Task 4 step).

- [ ] **Step 4: Run approval tests**

```bash
python3 -m pytest tests/test_approvals_respond.py -v
```

Expected: all pass including the 2 new tests.

- [ ] **Step 5: Run full API suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/routers/approvals.py services/api/tests/test_approvals_respond.py
git commit -m "feat: add GET /tasks/{task_id}/approvals list endpoint"
```

---

### Task 2: Project scaffold

**Files:**
- Create: `services/board/package.json`
- Create: `services/board/tsconfig.json`
- Create: `services/board/vite.config.ts`
- Create: `services/board/index.html`
- Create: `services/board/.env.development`
- Create: `services/board/src/test/setup.ts`

- [ ] **Step 1: Create package.json**

Create `services/board/package.json`:

```json
{
  "name": "nova-board",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.56.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^4.5.5"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.9",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^25.0.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.8",
    "vitest": "^2.1.1"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

Create `services/board/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create vite.config.ts**

Create `services/board/vite.config.ts`:

```ts
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/board": "http://localhost:8000",
      "/tasks": "http://localhost:8000",
      "/approvals": "http://localhost:8000",
      "/tools": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
})
```

- [ ] **Step 4: Create index.html**

Create `services/board/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Nova Board</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create .env.development**

Create `services/board/.env.development`:

```
VITE_API_URL=
```

(Empty string — the Vite dev proxy handles routing. No CORS config needed.)

- [ ] **Step 6: Create test setup file**

Create `services/board/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom"
```

- [ ] **Step 7: Install dependencies**

```bash
cd services/board
npm install
```

Expected: `node_modules/` created, no errors.

- [ ] **Step 8: Verify TypeScript compiles**

```bash
npx tsc --noEmit
```

Expected: no errors (only src/ contains nothing yet — that's fine at this stage; skip if tsc errors because src is empty).

- [ ] **Step 9: Commit scaffold**

```bash
git add services/board/package.json services/board/tsconfig.json services/board/vite.config.ts \
        services/board/index.html services/board/.env.development services/board/src/test/setup.ts \
        services/board/package-lock.json
git commit -m "feat: scaffold nova-board Vite+React+TS project"
```

---

### Task 3: Type definitions + API layer

**Files:**
- Create: `services/board/src/api/types.ts`
- Create: `services/board/src/api/client.ts`
- Create: `services/board/src/api/board.ts`
- Create: `services/board/src/api/tasks.ts`
- Create: `services/board/src/api/approvals.ts`

- [ ] **Step 1: Write failing tests for client.ts**

Create `services/board/src/api/__tests__/client.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest"
import { apiFetch } from "../client"

describe("apiFetch", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it("calls fetch with the correct URL", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
    await apiFetch("/board")
    expect(spy).toHaveBeenCalledWith("/board", undefined)
  })

  it("prepends VITE_API_URL when set", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000")
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 })
    )
    await apiFetch("/tasks")
    expect(spy).toHaveBeenCalledWith("http://localhost:8000/tasks", undefined)
    vi.unstubAllEnvs()
  })

  it("throws on non-2xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Not Found", { status: 404 })
    )
    await expect(apiFetch("/missing")).rejects.toThrow("404")
  })
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd services/board
npm test -- client
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create type definitions**

Create `services/board/src/api/types.ts`:

```ts
export interface BoardColumn {
  id: string
  name: string
  order: number
  work_in_progress_limit: number | null
  status_filter: Record<string, unknown> | null
  description: string | null
}

export interface Task {
  id: string
  title: string
  description: string | null
  goal: string | null
  status: string
  origin_event_id: string | null
  board_column_id: string | null
  owner_type: string | null
  owner_id: string | null
  created_at: string
  updated_at: string
  due_at: string | null
  priority: string
  risk_class: string
  approval_required: boolean
  last_decision: string
  next_check_at: string | null
  result_summary: string | null
  labels: string[]
  metadata: Record<string, unknown>
}

export interface TaskListResponse {
  tasks: Task[]
}

export interface BoardResponse {
  columns: BoardColumn[]
  tasks_by_column: Record<string, Task[]>
}

export interface Run {
  id: string
  tool_name: string
  status: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface ApprovalRead {
  id: string
  task_id: string
  requested_by: string
  requested_at: string
  summary: string
  consequence: string | null
  options: string[]
  status: string
  decided_by: string | null
  decided_at: string | null
  decision: string | null
  reason: string | null
}
```

- [ ] **Step 4: Create client.ts**

Create `services/board/src/api/client.ts`:

```ts
const BASE: string = import.meta.env.VITE_API_URL ?? ""

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}
```

- [ ] **Step 5: Run client tests**

```bash
npm test -- client
```

Expected: 3 passed.

- [ ] **Step 6: Write failing tests for board.ts, tasks.ts, approvals.ts**

Create `services/board/src/api/__tests__/board.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest"
import * as client from "../client"
import { getBoard, moveTask } from "../board"

vi.mock("../client")
const mockFetch = vi.mocked(client.apiFetch)

beforeEach(() => mockFetch.mockReset())

describe("getBoard", () => {
  it("calls GET /board with no filters", async () => {
    mockFetch.mockResolvedValue({ columns: [], tasks_by_column: {} })
    await getBoard()
    expect(mockFetch).toHaveBeenCalledWith("/board")
  })

  it("appends filter query params", async () => {
    mockFetch.mockResolvedValue({ columns: [], tasks_by_column: {} })
    await getBoard({ status: "running", labels: ["infra", "ci"] })
    const url = mockFetch.mock.calls[0][0] as string
    expect(url).toContain("status=running")
    expect(url).toContain("labels=infra")
    expect(url).toContain("labels=ci")
  })
})

describe("moveTask", () => {
  it("calls PATCH /board/tasks/{id} with correct body", async () => {
    mockFetch.mockResolvedValue({ id: "t1", board_column_id: "col-done" })
    await moveTask("t1", "col-done")
    expect(mockFetch).toHaveBeenCalledWith("/board/tasks/t1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board_column_id: "col-done" }),
    })
  })
})
```

Create `services/board/src/api/__tests__/tasks.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest"
import * as client from "../client"
import { getTask, getRuns, patchTask } from "../tasks"

vi.mock("../client")
const mockFetch = vi.mocked(client.apiFetch)

beforeEach(() => mockFetch.mockReset())

it("getTask calls GET /tasks/{id}", async () => {
  mockFetch.mockResolvedValue({ id: "t1", title: "test" })
  await getTask("t1")
  expect(mockFetch).toHaveBeenCalledWith("/tasks/t1")
})

it("getRuns calls GET /tasks/{id}/runs", async () => {
  mockFetch.mockResolvedValue({ runs: [] })
  await getRuns("t1")
  expect(mockFetch).toHaveBeenCalledWith("/tasks/t1/runs")
})

it("patchTask calls PATCH /tasks/{id} with body", async () => {
  mockFetch.mockResolvedValue({ id: "t1", status: "done" })
  await patchTask("t1", { status: "done" })
  expect(mockFetch).toHaveBeenCalledWith("/tasks/t1", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "done" }),
  })
})
```

Create `services/board/src/api/__tests__/approvals.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest"
import * as client from "../client"
import { getApproval, getTaskApprovals, respondToApproval } from "../approvals"

vi.mock("../client")
const mockFetch = vi.mocked(client.apiFetch)

beforeEach(() => mockFetch.mockReset())

it("getApproval calls GET /approvals/{id}", async () => {
  mockFetch.mockResolvedValue({ id: "a1", status: "pending" })
  await getApproval("a1")
  expect(mockFetch).toHaveBeenCalledWith("/approvals/a1")
})

it("getTaskApprovals calls GET /tasks/{id}/approvals", async () => {
  mockFetch.mockResolvedValue([])
  await getTaskApprovals("t1")
  expect(mockFetch).toHaveBeenCalledWith("/tasks/t1/approvals")
})

it("respondToApproval calls POST /approvals/{id}/respond with body", async () => {
  mockFetch.mockResolvedValue({ id: "a1", status: "approved" })
  await respondToApproval("a1", "approve", "user", "all good")
  expect(mockFetch).toHaveBeenCalledWith("/approvals/a1/respond", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: "approve", decided_by: "user", reason: "all good" }),
  })
})
```

- [ ] **Step 7: Run to verify they fail**

```bash
npm test -- board tasks approvals
```

Expected: FAIL — modules not found.

- [ ] **Step 8: Create board.ts**

Create `services/board/src/api/board.ts`:

```ts
import { apiFetch } from "./client"
import type { BoardResponse, Task } from "./types"

export interface BoardFilters {
  status?: string
  risk_class?: string
  priority?: string
  labels?: string[]
}

export function getBoard(filters?: BoardFilters): Promise<BoardResponse> {
  if (!filters || Object.keys(filters).every(k => !filters[k as keyof BoardFilters])) {
    return apiFetch<BoardResponse>("/board")
  }
  const params = new URLSearchParams()
  if (filters.status) params.set("status", filters.status)
  if (filters.risk_class) params.set("risk_class", filters.risk_class)
  if (filters.priority) params.set("priority", filters.priority)
  filters.labels?.forEach(l => params.append("labels", l))
  return apiFetch<BoardResponse>(`/board?${params.toString()}`)
}

export function moveTask(taskId: string, columnId: string): Promise<Task> {
  return apiFetch<Task>(`/board/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ board_column_id: columnId }),
  })
}
```

- [ ] **Step 9: Create tasks.ts**

Create `services/board/src/api/tasks.ts`:

```ts
import { apiFetch } from "./client"
import type { Task, TaskListResponse, Run } from "./types"

export function getTasks(filters?: Record<string, string>): Promise<TaskListResponse> {
  const qs = filters && Object.keys(filters).length
    ? `?${new URLSearchParams(filters).toString()}`
    : ""
  return apiFetch<TaskListResponse>(`/tasks${qs}`)
}

export function getTask(id: string): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}`)
}

export function getRuns(taskId: string): Promise<{ runs: Run[] }> {
  return apiFetch<{ runs: Run[] }>(`/tasks/${taskId}/runs`)
}

export function patchTask(id: string, patch: Partial<Task>): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  })
}
```

- [ ] **Step 10: Create approvals.ts**

Create `services/board/src/api/approvals.ts`:

```ts
import { apiFetch } from "./client"
import type { ApprovalRead } from "./types"

export function getApproval(id: string): Promise<ApprovalRead> {
  return apiFetch<ApprovalRead>(`/approvals/${id}`)
}

export function getTaskApprovals(taskId: string): Promise<ApprovalRead[]> {
  return apiFetch<ApprovalRead[]>(`/tasks/${taskId}/approvals`)
}

export function respondToApproval(
  id: string,
  decision: string,
  decidedBy: string,
  reason?: string,
): Promise<ApprovalRead> {
  return apiFetch<ApprovalRead>(`/approvals/${id}/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, decided_by: decidedBy, reason }),
  })
}
```

- [ ] **Step 11: Run all API layer tests**

```bash
npm test -- client board tasks approvals
```

Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add services/board/src/api/
git commit -m "feat: add API layer types and fetch functions"
```

---

### Task 4: Zustand store + hooks

**Files:**
- Create: `services/board/src/stores/uiStore.ts`
- Create: `services/board/src/hooks/useBoard.ts`
- Create: `services/board/src/hooks/useTask.ts`
- Create: `services/board/src/hooks/useApproval.ts`

- [ ] **Step 1: Write failing store test**

Create `services/board/src/stores/__tests__/uiStore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest"
import { useUIStore } from "../uiStore"

beforeEach(() => {
  useUIStore.setState({
    selectedTaskId: null,
    toast: null,
    activeFilters: {},
  })
})

it("setSelectedTask updates selectedTaskId", () => {
  useUIStore.getState().setSelectedTask("t1")
  expect(useUIStore.getState().selectedTaskId).toBe("t1")
})

it("setSelectedTask(null) clears selection", () => {
  useUIStore.getState().setSelectedTask("t1")
  useUIStore.getState().setSelectedTask(null)
  expect(useUIStore.getState().selectedTaskId).toBeNull()
})

it("setToast updates toast message", () => {
  useUIStore.getState().setToast("something went wrong")
  expect(useUIStore.getState().toast).toBe("something went wrong")
})

it("setFilters updates activeFilters", () => {
  useUIStore.getState().setFilters({ status: "running", labels: ["ci"] })
  expect(useUIStore.getState().activeFilters).toEqual({ status: "running", labels: ["ci"] })
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
npm test -- uiStore
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create uiStore.ts**

Create `services/board/src/stores/uiStore.ts`:

```ts
import { create } from "zustand"
import type { BoardFilters } from "../api/board"

interface UIState {
  selectedTaskId: string | null
  toast: string | null
  activeFilters: BoardFilters
  setSelectedTask: (id: string | null) => void
  setToast: (msg: string | null) => void
  setFilters: (filters: BoardFilters) => void
}

export const useUIStore = create<UIState>(set => ({
  selectedTaskId: null,
  toast: null,
  activeFilters: {},
  setSelectedTask: id => set({ selectedTaskId: id }),
  setToast: msg => set({ toast: msg }),
  setFilters: filters => set({ activeFilters: filters }),
}))
```

- [ ] **Step 4: Run store tests**

```bash
npm test -- uiStore
```

Expected: 4 passed.

- [ ] **Step 5: Write failing hook tests**

Create `services/board/src/hooks/__tests__/useBoard.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { useBoard } from "../useBoard"
import * as boardApi from "../../api/board"
import { useUIStore } from "../../stores/uiStore"

vi.mock("../../api/board")
const mockGetBoard = vi.mocked(boardApi.getBoard)

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => {
  mockGetBoard.mockReset()
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
})

it("calls getBoard on mount", async () => {
  mockGetBoard.mockResolvedValue({ columns: [], tasks_by_column: {} })
  const { result } = renderHook(() => useBoard(), { wrapper: makeWrapper() })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(mockGetBoard).toHaveBeenCalledTimes(1)
})

it("query key includes activeFilters so filter changes trigger refetch", async () => {
  mockGetBoard.mockResolvedValue({ columns: [], tasks_by_column: {} })
  const { result } = renderHook(() => useBoard(), { wrapper: makeWrapper() })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))

  mockGetBoard.mockResolvedValue({ columns: [], tasks_by_column: {} })
  useUIStore.getState().setFilters({ status: "running" })
  await waitFor(() => expect(mockGetBoard).toHaveBeenCalledTimes(2))
})
```

Create `services/board/src/hooks/__tests__/useApproval.test.ts`:

```ts
import { it, expect, vi, beforeEach } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { useApproval } from "../useApproval"
import * as approvalsApi from "../../api/approvals"

vi.mock("../../api/approvals")
const mockGetApproval = vi.mocked(approvalsApi.getApproval)

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => mockGetApproval.mockReset())

it("does not fetch when approvalId is null", () => {
  const { result } = renderHook(() => useApproval(null), { wrapper: makeWrapper() })
  expect(result.current.fetchStatus).toBe("idle")
  expect(mockGetApproval).not.toHaveBeenCalled()
})

it("fetches approval when approvalId is provided", async () => {
  mockGetApproval.mockResolvedValue({ id: "a1", status: "pending" } as any)
  const { result } = renderHook(() => useApproval("a1"), { wrapper: makeWrapper() })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(mockGetApproval).toHaveBeenCalledWith("a1")
})
```

- [ ] **Step 6: Run to verify they fail**

```bash
npm test -- useBoard useApproval
```

Expected: FAIL — modules not found.

- [ ] **Step 7: Create useBoard.ts**

Create `services/board/src/hooks/useBoard.ts`:

```ts
import { useQuery } from "@tanstack/react-query"
import { getBoard } from "../api/board"
import { useUIStore } from "../stores/uiStore"

export function useBoard() {
  const activeFilters = useUIStore(s => s.activeFilters)
  return useQuery({
    queryKey: ["board", activeFilters],
    queryFn: () => getBoard(activeFilters),
    refetchInterval: 5000,
  })
}
```

- [ ] **Step 8: Create useTask.ts**

Create `services/board/src/hooks/useTask.ts`:

```ts
import { useQuery } from "@tanstack/react-query"
import { getTask, getRuns } from "../api/tasks"
import { getTaskApprovals } from "../api/approvals"

export function useTask(id: string | null) {
  const task = useQuery({
    queryKey: ["task", id],
    queryFn: () => getTask(id!),
    enabled: !!id,
  })

  const runs = useQuery({
    queryKey: ["runs", id],
    queryFn: () => getRuns(id!),
    enabled: !!id,
  })

  const taskData = task.data
  const hasPendingApproval =
    !!taskData && taskData.approval_required && taskData.status === "needs_approval"

  const pendingApprovalQuery = useQuery({
    queryKey: ["task-approvals", id],
    queryFn: async () => {
      const approvals = await getTaskApprovals(id!)
      return approvals.find(a => a.status === "pending")?.id ?? null
    },
    enabled: hasPendingApproval,
  })

  return {
    task,
    runs,
    pendingApprovalId: pendingApprovalQuery.data ?? null,
  }
}
```

- [ ] **Step 9: Create useApproval.ts**

Create `services/board/src/hooks/useApproval.ts`:

```ts
import { useQuery } from "@tanstack/react-query"
import { getApproval } from "../api/approvals"

export function useApproval(approvalId: string | null) {
  return useQuery({
    queryKey: ["approval", approvalId],
    queryFn: () => getApproval(approvalId!),
    enabled: !!approvalId,
  })
}
```

- [ ] **Step 10: Run all hook + store tests**

```bash
npm test -- uiStore useBoard useApproval
```

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add services/board/src/stores/ services/board/src/hooks/
git commit -m "feat: add Zustand store and TanStack Query hooks"
```

---

### Task 5: CSS tokens + shared components

**Files:**
- Create: `services/board/src/styles/tokens.css`
- Create: `services/board/src/styles/global.css`
- Create: `services/board/src/components/shared/Badge.tsx`
- Create: `services/board/src/components/shared/Toast.tsx`
- Create: `services/board/src/components/shared/FilterBar.tsx`

- [ ] **Step 1: Write failing Badge tests**

Create `services/board/src/components/shared/__tests__/Badge.test.tsx`:

```tsx
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { Badge } from "../Badge"

describe("Badge", () => {
  it("renders the value as text", () => {
    render(<Badge type="status" value="running" />)
    expect(screen.getByText("running")).toBeInTheDocument()
  })

  it("applies type and value classes", () => {
    render(<Badge type="status" value="failed" />)
    const el = screen.getByText("failed")
    expect(el).toHaveClass("badge")
    expect(el).toHaveClass("badge--status")
    expect(el).toHaveClass("badge--failed")
  })

  it("renders each priority value", () => {
    const { rerender } = render(<Badge type="priority" value="low" />)
    expect(screen.getByText("low")).toBeInTheDocument()
    rerender(<Badge type="priority" value="high" />)
    expect(screen.getByText("high")).toBeInTheDocument()
    rerender(<Badge type="priority" value="critical" />)
    expect(screen.getByText("critical")).toBeInTheDocument()
  })

  it("renders each risk value", () => {
    render(<Badge type="risk" value="high" />)
    expect(screen.getByText("high")).toBeInTheDocument()
  })
})
```

Create `services/board/src/components/shared/__tests__/Toast.test.tsx`:

```tsx
import { it, expect, vi } from "vitest"
import { render, screen, act } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Toast } from "../Toast"

it("renders message text", () => {
  render(<Toast message="something failed" onDismiss={() => {}} />)
  expect(screen.getByText("something failed")).toBeInTheDocument()
})

it("calls onDismiss when dismiss button is clicked", async () => {
  const onDismiss = vi.fn()
  render(<Toast message="err" onDismiss={onDismiss} />)
  await userEvent.click(screen.getByRole("button"))
  expect(onDismiss).toHaveBeenCalledTimes(1)
})
```

Create `services/board/src/components/shared/__tests__/FilterBar.test.tsx`:

```tsx
import { it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FilterBar } from "../FilterBar"
import { useUIStore } from "../../../stores/uiStore"

beforeEach(() => {
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
})

it("renders status filter select", () => {
  render(<FilterBar />)
  expect(screen.getByLabelText(/status/i)).toBeInTheDocument()
})

it("selecting a status updates the store", async () => {
  render(<FilterBar />)
  await userEvent.selectOptions(screen.getByLabelText(/status/i), "running")
  expect(useUIStore.getState().activeFilters.status).toBe("running")
})

it("selecting empty status clears the filter", async () => {
  useUIStore.setState({ activeFilters: { status: "running" }, selectedTaskId: null, toast: null })
  render(<FilterBar />)
  await userEvent.selectOptions(screen.getByLabelText(/status/i), "")
  expect(useUIStore.getState().activeFilters.status).toBeUndefined()
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
npm test -- Badge Toast FilterBar
```

Expected: FAIL — modules not found.

- [ ] **Step 3: Create CSS tokens**

Create `services/board/src/styles/tokens.css`:

```css
:root {
  --bg: #f8fafc;
  --bg-card: #ffffff;
  --bg-card-border: #e2e8f0;
  --bg-card-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  --text: #1e293b;
  --text-muted: #64748b;
  --text-header: #334155;
  --accent-blue: #3b82f6;
  --accent-blue-bg: #eff6ff;
  --accent-amber: #d97706;
  --accent-amber-bg: #fffbeb;
  --accent-red: #dc2626;
  --accent-red-bg: #fef2f2;
  --accent-green: #16a34a;
  --accent-green-bg: #f0fdf4;
  --accent-gray: #64748b;
  --accent-gray-bg: #f1f5f9;
  --column-bg: #f1f5f9;
  --radius: 6px;
  --font: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117;
    --bg-card: #161b22;
    --bg-card-border: #30363d;
    --bg-card-shadow: none;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --text-header: #c9d1d9;
    --accent-blue: #58a6ff;
    --accent-blue-bg: rgba(31, 111, 235, 0.2);
    --accent-amber: #d29922;
    --accent-amber-bg: rgba(210, 153, 34, 0.15);
    --accent-red: #ff7b72;
    --accent-red-bg: rgba(218, 54, 51, 0.2);
    --accent-green: #3fb950;
    --accent-green-bg: rgba(63, 185, 80, 0.15);
    --accent-gray: #8b949e;
    --accent-gray-bg: rgba(139, 148, 158, 0.1);
    --column-bg: #161b22;
  }
}
```

- [ ] **Step 4: Create global.css**

Create `services/board/src/styles/global.css`:

```css
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;
}

.board-layout {
  display: flex;
  height: 100vh;
  flex-direction: column;
  overflow: hidden;
}

.board-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--bg-card-border);
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.board-columns {
  display: flex;
  gap: 12px;
  padding: 16px;
  overflow-x: auto;
  flex: 1;
  min-height: 0;
}

.board-with-detail {
  display: flex;
  flex: 1;
  min-height: 0;
}

.detail-panel {
  width: 400px;
  border-left: 1px solid var(--bg-card-border);
  background: var(--bg-card);
  overflow-y: auto;
  flex-shrink: 0;
  transform: translateX(100%);
  transition: transform 0.2s ease;
}

.detail-panel--open {
  transform: translateX(0);
}
```

- [ ] **Step 5: Create Badge.tsx**

Create `services/board/src/components/shared/Badge.tsx`:

```tsx
interface BadgeProps {
  type: "status" | "priority" | "risk" | "label"
  value: string
}

export function Badge({ type, value }: BadgeProps) {
  return (
    <span className={`badge badge--${type} badge--${value.replace(/_/g, "-")}`}>
      {value}
    </span>
  )
}
```

Add badge styles to `services/board/src/styles/global.css` (append after existing rules):

```css
.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid transparent;
}

/* Status */
.badge--running  { color: var(--accent-blue);  background: var(--accent-blue-bg);  border-color: var(--accent-blue); }
.badge--failed   { color: var(--accent-red);   background: var(--accent-red-bg);   border-color: var(--accent-red); }
.badge--needs-approval { color: var(--accent-amber); background: var(--accent-amber-bg); border-color: var(--accent-amber); }
.badge--done     { color: var(--accent-green); background: var(--accent-green-bg); border-color: var(--accent-green); }
.badge--cancelled { color: var(--accent-gray); background: var(--accent-gray-bg); border-color: var(--accent-gray); }
.badge--pending  { color: var(--accent-gray);  background: var(--accent-gray-bg); }
.badge--ready    { color: var(--accent-blue);  background: var(--accent-blue-bg); }

/* Priority */
.badge--critical { color: var(--accent-red);   background: var(--accent-red-bg); }
.badge--high     { color: var(--accent-amber);  background: var(--accent-amber-bg); }
.badge--normal   { color: var(--accent-gray);   background: var(--accent-gray-bg); }
.badge--low      { color: var(--accent-gray);   background: var(--accent-gray-bg); }

/* Risk */
.badge--risk { }
```

- [ ] **Step 6: Create Toast.tsx**

Create `services/board/src/components/shared/Toast.tsx`:

```tsx
interface ToastProps {
  message: string
  onDismiss: () => void
}

export function Toast({ message, onDismiss }: ToastProps) {
  return (
    <div className="toast" role="alert">
      <span>{message}</span>
      <button onClick={onDismiss} aria-label="Dismiss">&times;</button>
    </div>
  )
}
```

Append to global.css:

```css
.toast {
  position: fixed;
  bottom: 16px;
  right: 16px;
  background: var(--accent-red-bg);
  color: var(--accent-red);
  border: 1px solid var(--accent-red);
  border-radius: var(--radius);
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  z-index: 100;
}

.toast button {
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  font-size: 16px;
  line-height: 1;
}
```

- [ ] **Step 7: Create FilterBar.tsx**

Create `services/board/src/components/shared/FilterBar.tsx`:

```tsx
import { useUIStore } from "../../stores/uiStore"

const STATUS_OPTIONS = ["", "pending", "ready", "running", "needs_approval", "done", "failed", "cancelled"]
const PRIORITY_OPTIONS = ["", "low", "normal", "high", "critical"]
const RISK_OPTIONS = ["", "low", "medium", "high"]

export function FilterBar() {
  const { activeFilters, setFilters } = useUIStore(s => ({
    activeFilters: s.activeFilters,
    setFilters: s.setFilters,
  }))

  function update(key: string, value: string) {
    const next = { ...activeFilters }
    if (value) {
      (next as Record<string, string>)[key] = value
    } else {
      delete (next as Record<string, string>)[key]
    }
    setFilters(next)
  }

  return (
    <div className="filter-bar" role="search">
      <label>
        Status
        <select
          aria-label="Status"
          value={activeFilters.status ?? ""}
          onChange={e => update("status", e.target.value)}
        >
          {STATUS_OPTIONS.map(o => (
            <option key={o} value={o}>{o || "All"}</option>
          ))}
        </select>
      </label>

      <label>
        Priority
        <select
          aria-label="Priority"
          value={activeFilters.priority ?? ""}
          onChange={e => update("priority", e.target.value)}
        >
          {PRIORITY_OPTIONS.map(o => (
            <option key={o} value={o}>{o || "All"}</option>
          ))}
        </select>
      </label>

      <label>
        Risk
        <select
          aria-label="Risk"
          value={activeFilters.risk_class ?? ""}
          onChange={e => update("risk_class", e.target.value)}
        >
          {RISK_OPTIONS.map(o => (
            <option key={o} value={o}>{o || "All"}</option>
          ))}
        </select>
      </label>
    </div>
  )
}
```

Append to global.css:

```css
.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}

.filter-bar label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

.filter-bar select {
  background: var(--bg-card);
  color: var(--text);
  border: 1px solid var(--bg-card-border);
  border-radius: var(--radius);
  padding: 3px 6px;
  font-size: 12px;
}
```

- [ ] **Step 8: Run shared component tests**

```bash
npm test -- Badge Toast FilterBar
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add services/board/src/styles/ services/board/src/components/shared/
git commit -m "feat: add CSS tokens, global styles, and shared Badge/Toast/FilterBar components"
```

---

### Task 6: Board components

**Files:**
- Create: `services/board/src/components/Board/TaskCard.tsx`
- Create: `services/board/src/components/Board/Column.tsx`
- Create: `services/board/src/components/Board/Board.tsx`

- [ ] **Step 1: Write failing TaskCard tests**

Create `services/board/src/components/Board/__tests__/TaskCard.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { TaskCard } from "../TaskCard"
import { useUIStore } from "../../../stores/uiStore"
import type { Task } from "../../../api/types"

const baseTask: Task = {
  id: "t1",
  title: "Deploy to staging",
  description: null,
  goal: null,
  status: "pending",
  origin_event_id: null,
  board_column_id: "col-inbox",
  owner_type: null,
  owner_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  due_at: null,
  priority: "normal",
  risk_class: "low",
  approval_required: false,
  last_decision: "none",
  next_check_at: null,
  result_summary: null,
  labels: [],
  metadata: {},
}

beforeEach(() => {
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
})

it("renders the task title", () => {
  render(<TaskCard task={baseTask} />)
  expect(screen.getByText("Deploy to staging")).toBeInTheDocument()
})

it("renders status badge", () => {
  render(<TaskCard task={baseTask} />)
  expect(screen.getByText("pending")).toBeInTheDocument()
})

it("renders priority badge", () => {
  render(<TaskCard task={{ ...baseTask, priority: "high" }} />)
  expect(screen.getByText("high")).toBeInTheDocument()
})

it("shows approval warning when task needs approval", () => {
  render(<TaskCard task={{ ...baseTask, approval_required: true, status: "needs_approval" }} />)
  expect(screen.getByText(/approval/i)).toBeInTheDocument()
})

it("does not show approval warning when approval_required is false", () => {
  render(<TaskCard task={baseTask} />)
  expect(screen.queryByText(/approval needed/i)).not.toBeInTheDocument()
})

it("clicking the card sets selectedTaskId in the store", async () => {
  render(<TaskCard task={baseTask} />)
  await userEvent.click(screen.getByRole("article"))
  expect(useUIStore.getState().selectedTaskId).toBe("t1")
})

it("renders labels as badges", () => {
  render(<TaskCard task={{ ...baseTask, labels: ["ci", "infra"] }} />)
  expect(screen.getByText("ci")).toBeInTheDocument()
  expect(screen.getByText("infra")).toBeInTheDocument()
})
```

Create `services/board/src/components/Board/__tests__/Column.test.tsx`:

```tsx
import { it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { Column } from "../Column"
import type { BoardColumn, Task } from "../../../api/types"

const col: BoardColumn = {
  id: "col-inbox",
  name: "Inbox",
  order: 1,
  work_in_progress_limit: null,
  status_filter: null,
  description: "New tasks",
}

const task: Task = {
  id: "t1", title: "Task A", description: null, goal: null, status: "pending",
  origin_event_id: null, board_column_id: "col-inbox", owner_type: null, owner_id: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", due_at: null,
  priority: "normal", risk_class: "low", approval_required: false, last_decision: "none",
  next_check_at: null, result_summary: null, labels: [], metadata: {},
}

it("renders column name", () => {
  render(<Column column={col} tasks={[]} />)
  expect(screen.getByText("Inbox")).toBeInTheDocument()
})

it("renders task count", () => {
  render(<Column column={col} tasks={[task]} />)
  expect(screen.getByText("1")).toBeInTheDocument()
})

it("renders WIP limit pill when set", () => {
  render(<Column column={{ ...col, work_in_progress_limit: 3 }} tasks={[]} />)
  expect(screen.getByText(/3/)).toBeInTheDocument()
})

it("renders each task card", () => {
  render(<Column column={col} tasks={[task]} />)
  expect(screen.getByText("Task A")).toBeInTheDocument()
})
```

Create `services/board/src/components/Board/__tests__/Board.test.tsx`:

```tsx
import { it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { Board } from "../Board"
import * as hooks from "../../../hooks/useBoard"
import { useUIStore } from "../../../stores/uiStore"

vi.mock("../../../hooks/useBoard")
const mockUseBoard = vi.mocked(hooks.useBoard)

function makeWrapper() {
  const qc = new QueryClient()
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => {
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
})

it("renders 8 columns from board data", () => {
  const columns = [
    { id: "col-inbox", name: "Inbox", order: 1, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-ready", name: "Ready", order: 2, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-running", name: "Running", order: 3, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-waiting", name: "Waiting", order: 4, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-approval", name: "Needs Approval", order: 5, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-done", name: "Done", order: 6, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-failed", name: "Failed", order: 7, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-cancelled", name: "Cancelled", order: 8, work_in_progress_limit: null, status_filter: null, description: null },
  ]
  mockUseBoard.mockReturnValue({
    data: { columns, tasks_by_column: Object.fromEntries(columns.map(c => [c.id, []])) },
    isLoading: false,
    isError: false,
    error: null,
  } as any)

  render(<Board />, { wrapper: makeWrapper() })
  expect(screen.getByText("Inbox")).toBeInTheDocument()
  expect(screen.getByText("Needs Approval")).toBeInTheDocument()
  expect(screen.getByText("Cancelled")).toBeInTheDocument()
})

it("shows loading state", () => {
  mockUseBoard.mockReturnValue({ isLoading: true, isError: false, data: undefined, error: null } as any)
  render(<Board />, { wrapper: makeWrapper() })
  expect(screen.getByText(/loading/i)).toBeInTheDocument()
})

it("shows error state", () => {
  mockUseBoard.mockReturnValue({ isLoading: false, isError: true, data: undefined, error: new Error("fail") } as any)
  render(<Board />, { wrapper: makeWrapper() })
  expect(screen.getByText(/error/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
npm test -- TaskCard Column Board
```

Expected: FAIL — modules not found.

- [ ] **Step 3: Create TaskCard.tsx**

Create `services/board/src/components/Board/TaskCard.tsx`:

```tsx
import { useUIStore } from "../../stores/uiStore"
import { Badge } from "../shared/Badge"
import type { Task } from "../../api/types"

interface TaskCardProps {
  task: Task
}

export function TaskCard({ task }: TaskCardProps) {
  const setSelectedTask = useUIStore(s => s.setSelectedTask)
  const needsApproval = task.approval_required && task.status === "needs_approval"

  return (
    <article
      className={`task-card${needsApproval ? " task-card--approval" : ""}`}
      onClick={() => setSelectedTask(task.id)}
      role="article"
      tabIndex={0}
      onKeyDown={e => e.key === "Enter" && setSelectedTask(task.id)}
    >
      <div className="task-card__title">{task.title}</div>

      <div className="task-card__badges">
        <Badge type="status" value={task.status} />
        <Badge type="priority" value={task.priority} />
        {task.risk_class !== "low" && <Badge type="risk" value={task.risk_class} />}
        {task.labels.map(l => (
          <Badge key={l} type="label" value={l} />
        ))}
      </div>

      {needsApproval && (
        <div className="task-card__approval-warning">approval needed</div>
      )}
    </article>
  )
}
```

Append to global.css:

```css
.task-card {
  background: var(--bg-card);
  border: 1px solid var(--bg-card-border);
  box-shadow: var(--bg-card-shadow);
  border-radius: var(--radius);
  padding: 10px 12px;
  cursor: pointer;
  margin-bottom: 8px;
}

.task-card:hover { border-color: var(--accent-blue); }
.task-card--approval { border-color: var(--accent-amber); }

.task-card__title {
  font-size: 13px;
  color: var(--text);
  margin-bottom: 6px;
  font-weight: 500;
}

.task-card__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.task-card__approval-warning {
  margin-top: 6px;
  font-size: 11px;
  color: var(--accent-amber);
  font-weight: 600;
}
```

- [ ] **Step 4: Create Column.tsx**

Create `services/board/src/components/Board/Column.tsx`:

```tsx
import { TaskCard } from "./TaskCard"
import type { BoardColumn, Task } from "../../api/types"

interface ColumnProps {
  column: BoardColumn
  tasks: Task[]
}

export function Column({ column, tasks }: ColumnProps) {
  const atLimit = column.work_in_progress_limit !== null && tasks.length >= column.work_in_progress_limit

  return (
    <div className="column">
      <div className="column__header">
        <span className="column__name">{column.name}</span>
        <span className={`column__count${atLimit ? " column__count--limit" : ""}`}>
          {tasks.length}
          {column.work_in_progress_limit !== null && `/${column.work_in_progress_limit}`}
        </span>
      </div>
      <div className="column__cards">
        {tasks.map(task => (
          <TaskCard key={task.id} task={task} />
        ))}
      </div>
    </div>
  )
}
```

Append to global.css:

```css
.column {
  min-width: 220px;
  max-width: 260px;
  flex-shrink: 0;
  background: var(--column-bg);
  border-radius: var(--radius);
  padding: 10px;
  display: flex;
  flex-direction: column;
  max-height: 100%;
}

.column__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--bg-card-border);
}

.column__name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-header);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.column__count {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-card);
  border-radius: 10px;
  padding: 1px 6px;
}

.column__count--limit { color: var(--accent-red); }

.column__cards {
  overflow-y: auto;
  flex: 1;
}
```

- [ ] **Step 5: Create Board.tsx**

Create `services/board/src/components/Board/Board.tsx`:

```tsx
import { useBoard } from "../../hooks/useBoard"
import { Column } from "./Column"

export function Board() {
  const { data, isLoading, isError } = useBoard()

  if (isLoading) return <div className="board-loading">Loading board...</div>
  if (isError || !data) return <div className="board-error">Error loading board. Check API connection.</div>

  return (
    <div className="board-columns">
      {data.columns.map(col => (
        <Column
          key={col.id}
          column={col}
          tasks={data.tasks_by_column[col.id] ?? []}
        />
      ))}
    </div>
  )
}
```

- [ ] **Step 6: Run board component tests**

```bash
npm test -- TaskCard Column Board
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add services/board/src/components/Board/ services/board/src/styles/global.css
git commit -m "feat: add TaskCard, Column, and Board components"
```

---

### Task 7: TaskDetail + ApprovalBanner

**Files:**
- Create: `services/board/src/components/TaskDetail/RunList.tsx`
- Create: `services/board/src/components/TaskDetail/ApprovalBanner.tsx`
- Create: `services/board/src/components/TaskDetail/TaskDetail.tsx`

- [ ] **Step 1: Write failing tests**

Create `services/board/src/components/TaskDetail/__tests__/RunList.test.tsx`:

```tsx
import { it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { RunList } from "../RunList"
import type { Run } from "../../../api/types"

const run: Run = {
  id: "r1",
  tool_name: "bash",
  status: "success",
  started_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:00:05Z",
  error: null,
}

it("renders tool_name and status", () => {
  render(<RunList runs={[run]} />)
  expect(screen.getByText("bash")).toBeInTheDocument()
  expect(screen.getByText("success")).toBeInTheDocument()
})

it("renders empty state when no runs", () => {
  render(<RunList runs={[]} />)
  expect(screen.getByText(/no runs/i)).toBeInTheDocument()
})

it("renders error text when run has error", () => {
  render(<RunList runs={[{ ...run, status: "error", error: "timeout" }]} />)
  expect(screen.getByText("timeout")).toBeInTheDocument()
})
```

Create `services/board/src/components/TaskDetail/__tests__/ApprovalBanner.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { ApprovalBanner } from "../ApprovalBanner"
import * as approvalsApi from "../../../api/approvals"
import type { ApprovalRead } from "../../../api/types"

vi.mock("../../../api/approvals")
const mockRespond = vi.mocked(approvalsApi.respondToApproval)

const approval: ApprovalRead = {
  id: "a1",
  task_id: "t1",
  requested_by: "nova-lite",
  requested_at: "2026-01-01T00:00:00Z",
  summary: "Run shell command",
  consequence: "Will delete files",
  options: ["approve", "deny"],
  status: "pending",
  decided_by: null,
  decided_at: null,
  decision: null,
  reason: null,
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => mockRespond.mockReset())

it("renders summary and consequence", () => {
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  expect(screen.getByText("Run shell command")).toBeInTheDocument()
  expect(screen.getByText("Will delete files")).toBeInTheDocument()
})

it("renders approve and deny buttons", () => {
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /deny/i })).toBeInTheDocument()
})

it("calls respondToApproval with approve on Approve click", async () => {
  mockRespond.mockResolvedValue({ ...approval, status: "approved", decision: "approve" })
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  await userEvent.click(screen.getByRole("button", { name: /approve/i }))
  expect(mockRespond).toHaveBeenCalledWith("a1", "approve", "user", undefined)
})

it("disables buttons while mutation is pending", async () => {
  mockRespond.mockImplementation(() => new Promise(() => {}))  // never resolves
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  await userEvent.click(screen.getByRole("button", { name: /approve/i }))
  expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled()
  expect(screen.getByRole("button", { name: /deny/i })).toBeDisabled()
})

it("shows retry button on error", async () => {
  mockRespond.mockRejectedValue(new Error("network error"))
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  await userEvent.click(screen.getByRole("button", { name: /approve/i }))
  await waitFor(() => expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument())
})
```

Create `services/board/src/components/TaskDetail/__tests__/TaskDetail.test.tsx`:

```tsx
import { it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { TaskDetail } from "../TaskDetail"
import { useUIStore } from "../../../stores/uiStore"
import * as taskHooks from "../../../hooks/useTask"
import * as approvalHooks from "../../../hooks/useApproval"

vi.mock("../../../hooks/useTask")
vi.mock("../../../hooks/useApproval")

const mockUseTask = vi.mocked(taskHooks.useTask)
const mockUseApproval = vi.mocked(approvalHooks.useApproval)

function makeWrapper() {
  const qc = new QueryClient()
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

const mockTask = {
  id: "t1", title: "Deploy", description: "Deploy to prod", goal: null, status: "running",
  origin_event_id: null, board_column_id: "col-running", owner_type: null, owner_id: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", due_at: null,
  priority: "normal", risk_class: "low", approval_required: false, last_decision: "none",
  next_check_at: null, result_summary: null, labels: [], metadata: {},
}

beforeEach(() => {
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
  mockUseApproval.mockReturnValue({ data: undefined, isLoading: false } as any)
})

it("is not visible when no task selected", () => {
  mockUseTask.mockReturnValue({ task: { data: undefined, isLoading: false } as any, runs: { data: undefined } as any, pendingApprovalId: null })
  render(<TaskDetail />, { wrapper: makeWrapper() })
  const panel = document.querySelector(".detail-panel")
  expect(panel).not.toHaveClass("detail-panel--open")
})

it("becomes visible when a task is selected", () => {
  useUIStore.setState({ selectedTaskId: "t1", toast: null, activeFilters: {} })
  mockUseTask.mockReturnValue({
    task: { data: mockTask, isLoading: false } as any,
    runs: { data: { runs: [] } } as any,
    pendingApprovalId: null,
  })
  render(<TaskDetail />, { wrapper: makeWrapper() })
  expect(document.querySelector(".detail-panel--open")).toBeTruthy()
  expect(screen.getByText("Deploy")).toBeInTheDocument()
})

it("clicking close clears selectedTaskId", async () => {
  useUIStore.setState({ selectedTaskId: "t1", toast: null, activeFilters: {} })
  mockUseTask.mockReturnValue({
    task: { data: mockTask, isLoading: false } as any,
    runs: { data: { runs: [] } } as any,
    pendingApprovalId: null,
  })
  render(<TaskDetail />, { wrapper: makeWrapper() })
  await userEvent.click(screen.getByRole("button", { name: /close/i }))
  expect(useUIStore.getState().selectedTaskId).toBeNull()
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
npm test -- RunList ApprovalBanner TaskDetail
```

Expected: FAIL — modules not found.

- [ ] **Step 3: Create RunList.tsx**

Create `services/board/src/components/TaskDetail/RunList.tsx`:

```tsx
import type { Run } from "../../api/types"

interface RunListProps {
  runs: Run[]
}

export function RunList({ runs }: RunListProps) {
  if (runs.length === 0) {
    return <p className="run-list__empty">No runs yet.</p>
  }

  return (
    <ul className="run-list">
      {runs.map(run => (
        <li key={run.id} className={`run-item run-item--${run.status}`}>
          <span className="run-item__tool">{run.tool_name}</span>
          <span className="run-item__status">{run.status}</span>
          {run.started_at && (
            <span className="run-item__time">
              {new Date(run.started_at).toLocaleTimeString()}
            </span>
          )}
          {run.error && <span className="run-item__error">{run.error}</span>}
        </li>
      ))}
    </ul>
  )
}
```

- [ ] **Step 4: Create ApprovalBanner.tsx**

Create `services/board/src/components/TaskDetail/ApprovalBanner.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { respondToApproval } from "../../api/approvals"
import type { ApprovalRead } from "../../api/types"

interface ApprovalBannerProps {
  approval: ApprovalRead
  taskId: string
}

export function ApprovalBanner({ approval, taskId }: ApprovalBannerProps) {
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: ({ decision }: { decision: string }) =>
      respondToApproval(approval.id, decision, "user"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["board"] })
      queryClient.invalidateQueries({ queryKey: ["task", taskId] })
      queryClient.invalidateQueries({ queryKey: ["task-approvals", taskId] })
    },
  })

  const options = approval.options.length > 0 ? approval.options : ["approve", "deny"]

  return (
    <div className="approval-banner">
      <div className="approval-banner__summary">{approval.summary}</div>
      {approval.consequence && (
        <div className="approval-banner__consequence">{approval.consequence}</div>
      )}

      {mutation.isError && (
        <div className="approval-banner__error">
          Failed: {(mutation.error as Error).message}
          <button onClick={() => mutation.reset()} aria-label="Retry">Retry</button>
        </div>
      )}

      <div className="approval-banner__actions">
        {options.map(opt => (
          <button
            key={opt}
            className={`approval-btn approval-btn--${opt === "approve" ? "approve" : "deny"}`}
            disabled={mutation.isPending}
            onClick={() => mutation.mutate({ decision: opt })}
            aria-label={opt.charAt(0).toUpperCase() + opt.slice(1)}
          >
            {opt.charAt(0).toUpperCase() + opt.slice(1)}
          </button>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Create TaskDetail.tsx**

Create `services/board/src/components/TaskDetail/TaskDetail.tsx`:

```tsx
import { useUIStore } from "../../stores/uiStore"
import { useTask } from "../../hooks/useTask"
import { useApproval } from "../../hooks/useApproval"
import { Badge } from "../shared/Badge"
import { RunList } from "./RunList"
import { ApprovalBanner } from "./ApprovalBanner"

export function TaskDetail() {
  const { selectedTaskId, setSelectedTask } = useUIStore(s => ({
    selectedTaskId: s.selectedTaskId,
    setSelectedTask: s.setSelectedTask,
  }))

  const { task, runs, pendingApprovalId } = useTask(selectedTaskId)
  const approval = useApproval(pendingApprovalId)

  const isOpen = !!selectedTaskId
  const taskData = task.data
  const runsData = runs.data?.runs ?? []

  return (
    <div className={`detail-panel${isOpen ? " detail-panel--open" : ""}`}>
      <div className="detail-panel__header">
        <span>{taskData?.title ?? "Loading…"}</span>
        <button
          className="detail-panel__close"
          onClick={() => setSelectedTask(null)}
          aria-label="Close"
        >
          &times;
        </button>
      </div>

      {taskData && (
        <div className="detail-panel__body">
          <div className="detail-panel__badges">
            <Badge type="status" value={taskData.status} />
            <Badge type="priority" value={taskData.priority} />
            <Badge type="risk" value={taskData.risk_class} />
          </div>

          {taskData.description && (
            <p className="detail-panel__description">{taskData.description}</p>
          )}

          {approval.data && (
            <ApprovalBanner approval={approval.data} taskId={taskData.id} />
          )}

          <section className="detail-panel__section">
            <h3>Run History</h3>
            <RunList runs={runsData} />
          </section>
        </div>
      )}
    </div>
  )
}
```

Append to global.css:

```css
.detail-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--bg-card-border);
  font-weight: 600;
}

.detail-panel__close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 18px;
  line-height: 1;
}

.detail-panel__body { padding: 16px; }

.detail-panel__badges { display: flex; gap: 6px; margin-bottom: 12px; }

.detail-panel__description {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 16px;
}

.detail-panel__section h3 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin-bottom: 8px;
}

/* Approval banner */
.approval-banner {
  background: var(--accent-amber-bg);
  border: 1px solid var(--accent-amber);
  border-radius: var(--radius);
  padding: 12px;
  margin-bottom: 16px;
}

.approval-banner__summary { font-weight: 600; margin-bottom: 4px; }
.approval-banner__consequence { font-size: 12px; color: var(--text-muted); margin-bottom: 10px; }
.approval-banner__error {
  font-size: 12px;
  color: var(--accent-red);
  margin-bottom: 8px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.approval-banner__error button {
  background: none;
  border: 1px solid var(--accent-red);
  color: var(--accent-red);
  border-radius: 3px;
  padding: 1px 6px;
  cursor: pointer;
  font-size: 11px;
}
.approval-banner__actions { display: flex; gap: 8px; }
.approval-btn { padding: 5px 14px; border-radius: var(--radius); border: none; cursor: pointer; font-size: 13px; font-weight: 500; }
.approval-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.approval-btn--approve { background: var(--accent-green); color: #fff; }
.approval-btn--deny    { background: var(--accent-red); color: #fff; }

/* Run list */
.run-list { list-style: none; }
.run-list__empty { font-size: 12px; color: var(--text-muted); }
.run-item {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 4px 0;
  border-bottom: 1px solid var(--bg-card-border);
  font-size: 12px;
}
.run-item__tool { font-weight: 500; }
.run-item__status { color: var(--text-muted); }
.run-item__time { color: var(--text-muted); margin-left: auto; }
.run-item__error { color: var(--accent-red); font-size: 11px; }
```

- [ ] **Step 6: Run TaskDetail tests**

```bash
npm test -- RunList ApprovalBanner TaskDetail
```

Expected: all pass.

- [ ] **Step 7: Run full test suite**

```bash
npm test
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add services/board/src/components/TaskDetail/ services/board/src/styles/global.css
git commit -m "feat: add RunList, ApprovalBanner, and TaskDetail components"
```

---

### Task 8: App assembly + Docker

**Files:**
- Create: `services/board/src/main.tsx`
- Create: `services/board/src/App.tsx`
- Create: `services/board/Dockerfile`
- Create: `services/board/nginx.conf`
- Modify: `infra/docker-compose.yml`

- [ ] **Step 1: Create main.tsx**

Create `services/board/src/main.tsx`:

```tsx
import "./styles/tokens.css"
import "./styles/global.css"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { App } from "./App"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      retry: 1,
    },
  },
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
)
```

- [ ] **Step 2: Create App.tsx**

Create `services/board/src/App.tsx`:

```tsx
import { useUIStore } from "./stores/uiStore"
import { Board } from "./components/Board/Board"
import { FilterBar } from "./components/shared/FilterBar"
import { TaskDetail } from "./components/TaskDetail/TaskDetail"
import { Toast } from "./components/shared/Toast"

export function App() {
  const { toast, setToast } = useUIStore(s => ({
    toast: s.toast,
    setToast: s.setToast,
  }))

  return (
    <div className="board-layout">
      <header className="board-header">
        <span style={{ fontWeight: 700, fontSize: 15 }}>Nova Board</span>
        <FilterBar />
      </header>

      <div className="board-with-detail">
        <Board />
        <TaskDetail />
      </div>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
```

- [ ] **Step 3: Verify the dev server starts**

```bash
cd services/board
npm run dev
```

Expected: Vite dev server starts on http://localhost:5173. Open in browser. Board renders with "Loading board..." then the 8 columns (assuming the API is running at localhost:8000). Press Ctrl+C to stop.

- [ ] **Step 4: Create Dockerfile**

Create `services/board/Dockerfile`:

```dockerfile
# Stage 1: build
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# Stage 2: serve
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 5: Create nginx.conf**

Create `services/board/nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    gzip on;
    gzip_types text/plain text/css application/javascript application/json;
}
```

- [ ] **Step 6: Add board service to docker-compose.yml**

Open `infra/docker-compose.yml`. Add this service alongside the existing `api` and `db` services:

```yaml
  board:
    build:
      context: ../services/board
      args:
        VITE_API_URL: ""
    ports:
      - "5173:80"
    depends_on:
      - api
```

- [ ] **Step 7: Run full test suite one final time**

```bash
cd services/board
npm test
```

Expected: all pass.

- [ ] **Step 8: Run full API suite one final time**

```bash
cd services/api
python3 -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add services/board/src/main.tsx services/board/src/App.tsx \
        services/board/Dockerfile services/board/nginx.conf \
        infra/docker-compose.yml
git commit -m "feat: add App assembly, Dockerfile, nginx.conf, and docker-compose board service"
```

- [ ] **Step 10: Docker smoke test**

```bash
cd infra
docker compose up --build db api board
```

Expected: all three services start. Navigate to http://localhost:5173 — board renders with 8 columns. Navigate to http://localhost:8000/docs — Swagger shows all board + approval endpoints. Press Ctrl+C to stop.
