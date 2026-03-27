# Brain Topic Map & Display Settings

**Date:** 2026-03-27
**Status:** Approved
**Scope:** Dashboard Brain page — new graph view mode + starfield display toggles

## Problem

The Brain page currently shows all memory nodes at once (Full Graph). This works for exploration but makes it hard to answer high-level questions: "What does Nova know a lot about? Which knowledge areas connect? Where are the gaps?" Additionally, the starfield background has no user controls — users can't toggle the inner star layer or background stars on/off.

## Design

### Graph View Modes

A "Graph View" setting in the Brain page with two modes:

#### Full Graph (default, current behavior)
- All nodes visible, colored by cluster/type
- Existing spatial clustering via force simulation
- No changes to current implementation

#### Topic Map
- Each cluster collapses into a **super-node** — a single larger orb
- Super-node **size** proportional to memory count in that cluster
- Super-node **glow/brightness** reflects average activation (hot vs cold topics)
- Super-node displays the **count** inside and **topic label** below
- **Edges between super-nodes** represent cross-cluster connections, thickness proportional to connection density
- Clicking a super-node **drills in** (see below)

#### Topic Map Drill-Down (not a separate setting — triggered by clicking a super-node)
- The clicked super-node expands to show its individual memory nodes in the center
- Other super-nodes **dim and shrink** but remain visible around the periphery
- **Bridge edges** (dashed) connect expanded nodes to other super-nodes where cross-cluster edges exist
- Camera zooms to frame the expanded cluster
- A **breadcrumb** appears top-right: `All Topics > [Topic Name]`
- Clicking "All Topics" or pressing Escape collapses back to the Topic Map
- Clicking a bridge edge or a connection to another cluster: collapse current, expand target

### Display Settings

Two toggles added to the Brain page UI (near the graph view selector):

| Toggle | Controls | Default |
|--------|----------|---------|
| Background Stars | The deep-field star layer (radius 4000-8000, `sizeAttenuation: false`) | On |
| Inner Stars | The original dim/bright star layers (radius 500-1500, `sizeAttenuation: true`) | Off |

These are cosmetic — no impact on graph data or behavior.

## Data Flow

### Super-Node Computation (client-side)
The API already returns `clusters: ClusterInfo[]` with `{ id, label, count }` and each node has `cluster_id`. Super-nodes are computed in the Brain component by:

1. Grouping nodes by `cluster_id`
2. For each cluster: count nodes, compute average activation, collect cross-cluster edges
3. Build a super-node graph: nodes = clusters, edges = aggregated cross-cluster connections with weight = edge count

No backend changes required.

### Graph Data Switching
- **Topic Map mode:** Pass super-node graph data to `ForceGraph3D`
- **Drill-down:** Pass the expanded cluster's nodes + edges, plus super-node stubs for other clusters (rendered as dimmed orbs via custom node rendering)
- **Full Graph mode:** Pass all nodes/edges as today

The `ForceGraph3D` component already accepts `nodes` and `edges` as props. The data transformation happens in `Brain.tsx` before passing to the component.

### ForceGraph3D Changes
- New prop: `graphMode: 'full' | 'topic-map' | 'topic-drill'`
- Super-nodes need custom rendering (larger orb, count label inside, topic label below) — handled via the existing `nodeThreeObject` callback
- Dimmed super-nodes in drill mode: reduced opacity, smaller scale
- Bridge edges: dashed line material
- The existing `focusClusterId` mechanism can be reused for the drill-in camera animation

### State in Brain.tsx
```
graphMode: 'full' | 'topic-map'          // user setting
expandedCluster: number | null            // null = topic map overview, number = drilled into cluster ID
```

When `graphMode = 'topic-map'` and `expandedCluster = null`: show super-nodes.
When `graphMode = 'topic-map'` and `expandedCluster = 3`: show cluster 3 expanded + dimmed others.
When `graphMode = 'full'`: current behavior.

### Star Toggles
- `showBackgroundStars: boolean` — controls whether deep-field layer is added to starfield group
- `showInnerStars: boolean` — controls whether dim/bright layers are included in starfield group
- Passed as props to `ForceGraph3D`, which rebuilds the starfield when they change (existing `bgColor` effect already handles starfield rebuild)

## UI Placement

The graph view selector and star toggles go in the **top search bar area** of the Brain page, next to the existing stats badge. Compact inline controls:

```
[Search...] | 247 memories · 7 topics | [Full Graph v] | [Stars: on] [Inner: off]
```

The graph view is a small dropdown/segmented control. Star toggles are small icon buttons or toggle switches.

## Edge Cases

- **< 3 clusters:** Fall back to Full Graph — Topic Map with 1-2 nodes isn't useful
- **Uncategorized nodes (cluster_id = null):** Group into an "Other" super-node
- **50+ clusters:** Show all in Topic Map (force layout handles it). Sidebar already caps at 30 with "+N more"
- **Search active:** Topic Map doesn't apply to search results — search always shows Full Graph of matching nodes
- **Empty cluster after drill:** Show empty state with "No memories in this topic" and back button

## Out of Scope

- Zoom-based auto-collapse/expand (option C from brainstorming — too fragile)
- Persisting graph mode to localStorage (can add later if wanted)
- Backend changes or new API endpoints
