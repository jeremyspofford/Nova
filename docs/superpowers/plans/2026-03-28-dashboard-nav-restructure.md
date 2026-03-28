# Dashboard Navigation Restructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Brain the dashboard landing page, retire the Memory and Overview pages, and relocate memory admin tabs to Settings.

**Architecture:** Extract 5 tab components from `EngramExplorer.tsx` into standalone Settings section files. Rewire routes so `/` renders Brain (fullWidth). Add a Memory nav group to Settings. Enhance Brain's stats bar and add type filtering from the Explorer tab.

**Tech Stack:** React 18, TypeScript, React Router v6, TanStack Query, Tailwind CSS, Lucide React icons

**Spec:** `docs/superpowers/specs/2026-03-28-dashboard-nav-restructure-design.md`

---

## File Map

### Created
| File | Responsibility |
|------|---------------|
| `dashboard/src/pages/settings/SelfModelSection.tsx` | Self-model summary + bootstrap + identity engrams |
| `dashboard/src/pages/settings/ConsolidationSection.tsx` | Consolidation history, manual trigger, stat pills |
| `dashboard/src/pages/settings/MaintenanceSection.tsx` | Reindex controls, source selection, queue status |
| `dashboard/src/pages/settings/EngramSourcesSection.tsx` | Ingested source list with trust/staleness/coverage |
| `dashboard/src/pages/settings/RouterStatusSection.tsx` | Neural router training status + observation count |

### Modified
| File | Changes |
|------|---------|
| `dashboard/src/App.tsx` | `/` → Brain (fullWidth), `/brain` → redirect, remove `/engrams` + Overview |
| `dashboard/src/components/layout/Sidebar.tsx` | Remove Overview + Memory items, Brain first, logo clickable, icon swap |
| `dashboard/src/components/layout/MobileNav.tsx` | Brain replaces Memory in `primaryTabs` |
| `dashboard/src/components/CommandPalette.tsx` | Remove Memory entry, add Brain entry |
| `dashboard/src/pages/Settings.tsx` | Add Memory nav group + 5 section divs |
| `dashboard/src/pages/Brain.tsx` | Enhanced stats bar, type distribution filter |

### Deleted
| File | Reason |
|------|--------|
| `dashboard/src/pages/Overview.tsx` | Page removed entirely |
| `dashboard/src/pages/EngramExplorer.tsx` | All content relocated |

---

## Task 1: Extract Self-Model section from EngramExplorer

**Files:**
- Create: `dashboard/src/pages/settings/SelfModelSection.tsx`
- Read: `dashboard/src/pages/EngramExplorer.tsx:358-440` (SelfModelTab + SelfModelEngrams)

- [ ] **Step 1: Create SelfModelSection.tsx**

Extract `SelfModelTab` (lines 358-410) and `SelfModelEngrams` (lines 413-440) from `EngramExplorer.tsx` into a new file. Wrap in a `Section` component matching the Settings pattern.

```tsx
import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Brain, RefreshCw, Zap } from 'lucide-react'
import { apiFetch } from '../../api'
import { Section, Card, Badge, Button, EmptyState, Skeleton } from '../../components/ui'

// Types needed locally
interface GraphData {
  nodes: { id: string; type: string; content: string; importance: number; confidence: number }[]
  edges: unknown[]
  node_count: number
  edge_count: number
}

function SelfModelEngrams() {
  // Copy lines 413-440 from EngramExplorer.tsx exactly
  // Uses query key ['engram-self-model-graph']
  // Fetches /mem/api/v1/engrams/graph?query=self+identity+personality&depth=1&max_nodes=20
  // Renders Card with identity engrams filtered to type === 'self_model'
}

export function SelfModelSection() {
  // Copy SelfModelTab lines 358-410 from EngramExplorer.tsx
  // Wrap the return in <Section icon={Brain} title="Self-Model" description="...">
  // Uses query key ['engram-self-model']
  // Fetches /mem/api/v1/engrams/self-model (GET)
  // Bootstrap mutation: POST /mem/api/v1/engrams/self-model/bootstrap
  // Include <SelfModelEngrams /> at the bottom
}
```

