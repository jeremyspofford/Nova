# Brain Visual Overhaul — Phase 1: Star Shader + Layout

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Brain page from a dashboard panel into an immersive full-screen visualization with star-style nodes, bloom-based glow, and a minimal HUD layout.

**Architecture:** Replace the Fresnel orb shader with a soft radial-falloff star shader. Remove per-node glow sprites in favor of the existing `UnrealBloomPass` (already imported). Move per-frame animation loops (breathing, fade-in, highlights) into shader uniforms. Cap nodes at 500. Restructure the Brain page layout from scattered-corners to minimal HUD with icon-triggered overlays.

**Tech Stack:** React, TypeScript, Three.js ShaderMaterial, UnrealBloomPass, 3d-force-graph, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-28-brain-visual-overhaul-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `dashboard/src/components/ForceGraph3D.tsx` | Modify | Star shader, bloom-driven glow, shared time uniform, shader-driven animation, hit spheres, node cap |
| `dashboard/src/pages/Brain.tsx` | Modify | Minimal HUD layout, overlay state, restructured controls, mic button, node cap query param |

Two files. ForceGraph3D.tsx is 1318 lines — large but all the rendering logic lives here and splitting would break the tightly coupled Three.js lifecycle. We're replacing sections in place.

---

### Task 1: Cap Node Count and Shared Time Uniform

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx:111` (query param)
- Modify: `dashboard/src/components/ForceGraph3D.tsx` (shared time uniform)

This is the foundation — cap the node count for performance and set up the shared time uniform that the star shader will use.

- [ ] **Step 1: Cap max_nodes to 500 in Brain.tsx**

In `Brain.tsx:111`, change the graph query:

```typescript
queryFn: () => apiFetch('/mem/api/v1/engrams/graph?mode=full&max_nodes=500'),
```

- [ ] **Step 2: Create shared time uniform in ForceGraph3D.tsx**

After the existing imports (~line 22), add a shared uniform object that all node materials will reference:

```typescript
// Shared uniform — update once per frame, all materials see the new value
const sharedUniforms = {
  uTime: { value: 0 },
}
```

- [ ] **Step 3: Update uTime in the tick loop**

In the `tick()` function (~line 900), at the very top before any other logic:

```typescript
sharedUniforms.uTime.value = Date.now() * 0.001
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/Brain.tsx dashboard/src/components/ForceGraph3D.tsx
git commit -m "perf(brain): cap nodes at 500, add shared time uniform"
```

---

### Task 2: Star Shader — Replace Fresnel Orb

**Files:**
- Modify: `dashboard/src/components/ForceGraph3D.tsx:198-272` (shader code + makeOrbMaterial)

Replace the solid Fresnel orb shader with a soft radial-falloff star shader. The sphere geometry is kept for raycasting but the visual is a soft luminous glow with no hard surface edge.

- [ ] **Step 1: Replace the vertex and fragment shaders**

Replace `orbVertexShader` and `orbFragmentShader` (~lines 200-250) with:

```typescript
const starVertexShader = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vViewDir;
  varying float vFacing;
  void main() {
    vNormal = normalize(normalMatrix * normal);
    vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
    vViewDir = normalize(-mvPos.xyz);
    vFacing = dot(vNormal, vViewDir);
    gl_Position = projectionMatrix * mvPos;
  }
