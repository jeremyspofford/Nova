# Settings Page & Layout Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent settings page at `/settings` and redesign Nova Board's layout so chat and board are equal first-class panels configurable via user preferences saved to localStorage.

**Architecture:** React Router v6 handles `/` vs `/settings` navigation. A new `settingsStore` (Zustand `persist`) holds three settings: `theme`, `layoutMode`, `chatSide`. A new `AppShell` reads those settings and renders either a split layout (chat pinned, board fills rest) or a tabbed layout (tab buttons in header). `ChatPanel` becomes a structural element — always rendered, never toggled.

**Tech Stack:** React 18, React Router v6 (`react-router-dom`), Zustand 4.5 with `persist` middleware, Vitest + Testing Library, CSS custom properties

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `services/board/src/router.tsx` | Create | `createBrowserRouter` — `/` → AppShell, `/settings` → Settings |
| `services/board/src/AppShell.tsx` | Create | Layout wrapper: split or tabbed based on `settingsStore` + `uiStore` |
| `services/board/src/stores/settingsStore.ts` | Create | Persisted settings: `theme`, `layoutMode`, `chatSide`; applies `data-theme` to `<html>` |
| `services/board/src/components/Settings/Settings.tsx` | Create | Settings page: three segmented controls |
| `services/board/src/components/Settings/__tests__/Settings.test.tsx` | Create | Settings render + interaction tests |
| `services/board/src/stores/__tests__/settingsStore.test.ts` | Create | settingsStore action + theme side-effect tests |
| `services/board/src/App.tsx` | Modify | Replace layout logic with `<RouterProvider router={router} />` |
| `services/board/src/stores/uiStore.ts` | Modify | Remove `chatOpen`/`toggleChat`; add `activeTab`/`setActiveTab` |
| `services/board/src/stores/__tests__/uiStore.test.ts` | Modify | Add `activeTab` tests; reset `activeTab` in `beforeEach` |
| `services/board/src/stores/chatStore.ts` | Modify | Add `persist` middleware; persist only `conversationId` |
| `services/board/src/stores/__tests__/chatStore.test.ts` | Modify | Clear localStorage in `beforeEach` |
| `services/board/src/styles/tokens.css` | Modify | Add `[data-theme="light"]` and `[data-theme="dark"]` selectors |
| `services/board/src/styles/global.css` | Modify | Add AppShell layout classes; remove obsolete chat-overlay classes |
| `services/board/src/components/Chat/ChatPanel.tsx` | Modify | Remove `chatOpen` guard + close button; remove `toggleChat` usage |
| `services/board/src/components/Chat/__tests__/ChatPanel.test.tsx` | Modify | Replace `chatOpen`-based tests with always-rendered tests |

---

## Task 1: Install React Router and scaffold routes

Installs `react-router-dom`, creates the router with placeholder routes, and updates `App.tsx` to mount it. After this task the app still renders correctly at `/`.

**Files:**
- Modify: `services/board/package.json` (via install)
- Create: `services/board/src/router.tsx`
- Modify: `services/board/src/App.tsx`

- [ ] **Step 1: Install react-router-dom**

```bash
cd services/board && bun add react-router-dom
```

Expected: `react-router-dom` appears in `package.json` dependencies.

- [ ] **Step 2: Create `src/router.tsx`**

```tsx
import { createBrowserRouter } from "react-router-dom"
import { App as AppShell } from "./App"  // temporary — swapped in Task 9

export const router = createBrowserRouter([
  { path: "/", element: <AppShell /> },
])
```

- [ ] **Step 3: Move existing layout into a temporary file**

The current `App.tsx` layout logic needs to live somewhere while we build `AppShell`. Copy the current `App.tsx` content to `src/AppShell.tsx` — we will gut and replace it in Task 7, but having it there prevents import errors.

```bash
cp services/board/src/App.tsx services/board/src/AppShell.tsx
```

Then update `src/AppShell.tsx`: rename the exported function from `App` to `AppShell`.

```tsx
// src/AppShell.tsx — rename only, full rewrite comes in Task 7
export function AppShell() {
  // ... existing App body unchanged for now
}
```

Update `router.tsx` to import from `AppShell`:

```tsx
import { AppShell } from "./AppShell"
// ...
{ path: "/", element: <AppShell /> },
```

- [ ] **Step 4: Update `src/App.tsx` to use RouterProvider**

Now replace `App.tsx`:

```tsx
import { RouterProvider } from "react-router-dom"
import { router } from "./router"

export function App() {
  return <RouterProvider router={router} />
}
```

```tsx
// src/AppShell.tsx — rename only, full rewrite comes in Task 7
export function AppShell() {
  // ... existing App body unchanged for now
}
```

Update `router.tsx` to import from `AppShell`:

```tsx
import { AppShell } from "./AppShell"
// ...
{ path: "/", element: <AppShell /> },
```

- [ ] **Step 5: Run the test suite to confirm nothing broke**

```bash
cd services/board && bun run test --run
```

Expected: all 75 tests pass. If router-related tests fail, check that `makeWrapper()` helpers in test files don't need `MemoryRouter` — they shouldn't since stores are tested in isolation and components are tested with their own wrappers.

- [ ] **Step 6: Commit**

```bash
git add services/board/src/router.tsx services/board/src/App.tsx services/board/src/AppShell.tsx services/board/package.json services/board/bun.lockb
git commit -m "feat(board): add react-router-dom, scaffold / route"
```

---

## Task 2: settingsStore with persist and theme side effect

Creates the settings store. Applying `data-theme` to `document.documentElement` is a side effect inside each setter — this keeps the DOM in sync without needing a React effect.

**Files:**
- Create: `services/board/src/stores/settingsStore.ts`
- Create: `services/board/src/stores/__tests__/settingsStore.test.ts`

- [ ] **Step 1: Write failing tests**

Create `services/board/src/stores/__tests__/settingsStore.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { useSettingsStore } from "../settingsStore"

function resetStore() {
  localStorage.clear()
  useSettingsStore.setState({
    theme: "system",
    layoutMode: "split",
    chatSide: "left",
  })
  document.documentElement.removeAttribute("data-theme")
}

beforeEach(resetStore)
afterEach(resetStore)

it("has correct defaults", () => {
  const s = useSettingsStore.getState()
  expect(s.theme).toBe("system")
  expect(s.layoutMode).toBe("split")
  expect(s.chatSide).toBe("left")
})

it("setTheme('dark') applies data-theme=dark to <html>", () => {
  useSettingsStore.getState().setTheme("dark")
  expect(document.documentElement.dataset.theme).toBe("dark")
})

it("setTheme('light') applies data-theme=light to <html>", () => {
  useSettingsStore.getState().setTheme("light")
  expect(document.documentElement.dataset.theme).toBe("light")
})

it("setTheme('system') removes data-theme attribute", () => {
  document.documentElement.dataset.theme = "dark"
  useSettingsStore.getState().setTheme("system")
  expect(document.documentElement.dataset.theme).toBeUndefined()
})

it("setLayoutMode updates layoutMode", () => {
  useSettingsStore.getState().setLayoutMode("tabbed")
  expect(useSettingsStore.getState().layoutMode).toBe("tabbed")
})

it("setChatSide updates chatSide", () => {
  useSettingsStore.getState().setChatSide("right")
  expect(useSettingsStore.getState().chatSide).toBe("right")
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd services/board && bun run test --run src/stores/__tests__/settingsStore.test.ts
```

Expected: FAIL — `settingsStore` does not exist yet.

- [ ] **Step 3: Create `src/stores/settingsStore.ts`**

```ts
import { create } from "zustand"
import { persist } from "zustand/middleware"

type Theme = "light" | "dark" | "system"
type LayoutMode = "split" | "tabbed"
type ChatSide = "left" | "right"

interface SettingsState {
  theme: Theme
  layoutMode: LayoutMode
  chatSide: ChatSide
  setTheme: (theme: Theme) => void
  setLayoutMode: (mode: LayoutMode) => void
  setChatSide: (side: ChatSide) => void
}

function applyTheme(theme: Theme) {
  if (theme === "system") {
    delete document.documentElement.dataset.theme
  } else {
    document.documentElement.dataset.theme = theme
  }
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: "system",
      layoutMode: "split",
      chatSide: "left",
      setTheme: (theme) => {
        applyTheme(theme)
        set({ theme })
      },
      setLayoutMode: (layoutMode) => set({ layoutMode }),
      setChatSide: (chatSide) => set({ chatSide }),
    }),
    { name: "nova-settings" }
  )
)

// Apply theme on store initialization (page load)
applyTheme(useSettingsStore.getState().theme)
```

- [ ] **Step 4: Run tests**

```bash
bun run test --run src/stores/__tests__/settingsStore.test.ts
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add services/board/src/stores/settingsStore.ts services/board/src/stores/__tests__/settingsStore.test.ts
git commit -m "feat(board): add settingsStore with persist and theme side effect"
```

---

## Task 3: uiStore — add activeTab, remove chatOpen

`chatOpen` and `toggleChat` are replaced by `activeTab` / `setActiveTab`. Existing tests don't test `chatOpen` (they were written before it was added), so the test file just needs `activeTab` tests added and the `beforeEach` reset updated.

**Files:**
- Modify: `services/board/src/stores/uiStore.ts`
- Modify: `services/board/src/stores/__tests__/uiStore.test.ts`

- [ ] **Step 1: Add activeTab tests to `uiStore.test.ts`**

