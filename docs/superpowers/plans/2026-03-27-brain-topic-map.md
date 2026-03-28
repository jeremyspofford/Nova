# Brain Topic Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Topic Map graph mode to the Brain page where clusters appear as clickable super-nodes, plus display toggles for background/inner star layers.

**Architecture:** Client-side only. Super-nodes computed from existing cluster data in Brain.tsx, passed as transformed graph data to ForceGraph3D. Star toggles are boolean props that control which layers `createStarfield()` includes. No backend changes.

**Tech Stack:** React, TypeScript, Three.js (via 3d-force-graph), TanStack Query, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-27-brain-topic-map-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `dashboard/src/pages/Brain.tsx` | Modify | New state (`graphMode`, `expandedCluster`, star toggles), super-node data computation, UI controls, graph data transformation |
| `dashboard/src/components/ForceGraph3D.tsx` | Modify | New props (`showBackgroundStars`, `showInnerStars`), starfield rebuild logic, super-node custom rendering via `nodeThreeObject` |

Two files total. All logic stays in existing files — no new files needed.

---

### Task 1: Add Star Layer Toggles to ForceGraph3D

**Files:**
- Modify: `dashboard/src/components/ForceGraph3D.tsx:80-96` (props interface)
- Modify: `dashboard/src/components/ForceGraph3D.tsx:393-480` (`createStarfield` function)
- Modify: `dashboard/src/components/ForceGraph3D.tsx:997-1018` (starfield init + live-update effect)

- [ ] **Step 1: Add props to ForceGraph3DProps interface**

In `ForceGraph3D.tsx:80-96`, add two new optional props:

```typescript
interface ForceGraph3DProps {
  // ... existing props ...
  neuralMode?: NeuralModeConfig
  showBackgroundStars?: boolean   // deep-field layer (default true)
  showInnerStars?: boolean        // original dim/bright layers (default false)
}
```

- [ ] **Step 2: Accept props in component destructuring**

In the component function signature around line 506-522, add the new props with defaults:

```typescript
export const ForceGraph3D = forwardRef<ForceGraph3DHandle, ForceGraph3DProps>(function ForceGraph3D({
  // ... existing props ...
  showBackgroundStars = true,
  showInnerStars = false,
}: ForceGraph3DProps, ref) {
```

Add refs to track them (alongside existing `bgColorRef`):

```typescript
const showBgStarsRef = useRef(showBackgroundStars)
showBgStarsRef.current = showBackgroundStars
const showInnerStarsRef = useRef(showInnerStars)
showInnerStarsRef.current = showInnerStars
```

- [ ] **Step 3: Modify `createStarfield` to accept options**

Change the function signature and conditionally include layers:

