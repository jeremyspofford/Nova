# Brain Instanced Rendering + Lightweight API

**Date:** 2026-03-28
**Status:** Approved
**Scope:** ForceGraph3D rendering architecture, graph API optimization, Brain feature flag

## Problem

The Brain page renders each node as a separate Three.js Mesh object. At 2000+ nodes, this produces ~2000+ draw calls per frame. GPU pipelines stall on draw call overhead (not triangle count), causing visible jank during camera orbit and zoom. Previous optimizations (shader-driven animation, physics freeze, hit sphere removal) reduced per-frame JS cost but did not address draw call count.

Additionally, the graph API returns full node metadata (content, source_type, access_count, created_at) for every node, even though the 3D renderer only needs id, type, importance, and cluster assignment. This inflates the initial payload unnecessarily.

Finally, Brain is resource-intensive enough that it should be an opt-out feature for users on constrained hardware.

## Design

### 1. Lightweight Graph API

Add a `fields=minimal` query parameter to the existing `/api/v1/engrams/graph` endpoint.

**When `fields=minimal`:**
- Node fields returned: `id`, `type`, `importance`, `cluster_id`, `cluster_label`, `content` (truncated to 120 chars — needed for hover tooltips and sidebar node lists)
- Edge fields returned: `source_id`, `target_id`, `weight`
- Omitted: `activation`, `access_count`, `confidence`, `source_type`, `superseded`, `created_at`, edge `relation`, edge `co_activations`

**Why keep content:** The hover tooltip (`nodeLabel`) displays `node.content` and the topics sidebar lists nodes by content text. Omitting content entirely would break both. A short truncation (120 chars vs current 200) keeps the payload small while preserving these features.

**Full node detail on click:** Already handled by `GET /api/v1/engrams/engrams/{id}` — no changes needed. Returns full untruncated content, scores, metadata.

**Backend change:** In `memory-service/app/engram/router.py`, the `mode=full` SQL query adds a conditional SELECT list based on the `fields` parameter. Minimal mode: `SELECT id::text, type, LEFT(content, 120) AS content, importance FROM engrams`. The clustering logic (topic edges, centroid computation) is unchanged — it only needs `id` and `type`.

**Estimated payload reduction:** ~50-60% smaller for the initial graph load.

**Brain.tsx change:** The main graph query switches to `fields=minimal`. The `GraphNode` TypeScript interface makes `activation`, `access_count`, `confidence`, `source_type`, `superseded`, `created_at` optional.

### 2. Instanced Rendering

Replace per-node `Mesh` objects with a single `InstancedMesh` after physics stabilization.

**Lifecycle:**

1. **Physics phase (warmup + cooldown):** 3d-force-graph runs d3-force simulation using invisible placeholder nodes. The library computes positions via force-directed layout. Edge data is fed to d3-force but edges are not rendered (see Section 3).

2. **Transition:** When `onEngineStop` fires (physics complete), extract all node positions from the simulation. Build one `InstancedMesh` with per-instance attributes:
   - Position (vec3) — from d3-force computed coordinates
   - Color (vec3) — from node type/cluster
   - Scale (float) — `2 + importance * 6`
   - Importance (float) — for shader breathing amplitude
   - BirthTime (float) — `sharedUniforms.uTime.value` at creation (for fade-in)
   - HighlightStart (float) — `0` initially (set by `highlightNodes()`)

3. **Render phase:** Only the `InstancedMesh` renders. The library's per-node placeholder `Object3D`s remain in the scene (invisible, no geometry) so the library's built-in raycaster can still detect clicks via `onNodeClick`. The `InstancedMesh` handles all visuals. The star shader is adapted to read per-instance attributes via `InstancedBufferAttribute` instead of per-material uniforms. Visual output is identical — breathing, glow, bloom interaction all preserved.

**Draw calls:** ~2000 individual Mesh objects → 1 InstancedMesh. One draw call for all nodes. The invisible placeholder Object3Ds have no geometry and produce no draw calls.

**Click detection:** The library's `onNodeClick` raycasts against placeholder Object3Ds (which share the same positions as the InstancedMesh instances). Clicking triggers the existing node selection flow. No custom raycaster needed.

**Highlight and fade-in with InstancedMesh:** The `highlightNodes()` and `fadeInNodes()` imperative methods update specific entries in the `HighlightStart` and `BirthTime` `InstancedBufferAttribute` arrays, then set `attribute.needsUpdate = true`. The shader reads these per-instance values identically to how it read per-material uniforms.

**Camera controls:** 3d-force-graph's OrbitControls continue to handle orbit, zoom, and pan. No change needed.

**nodeThreeObject during physics:** Return an empty `Object3D` (no geometry, no material) so the library can track positions during simulation and handle raycasting. These remain in the scene permanently as invisible click targets.