Open `services/board/src/stores/__tests__/uiStore.test.ts`. Update the `beforeEach` reset and add two tests:

```ts
beforeEach(() => {
  useUIStore.setState({
    selectedTaskId: null,
    toast: null,
    activeFilters: {},
    activeTab: "chat",   // add this line
  })
})

// Add these two tests after the existing ones:
it("setActiveTab updates activeTab", () => {
  useUIStore.getState().setActiveTab("board")
  expect(useUIStore.getState().activeTab).toBe("board")
})

it("activeTab defaults to chat", () => {
  expect(useUIStore.getState().activeTab).toBe("chat")
})
```

- [ ] **Step 2: Run to verify new tests fail**

```bash
bun run test --run src/stores/__tests__/uiStore.test.ts
```

Expected: 2 new tests FAIL — `activeTab` not yet defined.

- [ ] **Step 3: Update `src/stores/uiStore.ts`**

Replace the file:

```ts
import { create } from "zustand"
import type { BoardFilters } from "../api/board"

type ActiveTab = "chat" | "board"

interface UIState {
  selectedTaskId: string | null
  toast: string | null
  activeFilters: BoardFilters
  activeTab: ActiveTab
  setSelectedTask: (id: string | null) => void
  setToast: (msg: string | null) => void
  setFilters: (filters: BoardFilters) => void
  setActiveTab: (tab: ActiveTab) => void
}

export const useUIStore = create<UIState>(set => ({
  selectedTaskId: null,
  toast: null,
  activeFilters: {},
  activeTab: "chat",
  setSelectedTask: id => set({ selectedTaskId: id }),
  setToast: msg => set({ toast: msg }),
  setFilters: filters => set({ activeFilters: filters }),
  setActiveTab: tab => set({ activeTab: tab }),
}))
```

- [ ] **Step 4: Run all tests — expect ChatPanel tests to fail**

```bash
bun run test --run
```

Expected: uiStore tests pass. ChatPanel tests fail because they reference `chatOpen`. That's expected — we fix those in Task 6.

- [ ] **Step 5: Commit**

```bash
git add services/board/src/stores/uiStore.ts services/board/src/stores/__tests__/uiStore.test.ts
git commit -m "feat(board): replace chatOpen/toggleChat with activeTab/setActiveTab in uiStore"
```

---

## Task 4: chatStore — add persist middleware

Only `conversationId` is persisted. Streaming state (`isStreaming`, `streamingContent`) is ephemeral and must not be persisted. The existing tests use `useChatStore.setState()` directly which bypasses persist — they continue to work, but `beforeEach` must clear localStorage to prevent state leaking between tests.

**Files:**
- Modify: `services/board/src/stores/chatStore.ts`
- Modify: `services/board/src/stores/__tests__/chatStore.test.ts`

- [ ] **Step 1: Update `chatStore.test.ts` to clear localStorage**

Add `localStorage.clear()` to the `beforeEach`:

```ts
beforeEach(() => {
  localStorage.clear()
  useChatStore.setState({
    conversationId: null,
    streamingContent: "",
    isStreaming: false,
  })
})
```

- [ ] **Step 2: Run to confirm existing tests still pass**

```bash
bun run test --run src/stores/__tests__/chatStore.test.ts
```

Expected: all 4 pass. (localStorage.clear is safe even without persist.)

- [ ] **Step 3: Update `src/stores/chatStore.ts`**

```ts
import { create } from "zustand"
import { persist } from "zustand/middleware"

interface ChatState {
  conversationId: string | null
  streamingContent: string
  isStreaming: boolean
  setConversation: (id: string | null) => void
  startStreaming: () => void
  appendDelta: (delta: string) => void
  finishStreaming: () => void
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      conversationId: null,
      streamingContent: "",
      isStreaming: false,
      setConversation: id => set({ conversationId: id }),
      startStreaming: () => set({ isStreaming: true, streamingContent: "" }),
      appendDelta: delta => set(s => ({ streamingContent: s.streamingContent + delta })),
      finishStreaming: () => set({ isStreaming: false, streamingContent: "" }),
    }),
    {
      name: "nova-chat",
      partialize: (state) => ({ conversationId: state.conversationId }),
    }
  )
)
```

- [ ] **Step 4: Run tests**

```bash
bun run test --run src/stores/__tests__/chatStore.test.ts
```

Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add services/board/src/stores/chatStore.ts services/board/src/stores/__tests__/chatStore.test.ts
git commit -m "feat(board): persist conversationId in chatStore across page reloads"
```

---

## Task 5: CSS — theme overrides and AppShell layout classes

Updates `tokens.css` to support `data-theme` attribute overrides and adds layout classes for the AppShell to `global.css`. No tests for CSS — verified visually in Task 10.

**Files:**
- Modify: `services/board/src/styles/tokens.css`
- Modify: `services/board/src/styles/global.css`

- [ ] **Step 1: Update `tokens.css`**

After the existing `:root` block and the `@media (prefers-color-scheme: dark)` block, add:

```css
[data-theme="light"] {
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
}