```typescript
function createStarfield(options: { bgStars: boolean; innerStars: boolean }): Group {
  const group = new Group()
  group.name = 'starfield'

  // ── Inner stars (original dim + bright layers) ──
  if (options.innerStars) {
    // Dim stars — 2000 particles, radius 600-1500
    const dimCount = 2000
    const dimPos = new Float32Array(dimCount * 3)
    const dimCol = new Float32Array(dimCount * 3)
    for (let i = 0; i < dimCount; i++) {
      const r = 600 + Math.random() * 900
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      dimPos[i * 3]     = r * Math.sin(phi) * Math.cos(theta)
      dimPos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      dimPos[i * 3 + 2] = r * Math.cos(phi)
      const t = Math.random()
      if (t < 0.5) {
        dimCol[i * 3] = 0.8 + Math.random() * 0.2
        dimCol[i * 3 + 1] = 0.85 + Math.random() * 0.15
        dimCol[i * 3 + 2] = 1.0
      } else if (t < 0.75) {
        dimCol[i * 3] = 1.0
        dimCol[i * 3 + 1] = 0.8 + Math.random() * 0.2
        dimCol[i * 3 + 2] = 0.5 + Math.random() * 0.2
      } else {
        dimCol[i * 3] = 0.5 + Math.random() * 0.2
        dimCol[i * 3 + 1] = 0.6 + Math.random() * 0.2
        dimCol[i * 3 + 2] = 1.0
      }
    }
    const dimGeo = new BufferGeometry()
    dimGeo.setAttribute('position', new Float32BufferAttribute(dimPos, 3))
    dimGeo.setAttribute('color', new Float32BufferAttribute(dimCol, 3))
    group.add(new Points(dimGeo, new PointsMaterial({
      size: 0.8, vertexColors: true, transparent: true, opacity: 0.6, sizeAttenuation: true,
    })))

    // Bright stars — 300 particles, radius 500-1500
    const brightCount = 300
    const brightPos = new Float32Array(brightCount * 3)
    const brightCol = new Float32Array(brightCount * 3)
    for (let i = 0; i < brightCount; i++) {
      const r = 500 + Math.random() * 1000
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      brightPos[i * 3]     = r * Math.sin(phi) * Math.cos(theta)
      brightPos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      brightPos[i * 3 + 2] = r * Math.cos(phi)
      brightCol[i * 3] = 0.9 + Math.random() * 0.1
      brightCol[i * 3 + 1] = 0.9 + Math.random() * 0.1
      brightCol[i * 3 + 2] = 1.0
    }
    const brightGeo = new BufferGeometry()
    brightGeo.setAttribute('position', new Float32BufferAttribute(brightPos, 3))
    brightGeo.setAttribute('color', new Float32BufferAttribute(brightCol, 3))
    group.add(new Points(brightGeo, new PointsMaterial({
      size: 2.0, vertexColors: true, transparent: true, opacity: 0.9, sizeAttenuation: true,
    })))
  }

  // ── Nebulae (keep as-is, always included) ──
  // ... existing nebulae code unchanged ...

  // ── Galaxies (keep as-is, always included) ──
  // ... existing galaxy code unchanged ...

  // ── Deep-field background stars ──
  if (options.bgStars) {
    // ... existing deep-field code unchanged ...
  }

  return group
}
```

- [ ] **Step 4: Update all `createStarfield()` call sites**

There are two call sites — initial mount and the live-update effect. Update both to pass the refs:

At graph init (~line 967-971):
```typescript
if (bgColorRef.current === 'galaxy') {
  const sf = createStarfield({ bgStars: showBgStarsRef.current, innerStars: showInnerStarsRef.current })
  graph.scene().add(sf)
  starfieldRef.current = sf
}
```

In the `bgColor` effect (~line 1057-1079), also add `showBackgroundStars` and `showInnerStars` to its dependency array and rebuild the starfield when they change:

```typescript
useEffect(() => {
  const graph = graphRef.current
  if (!graph) return
  const scene = graph.scene()

  if (starfieldRef.current) {
    scene.remove(starfieldRef.current)
    disposeStarfield(starfieldRef.current)
    starfieldRef.current = null
  }

  if (bgColor === 'galaxy') {
    graph.backgroundColor('#000000')
    const sf = createStarfield({ bgStars: showBackgroundStars, innerStars: showInnerStars })
    scene.add(sf)
    starfieldRef.current = sf
  } else {
    graph.backgroundColor(bgColor)
  }
}, [bgColor, showBackgroundStars, showInnerStars])
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`
Expected: Clean output, no errors

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/ForceGraph3D.tsx
git commit -m "feat(brain): add star layer toggle props to ForceGraph3D"
```

---

### Task 2: Add Star Toggle UI to Brain Page

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx:117-124` (state declarations)
- Modify: `dashboard/src/pages/Brain.tsx:241-264` (ForceGraph3D props)
- Modify: `dashboard/src/pages/Brain.tsx:266-292` (top-left controls area)

- [ ] **Step 1: Add state for star toggles**

After the existing state declarations (~line 124):

```typescript
const [showBgStars, setShowBgStars] = useState(true)
const [showInnerStars, setShowInnerStars] = useState(false)
```

- [ ] **Step 2: Pass star toggle props to ForceGraph3D**

In the JSX where ForceGraph3D is rendered (~line 241-264), add:

```typescript
<ForceGraph3D
  // ... existing props ...
  showBackgroundStars={showBgStars}
  showInnerStars={showInnerStars}
  className="w-full h-full"
/>
```

- [ ] **Step 3: Add toggle controls in the top-left controls area**

After the stats badge div (after line 291), add compact toggles:

```tsx
{/* Display toggles */}
<div className="flex items-center gap-2 px-1">
  <button
    onClick={() => setShowBgStars(v => !v)}
    className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
      showBgStars
        ? 'border-teal-500/30 text-teal-400 bg-teal-500/10'
        : 'border-white/10 text-stone-600 hover:text-stone-400'
    }`}
  >
    Stars
  </button>
  <button
    onClick={() => setShowInnerStars(v => !v)}
    className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
      showInnerStars
        ? 'border-teal-500/30 text-teal-400 bg-teal-500/10'
        : 'border-white/10 text-stone-600 hover:text-stone-400'
    }`}
  >
    Inner Stars
  </button>
</div>
```

- [ ] **Step 4: Verify TypeScript compiles and test in browser**

Run: `cd dashboard && npx tsc --noEmit`
Expected: Clean compile

Manual test: Open Brain page, toggle stars on/off. Background stars should appear/disappear. Inner stars toggle should add/remove the in-scene star particles.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/Brain.tsx
git commit -m "feat(brain): add star layer toggles to Brain UI"
```

---

### Task 3: Add Graph Mode State and View Selector UI

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx:117-124` (state)
- Modify: `dashboard/src/pages/Brain.tsx:266-292` (controls area)

- [ ] **Step 1: Add graph mode state**

After star toggle state:

```typescript
const [graphMode, setGraphMode] = useState<'full' | 'topic-map'>('full')
const [expandedCluster, setExpandedCluster] = useState<number | null>(null)
```

- [ ] **Step 2: Add mode selector in top-left controls**

Add a segmented control next to the stats badge, before the star toggles:

```tsx
{/* Graph mode selector */}
{activeGraph?.clusters && activeGraph.clusters.length >= 3 && (
  <div className="flex items-center gap-px bg-white/5 rounded-md p-0.5">
    <button
      onClick={() => { setGraphMode('full'); setExpandedCluster(null) }}
      className={`text-[10px] px-2.5 py-1 rounded transition-colors ${
        graphMode === 'full'
          ? 'bg-white/10 text-stone-200'
          : 'text-stone-500 hover:text-stone-300'
      }`}
    >
      Full Graph
    </button>
    <button
      onClick={() => { setGraphMode('topic-map'); setExpandedCluster(null) }}
      className={`text-[10px] px-2.5 py-1 rounded transition-colors ${
        graphMode === 'topic-map'
          ? 'bg-white/10 text-stone-200'
          : 'text-stone-500 hover:text-stone-300'
      }`}
    >
      Topic Map
    </button>
  </div>
)}
```

- [ ] **Step 3: Add breadcrumb for drill-down state**

Below the top-left controls or top-right, show breadcrumb when drilled in:

```tsx
{/* Breadcrumb when drilled into a topic */}
{graphMode === 'topic-map' && expandedCluster != null && (
  <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
    <button
      onClick={() => setExpandedCluster(null)}
      className="text-[11px] px-3 py-1.5 rounded-md border border-white/10 bg-white/5 text-stone-400 hover:text-stone-200 transition-colors"
    >
      All Topics
    </button>
    <span className="text-stone-600 text-xs">&rsaquo;</span>
    <span className="text-[11px] px-3 py-1.5 rounded-md border border-indigo-500/25 bg-indigo-500/10 text-indigo-400">
      {activeGraph?.clusters?.find(c => c.id === expandedCluster)?.label ?? 'Topic'}
    </span>
  </div>
)}
```

- [ ] **Step 4: Wire Escape key to collapse drill-down**

In the existing keyboard handler (~line 144-148), add before the existing Escape logic:

```typescript
if (e.key === 'Escape') {
  if (chatOpen) setChatOpen(false)
  else if (selectedNode) setSelectedNode(null)
  else if (expandedCluster != null) setExpandedCluster(null)
  else if (searchActive) { setSearchActive(false); setSearchQuery('') }
}
```

Add `expandedCluster` to the useEffect dependency array.

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`
Expected: Clean output

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/Brain.tsx
git commit -m "feat(brain): add graph mode selector and drill-down state"
```

---