- [ ] **Step 2: Verify file compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors referencing `SelfModelSection.tsx`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/settings/SelfModelSection.tsx
git commit -m "refactor: extract SelfModelSection from EngramExplorer"
```

---

## Task 2: Extract Consolidation section from EngramExplorer

**Files:**
- Create: `dashboard/src/pages/settings/ConsolidationSection.tsx`
- Read: `dashboard/src/pages/EngramExplorer.tsx:442-606` (helpers + ConsolidationTab + StatPill)

- [ ] **Step 1: Create ConsolidationSection.tsx**

Extract `summarizeConsolidation` (lines 444-461), `TRIGGER_COLOR` (lines 463-468), `ConsolidationTab` (lines 470-597), and `StatPill` (lines 599-606) from `EngramExplorer.tsx`.

```tsx
import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { GitMerge, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { apiFetch } from '../../api'
import { Section, Card, Badge, Button, EmptyState, Skeleton } from '../../components/ui'
import type { SemanticColor } from '../../lib/design-tokens'

// Copy ConsolidationEntry interface from EngramExplorer lines 68-82
// Copy TRIGGER_COLOR map from lines 463-468
// Copy summarizeConsolidation from lines 444-461
// Copy StatPill from lines 599-606

export function ConsolidationSection() {
  // Copy ConsolidationTab lines 470-597 from EngramExplorer.tsx
  // Wrap return in <Section icon={GitMerge} title="Consolidation" description="...">
  // Uses query key ['engram-consolidation-log']
  // Fetches /mem/api/v1/engrams/consolidation-log?limit=20 (GET)
  // Consolidate mutation: POST /mem/api/v1/engrams/consolidate
}
```

- [ ] **Step 2: Verify file compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors referencing `ConsolidationSection.tsx`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/settings/ConsolidationSection.tsx
git commit -m "refactor: extract ConsolidationSection from EngramExplorer"
```

---

## Task 3: Extract Maintenance section from EngramExplorer

**Files:**
- Create: `dashboard/src/pages/settings/MaintenanceSection.tsx`
- Read: `dashboard/src/pages/EngramExplorer.tsx:608-819` (REINDEX_SOURCES + MaintenanceTab)

- [ ] **Step 1: Create MaintenanceSection.tsx**

Extract `REINDEX_SOURCES` (lines 610-615) and `MaintenanceTab` (lines 617-819).

```tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Database, RefreshCw, Zap, MessageSquare, ClipboardList, Newspaper, Globe, Wrench,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { apiFetch, reindexMemory, getReindexStatus } from '../../api'
import type { ReindexResponse, ReindexStatusResponse } from '../../api'
import { Section, Card, Badge, Metric, ProgressBar, Button } from '../../components/ui'

// Copy EngramStats interface (lines 59-66 of EngramExplorer)
// Copy REINDEX_SOURCES (lines 610-615)

export function MaintenanceSection() {
  // Copy MaintenanceTab lines 617-819 from EngramExplorer.tsx
  // Wrap return in <Section icon={Wrench} title="Maintenance" description="...">
  // Uses query keys: ['reindex-status'], ['engram-stats']
  // API: reindexMemory(), getReindexStatus() from ../../api
}
```

- [ ] **Step 2: Verify file compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors referencing `MaintenanceSection.tsx`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/settings/MaintenanceSection.tsx
git commit -m "refactor: extract MaintenanceSection from EngramExplorer"
```

---

## Task 4: Extract Engram Sources section from EngramExplorer

**Files:**
- Create: `dashboard/src/pages/settings/EngramSourcesSection.tsx`
- Read: `dashboard/src/pages/EngramExplorer.tsx:821-872` (SourcesTab)

- [ ] **Step 1: Create EngramSourcesSection.tsx**

Extract `SourcesTab` (lines 823-872). This tab uses raw `fetch()` instead of `apiFetch` — convert to `apiFetch` for consistency.

```tsx
import { useState, useEffect } from 'react'
import { Database } from 'lucide-react'
import { apiFetch } from '../../api'
import { Section, EmptyState, Skeleton } from '../../components/ui'

export function EngramSourcesSection() {
  // Copy SourcesTab lines 823-872 from EngramExplorer.tsx
  // Replace raw fetch('/mem/api/v1/engrams/sources') with apiFetch('/mem/api/v1/engrams/sources')
  // Wrap return in <Section icon={Database} title="Engram Sources" description="...">
  // Note: hardcoded stone-* colors should be replaced with semantic classes
  //   bg-stone-800 → bg-surface-elevated
  //   text-stone-200 → text-content-primary
  //   text-stone-400 → text-content-tertiary
  //   text-stone-500 → text-content-quaternary
  //   bg-stone-700 → bg-surface-card
  //   text-teal-400 → text-accent
  //   text-amber-500 → text-warning
}
```

- [ ] **Step 2: Verify file compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors referencing `EngramSourcesSection.tsx`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/settings/EngramSourcesSection.tsx
git commit -m "refactor: extract EngramSourcesSection from EngramExplorer"
```

---

## Task 5: Extract Router Status section from EngramExplorer

**Files:**
- Create: `dashboard/src/pages/settings/RouterStatusSection.tsx`
- Read: `dashboard/src/pages/EngramExplorer.tsx:164-167` (router status query from ExplorerTab)

- [ ] **Step 1: Create RouterStatusSection.tsx**

New component showing the neural router training status. Data comes from the ExplorerTab's `routerStatus` query.

```tsx
import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'
import { apiFetch } from '../../api'
import { Section, Card, Badge, Metric } from '../../components/ui'

interface RouterStatus {
  observation_count: number
  ready: boolean
  phase: string
  message: string
}

export function RouterStatusSection() {
  const { data: status, isLoading } = useQuery<RouterStatus>({
    queryKey: ['engram-router-status'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/router-status'),
  })

  return (
    <Section icon={Activity} title="Neural Router" description="ML re-ranker that improves memory retrieval quality. Trains automatically after 200+ observations.">
      <div className="flex flex-wrap gap-6">
        <Metric label="Observations" value={status?.observation_count ?? '...'} tooltip="Retrieval feedback samples collected for training." />
        <Metric label="Phase" value={status?.phase ?? '...'} tooltip="Current training phase of the re-ranker." />
        <Metric label="Status" value={status?.ready ? 'Ready' : 'Training'} tooltip="Whether the router is active and influencing retrieval." />
      </div>
      {status?.message && (
        <p className="text-caption text-content-tertiary mt-3">{status.message}</p>
      )}
    </Section>
  )
}
```

- [ ] **Step 2: Verify file compiles**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors referencing `RouterStatusSection.tsx`

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/settings/RouterStatusSection.tsx
git commit -m "refactor: extract RouterStatusSection for Settings memory group"
```

---

## Task 6: Add Memory section to Settings

**Files:**
- Modify: `dashboard/src/pages/Settings.tsx`

- [ ] **Step 1: Add imports for new sections**

At the top of `Settings.tsx`, after the existing settings imports (around line 28), add:

```tsx
import { SelfModelSection } from './settings/SelfModelSection'
import { ConsolidationSection } from './settings/ConsolidationSection'
import { MaintenanceSection } from './settings/MaintenanceSection'
import { EngramSourcesSection } from './settings/EngramSourcesSection'
import { RouterStatusSection } from './settings/RouterStatusSection'
```

Add icons to the lucide import (line 4): `Brain` and `GitMerge` (`Wrench`, `Database`, and `Activity` are already imported).

- [ ] **Step 2: Add Memory nav group to NAV_GROUPS**

Insert a new group between "AI & Pipeline" and "Connections" (after line ~72 in the current array). This keeps memory-related settings near the AI section:

```tsx
{
  label: 'Memory',
  items: [
    { id: 'self-model', label: 'Self-Model', icon: Brain },
    { id: 'consolidation', label: 'Consolidation', icon: GitMerge },
    { id: 'maintenance', label: 'Maintenance', icon: Wrench },
    { id: 'engram-sources', label: 'Engram Sources', icon: Database },
    { id: 'router-status', label: 'Neural Router', icon: Activity },
  ],
},
```

- [ ] **Step 3: Add section content divs**

In the content area, immediately after the Voice section closing `</div>` at line 572 and before the `{/* ── Connections */}` comment at line 574, add:

```tsx
{/* ── Memory ───────────────────────────────────────────────── */}

<div id="self-model">
  <SelfModelSection />
</div>

<div id="consolidation">
  <ConsolidationSection />
</div>

<div id="maintenance">
  <MaintenanceSection />
</div>

<div id="engram-sources">
  <EngramSourcesSection />
</div>

<div id="router-status">
  <RouterStatusSection />
</div>
```

- [ ] **Step 4: Verify build**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: Clean compile

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/Settings.tsx
git commit -m "feat: add Memory section to Settings with 5 subsections"
```

---

## Task 7: Update routes in App.tsx

**Files:**
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Update imports**

- Remove: `import Overview from './pages/Overview'` (or `{ Overview }`)
- Remove: `import { EngramExplorer } from './pages/EngramExplorer'`
- Add: `import { Navigate } from 'react-router-dom'` (if not already imported)

- [ ] **Step 2: Update route definitions**

Replace the Overview route:
```tsx
// Before:
<Route path="/" element={<AppLayout><Overview /></AppLayout>} />

// After:
<Route path="/" element={<AppLayout fullWidth><Brain /></AppLayout>} />
```

Add redirect for old Brain URL (after the new `/` route):
```tsx
<Route path="/brain" element={<Navigate to="/" replace />} />
```

Remove the `/engrams` route entirely:
```tsx
// Delete this line:
<Route path="/engrams" element={<AppLayout><EngramExplorer /></AppLayout>} />
```

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: Clean compile (Overview and EngramExplorer files still exist but are no longer imported — that's fine, we delete them in Task 13)

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/App.tsx
git commit -m "feat: Brain is now the landing page at /"
```

---

## Task 8: Update Sidebar navigation

**Files:**
- Modify: `dashboard/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Update imports**

Replace `Sparkles` with nothing (remove it) and ensure `Brain` is imported from lucide-react. Also add `useNavigate` from react-router-dom:

```tsx
// Change this import line:
import { useLocation, NavLink } from 'react-router-dom'
// To:
import { useLocation, NavLink, useNavigate } from 'react-router-dom'
```

Remove `LayoutDashboard` and `Sparkles` from the lucide import (they're no longer used). Keep `Brain`.

- [ ] **Step 2: Update navSections array**

Replace the Core section items (lines 44-54):

```tsx
{
  // Core — no label, always visible
  items: [
    { to: '/', label: 'Brain', icon: Brain, minRole: 'guest' },
    { to: '/chat', label: 'Chat', icon: MessageSquare, minRole: 'guest' },
    { to: '/tasks', label: 'Tasks', icon: ListTodo, minRole: 'member' },
    { to: '/friction', label: 'Friction', icon: AlertTriangle, minRole: 'member', debugOnly: true },
    { to: '/goals', label: 'Goals', icon: Target, minRole: 'member' },
    { to: '/sources', label: 'Sources', icon: Globe, minRole: 'member' },
  ],
},
```

Removed: Overview (`/`), Memory (`/engrams`), Brain (`/brain`).
Added: Brain at `/` as first item with `minRole: 'guest'`.

- [ ] **Step 3: Make logo clickable**

In the logo section (around lines 108-116), wrap the existing logo div with a clickable element. Add `useNavigate` at the top of the component:

```tsx
const navigate = useNavigate()
```

Then update the logo section:

```tsx
{/* Logo */}
<div
  className={clsx('flex items-center gap-2.5 px-3 h-14 shrink-0 cursor-pointer', collapsed && 'justify-center')}
  onClick={() => navigate('/')}
  title="Go to Brain"
>
  <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center shrink-0 dark:shadow-[0_0_16px_rgb(var(--accent-500)/0.3)]">
    <span className="text-white text-compact font-bold leading-none">N</span>
  </div>
  {!collapsed && (
    <span className="text-h3 text-content-primary tracking-tight">Nova</span>
  )}
</div>
```

- [ ] **Step 4: Verify build**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: Clean compile

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/layout/Sidebar.tsx
git commit -m "feat: Brain first in sidebar, logo clickable to home"
```

---

## Task 9: Update MobileNav

**Files:**
- Modify: `dashboard/src/components/layout/MobileNav.tsx`

- [ ] **Step 1: Update primaryTabs**

Replace the Memory entry in `primaryTabs` with Brain. Ensure `Brain` is imported from lucide-react (it should already be — it was used for Memory). Remove `LayoutDashboard` import if it was there.

```tsx
const primaryTabs: NavItem[] = [
  { to: '/chat', label: 'Chat', icon: MessageSquare, minRole: 'guest' },
  { to: '/tasks', label: 'Tasks', icon: ListTodo, minRole: 'member' },
  { to: '/goals', label: 'Goals', icon: Target, minRole: 'member' },
  { to: '/', label: 'Brain', icon: Brain, minRole: 'guest' },
]
```

- [ ] **Step 2: Remove Memory from moreItems if present**

Check `moreItems` array — if Memory/Engrams appears there, remove it.

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: Clean compile

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/layout/MobileNav.tsx
git commit -m "feat: Brain replaces Memory in mobile bottom tab bar"
```

---

## Task 10: Update CommandPalette

**Files:**
- Modify: `dashboard/src/components/CommandPalette.tsx`

- [ ] **Step 1: Update palette items**

Find the Memory entry (line ~37):
```tsx
{ id: 'page-memory', label: 'Memory', icon: Brain, category: 'Pages', action: () => navigate('/engrams') }
```

Replace with Brain:
```tsx
{ id: 'page-brain', label: 'Brain', icon: Brain, category: 'Pages', action: () => navigate('/') }
```

Also remove the Overview entry if one exists.

- [ ] **Step 2: Verify build**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: Clean compile

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/CommandPalette.tsx
git commit -m "feat: command palette Brain replaces Memory"
```

---

## Task 11: Enhance Brain stats bar

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx`

- [ ] **Step 1: Add stats query**

Add a TanStack Query call to fetch the full engram stats (same endpoint the Explorer tab used). Add this near the other queries in Brain.tsx:

```tsx
const { data: engramStats } = useQuery<{
  total_engrams: number
  total_edges: number
  total_archived: number
  by_type: Record<string, { total: number; superseded: number }>
}>({
  queryKey: ['engram-stats'],
  queryFn: () => apiFetch('/mem/api/v1/engrams/stats'),
  staleTime: 30_000,
})
```

Ensure `apiFetch` is imported from `../api`. Also add a router status query:

```tsx
const { data: routerStatus } = useQuery<{ observation_count: number }>({
  queryKey: ['engram-router-status'],
  queryFn: () => apiFetch('/mem/api/v1/engrams/router-status'),
  staleTime: 30_000,
})
```

- [ ] **Step 2: Update the stats badge display**

Find the stats badge section (around lines 292-298). Replace:

```tsx
{/* Stats badge */}
{activeGraph && (
  <div className="text-xs text-stone-600 px-1">
    {activeGraph.nodes.length} memories · {activeGraph.edges.length} connections
    {activeGraph.clusters && ` · ${activeGraph.clusters.length} topics`}
  </div>
)}
```

With enhanced stats:

```tsx
{/* Stats badge */}
<div className="text-xs text-stone-600 px-1 flex items-center gap-1.5">
  {engramStats ? (
    <>
      {engramStats.total_engrams.toLocaleString()} memories
      {' · '}{engramStats.total_edges.toLocaleString()} edges
      {engramStats.total_archived > 0 && <> · {engramStats.total_archived} archived</>}
      {activeGraph?.clusters && ` · ${activeGraph.clusters.length} topics`}
      {routerStatus && routerStatus.observation_count > 0 && (
        <> · {routerStatus.observation_count} router obs</>
      )}
    </>
  ) : activeGraph ? (
    <>
      {activeGraph.nodes.length} memories · {activeGraph.edges.length} connections
      {activeGraph.clusters && ` · ${activeGraph.clusters.length} topics`}
    </>
  ) : null}
</div>
```

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: Clean compile

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/Brain.tsx
git commit -m "feat: Brain stats bar shows edges, archived, router observations"
```

---

## Task 12: Add type distribution filter to Brain sidebar

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx`

- [ ] **Step 1: Add type filter state**

Near the other state declarations in Brain.tsx, add:

```tsx
const [typeFilter, setTypeFilter] = useState<string | null>(null)
```

- [ ] **Step 2: Add type badge constants**

Add at the top of the file (or inside the component, matching existing patterns):

```tsx
const TYPE_COLORS: Record<string, string> = {
  fact: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  entity: 'bg-teal-500/20 text-teal-300 border-teal-500/30',
  preference: 'bg-green-500/20 text-green-300 border-green-500/30',
  procedure: 'bg-stone-500/20 text-stone-300 border-stone-500/30',
  self_model: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  episode: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  schema: 'bg-red-500/20 text-red-300 border-red-500/30',
  goal: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
}
```

These match Brain's existing node color scheme (check the `getNodeColor` function in Brain.tsx).

- [ ] **Step 3: Add type filter section to Brain sidebar**

In the topic clustering sidebar (inside the `sidebarOpen` conditional, around lines 335-451), add a type distribution section. Insert it above the existing cluster/type list. Place it after the sidebar header:

```tsx
{/* Type distribution filter */}
{engramStats?.by_type && (
  <div className="mb-4">
    <p className="text-[10px] uppercase tracking-wider text-stone-500 mb-2">Filter by type</p>
    <div className="flex flex-wrap gap-1">
      <button
        onClick={() => setTypeFilter(null)}
        className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
          !typeFilter
            ? 'border-white/20 text-white bg-white/10'
            : 'border-white/5 text-stone-600 hover:text-stone-400'
        }`}
      >
        All
      </button>
      {Object.entries(engramStats.by_type).map(([type, { total }]) => (
        <button
          key={type}
          onClick={() => setTypeFilter(typeFilter === type ? null : type)}
          className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
            typeFilter === type
              ? TYPE_COLORS[type] ?? 'border-white/20 text-white'
              : typeFilter
                ? 'border-white/5 text-stone-700 hover:text-stone-500'
                : 'border-white/5 text-stone-500 hover:text-stone-300'
          }`}
        >
          {type} ({total})
        </button>
      ))}
    </div>
  </div>
)}
```

- [ ] **Step 4: Apply filter to graph rendering**

Find where Brain renders nodes for the 3D graph (look for the ForceGraph3D component's `nodeVal`, `nodeVisibility`, or data prop). Add filtering logic:

If the graph component accepts `graphData` or similar, filter nodes:

```tsx
const filteredGraphData = useMemo(() => {
  if (!activeGraph || !typeFilter) return activeGraph
  const filteredNodes = activeGraph.nodes.filter(n => n.type === typeFilter)
  const nodeIds = new Set(filteredNodes.map(n => n.id))
  const filteredEdges = activeGraph.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
  return { ...activeGraph, nodes: filteredNodes, edges: filteredEdges }
}, [activeGraph, typeFilter])
```

Then update the ForceGraph3D component props to use the filtered data. The component takes `nodes`, `edges`, and `clusters` as separate props:

```tsx
<ForceGraph3D
  nodes={filteredGraphData?.nodes ?? []}
  edges={filteredGraphData?.edges ?? []}
  clusters={filteredGraphData?.clusters}
  // ... rest of existing props unchanged
```

- [ ] **Step 5: Verify build**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: Clean compile

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/Brain.tsx
git commit -m "feat: Brain sidebar type distribution filter"
```

---

## Task 13: Delete Overview.tsx and EngramExplorer.tsx

**Files:**
- Delete: `dashboard/src/pages/Overview.tsx`
- Delete: `dashboard/src/pages/EngramExplorer.tsx`

- [ ] **Step 1: Verify no remaining imports**

Run: `grep -r 'Overview\|EngramExplorer' dashboard/src/ --include='*.tsx' --include='*.ts' -l`

Expected: Only `App.tsx` should reference these (already updated in Task 7). If other files reference them, update those first.

- [ ] **Step 2: Delete the files**

```bash
rm dashboard/src/pages/Overview.tsx
rm dashboard/src/pages/EngramExplorer.tsx
```

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: Clean compile, no missing module errors

- [ ] **Step 4: Commit**

```bash
git add -u dashboard/src/pages/Overview.tsx dashboard/src/pages/EngramExplorer.tsx
git commit -m "chore: delete retired Overview and EngramExplorer pages"
```

---

## Task 14: Full build verification and smoke test

- [ ] **Step 1: Full TypeScript build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 2: Smoke test checklist (manual)**

With `make dev` running:

- [ ] Opening `http://localhost:3000/` or `:5173/` shows Brain (3D graph, fullWidth)
- [ ] Brain stats bar shows: memories, edges, archived, topics, router observations
- [ ] Brain sidebar has type filter badges that filter visible nodes
- [ ] Clicking Nova logo in sidebar navigates to Brain
- [ ] Brain is first sidebar item with Brain icon and active indicator
- [ ] `/brain` redirects to `/`
- [ ] `/engrams` returns no match (404 or fallback)
- [ ] Chat, Tasks, Goals, Sources all still load correctly
- [ ] Settings page shows Memory section with: Self-Model, Consolidation, Maintenance, Engram Sources, Neural Router
- [ ] Settings Memory > Consolidation "Run Now" button works
- [ ] Settings Memory > Maintenance reindex preview works
- [ ] Cmd+K command palette shows "Brain" (no "Memory" or "Overview")
- [ ] Mobile nav bottom bar shows Brain instead of Memory

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: post-merge cleanup from nav restructure"
```