**Graph data updates (search, new nodes):** When `updateGraphData()` is called, the simulation restarts. The existing `InstancedMesh` is disposed. New placeholder Object3Ds are created by the library. When `onEngineStop` fires again after the new layout stabilizes, a new `InstancedMesh` is built from the updated positions. The `onEngineTick` clustering force runs during the new simulation and stops when the engine stops.

### 3. Edges — Fetch for Physics, Don't Render

Edge data is fetched from the API and provided to d3-force for layout computation. Connected nodes pull toward each other during simulation, which creates the spatial clustering. However, edges are **not rendered** by default — no line draw calls.

**On node click:** The detail modal already shows a node's connections from the in-memory graph data. No change needed.

**Toggleable:** Edges can be enabled in the display settings overlay. Implemented via `graph.linkVisibility(showEdges)`. When toggled on, edges render as simple static lines (no directional particles — particles are expensive and add minimal value at this scale). Off by default.

### 4. Progressive Enhancement Settings

All visual features default to the most performant state. Users toggle on what their hardware can handle. **Persisted to localStorage** (key: `nova-brain-settings`).

| Setting | Default | Effect | Approximate cost |
|---------|---------|--------|-----------------|
| Edges | Off | Render connection lines | +5000 draw calls |
| Bloom | Off | Post-processing glow pass | +1 full-screen pass |
| Stars | Off | Background star field | +1 draw call |
| Inner Stars | Off | In-scene star particles | +1 draw call |
| Clouds | Off | Nebulae / galaxy sprites | +handful of sprites |

**When everything is off:** Black background, instanced star nodes (1 draw call), camera controls. Minimal GPU cost.

**Settings overlay:** The existing gear icon overlay in Brain.tsx already has the background toggles. Add the Edges and Bloom toggles to it. Group as "Effects" (bloom, edges) and "Background" (stars, inner stars, clouds).

**Reading persisted settings:** On mount, Brain.tsx reads `nova-brain-settings` from localStorage and initializes state from it. On change, writes back.

### 5. Brain Feature Flag

Per-user toggle stored in localStorage (key: `nova-brain-enabled`, default: `true`).

**Brain enabled (default):**
- `/` renders Brain as the landing page
- Brain appears in sidebar, mobile nav, command palette
- Nova logo click navigates to Brain

**Brain disabled:**
- `/` renders Chat as the landing page
- Brain route is not registered — navigating to `/` shows Chat
- Brain is removed from the sidebar, mobile nav, and command palette
- Nova logo click navigates to Chat
- Brain-related code does not load (route-level code splitting via `React.lazy`)

**Toggle location:** Settings > General, labeled "Brain visualization" with a description explaining the performance trade-off. A secondary toggle is accessible from within the Brain page itself (in the settings overlay) so users can disable it without navigating away if it's lagging.

**Re-enabling:** Toggling back on re-registers the Brain route and restores nav items. Takes effect on next page load (or immediately via router re-evaluation).

## Files Affected

### Backend (memory-service)
- Modify: `memory-service/app/engram/router.py` — add `fields` query parameter, conditional SELECT

### Frontend (dashboard)
- Modify: `dashboard/src/components/ForceGraph3D.tsx` — instanced rendering post-stabilization, edge rendering toggle, adapted star shader for instanced attributes
- Modify: `dashboard/src/pages/Brain.tsx` — lightweight API query, settings persistence, progressive enhancement toggles, feature flag toggle in settings overlay
- Modify: `dashboard/src/App.tsx` — conditional Brain route registration based on feature flag, React.lazy for code splitting
- Modify: `dashboard/src/components/layout/Sidebar.tsx` — conditional Brain nav item based on feature flag
- Modify: `dashboard/src/components/layout/MobileNav.tsx` — conditional Brain in primaryTabs
- Modify: `dashboard/src/components/CommandPalette.tsx` — conditional Brain entry
- Modify: `dashboard/src/pages/Settings.tsx` — Brain toggle in General section

## Performance Budget

Target: 60 FPS (16ms frame time) with 2000+ nodes, bloom off, edges off, on a mid-range GPU (e.g., integrated Intel UHD 630).

| Metric | Before (current) | After (this spec) |
|--------|-------------------|-------------------|
| Draw calls per frame | ~2000+ | ~2 (instanced mesh + background) |
| Initial payload | ~1.5MB | ~400KB (minimal fields) |
| Physics CPU (post-layout) | 0 (already frozen) | 0 |
| Per-frame JS iteration | Label check every 5th frame | Label check every 5th frame |

## Out of Scope

- Server-side position caching (pre-computed layouts)
- Color mode selector (domain/type/importance) — Phase 2 of visual overhaul
- Edge style selector (static/gradient/animated) — Phase 2
- WebWorker for physics computation
- Level-of-detail by zoom distance
