# Brain Visual Overhaul

**Date:** 2026-03-28
**Status:** Approved
**Scope:** Dashboard Brain page — node rendering, edge styles, layout redesign, display settings

## Problem

The Brain page currently renders nodes as solid Fresnel-shaded spheres with subtle glow sprites. The layout has UI scattered across all four corners (search, stats, toggles, sidebar, legend, chat FAB). As the Brain evolves into Nova's primary interface — a full-screen living visualization that users interact with via voice — the current approach doesn't scale. Nodes should look like luminous stars, edges should be configurable, and the UI should get out of the way.

## Vision

The Brain page is the app. The 3D graph fills the viewport. Users talk to Nova via microphone. The graph reacts — nodes glow during memory retrieval, new nodes animate in, the whole thing breathes during conversation. All secondary UI (topics, search, settings) is behind minimal icon buttons that open dismissable overlays.

## Design

### Node Rendering: Star-Style Glow

Replace the current solid Fresnel orb + faint glow sprite with a luminous star effect:

**Core:** Soft radial gradient centered on the node. No hard sphere edge. The core blends smoothly into the surrounding glow. A tiny bright white center point provides a focal anchor.

**Glow:** Large radial halo (5-6x core radius) using additive blending. Importance drives both core brightness and glow intensity — high-importance nodes are bright stars, low-importance nodes are dim specks.

**Shader changes:** Replace the current `orbFragmentShader` (Fresnel rim + specular + core illumination) with a softer shader that produces a radial falloff without a hard surface edge. The sphere geometry is kept for raycasting but the visual is dominated by the glow.

**Hit target:** Add an invisible sphere (2-3x visible core radius) to each node group for click detection. This prevents missed clicks on dim/small stars without triggering false positives from glow overlap.

**Size mapping:**
- Core radius: `2 + importance * 6` (small range — the glow does the heavy lifting)
- Glow radius: `coreRadius * 5-6`
- Brightness: `0.3 + importance * 0.7` (dim specks to bright stars)

### Color Modes

A 3-way toggle in display settings:

| Mode | What it shows | When to use |
|------|--------------|-------------|
| **Domain** | Each topic cluster gets a color from CLUSTER_COLORS palette | "What are the knowledge areas?" |
| **Type** | 8 fixed colors by engram type (fact=blue, entity=teal, procedure=gray, episode=amber, schema=red, goal=purple, preference=green, self_model=indigo) | "What kinds of knowledge?" |
| **Importance** | Single base color (teal), brightness = importance | "What matters most?" |

Default: Domain (current behavior). The `getNodeColor` function already supports cluster and type modes — this adds a third path.

### Edge Styles

A 3-way selector in display settings:

**Static:** Thin lines at low opacity (0.07-0.1 alpha). White. Quiet, calm. No animation.

**Gradient:** Lines pick up color from their source and target nodes. Full node color near each endpoint, fading to near-transparent at the midpoint. Line width ~1.2px. No animation.

**Animated Particles:** Faint static base lines (0.04 alpha) with slow, sparse particles drifting along them. 2 particles per edge. Each particle is a small glow dot in the source node's color. Particles fade in/out at edge endpoints.

**Particle speed slider:** When animated mode is selected, a slider controls particle speed (0.2x to 3x, default 1x). Stored as a multiplier applied to the base speed.

Default: Gradient.

### Background Toggles

Three on/off toggles (already partially built):

| Toggle | What | Default |
|--------|------|---------|
| **Stars** | Deep-field background star layer | On |
| **Inner Stars** | In-scene dim/bright star particles | Off |
| **Clouds** | Nebulae + distant galaxy sprites | On |

### Layout: Minimal HUD

Replace the current scattered-corners layout with a minimal heads-up display:

**Full-viewport graph** — the 3D visualization fills the entire screen. No permanent panels.

**Top-center:** Subtle stats pill — memory count, topic count. Semi-transparent, small text. Unobtrusive.

