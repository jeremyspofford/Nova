# Design: Hardening Sprint + In-App Friction Log

**Date:** 2026-03-19
**Status:** APPROVED (CEO + Eng + Design review complete)
**Branch:** main
**Mode:** SELECTIVE EXPANSION
**Source:** `/office-hours` design doc + `/plan-ceo-review`

## Problem Statement

Nova is a 9-service autonomous AI platform with a 7-stage pipeline, 11 agent types, subscription routing, SSE notifications, and a React dashboard. It's technically ambitious but has never been used for real work. Known errors exist throughout. Features have been built on untested features.

**The pivot:** Stop building features. Start using Nova daily. Fix everything that breaks. Build confidence that the core works reliably.

## Approach

**Approach B (selected): Friction Log Feature + Dogfood Sprint (2-3 weeks)**

Build a lightweight friction log (CRUD API, dashboard widget, friction log page, "Fix This" action), then dogfood for 2 weeks. The friction log enables structured capture, demonstrates Nova's value loop (meta-dogfooding), and becomes a real feature for future users.

## Scope (after cherry-pick ceremony)

### Core Feature: Friction Log
1. **DB table** — `friction_log` with id, description, severity, status, task_id, screenshot, screenshot_thumb, user_id (nullable FK), metadata (JSONB), created_at, updated_at
2. **CRUD API** — Dedicated `friction_router.py` with endpoints:
   - `POST /api/v1/friction` — create entry
   - `GET /api/v1/friction` — list (with severity/status filters, thumbnails, pagination)
   - `GET /api/v1/friction/:id` — detail (full screenshot)
   - `PATCH /api/v1/friction/:id` — update status
   - `POST /api/v1/friction/:id/fix` — create pipeline task from friction entry
   - `GET /api/v1/friction/stats` — aggregate for Sprint Health card
3. **Dashboard widget** — Floating "Log Friction" button on all pages, opens modal with description, severity picker, screenshot paste/drop zone
4. **Friction log page** — List view with filters, thumbnails, "Fix This" / "Mark Fixed" actions, empty state
5. **Nav bar** — Add "Friction" link

### Accepted Cherry-Picks
1. **Sprint Health card** — Overview page metric card: success rate (X/Y sparkline), today's stats (submitted/succeeded/failed), open friction count, top error
2. **Auto-friction from pipeline failures** — When a task fails, auto-create a friction_log entry with severity=blocker, pre-populated error details. Loop guard: skip tasks tagged `source: friction_log`
3. **Screenshot support** — Clipboard paste + drag-drop. Client-side resize to ~50KB thumbnail. Store both full + thumb in DB
4. **user_id column** — Nullable `user_id UUID REFERENCES users(id)` for multi-tenant future
5. **Daily summary** — Combined with Sprint Health card (cherry-pick 1)

### Sprint Structure
- **Week 1:** Build friction log (Day 1-2), start dogfooding (Day 3-7)
- **Week 2-3:** Triage friction log, fix blockers, every fix gets a test

### Success Criteria
- [ ] Nova used for at least 10 real coding tasks
- [ ] Friction log has 20+ entries
- [ ] Top 10 friction points fixed with tests
- [ ] Pipeline task completion rate > 90% for simple tasks
- [ ] Founder can demonstrate "I built X with Nova" for at least 3 real outputs

## Architecture

```
                         +---------------------+
                         |   Dashboard (3000)   |
                         |  +-----------------+ |
                         |  | FrictionLog page| | <-- NEW
                         |  | LogFriction btn | | <-- NEW
                         |  | Sprint Health   | | <-- NEW
                         |  +--------+--------+ |
                         +-----------+-----------+
                                     | /api/v1/friction/*
                                     v
                         +---------------------+
                         | Orchestrator (8000)  |
                         |  +-----------------+ |
                         |  | friction_router  | | <-- NEW (dedicated file)
                         |  | friction_log tbl | | <-- NEW (migration 030)
                         |  | executor.py      | | <-- MODIFIED (auto-friction on fail)
                         |  +--------+--------+ |
                         +-----------+-----------+
                                     |
                    +----------------+----------------+
                    v                v                 v
              +----------+   +----------+      +----------+
              | Postgres  |   |  Redis   |      | LLM GW   |
              | (5432)    |   | (6379)   |      | (8001)   |
              +----------+   +----------+      +----------+
```

## Key Design Decisions (from CEO + Eng + Design reviews)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Router placement | Dedicated `friction_router.py` | router.py is 600+ lines, #3 most-touched file |
| Auto-friction loop guard | Tag Fix-This tasks with `source: friction_log`, skip | Simpler than parent_id chains, prevents noise |
| Screenshot in list API | Thumbnail in list, full on detail | Better UX, client-side resize avoids backend Pillow dep |
| Screenshot storage | Files on disk, path in DB | Keeps DB lean, file serve endpoint |
| Sprint Health placement | Header on Friction Log page | Minimal diff, sprint-focused context |
| Nav placement | Core section, after Tasks | Primary workflow during sprint |
| Floating button | Fixed bottom-right, all pages | Frictionless capture from any context |
| Implementation approach | Approach B (friction log + dogfood) | Balances "start fixing" with structured capture |

## Edge Cases

- **Auto-friction loop:** Fix-This tasks tagged `source: friction_log` → auto-friction skips them
- **Double-click submit:** Disable button on submit
- **Already-fixed entry:** Disable "Fix This" if status=fixed or task_id is set
- **Large screenshots:** Client-side 5MB limit + server content-length check
- **Zero tasks:** Sprint Health shows "No tasks yet" empty state
- **500+ friction entries:** Pagination on list endpoint