[data-theme="dark"] {
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
```

- [ ] **Step 2: Add AppShell layout classes to `global.css`**

Add after the existing `.board-with-detail` block:

```css
/* AppShell */
.app-shell {
  display: flex;
  height: 100vh;
  flex-direction: column;
  overflow: hidden;
}

.app-shell__header {
  padding: 0 16px;
  border-bottom: 1px solid var(--bg-card-border);
  display: flex;
  align-items: center;
  gap: 0;
  flex-shrink: 0;
  height: 48px;
}

.app-shell__title {
  font-weight: 700;
  font-size: 15px;
  margin-right: 16px;
  flex-shrink: 0;
}

.app-shell__body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* Split layout */
.app-shell__chat-pane {
  width: 320px;
  flex-shrink: 0;
  border-right: 1px solid var(--bg-card-border);
  display: flex;
  flex-direction: column;
}

.app-shell__chat-pane--right {
  border-right: none;
  border-left: 1px solid var(--bg-card-border);
  order: 1;
}

.app-shell__board-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

/* Tabbed layout */
.app-shell__tabs {
  display: flex;
  align-items: stretch;
  margin-right: 16px;
}

.app-shell__tab {
  padding: 0 16px;
  height: 100%;
  display: flex;
  align-items: center;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  border: none;
  background: none;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}

.app-shell__tab--active {
  color: var(--accent-blue);
  border-bottom-color: var(--accent-blue);
}

.app-shell__tab-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* Settings gear link */
.app-shell__settings-link {
  margin-left: auto;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 16px;
  padding: 8px;
  line-height: 1;
  border-radius: var(--radius);
}

.app-shell__settings-link:hover {
  color: var(--text);
  background: var(--accent-gray-bg);
}

/* Responsive: force tabbed below 900px */
@media (max-width: 899px) {
  .app-shell__chat-pane,
  .app-shell__board-pane {
    width: 100% !important;
    border: none !important;
  }
}

/* Settings page */
.settings-page {
  max-width: 520px;
  margin: 0 auto;
  padding: 32px 24px;
}

.settings-page__back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--accent-blue);
  text-decoration: none;
  margin-bottom: 16px;
}

.settings-page__title {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 32px;
}

.settings-section {
  margin-bottom: 32px;
}

.settings-section__label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin-bottom: 12px;
  padding-left: 4px;
}

.settings-group {
  border: 1px solid var(--bg-card-border);
  border-radius: 8px;
  overflow: hidden;
}

.settings-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--bg-card-border);
}

.settings-row:last-child {
  border-bottom: none;
}

.settings-row--dimmed {
  opacity: 0.5;
}

.settings-row__label { font-size: 14px; font-weight: 500; }

.settings-row__desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 3px;
}

.seg-control {
  display: flex;
  border: 1px solid var(--bg-card-border);
  border-radius: 6px;
  overflow: hidden;
  font-size: 12px;
  font-weight: 500;
}

.seg-control__btn {
  padding: 6px 14px;
  color: var(--text-muted);
  background: none;
  border: none;
  border-left: 1px solid var(--bg-card-border);
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
}

.seg-control__btn:first-child { border-left: none; }

.seg-control__btn--active {
  background: var(--accent-blue);
  color: #fff;
}
```

- [ ] **Step 3: Run tests to confirm no breakage**

```bash
bun run test --run
```

Expected: same pass/fail count as before (ChatPanel tests still failing from Task 3 — that's expected until Task 6).

- [ ] **Step 4: Commit**

```bash
git add services/board/src/styles/tokens.css services/board/src/styles/global.css
git commit -m "feat(board): add data-theme CSS overrides and AppShell/Settings layout classes"
```

---

## Task 6: ChatPanel — remove chatOpen guard and close button

`ChatPanel` becomes structurally always-rendered. The `chatOpen` / `toggleChat` references are removed. Tests are rewritten: the "does not render" and "close button" tests are removed; a basic render test replaces them.

**Files:**
- Modify: `services/board/src/components/Chat/ChatPanel.tsx`
- Modify: `services/board/src/components/Chat/__tests__/ChatPanel.test.tsx`

- [ ] **Step 1: Update ChatPanel tests**

Replace `services/board/src/components/Chat/__tests__/ChatPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { ChatPanel } from "../ChatPanel"
import { useChatStore } from "../../../stores/chatStore"
import * as chatApi from "../../../api/chat"

vi.mock("../../../api/chat")

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => {
  localStorage.clear()
  useChatStore.setState({ conversationId: "c1", streamingContent: "", isStreaming: false })
  vi.mocked(chatApi.getMessages).mockResolvedValue({ messages: [] })
})

