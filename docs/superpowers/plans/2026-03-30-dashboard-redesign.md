# Dashboard Redesign: Mission Flow + Living Observatory

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Chat and Brain pages to match the two approved design directions: "Mission Flow" (spacious chat + collapsible context panel) and "Living Observatory" (embedded chat in the brain graph with HUD widgets and live node activation).

**Architecture:** The Chat page gains two new panels (ThreadRail on the left, ContextPanel on the right) while preserving all existing chat functionality (streaming, voice, file attachments, delegation cards). The Brain page's existing BrainChat overlay (416 lines, already functional) is restyled with glass-morphism and gains HUD widgets. No new backend APIs required — thread list uses the existing conversations API, context panel reads from the existing activity step stream, and brain HUD reads from existing engram stats.

**Tech Stack:** React 18, TypeScript, Tailwind CSS (stone/teal/amber palette), TanStack Query, existing SSE streaming, existing ForceGraph3D with UnrealBloomPass

**Design References:**
- Chat: `~/.gstack/projects/arialabs-nova/designs/chat-missionflow-20260330/finalized.html`
- Brain: `~/.gstack/projects/arialabs-nova/designs/brain-livingobservatory-20260330/finalized.html`

---

## File Structure

### New Files
- `dashboard/src/components/chat/ThreadRail.tsx` — Collapsible conversation list sidebar (4px collapsed, 260px on hover)
- `dashboard/src/components/chat/ContextPanel.tsx` — Right panel showing active tasks, memory hits, tool calls
- `dashboard/src/components/brain/HudWidgets.tsx` — System status + active topics HUD overlays
- `dashboard/src/components/brain/HudBar.tsx` — Top bar with stats, search, settings, chat toggle

### Modified Files
- `dashboard/src/pages/chat/ChatPage.tsx` — Restructure layout to 4-panel (sidebar + rail + chat + context)
- `dashboard/src/pages/chat/ChatInput.tsx` — Styling updates to match Mission Flow design
- `dashboard/src/pages/chat/MessageBubble.tsx` — Restyle bubbles (teal border on AI, breathing room, tool call blocks)
- `dashboard/src/pages/Brain.tsx` — Integrate new HUD components, restyle layout
- `dashboard/src/components/BrainChat.tsx` — Glass-morphism overlay styling, activation annotations
- `dashboard/src/components/ForceGraph3D.tsx` — No changes needed (existing highlightNodes API is sufficient)
- `dashboard/src/stores/chat-store.tsx` — Add conversation list state for ThreadRail

### Unchanged (but referenced)
- `dashboard/src/api.ts` — Already has `streamChat()`, conversation CRUD, model discovery
- `dashboard/src/components/layout/AppLayout.tsx` — Chat uses `fullWidth` mode, Brain bypasses it entirely
- `dashboard/src/hooks/useVoiceChat.ts` — Preserved as-is
- `dashboard/src/hooks/useFileAttach.ts` — Preserved as-is

---

## Phase 1: Chat Page — Mission Flow

### Task 1: ThreadRail Component

**Files:**
- Create: `dashboard/src/components/chat/ThreadRail.tsx`
- Modify: `dashboard/src/stores/chat-store.tsx` (add conversations list)

- [ ] **Step 1: Create ThreadRail component skeleton**

Create `dashboard/src/components/chat/ThreadRail.tsx`:

```tsx
import { useState } from 'react'
import { useChatStore } from '../../stores/chat-store'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../../api'
import { Search, Plus } from 'lucide-react'

interface Conversation {
  id: string
  title: string | null
  preview: string | null
  updated_at: string
  message_count: number
}

export function ThreadRail() {
  const { conversationId, loadConversation, newConversation } = useChatStore()
  const [search, setSearch] = useState('')

  const { data: conversations = [] } = useQuery<Conversation[]>({
    queryKey: ['conversations'],
    queryFn: () => apiFetch<Conversation[]>('/api/v1/conversations?limit=20'),
    staleTime: 10_000,
  })

  const filtered = search
    ? conversations.filter(c =>
        (c.title ?? '').toLowerCase().includes(search.toLowerCase())
      )
    : conversations

  return (
    <div className="thread-rail group h-full shrink-0 relative z-40">
      {/* Collapsed strip */}
      <div className="w-1 h-full bg-teal-800 group-hover:hidden" />

      {/* Expanded panel */}
      <div className="absolute inset-y-0 left-0 w-0 group-hover:w-[260px] overflow-hidden
                      bg-stone-800 border-r border-stone-700
                      transition-[width] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)]">
        <div className="w-[260px] h-full flex flex-col p-3 gap-2
                        opacity-0 group-hover:opacity-100 transition-opacity duration-150 delay-50">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-stone-500" />
            <input
              type="text"
              placeholder="Search threads..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 bg-stone-700 border border-transparent
                         focus:border-teal-500 rounded-lg text-[13px] text-stone-300
                         placeholder:text-stone-500 outline-none"
            />
          </div>

          {/* New Chat */}
          <button
            onClick={() => newConversation()}
            className="w-full flex items-center justify-center gap-2 py-2 px-3
                       bg-teal-500 hover:bg-teal-600 text-white text-[13px] font-semibold
                       rounded-lg transition-colors duration-150"
          >
            <Plus className="w-4 h-4" />
            New Chat
          </button>

          {/* Thread list */}
          <div className="flex-1 overflow-y-auto space-y-0.5">
            {filtered.map(conv => (
              <button
                key={conv.id}
                onClick={() => loadConversation(conv.id)}
                className={`w-full text-left px-3 py-2.5 rounded-md border-l-2 transition-colors duration-100
                  ${conv.id === conversationId
                    ? 'border-teal-500 bg-teal-900/15'
                    : 'border-transparent hover:bg-stone-700/40'}`}
              >
                <div className="text-sm font-semibold text-stone-200 truncate">
                  {conv.title ?? `Conversation ${conv.id.slice(0, 8)}`}
                </div>
                {conv.preview && (
                  <div className="text-xs text-stone-500 truncate mt-0.5">
                    {conv.preview}
                  </div>
                )}
                <div className="text-[11px] font-mono text-stone-500 mt-0.5">
                  {formatRelativeTime(conv.updated_at)}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days === 1) return 'yesterday'
  return `${days}d ago`
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/chat/ThreadRail.tsx
git commit -m "feat(dashboard): add ThreadRail conversation sidebar component"
```

---

### Task 2: ContextPanel Component

**Files:**
- Create: `dashboard/src/components/chat/ContextPanel.tsx`

This panel reads from the chat store's activity steps (already streamed via SSE) to show what Nova is doing in real time.

- [ ] **Step 1: Create ContextPanel component**

Create `dashboard/src/components/chat/ContextPanel.tsx`:

```tsx
import { ChevronRight, Activity, Brain, Terminal, Loader2 } from 'lucide-react'
import type { ActivityStep, Message } from '../../stores/chat-store'

interface Props {
  messages: Message[]
  isStreaming: boolean
  collapsed: boolean
  onToggle: () => void
}

export function ContextPanel({ messages, isStreaming, collapsed, onToggle }: Props) {
  // Extract live state from the most recent assistant message
  const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
  const steps = lastAssistant?.activitySteps ?? []
  const engramIds = steps
    .filter(s => s.step === 'memory' && s.engram_ids?.length)
    .flatMap(s => s.engram_ids ?? [])

  // Only show when Nova is actively working
  const hasActivity = isStreaming || steps.some(s => s.state === 'running')

  if (collapsed) {
    return (
      <button
        onClick={onToggle}
        className="w-6 h-full flex items-center justify-center
                   border-l border-stone-700/60 hover:bg-stone-800/50
                   text-stone-500 hover:text-stone-300 transition-colors"
        aria-label="Expand context panel"
      >
        <ChevronRight className="w-3.5 h-3.5 rotate-180" />
      </button>
    )
  }

  return (
    <aside
      className="w-[340px] shrink-0 h-full flex
                 bg-stone-900/85 backdrop-blur-xl border-l border-stone-700/60"
      aria-label="Context panel"
    >
      {/* Collapse strip */}
      <button
        onClick={onToggle}
        className="w-6 shrink-0 flex items-center justify-center
                   border-r border-stone-700/30 hover:bg-stone-700/30
                   text-stone-500 hover:text-stone-300 transition-colors cursor-pointer"
        aria-label="Collapse context panel"
      >
        <ChevronRight className="w-3.5 h-3.5" />
      </button>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Active Tasks */}
        <ContextSection icon={Activity} title="ACTIVE TASKS" count={steps.filter(s => s.state === 'running').length}>
          {steps.map((step, i) => (
            <div key={i} className="py-2.5 border-t border-stone-700/30 first:border-0">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-medium text-stone-200 truncate">
                  {stepLabel(step)}
                </span>
                <span className={`text-[10px] font-mono font-semibold uppercase px-1.5 py-0.5 rounded
                  ${step.state === 'running'
                    ? 'bg-teal-500 text-white'
                    : 'bg-stone-700 text-stone-400'}`}>
                  {step.state === 'running' ? 'RUNNING' : 'DONE'}
                </span>
              </div>
              {step.detail && (
                <div className="text-[11px] text-stone-500 mt-1">{step.detail}</div>
              )}
              {step.elapsed_ms != null && (
                <div className="text-[11px] font-mono text-stone-500 mt-0.5">
                  {(step.elapsed_ms / 1000).toFixed(1)}s
                </div>
              )}
              {/* Progress bar */}
              <div className="h-[3px] bg-stone-700 rounded-full mt-1.5 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500
                    ${step.state === 'running' ? 'bg-teal-500 animate-pulse' : 'bg-stone-600'}`}
                  style={{ width: step.state === 'done' ? '100%' : '60%' }}
                />
              </div>
            </div>
          ))}
          {steps.length === 0 && (
            <div className="text-xs text-stone-500 py-2">No active tasks</div>
          )}
        </ContextSection>

        {/* Memory Hits */}
        {engramIds.length > 0 && (
          <ContextSection icon={Brain} title="MEMORY HITS" count={engramIds.length}>
            {engramIds.slice(0, 6).map((id, i) => (
              <div key={id} className="flex items-center gap-2 py-1 border-t border-stone-700/20 first:border-0">
                <span className="text-[13px] font-mono text-teal-400 w-8 shrink-0">
                  {/* Engram IDs don't carry relevance scores in activity steps,
                      so we show the index as a visual indicator */}
                </span>
                <span className="text-[13px] text-stone-200 truncate flex-1">
                  {id.slice(0, 12)}...
                </span>
              </div>
            ))}
          </ContextSection>
        )}

        {/* Tool Calls */}
        <ContextSection icon={Terminal} title="TOOL CALLS" count={steps.filter(s => s.step !== 'classifying' && s.step !== 'generating').length}>
          {steps
            .filter(s => s.detail && s.step !== 'classifying' && s.step !== 'generating')
            .map((step, i) => (
              <div key={i} className="flex items-center gap-2 py-1.5">
                {step.state === 'done' ? (
                  <span className="text-green-400 text-sm">&#10003;</span>
                ) : (
                  <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
                )}
                <span className="text-xs font-mono text-stone-300">{step.step}</span>
                <span className="text-xs font-mono text-stone-500 truncate flex-1">
                  {step.detail}
                </span>
                {step.elapsed_ms != null && (
                  <span className="text-[11px] font-mono text-stone-500 shrink-0">
                    {(step.elapsed_ms / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
            ))}
        </ContextSection>
      </div>
    </aside>
  )
}

function ContextSection({ icon: Icon, title, count, children }: {
  icon: React.ElementType; title: string; count: number; children: React.ReactNode
}) {
  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-3.5 h-3.5 text-stone-400" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-stone-400">
          {title}
        </span>
        <span className="text-[10px] font-mono px-1.5 py-0.5 bg-stone-700 rounded-full text-stone-400">
          {count}
        </span>
      </div>
      {children}
    </section>
  )
}

function stepLabel(step: ActivityStep): string {
  switch (step.step) {
    case 'classifying': return 'Classifying request'
    case 'memory': return 'Searching memory'
    case 'model': return 'Selecting model'
    case 'generating': return 'Generating response'
    default: return step.step
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -20`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/chat/ContextPanel.tsx
git commit -m "feat(dashboard): add ContextPanel component for live task/memory/tool display"
```

---

### Task 3: Restructure ChatPage Layout

**Files:**
- Modify: `dashboard/src/pages/chat/ChatPage.tsx`

The existing ChatPage is a single-column layout. We need to wrap it in a 4-panel structure: sidebar (handled by AppLayout) + thread rail + chat area + context panel.

- [ ] **Step 1: Add ThreadRail and ContextPanel imports to ChatPage**

At the top of `ChatPage.tsx`, add imports:

```tsx
import { ThreadRail } from '../../components/chat/ThreadRail'
import { ContextPanel } from '../../components/chat/ContextPanel'
```

- [ ] **Step 2: Add context panel state**

In the `Chat` component body, add:

```tsx
const [contextCollapsed, setContextCollapsed] = useLocalStorage('chat.contextCollapsed', false)
```

Import `useLocalStorage` if not already imported.

- [ ] **Step 3: Wrap the return JSX with the new layout**

The existing ChatPage return has a column layout. Wrap the entire chat area with the thread rail on the left and context panel on the right. The exact edit depends on the current JSX structure, but the pattern is:

```tsx
return (
  <div className="flex h-full w-full overflow-hidden">
    {/* Thread Rail - collapsible conversation list */}
    <ThreadRail />

    {/* Chat Area - existing content */}
    <div className="flex-1 flex flex-col min-w-0 relative">
      {/* ... existing chat header, messages, input ... */}
    </div>

    {/* Context Panel - live activity */}
    <ContextPanel
      messages={messages}
      isStreaming={isStreaming}
      collapsed={contextCollapsed}
      onToggle={() => setContextCollapsed(c => !c)}
    />
  </div>
)
```

- [ ] **Step 4: Update the chat messages container max-width**

Find the messages scroll container and ensure the inner content has `max-w-[780px] mx-auto` for the spacious centered feel.

- [ ] **Step 5: Verify builds and visually test**

Run: `cd dashboard && npm run build`
Then open `http://localhost:5173/chat` and verify:
- Thread rail appears as thin teal strip on left
- Hovering expands to show conversation list
- Context panel shows on right when Nova is responding
- Chat messages are centered with breathing room

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/chat/ChatPage.tsx
git commit -m "feat(dashboard): integrate ThreadRail and ContextPanel into Chat layout"
```

---

### Task 4: Update Message Styling

**Files:**
- Modify: `dashboard/src/pages/chat/MessageBubble.tsx`

Update the message bubbles to match Mission Flow: teal left border on AI messages, more padding, larger gap, amber thinking indicator styling.

- [ ] **Step 1: Add teal border and spacing to AI messages**

In `MessageBubble.tsx`, update the assistant message wrapper to include:
- `border-l-2 border-teal-800` on the bubble container
- Increase padding to `p-[18px]` or `px-5 py-[18px]`
- Background: `bg-stone-800/60`
- Border radius: `rounded-r-xl` (flat left edge for the border accent)

- [ ] **Step 2: Style user messages**

User messages should be:
- Right-aligned with `ml-auto`
- `bg-stone-800` background
- `rounded-xl` border radius
- `max-w-[85%]` to prevent full-width

- [ ] **Step 3: Add memory access dots between AI messages**

Between consecutive AI messages, add 3 small teal dots as decorative separators:

```tsx
{/* Memory access indicator */}
<div className="flex justify-center gap-1.5 py-1">
  <div className="w-[3px] h-[3px] rounded-full bg-teal-500/30" />
  <div className="w-[3px] h-[3px] rounded-full bg-teal-500/40" />
  <div className="w-[3px] h-[3px] rounded-full bg-teal-500/20" />
</div>
```

- [ ] **Step 4: Verify and commit**

Run: `cd dashboard && npm run build`
Visual check: Messages should have teal accent borders, more breathing room.

```bash
git add dashboard/src/pages/chat/MessageBubble.tsx
git commit -m "feat(dashboard): restyle message bubbles for Mission Flow design"
```

---

### Task 5: Update Chat Input Bar

**Files:**
- Modify: `dashboard/src/pages/chat/ChatInput.tsx`

Match the Mission Flow input bar: model picker pill on left, spacious textarea, icon buttons, glowing teal send button.

- [ ] **Step 1: Style the send button with teal glow**

Find the send button and update to:
```
className="w-11 h-11 rounded-full bg-teal-500 hover:bg-teal-600
           text-white flex items-center justify-center
           shadow-[0_0_12px_rgba(25,168,158,0.3)]
           hover:shadow-[0_0_20px_rgba(25,168,158,0.4)]
           transition-all duration-150"
```

- [ ] **Step 2: Style model picker as a pill**

Update the model selector to use a pill shape:
```
className="px-3 py-1.5 bg-stone-700 rounded-full text-[13px] font-mono
           text-stone-300 border-none outline-none cursor-pointer"
```

- [ ] **Step 3: Verify and commit**

Run: `cd dashboard && npm run build`

```bash
git add dashboard/src/pages/chat/ChatInput.tsx
git commit -m "feat(dashboard): restyle chat input bar for Mission Flow design"
```

---

### Task 6: Chat Responsive Breakpoints

**Files:**
- Modify: `dashboard/src/pages/chat/ChatPage.tsx`
- Modify: `dashboard/src/components/chat/ContextPanel.tsx`
- Modify: `dashboard/src/components/chat/ThreadRail.tsx`

- [ ] **Step 1: Hide context panel below 768px**

In `ContextPanel.tsx`, add responsive hiding:
```tsx
// At the top of the return, wrap in a responsive container
<aside className="hidden md:flex w-[340px] lg:w-[340px] md:w-[280px] ...">
```

- [ ] **Step 2: Hide thread rail below 768px**

In `ThreadRail.tsx`, add:
```tsx
<div className="thread-rail group h-full shrink-0 relative z-40 hidden md:block">
```

- [ ] **Step 3: Reduce chat padding on mobile**

In ChatPage, add responsive padding:
```
className="px-4 md:px-8 pb-[100px] md:pb-[120px]"
```

- [ ] **Step 4: Verify at all viewports and commit**

Test at 375px, 768px, 1280px widths.

```bash
git add dashboard/src/pages/chat/ChatPage.tsx dashboard/src/components/chat/ContextPanel.tsx dashboard/src/components/chat/ThreadRail.tsx
git commit -m "feat(dashboard): add responsive breakpoints to Mission Flow chat"
```

---

## Phase 2: Brain Page — Living Observatory

### Task 7: HUD Widgets Component

**Files:**
- Create: `dashboard/src/components/brain/HudWidgets.tsx`

- [ ] **Step 1: Create SystemStatus + ActiveTopics widgets**

Create `dashboard/src/components/brain/HudWidgets.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../../api'

interface EngramStats {
  total_engrams: number
  total_edges: number
  by_type: Record<string, number>
}

interface Cluster {
  id: string
  label: string
  count: number
}

export function SystemStatusWidget({ stats }: { stats?: EngramStats }) {
  return (
    <div className="fixed bottom-5 left-5 z-10 w-[220px] p-3.5 px-4 rounded-xl
                    bg-[rgba(12,10,9,0.88)] backdrop-blur-[20px]
                    border border-[rgba(68,64,60,0.55)]
                    shadow-[0_4px_24px_rgba(0,0,0,0.25),inset_0_1px_0_rgba(250,250,249,0.03)]">
      {/* Health row */}
      <div className="flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        <span className="text-xs font-medium text-stone-300">Healthy</span>
        <span className="text-[11px] font-mono text-stone-500 ml-auto">
          {stats?.total_engrams?.toLocaleString() ?? '—'} nodes
        </span>
      </div>

      {/* Divider */}
      <div className="h-px bg-[rgba(68,64,60,0.55)] my-2.5" />

      {/* Consolidation row */}
      <div className="flex items-center gap-3">
        {/* Progress ring */}
        <div className="relative w-12 h-12 shrink-0">
          <svg viewBox="0 0 100 100" className="w-12 h-12 -rotate-90">
            <circle cx="50" cy="50" r="45" fill="none"
                    stroke="rgb(68,64,60)" strokeWidth="4" />
            <circle cx="50" cy="50" r="45" fill="none"
                    stroke="rgb(25,168,158)" strokeWidth="4"
                    strokeLinecap="round"
                    strokeDasharray="283"
                    strokeDashoffset="76"
                    className="transition-[stroke-dashoffset] duration-1000" />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center
                          text-sm font-semibold font-mono text-stone-200">
            73%
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-stone-400 mb-1">
            Consolidation
          </div>
          <div className="text-[11px] font-mono text-stone-400 space-y-0.5">
            <div>{stats?.total_engrams?.toLocaleString() ?? '—'} processed</div>
            <div>{Object.keys(stats?.by_type ?? {}).length} types</div>
          </div>
          <div className="text-[10px] text-stone-500 mt-1">Last run: 2h ago</div>
        </div>
      </div>
    </div>
  )
}

export function ActiveTopicsWidget({ clusters }: { clusters: Cluster[] }) {
  const top = clusters.slice(0, 6)
  if (top.length === 0) return null

  return (
    <div className="fixed top-16 left-5 z-10 max-w-[220px] p-3 rounded-xl
                    bg-[rgba(12,10,9,0.88)] backdrop-blur-[20px]
                    border border-[rgba(68,64,60,0.55)]
                    shadow-[0_4px_24px_rgba(0,0,0,0.25),inset_0_1px_0_rgba(250,250,249,0.03)]">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-stone-400 mb-2">
        Active Topics
      </div>
      <div className="flex flex-wrap gap-[5px]">
        {top.map((c, i) => (
          <span
            key={c.id}
            className={`text-[11px] font-medium px-2.5 py-1 rounded-xl
              ${i < 3
                ? 'bg-teal-500/15 text-teal-400'
                : 'bg-stone-700 text-stone-400'}`}
          >
            {c.label} {c.count}
          </span>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit 2>&1 | head -20`

- [ ] **Step 3: Commit**

```bash
mkdir -p dashboard/src/components/brain
git add dashboard/src/components/brain/HudWidgets.tsx
git commit -m "feat(dashboard): add HUD widgets for Living Observatory brain page"
```

---

### Task 8: Restyle BrainChat Overlay

**Files:**
- Modify: `dashboard/src/components/BrainChat.tsx`

The existing BrainChat (416 lines) already handles streaming, voice, message display. We need to restyle it with glass-morphism to match the Living Observatory design.

- [ ] **Step 1: Update the outer container to glass-morphism**

Find the root container div in BrainChat.tsx and update to:

```tsx
<div className="fixed bottom-5 right-5 z-20 w-[420px] h-[520px]
                flex flex-col overflow-hidden rounded-2xl
                bg-[rgba(12,10,9,0.85)] backdrop-blur-[20px]
                border border-[rgba(68,64,60,0.55)]
                shadow-[0_8px_32px_rgba(0,0,0,0.3)]">
```

- [ ] **Step 2: Update the chat header**

Style the header to match the glass panel design:
```tsx
<div className="min-h-[48px] flex items-center px-4
                border-b border-[rgba(68,64,60,0.55)]">
  <span className="text-sm font-semibold text-stone-200">Chat with Nova</span>
  <span className="ml-2 px-2.5 py-0.5 text-[11px] font-mono text-teal-400
                   bg-teal-500/15 rounded-full">
    {modelId}
  </span>
  <button onClick={onClose} className="ml-auto ...">
    {/* minimize chevron */}
  </button>
</div>
```

- [ ] **Step 3: Add node activation annotations**

When a message's activity steps include `engram_ids`, show a small annotation below the thinking indicator:

```tsx
{step.engram_ids?.length > 0 && (
  <span className="text-[11px] italic text-stone-500 mt-1">
    ({step.engram_ids.length} nodes activated)
  </span>
)}
```

- [ ] **Step 4: Add responsive sizing for tablet**

At 1024px and below, reduce width to 360px:
```
className="... w-[420px] lg:w-[420px] md:w-[360px]"
```

- [ ] **Step 5: Verify and commit**

Run: `cd dashboard && npm run build`
Visual check: Open Brain page, press `/` to toggle chat, verify glass styling.

```bash
git add dashboard/src/components/BrainChat.tsx
git commit -m "feat(dashboard): restyle BrainChat with glass-morphism for Living Observatory"
```

---

### Task 9: Integrate HUD Widgets into Brain Page

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx`

- [ ] **Step 1: Import and render HUD widgets**

In `Brain.tsx`, import the new widgets:

```tsx
import { SystemStatusWidget, ActiveTopicsWidget } from '../components/brain/HudWidgets'
```

Add them to the JSX, after the ForceGraph3D component and before the existing overlay panels:

```tsx
{/* HUD Widgets */}
<SystemStatusWidget stats={stats} />
<ActiveTopicsWidget clusters={clusters} />
```

The `stats` data is already fetched by the existing `useQuery({ queryKey: ['engram-stats'] })`.
The `clusters` data comes from the existing graph data — extract unique cluster labels with counts.

- [ ] **Step 2: Extract cluster data from graph for ActiveTopicsWidget**

Add a `useMemo` to derive clusters from graph data:

```tsx
const clusters = useMemo(() => {
  if (!activeGraph?.nodes) return []
  const map = new Map<string, { id: string; label: string; count: number }>()
  for (const node of activeGraph.nodes) {
    if (node.cluster_label) {
      const existing = map.get(node.cluster_id)
      if (existing) existing.count++
      else map.set(node.cluster_id, { id: node.cluster_id, label: node.cluster_label, count: 1 })
    }
  }
  return [...map.values()].sort((a, b) => b.count - a.count)
}, [activeGraph?.nodes])
```

- [ ] **Step 3: Verify and commit**

Run: `cd dashboard && npm run build`
Visual check: Open Brain page, see System Status bottom-left and Active Topics top-left.

```bash
git add dashboard/src/pages/Brain.tsx
git commit -m "feat(dashboard): integrate HUD widgets into Brain page"
```

---

### Task 10: Update Brain HUD Top Bar

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx`

The existing Brain page has a top stats pill and scattered buttons. Consolidate into a proper HUD bar matching the Living Observatory design.

- [ ] **Step 1: Update the top bar to glass styling**

Find the existing stats display (the top-center pill) and the menu/settings buttons. Restructure into a single full-width bar:

```tsx
<div className="fixed top-0 left-0 right-0 z-10 h-[52px] flex items-center px-5
                bg-[rgba(12,10,9,0.88)] backdrop-blur-[20px]
                border-b border-[rgba(68,64,60,0.55)]">
  {/* Logo */}
  <div className="w-7 h-7 rounded-full bg-teal-500 flex items-center justify-center
                  text-white text-sm font-bold mr-2">N</div>
  <span className="text-base font-semibold text-stone-200">Brain</span>

  {/* Center stats */}
  <div className="flex-1 text-center text-xs font-mono text-stone-400 truncate px-4">
    {stats?.total_engrams?.toLocaleString()} memories
    {' · '}{stats?.total_edges?.toLocaleString()} edges
    {' · '}{clusters.length} topics
  </div>

  {/* Right controls */}
  <div className="flex items-center gap-1">
    {/* existing search, filter, settings buttons */}
    {/* Chat toggle pill */}
    <button
      onClick={() => setChatOpen(c => !c)}
      className={`ml-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-colors duration-150
        ${chatOpen
          ? 'bg-teal-500 text-white'
          : 'bg-stone-800 text-stone-400 hover:text-stone-300'}`}
    >
      Chat
    </button>
  </div>
</div>
```

- [ ] **Step 2: Adjust ForceGraph3D container to account for the 52px bar**

Add `pt-[52px]` or equivalent margin to the graph container so nodes aren't hidden behind the HUD bar.

- [ ] **Step 3: Verify and commit**

Run: `cd dashboard && npm run build`

```bash
git add dashboard/src/pages/Brain.tsx
git commit -m "feat(dashboard): update Brain top bar to glass HUD for Living Observatory"
```

---

### Task 11: Final Integration & Visual QA

**Files:**
- Various (no new files)

- [ ] **Step 1: Run full dashboard build**

```bash
cd dashboard && npm run build
```
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 2: Visual QA — Chat page**

Open `http://localhost:5173/chat` and verify:
- Thread rail: thin teal strip, expands on hover to show conversations
- Chat area: messages centered (780px max), teal borders on AI messages
- Context panel: visible during streaming with tasks/memory/tools
- Input bar: model pill, glowing send button
- Responsive: test at 375px, 768px, 1280px

- [ ] **Step 3: Visual QA — Brain page**

Open `http://localhost:5173/` (brain is home) and verify:
- HUD bar: glass panel at top with stats and Chat toggle
- Active Topics: top-left glass widget with topic pills
- System Status: bottom-left glass widget with health + consolidation ring
- Chat overlay: press `/`, verify glass-morphism styling, node activation annotations
- Graph: still renders with bloom, nodes still highlight on memory access

- [ ] **Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(dashboard): Mission Flow chat + Living Observatory brain redesign"
```
