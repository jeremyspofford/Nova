# Dashboard Refactoring: UI Primitives, Mobile-First, Responsive Tables

Date: 2026-03-05

## Problem

The Nova dashboard has ~8,700 lines across 30 files. While well-structured internally
(pages decompose into sub-components), it suffers from:

1. Heavy CSS duplication (input fields 20x, labels 17x, buttons 27x, badges 10x+)
2. No mobile-first experience (Overview is default page; Chat is what you'd use on a phone)
3. Tables on Models and Recovery pages show all columns regardless of screen width
4. NavBar mobile menu is missing 3 routes (Settings, Recovery, Remote Access)
5. `formatBytes()` duplicated identically in 3 files

## Design

### 1. Shared UI Primitives

Create `dashboard/src/components/ui/` with five thin wrapper components:

- **Input.tsx** (~25 lines) -- wraps `<input>` and `<textarea>`, single className source. Props extend native HTML attrs + `multiline?: boolean`.
- **Label.tsx** (~10 lines) -- standard `mb-1 block text-xs text-neutral-500` label. Props: `children`, `htmlFor`.
- **Button.tsx** (~40 lines) -- variants: `primary` (accent bg), `secondary` (bordered), `danger` (red). Props: `variant`, `size?: 'sm' | 'md'`, `loading?: boolean` (shows Loader2 spinner), extends `<button>`.
- **Badge.tsx** (~30 lines) -- colored pill. Props: `color` (preset name) or `className` override, `children`.
- **Select.tsx** (~20 lines) -- styled `<select>` matching Input look.
- **index.ts** -- barrel export.

Then replace inline className strings across all pages with these components.

### 2. Mobile Chat Hero Card

Add a `ChatHeroCard` to Overview that renders only on mobile (`md:hidden`). It's a gradient-accented Card linking to `/chat` with a message icon and "Chat with Nova" CTA. Appears above Pipeline/System cards. Hidden on desktop -- Overview looks identical to current.

### 3. NavBar Mobile Menu

Add Settings, Recovery, and Remote Access to the mobile hamburger menu `links` array. All 13 items show in the 3-column grid. Desktop icon buttons remain for quick access.

### 4. Table Responsiveness

**Models.tsx** -- progressive column hiding: mobile shows name + type only. Provider/status at `sm`, parameters at `lg`.

**Recovery.tsx** -- same pattern for service status and backup tables.

### 5. Shared Utility

Create `lib/format.ts` with `formatBytes()`. Remove duplicates from Settings.tsx, Recovery.tsx, Models.tsx.

## Files

| File | Action | Description |
|------|--------|-------------|
| components/ui/Input.tsx | New | Shared input/textarea |
| components/ui/Label.tsx | New | Shared label |
| components/ui/Button.tsx | New | Primary/secondary/danger + loading |
| components/ui/Badge.tsx | New | Colored pill |
| components/ui/Select.tsx | New | Styled select |
| components/ui/index.ts | New | Barrel export |
| lib/format.ts | New | formatBytes shared utility |
| pages/Overview.tsx | Modify | Add ChatHeroCard (mobile only) |
| components/NavBar.tsx | Modify | Add 3 routes to mobile menu |
| pages/Models.tsx | Modify | Progressive column hiding |
| pages/Recovery.tsx | Modify | Progressive column hiding |
| All pages with raw input/button/label | Modify | Swap to shared components |

## Constraints

- No new npm dependencies
- No routing changes
- No behavior changes -- purely presentation refactoring
- All components use existing Tailwind classes and design tokens (accent/neutral CSS variables)