it("renders the chat region", () => {
  render(<ChatPanel />, { wrapper: makeWrapper() })
  expect(screen.getByRole("region", { name: /chat/i })).toBeInTheDocument()
})

it("renders message bubbles from query data", async () => {
  vi.mocked(chatApi.getMessages).mockResolvedValue({
    messages: [{ id: "m1", role: "assistant", content: "Hello", created_at: "" }],
  })
  render(<ChatPanel />, { wrapper: makeWrapper() })
  expect(await screen.findByText("Hello")).toBeInTheDocument()
})

it("shows streaming bubble while isStreaming", () => {
  useChatStore.setState({ conversationId: "c1", streamingContent: "typing...", isStreaming: true })
  render(<ChatPanel />, { wrapper: makeWrapper() })
  expect(screen.getByText("typing...")).toBeInTheDocument()
})
```

- [ ] **Step 2: Run new tests — expect failures**

```bash
bun run test --run src/components/Chat/__tests__/ChatPanel.test.tsx
```

Expected: tests 1 and 3 pass (ChatPanel still has `if (!chatOpen) return null` but test 1 will fail since chatOpen defaults to false and is now not in uiStore). Actually all may fail/error due to `chatOpen` reference in ChatPanel — that's expected.

- [ ] **Step 3: Update `src/components/Chat/ChatPanel.tsx`**

Remove the `useUIStore` import (no longer needed). Remove `chatOpen`, `toggleChat` from the component. Remove `if (!chatOpen) return null`. Remove the close button from the header. Remove `handleToggleChat` logic from `App.tsx` imports.

```tsx
import { useEffect, useRef } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useShallow } from "zustand/react/shallow"
import { useChatStore } from "../../stores/chatStore"
import { getMessages, sendMessageStream } from "../../api/chat"
import { ChatInput } from "./ChatInput"
import { MessageBubble } from "./MessageBubble"

export function ChatPanel() {
  const { conversationId, streamingContent, isStreaming, startStreaming, appendDelta, finishStreaming } =
    useChatStore(
      useShallow(s => ({
        conversationId: s.conversationId,
        streamingContent: s.streamingContent,
        isStreaming: s.isStreaming,
        startStreaming: s.startStreaming,
        appendDelta: s.appendDelta,
        finishStreaming: s.finishStreaming,
      }))
    )
  const queryClient = useQueryClient()
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () => (conversationId ? getMessages(conversationId) : Promise.resolve({ messages: [] })),
    enabled: !!conversationId,
  })

  const messages = data?.messages ?? []

  useEffect(() => {
    if (bottomRef.current && typeof bottomRef.current.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [messages, streamingContent])

  async function handleSend(content: string) {
    if (!conversationId || isStreaming) return
    startStreaming()
    try {
      for await (const event of sendMessageStream(conversationId, content)) {
        if ("delta" in event) appendDelta(event.delta)
      }
    } catch {
      // fetch or parse error
    } finally {
      finishStreaming()
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] })
    }
  }

  return (
    <section className="chat-panel" aria-label="Chat">
      <div className="chat-panel__header">
        <span className="chat-panel__title">Nova</span>
      </div>

      <div className="chat-panel__messages">
        {messages.map(m => (
          <MessageBubble key={m.id} role={m.role} content={m.content} />
        ))}
        {isStreaming && (
          <MessageBubble role="assistant" content={streamingContent} streaming={true} />
        )}
        <div ref={bottomRef} />
      </div>

      <ChatInput onSend={handleSend} disabled={isStreaming} />
    </section>
  )
}
```

- [ ] **Step 4: Run ChatPanel tests**

```bash
bun run test --run src/components/Chat/__tests__/ChatPanel.test.tsx
```

Expected: all 3 pass.

- [ ] **Step 5: Run full suite**

```bash
bun run test --run
```

Expected: all tests pass. If any component test references `chatOpen` or `toggleChat` in uiStore setup, update its `beforeEach` to remove those fields.

- [ ] **Step 6: Commit**

```bash
git add services/board/src/components/Chat/ChatPanel.tsx services/board/src/components/Chat/__tests__/ChatPanel.test.tsx
git commit -m "feat(board): make ChatPanel structural — remove chatOpen guard and close button"
```

---

## Task 7: AppShell — layout wrapper

Replaces the stub `AppShell.tsx` (which currently has the old App layout) with the real split/tabbed layout. The `useIsNarrow` hook is defined locally in this file — it's only used here.

**Files:**
- Modify: `services/board/src/AppShell.tsx` (full rewrite)
- Create: `services/board/src/components/__tests__/AppShell.test.tsx`

- [ ] **Step 1: Write AppShell tests**

Create `services/board/src/components/__tests__/AppShell.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { AppShell } from "../../AppShell"
import { useSettingsStore } from "../../stores/settingsStore"
import { useUIStore } from "../../stores/uiStore"
import { useChatStore } from "../../stores/chatStore"

