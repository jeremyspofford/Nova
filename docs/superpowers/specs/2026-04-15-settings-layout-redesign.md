# Nova Board — Settings Page & Layout Redesign

**Date:** 2026-04-15
**Status:** Approved for implementation

---

## Overview

Nova Board currently treats the Kanban board as the primary UI with chat as a toggled overlay. This redesign inverts that framing: chat and board are equal first-class panels. A new settings page lets users configure how they're arranged. All preferences persist across sessions via localStorage.

---

## Scope

### New files

| File | Purpose |
|---|---|
| `src/router.tsx` | React Router setup — `/` and `/settings` routes |
| `src/stores/settingsStore.ts` | Zustand persist store — theme, layoutMode, chatSide |
| `src/components/Settings/Settings.tsx` | Settings page component |
| `src/AppShell.tsx` | Layout wrapper replacing App.tsx logic |

### Modified files

| File | Change |
|---|---|
| `src/main.tsx` | Wrap app in `<RouterProvider>` |
| `src/App.tsx` | Becomes thin route host; layout logic moves to AppShell |
| `src/stores/uiStore.ts` | Remove `chatOpen` and `toggleChat` |
| `src/stores/chatStore.ts` | Add `persist` middleware to survive page reload |
| `src/styles/tokens.css` | Add `[data-theme="light"]` and `[data-theme="dark"]` selectors |
| `src/styles/global.css` | Update layout classes for split/tabbed shell |
| `src/components/Chat/ChatPanel.tsx` | Remove `if (!chatOpen) return null` — always rendered in layout |

---

## Routing

React Router v6. Two routes:

- `/` — main app (AppShell with board + chat)
- `/settings` — settings page

The gear icon (⚙) in the header is a `<Link to="/settings">`. The settings page has a `<Link to="/">← Back to board</Link>` at the top. No other routes.

---

## Settings Store

```ts
// src/stores/settingsStore.ts
interface SettingsState {
  layoutMode: 'split' | 'tabbed'
  chatSide:   'left'  | 'right'
  theme:      'light' | 'dark' | 'system'
}

// Defaults
layoutMode: 'split'
chatSide:   'left'
theme:      'system'
```

Persisted via `zustand/middleware` `persist` to `localStorage` key `nova-settings`.

On every settings change and on app load, the store writes `document.documentElement.dataset.theme` to match the `theme` value. `'system'` clears the attribute, allowing the existing `@media (prefers-color-scheme: dark)` query to take effect.

---

## Theme Implementation

`tokens.css` currently applies dark tokens via `@media (prefers-color-scheme: dark)`. Add explicit overrides:

```css
[data-theme="light"] {
  /* light token values — same as :root defaults */
}

[data-theme="dark"] {
  /* dark token values — same as current @media block */
}
```

The media query block remains unchanged, handling the `'system'` case. The `data-theme` attribute, when present, takes precedence via specificity.

---

## App Shell

`AppShell.tsx` reads `layoutMode`, `chatSide` from `settingsStore` and renders the appropriate structure.

### Split mode

```
┌─────────────────────────────────────────────┐
│ Header: [Nova Board] [filters] [⚙]          │
├──────────────┬──────────────────────────────┤
│  ChatPanel   │  Board (overflow-x: auto)    │
│  (320px)     │  columns: 200–240px each     │
└──────────────┴──────────────────────────────┘
```

- Chat is on the left or right based on `chatSide`
- Board columns are `min-width: 200px; max-width: 240px; flex-shrink: 0`
- Board container is `overflow-x: auto; display: flex; gap: 10px`
- At viewport width < 900px, split mode auto-falls back to tabbed layout regardless of the setting

### Tabbed mode

```
┌──────────────────────────────────────────────┐
│ Header: [Nova Board] [Chat] [Board] [⚙]      │
├──────────────────────────────────────────────┤
│  Active tab content (full viewport height)   │
└──────────────────────────────────────────────┘
```

- Tab links (`Chat`, `Board`) are inline in the header after the app name
- Filters appear in the header only when the Board tab is active
- Each tab takes full width and height below the header

Tab state is managed via React Router — `/` defaults to whichever tab was last active (stored in `uiStore` as `activeTab: 'chat' | 'board'`), or `'chat'` by default.

---

## Chat Panel

`ChatPanel` becomes a structural layout element, not a conditional overlay. The `if (!chatOpen) return null` guard is removed. In split mode it's always visible. In tabbed mode it's the Chat tab content.

`chatOpen` and `toggleChat` are removed from `uiStore`. The chat toggle button in the header is replaced by the gear icon link and (in tabbed mode) the tab links.

### Chat store persistence

`chatStore` gains `persist` middleware so `conversationId` survives page reload. The user's active conversation is restored on refresh rather than starting fresh.

---

## Settings Page

Route: `/settings`

Two sections, rendered as grouped rows (no save button — changes apply immediately):

### Appearance
- **Theme** — segmented control: `Light | Dark | System`

### Layout
- **Mode** — segmented control: `Split | Tabbed`
- **Chat side** — segmented control: `Left | Right`

The "Chat side" row is visually dimmed (but still functional) when Mode is set to Tabbed, since it only meaningfully affects split mode.

---

## Future Direction — Memory System

Nova's chat is currently limited to per-conversation history. A persistent memory layer is a planned future subsystem. Two paths under consideration:

1. **Near-term:** Integrate with the user's Obsidian vault via the existing MCP server — Nova reads and writes notes as long-term context for conversations.
2. **Long-term:** A purpose-built knowledge store that ships with Nova Suite — an Obsidian-like notes system as a first-party Nova subsystem.

No implementation decisions are made here. This note exists to ensure architectural choices in the chat and agent layers don't inadvertently foreclose the memory integration.

---

## What Is Not Changing

- The board data model, API contracts, and polling behavior are unchanged
- `TaskDetail` slide-in panel remains as-is
- Filter behavior is unchanged
- No new dependencies beyond React Router