### Task 4: Compute Super-Node Graph Data

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx` — add `useMemo` computation between state and JSX return

This is the core data transformation. We compute super-nodes from the existing cluster data.

- [ ] **Step 1: Add useMemo import**

Verify `useMemo` is imported (add it to the existing React import if not):

```typescript
import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
```

- [ ] **Step 2: Compute super-node graph data**

Add after `activeGraph` declaration (~line 134) and before the JSX return:

```typescript
// ── Super-node graph for Topic Map mode ─────────────────────────────
const topicMapData = useMemo(() => {
  if (!activeGraph?.clusters || activeGraph.clusters.length < 3) return null

  const clusters = activeGraph.clusters
  const nodesByCluster = new Map<number, GraphNode[]>()
  for (const node of activeGraph.nodes) {
    const cid = node.cluster_id ?? -1
    const list = nodesByCluster.get(cid) ?? []
    list.push(node)
    nodesByCluster.set(cid, list)
  }

  // Build super-nodes
  const superNodes: GraphNode[] = clusters.map(c => {
    const members = nodesByCluster.get(c.id) ?? []
    const avgActivation = members.length > 0
      ? members.reduce((s, n) => s + n.activation, 0) / members.length
      : 0
    return {
      id: `super-${c.id}`,
      type: 'cluster',
      content: c.label,
      activation: avgActivation,
      importance: c.count / Math.max(...clusters.map(cl => cl.count)),  // normalized 0-1
      access_count: c.count,
      confidence: 1,
      source_type: 'cluster',
      cluster_id: c.id,
      cluster_label: c.label,
    }
  })

  // Uncategorized bucket
  const uncategorized = nodesByCluster.get(-1) ?? []
  if (uncategorized.length > 0) {
    superNodes.push({
      id: 'super-uncategorized',
      type: 'cluster',
      content: 'Other',
      activation: uncategorized.reduce((s, n) => s + n.activation, 0) / uncategorized.length,
      importance: uncategorized.length / Math.max(...clusters.map(c => c.count)),
      access_count: uncategorized.length,
      confidence: 1,
      source_type: 'cluster',
      cluster_id: -1,
      cluster_label: 'Other',
    })
  }

  // Build cross-cluster edges
  const edgeMap = new Map<string, number>()
  for (const edge of activeGraph.edges) {
    const srcNode = activeGraph.nodes.find(n => n.id === edge.source)
    const tgtNode = activeGraph.nodes.find(n => n.id === edge.target)
    if (!srcNode || !tgtNode) continue
    const srcCluster = srcNode.cluster_id ?? -1
    const tgtCluster = tgtNode.cluster_id ?? -1
    if (srcCluster === tgtCluster) continue
    const key = [Math.min(srcCluster, tgtCluster), Math.max(srcCluster, tgtCluster)].join('-')
    edgeMap.set(key, (edgeMap.get(key) ?? 0) + 1)
  }

  const superEdges: GraphEdge[] = []
  for (const [key, count] of edgeMap) {
    const [a, b] = key.split('-').map(Number)
    const srcId = a === -1 ? 'super-uncategorized' : `super-${a}`
    const tgtId = b === -1 ? 'super-uncategorized' : `super-${b}`
    superEdges.push({
      source: srcId,
      target: tgtId,
      relation: 'cross_topic',
      weight: count,
    })
  }

  return { nodes: superNodes, edges: superEdges, nodesByCluster }
}, [activeGraph])
```

- [ ] **Step 3: Compute drill-down data when a cluster is expanded**

Add right after `topicMapData`:

```typescript
const drillData = useMemo(() => {
  if (!topicMapData || expandedCluster == null || !activeGraph) return null

  const members = topicMapData.nodesByCluster.get(expandedCluster) ?? []
  const memberIds = new Set(members.map(n => n.id))

  // Edges within the expanded cluster
  const innerEdges = activeGraph.edges.filter(
    e => memberIds.has(e.source) && memberIds.has(e.target)
  )

  return { nodes: members, edges: innerEdges }
}, [topicMapData, expandedCluster, activeGraph])
```

- [ ] **Step 4: Select which data to pass to ForceGraph3D**

Replace the current static `nodes={activeGraph?.nodes ?? []}` and `edges={activeGraph?.edges ?? []}` props with a computed selection. Add before the JSX return:

```typescript
// Determine graph data based on mode
const graphNodes = (() => {
  if (searchActive) return activeGraph?.nodes ?? []
  if (graphMode === 'topic-map' && expandedCluster != null && drillData) return drillData.nodes
  if (graphMode === 'topic-map' && topicMapData) return topicMapData.nodes
  return activeGraph?.nodes ?? []
})()