`

const starFragmentShader = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform float uImportance;
  uniform float uBirthTime;
  uniform float uHighlightStart;
  uniform float uTime;

  varying float vFacing;

  void main() {
    // Soft radial falloff — facing=1 at center, 0 at rim
    // Steep power curve makes the center bright with a smooth fade
    float glow = pow(max(vFacing, 0.0), 1.8);

    // Bright white-hot center point
    float center = pow(max(vFacing, 0.0), 8.0);

    // Breathing animation — importance-based phase offset
    float breathe = 1.0 + sin(uTime * 0.4 + uImportance * 6.28) * 0.08;

    // Birth fade-in (1 second)
    float age = uTime - uBirthTime;
    float birthFade = clamp(age, 0.0, 1.0);

    // Highlight pulse (fades out over 2.5 seconds)
    float highlightAge = uTime - uHighlightStart;
    float highlight = uHighlightStart > 0.0
      ? max(0.0, 1.0 - highlightAge / 2.5) * 0.4
      : 0.0;

    // Combine: colored glow + white center
    float brightness = (0.3 + uImportance * 0.7) * breathe;
    vec3 col = uColor * glow * brightness + vec3(1.0) * center * brightness * 0.6;
    col += uColor * highlight;

    // Alpha: glow fades to transparent at rim
    float alpha = glow * uOpacity * birthFade + center * 0.5 * birthFade;
    alpha = clamp(alpha, 0.0, 1.0);

    gl_FragColor = vec4(col, alpha);
  }
`
```

- [ ] **Step 2: Replace makeOrbMaterial with makeStarMaterial**

Replace the `makeOrbMaterial` function (~lines 252-272) with:

```typescript
function makeStarMaterial(
  color: string,
  importance: number,
  birthTime: number,
): ShaderMaterial {
  const mat = new ShaderMaterial({
    uniforms: {
      uColor: { value: new Color(color) },
      uOpacity: { value: 0.3 + importance * 0.7 },
      uImportance: { value: importance },
      uBirthTime: { value: birthTime },
      uHighlightStart: { value: 0 },
      uTime: sharedUniforms.uTime,  // shared reference — updated once per frame
    },
    vertexShader: starVertexShader,
    fragmentShader: starFragmentShader,
    transparent: true,
    side: FrontSide,
    depthWrite: false,
  })
  Object.defineProperty(mat, 'opacity', {
    get() { return mat.uniforms.uOpacity.value },
    set(v: number) { mat.uniforms.uOpacity.value = v },
  })
  return mat
}
```

Note: `depthWrite: false` because stars are transparent glows, not solid surfaces.

- [ ] **Step 3: Update all references from makeOrbMaterial to makeStarMaterial**

Search for `makeOrbMaterial` in the file and replace each call. The main call site is in the `nodeThreeObject` callback (~line 706):

Old:
```typescript
const mat = makeOrbMaterial(color, alpha, activation)
```

New:
```typescript
const birthTime = sharedUniforms.uTime.value
const mat = makeStarMaterial(color, importance, birthTime)
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/ForceGraph3D.tsx
git commit -m "feat(brain): replace Fresnel orb with star glow shader"
```

---

### Task 3: Remove Per-Node Glow Sprites, Rely on Bloom

**Files:**
- Modify: `dashboard/src/components/ForceGraph3D.tsx` (nodeThreeObject callback, bloom config)

The star shader produces bright cores. The existing `UnrealBloomPass` will create the glow halo automatically. Remove the per-node glow sprites to eliminate 500 additive draw calls.

- [ ] **Step 1: Remove glow sprite creation from nodeThreeObject**

In the `nodeThreeObject` callback (~lines 710-723), remove the entire glow sprite block:

```typescript
// DELETE this entire block:
// Glow sprite — skip for unimportant nodes in large graphs
if (!isLargeGraph || importance >= 0.3) {
  const spriteMat = new SpriteMaterial({
    ...
  })
  const sprite = new Sprite(spriteMat)
  sprite.scale.set(radius * 3, radius * 3, 1)
  group.add(sprite)
}
```

- [ ] **Step 2: Tune bloom pass for star rendering**

Find where the bloom pass is configured. The `neuralMode.bloomStrength` is currently 1.2. For star-style rendering, increase bloom radius and adjust threshold so bright star cores produce visible halos. Find the bloom pass initialization (search for `UnrealBloomPass`) and update:

The bloom pass is likely created with something like:
```typescript
new UnrealBloomPass(new Vector2(w, h), strength, radius, threshold)
```

Update to:
```typescript
new UnrealBloomPass(new Vector2(w, h), 1.5, 0.6, 0.15)
// strength=1.5 (stronger bloom), radius=0.6 (wider halo), threshold=0.15 (catch dimmer cores)
```

The exact values may need tuning — these are starting points. The threshold at 0.15 means any fragment brighter than ~15% will bloom.

- [ ] **Step 3: Adjust node size for star rendering**

In the `nodeThreeObject` callback, update the radius calculation to match the spec:

Old:
```typescript
const baseRadius = isLargeGraph ? 1.2 : 2
const radiusScale = isLargeGraph ? 2.5 : 4
const radius = baseRadius + importance * radiusScale
```

New (with 500-node cap, `isLargeGraph` is false for < 500):
```typescript
const radius = 2 + importance * 6
```

- [ ] **Step 4: Add invisible hit sphere for click detection**

After creating the mesh in `nodeThreeObject`, add a larger invisible sphere for raycasting:

```typescript
// Invisible hit target — 2.5x core radius for comfortable clicking
const hitGeo = new SphereGeometry(radius * 2.5, 8, 8)
const hitMat = new ShaderMaterial({
  transparent: true,
  depthWrite: false,
  fragmentShader: 'void main() { gl_FragColor = vec4(0.0); }',
  vertexShader: 'void main() { gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
})
const hitSphere = new Mesh(hitGeo, hitMat)
hitSphere.renderOrder = -1
group.add(hitSphere)
```

Note: use a shared `SphereGeometry` instance for the hit sphere to prepare for instancing. Create one outside the callback:

```typescript
// Outside nodeThreeObject, near top of component:
const hitGeoRef = useRef(new SphereGeometry(1, 8, 8))  // unit sphere, scaled per node
```

Then inside the callback:
```typescript
const hitSphere = new Mesh(hitGeoRef.current, hitMat)
hitSphere.scale.setScalar(radius * 2.5)
```

- [ ] **Step 5: Share the core SphereGeometry too**

Create a shared geometry for the star core:

```typescript
const coreGeoRef = useRef(new SphereGeometry(1, 24, 24))  // unit sphere
```

Then in nodeThreeObject:
```typescript
const mesh = new Mesh(coreGeoRef.current, mat)
mesh.scale.setScalar(radius)
```

This reuses geometry across all nodes (prep for instanced rendering).

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/components/ForceGraph3D.tsx
git commit -m "feat(brain): bloom-driven glow, remove per-node sprites, shared geometry"
```