**Top-left:** Single icon button (hamburger/list icon). Opens a **topics/search overlay** — a slide-out panel or modal containing the topic browser and search bar. Dismissable via click-outside, Escape, or the icon.

**Top-right:** Single icon button (gear icon). Opens a **display settings overlay** — a compact floating panel with all visual controls grouped by category. Dismissable same way.

**Bottom-center:** Mic button — the primary action. Teal accent, subtle glow. This is the entry point for voice conversation.

**Bottom-left:** Faint search hint (`/ search`) — reminds keyboard users of the shortcut.

**Overlays replace current UI:**
- Topic sidebar → inside the top-left overlay
- Graph key legend → removed (the settings panel explains what's configurable; the graph is self-explanatory once you interact)
- Star/cloud toggles → inside the settings overlay
- Chat FAB → the mic button serves this role; text chat accessible from within the overlay or via `/` shortcut
- Memory detail modal → stays as-is (centered modal on node click)

### Settings Overlay Structure

Opened by the gear icon. Compact floating panel, anchored to top-right.

```
Display Settings
─────────────────────────────
Nodes
  Color: [Domain] [Type] [Importance]

Edges
  Style: [Static] [Gradient] [Animated]
  Speed: ──●────────── (when animated)

Background
  [Stars: on]  [Inner: off]  [Clouds: on]
```

### Topics/Search Overlay Structure

Opened by the hamburger icon. Slide-out panel from the left.

```
┌─────────────────────┐
│ [Search memories...] │
│                      │
│ 12 TOPICS            │
│ ● Infrastructure  52 │
│ ● AI & ML         45 │
│ ● User Prefs      38 │
│ ...                  │
│                      │
│ (expand to see nodes)│
└─────────────────────┘
```

Same content as the current collapsible sidebar, just housed in an overlay.

## Data Flow

No backend changes. All changes are client-side in two files:

- `Brain.tsx` — layout restructure, state for color mode / edge style / particle speed, overlay open/close state
- `ForceGraph3D.tsx` — new star shader, edge rendering modes, hit target spheres, new props for color mode and edge style

### New Props on ForceGraph3D

```typescript
interface ForceGraph3DProps {
  // ... existing props ...
  colorMode?: 'domain' | 'type' | 'importance'
  edgeStyle?: 'static' | 'gradient' | 'animated'
  particleSpeed?: number  // multiplier, default 1
  showBackgroundStars?: boolean
  showInnerStars?: boolean
  showNebulae?: boolean
}
```

### State in Brain.tsx

```typescript
// Display settings
const [colorMode, setColorMode] = useState<'domain' | 'type' | 'importance'>('domain')
const [edgeStyle, setEdgeStyle] = useState<'static' | 'gradient' | 'animated'>('gradient')
const [particleSpeed, setParticleSpeed] = useState(1)
const [showBgStars, setShowBgStars] = useState(true)
const [showInnerStars, setShowInnerStars] = useState(false)
const [showNebulae, setShowNebulae] = useState(true)

// Overlay state
const [settingsOpen, setSettingsOpen] = useState(false)
const [topicsOpen, setTopicsOpen] = useState(false)
```

## Edge Cases

- **Mobile viewport:** The minimal HUD works at any size. Mic button and icon buttons scale fine. Overlays should be full-height on mobile.
- **No clusters (< 3):** Color mode "Domain" falls back to type colors. Mode selector still shows all three options.
- **Animated edges disabled when graph > 500 nodes:** Too many particles would impact performance. Fall back to gradient with a note in settings.
- **Settings persistence:** Settings are ephemeral (useState) for now. Future: persist to localStorage or Redis config.

## Out of Scope

- Voice input/output integration (separate feature)
- Graph animation during conversation (reactive breathing, retrieval glow — separate feature)
- Mobile app shell / iOS/Android packaging
- Topic Map mode (removed — revisit after clustering improvements)
- Backend clustering algorithm changes