// Mock child components to keep tests fast and focused
vi.mock("../../components/Board/Board", () => ({ Board: () => <div data-testid="board" /> }))
vi.mock("../../components/Chat/ChatPanel", () => ({ ChatPanel: () => <div data-testid="chat-panel" /> }))
vi.mock("../../components/TaskDetail/TaskDetail", () => ({ TaskDetail: () => null }))
vi.mock("../../components/shared/FilterBar", () => ({ FilterBar: () => <div data-testid="filter-bar" /> }))
vi.mock("../../components/shared/Toast", () => ({ Toast: () => null }))
vi.mock("../../api/chat", () => ({
  createConversation: vi.fn().mockResolvedValue({ id: "c1", title: "New Chat", created_at: "", updated_at: "", message_count: 0 }),
}))

// Mock matchMedia (not available in jsdom)
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })),
})

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(MemoryRouter, {}, createElement(QueryClientProvider, { client: qc }, children))
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ layoutMode: "split", chatSide: "left", theme: "system" })
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {}, activeTab: "chat" })
  useChatStore.setState({ conversationId: null, streamingContent: "", isStreaming: false })
})

it("renders chat panel and board in split mode", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByTestId("chat-panel")).toBeInTheDocument()
  expect(screen.getByTestId("board")).toBeInTheDocument()
})

it("renders tab buttons in tabbed mode", () => {
  useSettingsStore.setState({ layoutMode: "tabbed", chatSide: "left", theme: "system" })
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByRole("button", { name: /chat/i })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /board/i })).toBeInTheDocument()
})

it("clicking Board tab in tabbed mode shows board", () => {
  useSettingsStore.setState({ layoutMode: "tabbed", chatSide: "left", theme: "system" })
  render(<AppShell />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /board/i }))
  expect(screen.getByTestId("board")).toBeInTheDocument()
  expect(screen.queryByTestId("chat-panel")).not.toBeInTheDocument()
})

it("settings gear link is present", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByRole("link", { name: /settings/i })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify tests fail**

```bash
bun run test --run src/components/__tests__/AppShell.test.tsx
```

Expected: FAIL — AppShell doesn't have the new layout yet.

- [ ] **Step 3: Rewrite `src/AppShell.tsx`**

```tsx
import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useShallow } from "zustand/react/shallow"
import { useSettingsStore } from "./stores/settingsStore"
import { useUIStore } from "./stores/uiStore"
import { useChatStore } from "./stores/chatStore"
import { Board } from "./components/Board/Board"
import { FilterBar } from "./components/shared/FilterBar"
import { TaskDetail } from "./components/TaskDetail/TaskDetail"
import { Toast } from "./components/shared/Toast"
import { ChatPanel } from "./components/Chat/ChatPanel"
import { createConversation } from "./api/chat"

function useIsNarrow(breakpoint = 900): boolean {
  const [isNarrow, setIsNarrow] = useState(() => window.innerWidth < breakpoint)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
    const handler = (e: MediaQueryListEvent) => setIsNarrow(e.matches)
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [breakpoint])
  return isNarrow
}

export function AppShell() {
  const { layoutMode, chatSide } = useSettingsStore(
    useShallow(s => ({ layoutMode: s.layoutMode, chatSide: s.chatSide }))
  )
  const { toast, setToast, activeTab, setActiveTab } = useUIStore(
    useShallow(s => ({ toast: s.toast, setToast: s.setToast, activeTab: s.activeTab, setActiveTab: s.setActiveTab }))
  )
  const setConversation = useChatStore(s => s.setConversation)

  const isNarrow = useIsNarrow()
  const effectiveMode = isNarrow ? "tabbed" : layoutMode

  useEffect(() => {
    // Read conversationId inside the effect to avoid stale closure.
    // Zustand persist rehydrates synchronously from localStorage before first render,
    // so getState() here reflects the restored value.
    if (!useChatStore.getState().conversationId) {
      createConversation().then(conv => setConversation(conv.id))
    }
  }, [])

  const isSplit = effectiveMode === "split"

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <span className="app-shell__title">Nova Board</span>

        {isSplit ? (
          <FilterBar />
        ) : (
          <nav className="app-shell__tabs">
            <button
              className={`app-shell__tab${activeTab === "chat" ? " app-shell__tab--active" : ""}`}
              onClick={() => setActiveTab("chat")}
            >
              Chat
            </button>
            <button
              className={`app-shell__tab${activeTab === "board" ? " app-shell__tab--active" : ""}`}
              onClick={() => setActiveTab("board")}
            >
              Board
            </button>
          </nav>
        )}

        {!isSplit && activeTab === "board" && <FilterBar />}

        <Link to="/settings" className="app-shell__settings-link" aria-label="Settings">
          ⚙
        </Link>
      </header>

      <div className="app-shell__body">
        {isSplit ? (
          <>
            <div className={`app-shell__chat-pane${chatSide === "right" ? " app-shell__chat-pane--right" : ""}`}>
              <ChatPanel />
            </div>
            <div className="app-shell__board-pane">
              <div className="board-with-detail">
                <Board />
                <TaskDetail />
              </div>
            </div>
          </>
        ) : (
          <div className="app-shell__tab-content">
            {activeTab === "chat" ? (
              <ChatPanel />
            ) : (
              <div className="board-with-detail">
                <Board />
                <TaskDetail />
              </div>
            )}
          </div>
        )}
      </div>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
```

- [ ] **Step 4: Run AppShell tests**

```bash
bun run test --run src/components/__tests__/AppShell.test.tsx
```

Expected: all 4 pass.

- [ ] **Step 5: Run full suite**

```bash
bun run test --run
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/board/src/AppShell.tsx services/board/src/components/__tests__/AppShell.test.tsx
git commit -m "feat(board): add AppShell with split/tabbed layout driven by settingsStore"
```

---

## Task 8: Settings page

Three segmented controls in two grouped sections. Changes apply immediately (no save button). The `chatSide` row is dimmed but interactive when `layoutMode` is `tabbed`.

**Files:**
- Create: `services/board/src/components/Settings/Settings.tsx`
- Create: `services/board/src/components/Settings/__tests__/Settings.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `services/board/src/components/Settings/__tests__/Settings.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, beforeEach } from "vitest"
import { MemoryRouter } from "react-router-dom"
import { createElement } from "react"
import { Settings } from "../Settings"
import { useSettingsStore } from "../../../stores/settingsStore"