## Error Handling

- Auto-friction hook MUST be wrapped in try/except — never crash the pipeline because friction logging failed
- "Fix This" failure keeps friction entry open (doesn't lose the report)
- All CRUD follows existing error patterns (422 validation, 404 not found, 500 server error)

## UI Design (from design review)

### Page Layout — Friction Log

```
+----------------------------------------------------------------+
|  PageHeader: "Friction Log"                    [Log Friction]   |
+----------------------------------------------------------------+
|                                                                 |
|  +--- Sprint Health (4x Metric grid) ---------------------+    |
|  | Success Rate | Submitted Today | Failed Today | Open   |    |
|  |    73%       |       11        |      3       |   7    |    |
|  +--------------------------------------------------------+    |
|                                                                 |
|  [All Severity v]  [All Status v]                  [Search]     |
|                                                                 |
|  +--- Entry Card -----------------------------------------+    |
|  | * open   Chat input loses text...            [blocker]  |    |
|  |          2 hours ago                              (img) |    |
|  |          Description text...                            |    |
|  |          [Fix This]  [Mark Fixed]  [Delete]             |    |
|  +---------------------------------------------------------+    |
|                                                                 |
|  +--- Entry Card (auto) ----------------------------------+    |
|  | * open   Pipeline task failed: "Write tests..." [auto]  |    |
|  |          [blocker]  35 minutes ago                       |    |
|  |          Task c8a2... failed: timeout...                 |    |
|  |          [Fix This]  [Dismiss]                           |    |
|  +---------------------------------------------------------+    |
+----------------------------------------------------------------+
```

### Log Friction Sheet (right drawer)

```
+------------------------------+
|  Log Friction            x   |
|                              |
|  What went wrong?            |
|  +==========================+|
|  |  [textarea, 4 rows]      ||
|  +==========================+|
|                              |
|  Severity                    |
|  (*) Blocker                 |
|  ( ) Annoyance               |
|  ( ) Idea                    |
|                              |
|  Screenshot (optional)       |
|  +- - - - - - - - - - - - -+|
|  |  Paste (Ctrl+V) or drop  ||
|  +- - - - - - - - - - - - -+|
|                              |
|  [Submit]            [Cancel]|
+------------------------------+
```

### Component Mapping

| UI element | Component | Notes |
|-----------|-----------|-------|
| Sprint Health metrics | `Metric` x4 in `grid-cols-2 md:grid-cols-4` | Recharts sparkline for success rate |
| Severity/status filters | `Select` x2 + `SearchInput` | Inline row |
| Entry cards | `Card` + `StatusDot` + `Badge` | Action buttons inside card footer |
| Form drawer | `Sheet` (right) | Auto-focus textarea on open |
| Severity picker | `RadioGroup` | Default: blocker |
| Screenshot zone | Custom drop zone | `border-dashed`, accent on hover/drag |
| Floating button | `Button` (accent) | `fixed bottom-6 right-6 z-40` |
| Loading states | `Skeleton` | Card-sized for list, Metric-sized for stats |
| Empty states | `EmptyState` | ClipboardX icon + primary action |
| Toasts | `Toast` | Success/error on submit, fix, delete |
| Delete confirm | `ConfirmDialog` | "Delete this entry?" |

### Severity → Color

| Severity | SemanticColor | Visual |
|----------|--------------|--------|
| blocker | `danger` | Red badge |
| annoyance | `warning` | Amber badge |
| idea | `info` | Blue badge |

### Status → Color

| Status | SemanticColor | Visual |
|--------|--------------|--------|
| open | `neutral` | Gray dot + badge |
| in-progress | `warning` | Amber dot + badge |
| fixed | `success` | Green dot + badge |

### Auto-Generated Entries

Auto-created friction entries (from pipeline failures) display a small `[auto]` badge in `info` color after the severity badge. Manual entries do not have this badge.

### Interaction States

| Feature | Loading | Empty | Error | Success |
|---------|---------|-------|-------|---------|
| Sprint Health | 4x Skeleton | "No tasks yet" | "—" fallback | Metric cards |
| Friction list | 3x Skeleton | EmptyState: ClipboardX + "Log Friction" btn | Error card + Retry | Sorted entry cards |
| Log Friction form | — | Empty textarea + radio default | Toast error | Toast + close + refetch |
| "Fix This" | Loader2 spinner in button | — | Toast error | Toast + badge update |
| Screenshot paste | — | Dashed border + hint text | Toast "too large" | Image preview + remove btn |

### Responsive

- Metrics grid: `grid-cols-2 md:grid-cols-4`
- Sheet: full-width on `<md`, 400px right-drawer on `>=md`
- Floating button: icon-only on `<md`, icon + text on `>=md`
- Filters: stacked on `<sm`, inline on `>=sm`

### Accessibility

- Floating button: `aria-label="Log friction"`
- Sheet: focus trap, Escape to close, auto-focus textarea
- RadioGroup: arrow key nav (built-in)
- Drop zone: `aria-label="Drop screenshot here or paste with Ctrl+V"`
- Action buttons: descriptive `aria-label` per entry
- All Badge colors meet WCAG AA contrast

## Deferred

- GitHub Issue export from friction entries (P3, post-sprint)
- Screenshot file cleanup tooling (orphan detection, disk usage) (P3)

## NOT in Scope

- Full observability dashboard (Sprint Health card covers core metric)
- Nova self-healing / anomaly detection
- Multi-tenant friction scoping (beyond user_id column)
- Mobile-first optimization (responsive basics specified, not mobile-first)
- Notification on auto-friction creation
- DESIGN.md creation (design system established through code)
