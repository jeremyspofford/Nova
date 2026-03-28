# Dashboard Navigation Restructure

## Problem

The Brain (`/brain`) and Memory (`/engrams`) pages overlap in domain — both deal with Nova's memory system — but their names don't communicate the distinction. Brain is a 3D visualization/exploration tool; Memory is an admin dashboard with 5 tabs. Users see two similarly-named pages and aren't sure which to use.

Additionally, the Overview page (`/`) serves as a thin landing page (4 metric cards, activity feed, nav grid) that doesn't represent what Nova actually is. Brain — the living knowledge graph — is a better first impression.

## Design Decisions

### 1. Brain becomes the landing page

- Brain renders at `/` (replaces Overview) with `fullWidth` layout preserved — Brain requires full-viewport rendering for the 3D graph
- Brain is the first item in the sidebar Core section
- Nova logo in the sidebar becomes clickable, also navigates to `/` (Brain)
- Brain icon changes from `Sparkles` to `Brain` (no longer conflicts with the removed Memory page)
- Brain `minRole` changes from `member` to `guest` (matches Overview's current accessibility — unauthenticated users should see the landing page)
- `/brain` route adds a `<Navigate to="/" />` redirect for existing bookmarks/links
- MobileNav: Brain replaces Memory in the `primaryTabs` bottom tab bar (4 items). Brain is the landing page so it belongs in the persistent bottom nav, not the overflow drawer.
- CommandPalette: remove "Memory" entry, add "Brain" entry navigating to `/`

**Rationale:** The 3D knowledge graph is the most compelling representation of Nova's state. It answers "what does Nova know?" which is more interesting than "how many tasks ran today?"

### 2. Overview page removed entirely

- `Overview.tsx` deleted — no content preserved
- Sprint Health metrics (success rate, submitted/failed today) are available on the Tasks page
- Recent Activity is available via container logs
- Quick Navigation grid is redundant with the sidebar
- A proper system monitoring page may be designed as future work

**Rationale:** The Overview content is too thin to justify a page. The valuable metrics are accessible elsewhere.

### 3. Memory Explorer tab merges into Brain

Brain absorbs two pieces from the Memory page's Explorer tab:

- **Enhanced stats bar** — add edge count, archived count, and router observation count to Brain's existing stats display
- **Memory type distribution with filtering** — visual breakdown of engram types (fact, entity, preference, procedure, etc.) with click-to-filter. Integrates with Brain's existing topic clustering sidebar and node color-coding

**Not absorbed:**
- Explorer's graph search — Brain already has better search (depth 2, 200 nodes vs Explorer's depth 1, 50 nodes)
- Neural router status — operational/diagnostic, moves to Settings

### 4. Remaining Memory tabs move to Settings > Memory section

Settings gains a new "Memory" section (6th section, alongside General, Security, AI & Pipeline, Connections, System) containing:

| Subsection | Source | Purpose |
|---|---|---|
| Self-Model | EngramExplorer Self-Model tab | View/bootstrap Nova's identity engrams |
| Consolidation | EngramExplorer Consolidation tab | Memory sleep cycle triggers, logs, stats |
| Maintenance | EngramExplorer Maintenance tab | Reindexing, deduplication controls |
| Engram Sources | EngramExplorer Sources tab | Ingestion origin tracking (trust, coverage, staleness) |
| Router Status | EngramExplorer Explorer tab | Neural re-ranker training status and observations |

**Note:** The standalone `/sources` page (knowledge source configuration) is unrelated to Engram Sources (ingestion tracking) and remains unchanged in the sidebar.

### 5. Memory page and nav item removed

- `EngramExplorer.tsx` deleted after all components are extracted
- "Memory" sidebar item removed
- `/engrams` route removed

## Sidebar Before & After

**Before:**
```
[N] Nova (decorative)
  Overview          /           <- landing page
  Chat              /chat
  Tasks             /tasks
  Friction          /friction   (debug)
  Goals             /goals
  Sources           /sources
  Memory            /engrams
  Brain             /brain

CONFIGURE
  Pods / Models / Keys / Integrations

MONITOR
  Usage

SYSTEM
  Settings
```

**After:**
```
[N] Nova            -> /        <- clickable, goes to Brain
  Brain             /           <- landing page (first item)
  Chat              /chat
  Tasks             /tasks
  Friction          /friction   (debug)
  Goals             /goals
  Sources           /sources

CONFIGURE
  Pods / Models / Keys / Integrations

MONITOR
  Usage

SYSTEM
  Settings                      <- now includes Memory section
```

## Files Affected

### Modified
- `dashboard/src/components/layout/Sidebar.tsx` — nav items, logo click handler
- `dashboard/src/components/layout/MobileNav.tsx` — Brain replaces Memory in primaryTabs bottom bar
- `dashboard/src/components/CommandPalette.tsx` — remove Memory entry, add Brain entry
- `dashboard/src/App.tsx` — route changes (/ renders Brain with fullWidth, /brain redirects to /, remove /engrams and Overview routes)
- `dashboard/src/pages/Brain.tsx` — add enhanced stats, type distribution filter
- `dashboard/src/pages/Settings.tsx` — add Memory section with 5 subsections (add to NAV_GROUPS for scroll tracking)

### Deleted
- `dashboard/src/pages/Overview.tsx`
- `dashboard/src/pages/EngramExplorer.tsx` (after component extraction)

### Created
- Settings Memory subsection components (extracted from EngramExplorer)