function makeWrapper() {
  return ({ children }: { children: React.ReactNode }) =>
    createElement(MemoryRouter, {}, children)
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ theme: "system", layoutMode: "split", chatSide: "left" })
})

it("renders all three setting rows", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  expect(screen.getByText("Theme")).toBeInTheDocument()
  expect(screen.getByText("Mode")).toBeInTheDocument()
  expect(screen.getByText("Chat side")).toBeInTheDocument()
})

it("clicking Dark theme button updates settingsStore", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /^dark$/i }))
  expect(useSettingsStore.getState().theme).toBe("dark")
})

it("clicking Tabbed mode button updates settingsStore", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /^tabbed$/i }))
  expect(useSettingsStore.getState().layoutMode).toBe("tabbed")
})

it("clicking Right chat side button updates settingsStore", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /^right$/i }))
  expect(useSettingsStore.getState().chatSide).toBe("right")
})

it("chat side row is dimmed when mode is tabbed", () => {
  useSettingsStore.setState({ theme: "system", layoutMode: "tabbed", chatSide: "left" })
  render(<Settings />, { wrapper: makeWrapper() })
  const chatSideRow = screen.getByText("Chat side").closest(".settings-row")
  expect(chatSideRow).toHaveClass("settings-row--dimmed")
})

it("back link points to /", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/")
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
bun run test --run src/components/Settings/__tests__/Settings.test.tsx
```

Expected: FAIL — `Settings` does not exist.

- [ ] **Step 3: Create `src/components/Settings/Settings.tsx`**

```tsx
import { Link } from "react-router-dom"
import { useShallow } from "zustand/react/shallow"
import { useSettingsStore } from "../../stores/settingsStore"

type SegOption<T extends string> = { label: string; value: T }

function SegControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: SegOption<T>[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="seg-control">
      {options.map(opt => (
        <button
          key={opt.value}
          className={`seg-control__btn${value === opt.value ? " seg-control__btn--active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export function Settings() {
  const { theme, layoutMode, chatSide, setTheme, setLayoutMode, setChatSide } = useSettingsStore(
    useShallow(s => ({
      theme: s.theme,
      layoutMode: s.layoutMode,
      chatSide: s.chatSide,
      setTheme: s.setTheme,
      setLayoutMode: s.setLayoutMode,
      setChatSide: s.setChatSide,
    }))
  )

  return (
    <div className="settings-page">
      <Link to="/" className="settings-page__back">← Back to board</Link>
      <h1 className="settings-page__title">Settings</h1>

      <section className="settings-section">
        <div className="settings-section__label">Appearance</div>
        <div className="settings-group">
          <div className="settings-row">
            <div>
              <div className="settings-row__label">Theme</div>
              <div className="settings-row__desc">Override your system setting</div>
            </div>
            <SegControl
              options={[
                { label: "Light", value: "light" },
                { label: "Dark",  value: "dark"  },
                { label: "System", value: "system" },
              ]}
              value={theme}
              onChange={setTheme}
            />
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section__label">Layout</div>
        <div className="settings-group">
          <div className="settings-row">
            <div>
              <div className="settings-row__label">Mode</div>
              <div className="settings-row__desc">Side-by-side or full-screen tabs</div>
            </div>
            <SegControl
              options={[
                { label: "Split",  value: "split"  },
                { label: "Tabbed", value: "tabbed" },
              ]}
              value={layoutMode}
              onChange={setLayoutMode}
            />
          </div>

          <div className={`settings-row${layoutMode === "tabbed" ? " settings-row--dimmed" : ""}`}>
            <div>
              <div className="settings-row__label">Chat side</div>
              <div className="settings-row__desc">Which side of the split</div>
            </div>
            <SegControl
              options={[
                { label: "Left",  value: "left"  },
                { label: "Right", value: "right" },
              ]}
              value={chatSide}
              onChange={setChatSide}
            />
          </div>
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Run Settings tests**

```bash
bun run test --run src/components/Settings/__tests__/Settings.test.tsx
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add services/board/src/components/Settings/Settings.tsx services/board/src/components/Settings/__tests__/Settings.test.tsx
git commit -m "feat(board): add Settings page with theme, layout mode, and chat side controls"
```

---

## Task 9: Wire router — add /settings route, clean up App.tsx

Connects `Settings` into the router. Updates `App.tsx` to wrap `RouterProvider`. Removes the old `board-layout` / `chat-toggle-btn` and `ChatPanel` usage from any remaining old App code.

**Files:**
- Modify: `services/board/src/router.tsx`
- Modify: `services/board/src/App.tsx`

- [ ] **Step 1: Update `src/router.tsx`**

```tsx
import { createBrowserRouter } from "react-router-dom"
import { AppShell } from "./AppShell"
import { Settings } from "./components/Settings/Settings"

export const router = createBrowserRouter([
  { path: "/",         element: <AppShell /> },
  { path: "/settings", element: <Settings /> },
])
```

- [ ] **Step 2: Confirm `src/App.tsx` is correct**

It should already read:

```tsx
import { RouterProvider } from "react-router-dom"
import { router } from "./router"

export function App() {
  return <RouterProvider router={router} />
}
```

If it doesn't, update it now.

- [ ] **Step 3: Run full test suite**

```bash
cd services/board && bun run test --run
```

Expected: all tests pass.

- [ ] **Step 4: TypeScript build check**

```bash
bun run build 2>&1 | head -30
```

Expected: build succeeds with no errors. If any TypeScript errors appear, fix them before proceeding.

- [ ] **Step 5: Commit**

```bash
git add services/board/src/router.tsx services/board/src/App.tsx
git commit -m "feat(board): wire /settings route; complete layout redesign"
```

---

## Task 10: End-to-end smoke test

Verifies the full app works in the browser with both layout modes, settings persistence, and theme switching.

**Prerequisites:** Docker services running (`cd infra && docker compose up -d`). Board built and served at `http://localhost:5173`.

- [ ] **Step 1: Rebuild the board container**

```bash
cd infra && docker compose up --build board -d
```

- [ ] **Step 2: Test split mode (default)**

Open `http://localhost:5173`. Confirm:
- Chat panel visible on the left (~320px wide)
- Board columns visible on the right, sized to content (not stretched)
- Gear icon (⚙) in the top-right of the header

- [ ] **Step 3: Test settings page**

Click ⚙. Confirm:
- URL changes to `http://localhost:5173/settings`
- Three settings rows visible with segmented controls
- "← Back to board" link works

- [ ] **Step 4: Test theme switching**

On the settings page, click "Dark" then "Light" then "System". Confirm the app visually switches themes on each click without a page reload.

- [ ] **Step 5: Test tabbed mode**

Click "Tabbed" under Mode. Click "← Back to board". Confirm:
- Chat and Board tabs appear in the header
- Clicking Board tab shows the board, clicking Chat tab shows chat
- Filters appear only when Board tab is active

- [ ] **Step 6: Test settings persistence**

While in tabbed mode with Dark theme, hard-refresh the page (`Ctrl+Shift+R`). Confirm the app loads in tabbed + dark mode — settings survived the reload.

- [ ] **Step 7: Test chat side (split mode)**

Go to settings, switch to Split mode. Change Chat Side to "Right". Return to board. Confirm chat panel appears on the right.

- [ ] **Step 8: Test responsive fallback**

Resize the browser window below 900px width. Confirm the layout switches to tabbed regardless of the Mode setting.

- [ ] **Step 9: Commit any fixes found during smoke test**

```bash
git add <changed files>
git commit -m "fix: <description of smoke test fix>"
```