---

### Task 4: Shader-Driven Animation — Remove forEach Loops

**Files:**
- Modify: `dashboard/src/components/ForceGraph3D.tsx:934-1017` (tick loop animation blocks)

The star shader already handles breathing and birth fade-in via uniforms. Remove the 3 per-frame forEach loops that iterate all nodes.

- [ ] **Step 1: Remove the neural mode per-node pulsation loop**

In the tick function (~lines 942-954), remove the `graphData.nodes.forEach` block that sets `child.scale.setScalar(scale)`. Keep the bloom breathing block (lines 956-961) — that's one uniform update, not a per-node loop.

- [ ] **Step 2: Remove the highlight opacity forEach loop**

In the tick function (~lines 967-982), remove the `graphData.nodes.forEach` block that boosts opacity on highlighted nodes.

Replace with a shader-based approach: when `highlightNodes()` is called on the imperative handle, set `uHighlightStart` on each highlighted node's material:

```typescript
// In the highlightNodes imperative handle method:
highlightNodes: (ids: string[], durationMs: number) => {
  const graph = graphRef.current
  if (!graph) return
  const now = sharedUniforms.uTime.value
  const data = graph.graphData()
  for (const node of data.nodes) {
    if (!ids.includes(node.id)) continue
    const obj = node.__threeObj
    if (!obj) continue
    obj.children.forEach((child: any) => {
      if (child.material?.uniforms?.uHighlightStart) {
        child.material.uniforms.uHighlightStart.value = now
      }
    })
  }
  // Remove the old timeout-based cleanup — shader handles fade-out
}
```