const graphEdges = (() => {
  if (searchActive) return activeGraph?.edges ?? []
  if (graphMode === 'topic-map' && expandedCluster != null && drillData) return drillData.edges
  if (graphMode === 'topic-map' && topicMapData) return topicMapData.edges
  return activeGraph?.edges ?? []
})()
```

Then update the ForceGraph3D JSX:

```tsx
<ForceGraph3D
  ref={graphRef}
  nodes={graphNodes}
  edges={graphEdges}
  // ... rest unchanged ...
/>
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`
Expected: Clean output

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/Brain.tsx
git commit -m "feat(brain): compute super-node and drill-down graph data for topic map"
```

---

### Task 5: Custom Super-Node Rendering in ForceGraph3D

**Files:**
- Modify: `dashboard/src/components/ForceGraph3D.tsx:80-96` (add `graphMode` prop)
- Modify: `dashboard/src/components/ForceGraph3D.tsx` (node rendering callback)

Super-nodes need to render as larger orbs with count labels. This uses the existing `nodeThreeObject` callback.

- [ ] **Step 1: Add graphMode prop**

```typescript
interface ForceGraph3DProps {
  // ... existing ...
  graphMode?: 'full' | 'topic-map' | 'topic-drill'
}
```

Accept it in the component with default `'full'`.

- [ ] **Step 2: Detect super-nodes in the node rendering callback**

In the existing `nodeThreeObject` callback (where `makeOrbMaterial` creates node meshes), add a branch for super-nodes. Super-nodes have `type === 'cluster'`:

```typescript
.nodeThreeObject((node: any) => {
  const isSuperNode = node.type === 'cluster'

  if (isSuperNode) {
    const count = node.access_count ?? 0
    const maxCount = Math.max(...(graphRef.current?.graphData().nodes ?? [node])
      .filter((n: any) => n.type === 'cluster')
      .map((n: any) => n.access_count ?? 1))
    const normSize = count / Math.max(maxCount, 1)
    const radius = 4 + normSize * 12  // super-nodes are 4-16 units

    const color = node.cluster_id != null && node.cluster_id >= 0
      ? CLUSTER_COLORS[node.cluster_id % CLUSTER_COLORS.length]
      : '#71717a'

    const group = new Group()

    // Main orb
    const mat = makeOrbMaterial(color, 0.6 + node.activation * 0.3, node.activation)
    const mesh = new Mesh(new SphereGeometry(radius, 24, 24), mat)
    group.add(mesh)

    // Count label (sprite)
    const canvas = document.createElement('canvas')
    canvas.width = 256; canvas.height = 128
    const ctx = canvas.getContext('2d')!
    ctx.clearRect(0, 0, 256, 128)
    ctx.font = '700 48px system-ui'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = 'rgba(255,255,255,0.85)'
    ctx.fillText(String(count), 128, 50)
    ctx.font = '400 24px system-ui'
    ctx.fillStyle = color
    ctx.fillText(node.content?.slice(0, 20) ?? '', 128, 90)
    const tex = new CanvasTexture(canvas)
    const spriteMat = new SpriteMaterial({ map: tex, transparent: true, depthWrite: false })
    const sprite = new Sprite(spriteMat)
    sprite.position.set(0, -radius - 6, 0)
    sprite.scale.set(30, 15, 1)
    group.add(sprite)

    return group
  }

  // ... existing node rendering for regular nodes ...
})
```

- [ ] **Step 3: Handle super-node click to trigger drill-down**

In the `ForceGraph3D` component, the `onSelectNode` callback already fires when any node is clicked. In `Brain.tsx`, intercept super-node clicks:

In Brain.tsx, modify the `onSelectNode` callback:

```typescript
onSelectNode={(id: string) => {
  if (graphMode === 'topic-map' && id.startsWith('super-')) {
    const clusterId = id === 'super-uncategorized' ? -1 : parseInt(id.replace('super-', ''))
    setExpandedCluster(clusterId)
    setSelectedNode(null)
  } else {
    setSelectedNode(id)
  }
}}
```

- [ ] **Step 4: Pass graphMode to ForceGraph3D**

```tsx
<ForceGraph3D
  // ...
  graphMode={graphMode === 'topic-map' ? (expandedCluster != null ? 'topic-drill' : 'topic-map') : 'full'}
/>
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`
Expected: Clean output

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/ForceGraph3D.tsx dashboard/src/pages/Brain.tsx
git commit -m "feat(brain): custom super-node rendering and click-to-drill"
```

---

### Task 6: Polish — Drill-Down Transitions and Edge Cases

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx`
- Modify: `dashboard/src/components/ForceGraph3D.tsx`

- [ ] **Step 1: Auto-zoom when entering/exiting drill mode**

When `expandedCluster` changes, trigger a `zoomToFit`:

```typescript
useEffect(() => {
  if (graphMode !== 'topic-map') return
  // Give the force sim a moment to settle, then zoom
  const timer = setTimeout(() => {
    try {
      graphRef.current?.// call internal graph zoomToFit if exposed, or use focusCluster
    } catch { /* ok */ }
  }, 600)
  return () => clearTimeout(timer)
}, [expandedCluster, graphMode])
```

Since `ForceGraph3DHandle` doesn't expose `zoomToFit`, use the existing `focusClusterId` prop when entering drill-down to animate the camera:

```typescript
// When drilling in, set focusCluster to trigger camera animation
useEffect(() => {
  if (expandedCluster != null) {
    setFocusCluster({ id: expandedCluster, ts: Date.now() })
  }
}, [expandedCluster])
```

- [ ] **Step 2: Fall back to Full Graph when < 3 clusters**

Already handled: the mode selector only renders when `clusters.length >= 3`. If clusters drop below 3 (e.g., after search), force mode to full:

```typescript
useEffect(() => {
  if (graphMode === 'topic-map' && (!activeGraph?.clusters || activeGraph.clusters.length < 3)) {
    setGraphMode('full')
    setExpandedCluster(null)
  }
}, [activeGraph?.clusters, graphMode])
```

- [ ] **Step 3: Reset drill-down when switching modes**

Already handled in the mode selector onClick: `setExpandedCluster(null)`. Also reset when search becomes active:

```typescript
// In handleSearch:
const handleSearch = (e: React.FormEvent) => {
  e.preventDefault()
  if (searchQuery.trim().length > 2) {
    setSearchActive(true)
    setExpandedCluster(null)  // collapse drill on search
  }
}
```

- [ ] **Step 4: Hide topic sidebar when in Topic Map mode (super-nodes are the navigation)**

Wrap the existing topic sidebar with a condition:

```typescript
{graphMode !== 'topic-map' && activeGraph && activeGraph.nodes.length > 0 && (
  // ... existing topic sidebar ...
)}
```

Or keep it visible in drill-down mode for navigation. Either way — when in topic-map overview, the super-nodes serve as the sidebar, so hiding the sidebar reduces clutter.

- [ ] **Step 5: Full manual QA pass**

Test in browser:
1. Full Graph mode — unchanged behavior
2. Switch to Topic Map — super-nodes appear with counts and labels
3. Click a super-node — drills into its memories, breadcrumb appears
4. Click "All Topics" or press Escape — collapses back
5. Toggle background stars on/off
6. Toggle inner stars on/off
7. Search while in Topic Map — falls back to Full Graph results
8. Fewer than 3 clusters — mode selector hidden

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/Brain.tsx dashboard/src/components/ForceGraph3D.tsx
git commit -m "feat(brain): polish drill transitions, edge cases, and sidebar behavior"
```

---

### Task 7: Final TypeScript Build Verification

- [ ] **Step 1: Full build check**

Run: `cd dashboard && npm run build`
Expected: Clean build, no errors

- [ ] **Step 2: Commit any remaining fixes if needed**