- [ ] **Step 3: Remove the fade-in nodes forEach loop**

In the tick function (~lines 999-1016), remove the `graphData.nodes.forEach` block that multiplies opacity by birth alpha. The star shader handles this via `uBirthTime`.

Update the `fadeInNodes` imperative handle to set `uBirthTime` instead:

```typescript
fadeInNodes: (ids: string[], _durationMs: number) => {
  const graph = graphRef.current
  if (!graph) return
  const now = sharedUniforms.uTime.value
  const data = graph.graphData()
  for (const node of data.nodes) {
    if (!ids.includes(node.id)) continue
    const obj = node.__threeObj
    if (!obj) continue
    obj.children.forEach((child: any) => {
      if (child.material?.uniforms?.uBirthTime) {
        child.material.uniforms.uBirthTime.value = now
      }
    })
  }
}
```

- [ ] **Step 4: Clean up unused refs**

Remove `highlightedNodesRef` and `fadeInNodesRef` if they're no longer read anywhere. Keep `globalPulseRef` (it modifies bloom strength, not per-node — that's fine).

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/ForceGraph3D.tsx
git commit -m "perf(brain): move animation to shader uniforms, remove per-frame forEach loops"
```

---

### Task 5: Minimal HUD Layout — Restructure Brain.tsx

**Files:**
- Modify: `dashboard/src/pages/Brain.tsx` (complete layout restructure)

Replace the scattered-corners layout with the minimal HUD: stats pill top-center, icon buttons for overlays, mic button bottom-center.

- [ ] **Step 1: Add overlay state and new imports**

Add to Brain.tsx state declarations:

```typescript
const [settingsOpen, setSettingsOpen] = useState(false)
const [topicsOpen, setTopicsOpen] = useState(false)
```

Add lucide imports (check which are already imported):
```typescript
import { Search, X, ChevronRight, Network, Settings, Menu, Mic } from 'lucide-react'
```

Remove `MessageSquare` if no longer used (the chat FAB is replaced by the mic button).

- [ ] **Step 2: Replace the top-left controls block**

Remove the entire `{/* ── Top Left: Search + Layout + Stats */}` div (the one containing search bar, stats badge, and display toggles). Remove the collapsible sidebar block too.

Replace with the minimal HUD elements:

```tsx
{/* ── HUD: Stats pill top-center ──────────────────────────────────── */}
{activeGraph && (
  <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10">
    <div className="bg-black/40 backdrop-blur-sm border border-white/6 rounded-full px-3.5 py-1 flex items-center gap-2">
      <span className="text-[10px] text-stone-600">{activeGraph.nodes.length} memories</span>
      <span className="w-px h-2.5 bg-white/8" />
      <span className="text-[10px] text-stone-600">
        {activeGraph.clusters ? `${activeGraph.clusters.length} topics` : `${activeGraph.edges.length} connections`}
      </span>
    </div>
  </div>
)}

{/* ── HUD: Topics icon top-left ───────────────────────────────────── */}
<button
  onClick={() => setTopicsOpen(v => !v)}
  className="absolute top-3 left-3 z-10 w-8 h-8 rounded-full bg-black/40 backdrop-blur-sm border border-white/6 flex items-center justify-center text-stone-600 hover:text-stone-300 transition-colors"
>
  <Menu size={14} />
</button>

{/* ── HUD: Settings icon top-right ────────────────────────────────── */}
<button
  onClick={() => setSettingsOpen(v => !v)}
  className="absolute top-3 right-3 z-10 w-8 h-8 rounded-full bg-black/40 backdrop-blur-sm border border-white/6 flex items-center justify-center text-stone-600 hover:text-stone-300 transition-colors"
>
  <Settings size={14} />
</button>

{/* ── HUD: Mic button bottom-center ───────────────────────────────── */}
<button
  onClick={() => setChatOpen(v => !v)}
  className="absolute bottom-5 left-1/2 -translate-x-1/2 z-10 w-12 h-12 rounded-full bg-teal-500/15 border-2 border-teal-500/40 flex items-center justify-center text-teal-400 hover:bg-teal-500/25 transition-colors shadow-[0_0_20px_rgba(20,184,166,0.15)]"
>
  <Mic size={18} />
</button>

{/* ── HUD: Search hint bottom-left ────────────────────────────────── */}
<div className="absolute bottom-5 left-3 z-10">
  <div className="bg-black/30 rounded-full px-2.5 py-1">
    <span className="text-[9px] text-stone-700">/ search</span>
  </div>
</div>
```

- [ ] **Step 3: Create the Topics/Search overlay**

This replaces the old sidebar + search bar. Opens from the top-left icon:

```tsx
{/* ── Overlay: Topics & Search ────────────────────────────────────── */}
{topicsOpen && (
  <div
    className="absolute inset-0 z-20"
    onClick={(e) => { if (e.target === e.currentTarget) setTopicsOpen(false) }}
  >
    <div className="absolute top-0 left-0 w-[280px] h-full bg-black/80 backdrop-blur-md border-r border-white/6 p-4 overflow-y-auto scrollbar-thin">
      {/* Close */}
      <button
        onClick={() => setTopicsOpen(false)}
        className="absolute top-3 right-3 text-stone-600 hover:text-stone-300 transition-colors"
      >
        <X size={14} />
      </button>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex items-center gap-1.5 border border-white/10 rounded-lg px-3 py-1.5 mb-4">
        <Search size={13} className="text-stone-600 shrink-0" />
        <input
          type="text"
          value={searchQuery}
          onChange={e => { setSearchQuery(e.target.value); if (!e.target.value) clearSearch() }}
          placeholder="Search memories..."
          className="bg-transparent text-sm text-stone-300 placeholder:text-stone-700 outline-none flex-1"
        />
        {searchActive && (
          <button type="button" onClick={clearSearch} className="text-stone-600 hover:text-stone-300">
            <X size={11} />
          </button>
        )}
      </form>

      {/* Topic list — reuse existing cluster/type listing content */}
      {activeGraph && activeGraph.clusters && activeGraph.clusters.length > 0 ? (
        <>
          <div className="text-[10px] text-stone-600 uppercase tracking-wider px-1 pb-1.5 mb-1 border-b border-white/5">
            {activeGraph.clusters.length} topics
          </div>
          {/* Existing cluster listing JSX goes here — copy from current sidebar */}
        </>
      ) : activeGraph ? (
        <>
          <div className="text-[10px] text-stone-600 uppercase tracking-wider px-1 pb-1.5 mb-1 border-b border-white/5">
            Types
          </div>
          {/* Existing type listing JSX goes here — copy from current sidebar */}
        </>
      ) : null}
    </div>
  </div>
)}
```

Move the existing cluster listing and type listing JSX from the old sidebar into this overlay. The content stays the same — only the container changes.

- [ ] **Step 4: Create the Settings overlay**

This will hold the background toggles for now (color mode and edge style come in Phase 2):

```tsx
{/* ── Overlay: Display Settings ───────────────────────────────────── */}
{settingsOpen && (
  <div
    className="absolute inset-0 z-20"
    onClick={(e) => { if (e.target === e.currentTarget) setSettingsOpen(false) }}
  >
    <div className="absolute top-12 right-3 w-[220px] bg-black/80 backdrop-blur-md border border-white/8 rounded-xl p-4 space-y-4">
      {/* Close */}
      <button
        onClick={() => setSettingsOpen(false)}
        className="absolute top-3 right-3 text-stone-600 hover:text-stone-300 transition-colors"
      >
        <X size={12} />
      </button>

      <div className="text-[10px] text-stone-500 uppercase tracking-wider">Display</div>

      {/* Background toggles */}
      <div className="space-y-2">
        <div className="text-[10px] text-stone-600 mb-1">Background</div>
        {[
          { label: 'Stars', value: showBgStars, set: setShowBgStars },
          { label: 'Inner Stars', value: showInnerStars, set: setShowInnerStars },
          { label: 'Clouds', value: showNebulae, set: setShowNebulae },
        ].map(({ label, value, set }) => (
          <button
            key={label}
            onClick={() => set((v: boolean) => !v)}
            className={`block w-full text-left text-[11px] px-2 py-1 rounded transition-colors ${
              value
                ? 'text-teal-400 bg-teal-500/10'
                : 'text-stone-600 hover:text-stone-400'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 5: Remove the old Graph Key legend**

Remove the entire `{/* ── Bottom Left: Graph Key */}` block. The settings panel will explain what's configurable.

- [ ] **Step 6: Wire Escape key to close overlays**

Update the keyboard handler to close overlays:

```typescript
if (e.key === 'Escape') {
  if (settingsOpen) setSettingsOpen(false)
  else if (topicsOpen) setTopicsOpen(false)
  else if (chatOpen) setChatOpen(false)
  else if (selectedNode) setSelectedNode(null)
  else if (searchActive) { setSearchActive(false); setSearchQuery('') }
}
```

Add `settingsOpen, topicsOpen` to the useEffect dependency array.

- [ ] **Step 7: Verify TypeScript compiles**

Run: `cd dashboard && npx tsc --noEmit`

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/pages/Brain.tsx
git commit -m "feat(brain): minimal HUD layout with overlay panels"
```

---

### Task 6: Visual QA and Bloom Tuning

**Files:**
- Modify: `dashboard/src/components/ForceGraph3D.tsx` (bloom params, shader tweaks)
- Modify: `dashboard/src/pages/Brain.tsx` (any layout fixes)

This is a manual tuning pass. Open the Brain page and adjust values until the star rendering looks right.

- [ ] **Step 1: Open Brain page and evaluate star rendering**

Run: open `http://localhost:5173/brain` in the browser

Check:
- Do nodes look like luminous stars (soft glow, no hard edge)?
- Does the bloom create visible halos around bright nodes?
- Are dim nodes (low importance) visible as faint specks?
- Is the breathing animation subtle and smooth?
- Can you click nodes reliably (hit sphere working)?

- [ ] **Step 2: Tune bloom parameters if needed**

Adjust in the bloom pass initialization:
- `strength`: higher = more glow (try 1.0-2.0)
- `radius`: higher = wider bloom (try 0.4-0.8)
- `threshold`: lower = more nodes bloom (try 0.1-0.3)

- [ ] **Step 3: Tune shader parameters if needed**

In `starFragmentShader`:
- Core falloff power (currently `pow(vFacing, 1.8)`) — higher = tighter core
- Center point power (currently `pow(vFacing, 8.0)`) — higher = smaller hot center
- Breathing amplitude (currently `0.08`) — lower for subtler
- Breathing speed (currently `0.4`) — lower for slower

- [ ] **Step 4: Verify layout on different viewport sizes**

Resize browser window. Check:
- HUD elements stay positioned correctly
- Overlays don't overflow
- Mic button stays centered

- [ ] **Step 5: Commit any tuning changes**

```bash
git add dashboard/src/components/ForceGraph3D.tsx dashboard/src/pages/Brain.tsx
git commit -m "fix(brain): tune bloom and star shader parameters"
```

---

### Task 7: Full Build Verification

- [ ] **Step 1: TypeScript check**

Run: `cd dashboard && npx tsc --noEmit`

- [ ] **Step 2: Production build**

Run: `cd dashboard && npm run build`
Expected: Clean build

- [ ] **Step 3: Commit any fixes**
