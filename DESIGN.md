# Design System — Nova

## Product Context
- **What this is:** Self-directed autonomous AI platform. Users define a goal; Nova decomposes, executes, evaluates, and re-plans autonomously.
- **Who it's for:** Technical users (developers, engineers) running AI agents on their own hardware.
- **Space/industry:** AI infrastructure / developer tools. Peers: Vercel, Linear, LangSmith, Weights & Biases, Open WebUI.
- **Project type:** Dashboard-heavy admin UI (React/Tailwind) + Astro marketing site (arialabs.ai).

## Aesthetic Direction
- **Direction:** Industrial/Utilitarian — function-first, data-dense, monospace accents for system data.
- **Decoration level:** Intentional — glass morphism on overlays, accent glows on interactive elements. No decoration for decoration's sake.
- **Mood:** Calm control room. The UI should feel like a well-engineered instrument panel — precise, readable, and warm enough to spend hours with. Not cold and clinical, not playful.
- **Reference sites:** Vercel (restraint, layout discipline), Linear (dark-first premium feel), W&B (amber warmth on dark surfaces).

## Typography
- **Display/Hero:** Plus Jakarta Sans (800 weight) — humanist shapes give warmth that geometric fonts (Inter, Geist) can't. Differentiates from the cold sans-serif monoculture in dev tools.
- **Body:** Plus Jakarta Sans (400/500/600) — readable at 13-14px, pairs naturally with display weight.
- **UI/Labels:** Plus Jakarta Sans (600 weight, 11-12px uppercase with letter-spacing for section headers).
- **Data/Tables:** Geist Mono (tabular-nums) — clean monospace with excellent number alignment. Use for durations, counts, token budgets, queue depths.
- **Code:** Geist Mono — ligature-free, clear 0/O and 1/l/I distinction.
- **Loading:** `@fontsource-variable/geist-mono` (npm), Plus Jakarta Sans via Google Fonts CDN.
- **Scale:**

| Token | Size | Weight | Tracking | Use |
|-------|------|--------|----------|-----|
| display | 32px | 800 | -0.02em | Page heroes, landing page |
| h1 | 24px | 700 | -0.02em | Page titles |
| h2 | 18px | 600 | — | Section headers |
| h3 | 16px | 600 | — | Card titles |
| h4 | 14px | 600 | — | Sub-section headers |
| body | 14px | 400 | — | Primary body text |
| compact | 13px | 400 | — | Secondary text, descriptions |
| caption | 12px | 400 | — | Timestamps, metadata |
| micro | 11px | 400 | — | Badges, fine print |
| mono | 13px | 400 | — | API paths, data values |
| mono-sm | 11px | 400 | — | Queue stats, heartbeats |

All sizes scale via `--font-scale` CSS variable for accessibility.

## Color

### Approach
Restrained — one primary accent (teal) + one secondary accent (amber for cognitive states) + neutrals + semantics.

### Nova Teal (Primary Accent)
Custom palette — NOT stock Tailwind teal. Slightly cooler and more saturated to own the color space.

| Token | Hex | RGB | Use |
|-------|-----|-----|-----|
| teal-50 | #ECFDF9 | 236 253 249 | Tinted backgrounds (light mode) |
| teal-100 | #CCFBF0 | 204 251 240 | Hover states (light mode) |
| teal-200 | #96F3E3 | 150 243 227 | Light borders, decorative |
| teal-300 | #5CE8D0 | 92 232 208 | Hover states (dark mode) |
| teal-400 | #24C9B8 | 36 201 184 | Active text, links (dark mode) |
| teal-500 | #19A89E | 25 168 158 | Primary accent, buttons, focus rings |
| teal-600 | #168E85 | 22 142 133 | Hover on primary buttons |
| teal-700 | #14746C | 20 116 108 | Active links (light mode) |
| teal-800 | #115D57 | 17 93 87 | Dark accent backgrounds |
| teal-900 | #104D48 | 16 77 72 | Very dark accent |
| teal-950 | #082D2A | 8 45 42 | Accent on darkest backgrounds |

### Amber (Secondary — Cognitive States)
Signals "the AI is thinking." Creates visual warmth to communicate active cognition, distinct from the cool teal of steady-state operation. Used for: Cortex thinking, agent planning, processing indicators.

| Token | Hex | Use |
|-------|-----|-----|
| amber-400 | #FBBF24 | Thinking badges, active glow |
| amber-500 | #F59E0B | Thinking buttons, amber CTA |
| amber-600 | #D97706 | Hover on amber elements |

Full amber scale (50-900) available for edge cases. See `index.css` for complete values.

### Stone Neutrals
Warm gray family. The warmth prevents the UI from feeling sterile on long sessions.

| Token | Hex | Use |
|-------|-----|-----|
| stone-50 | #FAFAF9 | Light mode root background |
| stone-100 | #F5F5F4 | Light mode elevated surfaces |
| stone-200 | #E7E5E4 | Light mode borders |
| stone-300 | #D6D3D1 | Light mode disabled text |
| stone-400 | #A8A29E | Secondary text (dark mode) |
| stone-500 | #78716C | Secondary text (light mode) |
| stone-600 | #57534E | Tertiary (dark mode) |
| stone-700 | #44403C | Dark mode borders |
| stone-800 | #292524 | Dark mode card surfaces |
| stone-900 | #1C1917 | Dark mode default surface |
| stone-950 | #0C0A09 | Dark mode root background |

### Semantic Status
Status colors are fixed across themes — only opacity/dim variants change.

| Token | Hex | Use |
|-------|-----|-----|
| success | #34D399 | Completed, healthy, connected |
| warning | #FBBF24 | Budget warnings, approaching limits |
| error | #F87171 | Failed, disconnected, rejected |
| info | #60A5FA | Informational, consolidation cycles |

Each has a `dim` variant at 12% opacity for background tints: `rgba(hex, 0.12)`.

### Dark Mode Strategy
Dark-first design. CSS class-based (`html.dark`). Semantic surface tokens (`--surface-root`, `--surface-card`, etc.) resolve to the appropriate neutral via CSS custom properties. Color inversion rules:
- Reduce accent saturation by ~10% in dark mode (use 400 instead of 500 for text)
- Borders use stone-800 in dark, stone-200 in light
- Focus rings use accent-400 in dark, accent-500 in light
- Status colors stay the same; only dim backgrounds adjust

## Spacing
- **Base unit:** 4px
- **Density:** Comfortable — enough breathing room for long sessions, tight enough for data density.
- **Scale:** 2xs(2px) xs(4px) sm(8px) md(16px) lg(24px) xl(32px) 2xl(48px) 3xl(64px)

## Layout
- **Approach:** Grid-disciplined — sidebar nav, card-based content areas. Data tables get full width.
- **Grid:** Sidebar (220px fixed) + fluid main. Content areas use CSS Grid with `auto-fit, minmax(280px, 1fr)`.
- **Max content width:** 1200px for settings/config pages. Full-width for dashboards and tables.
- **Border radius:** Hierarchical — smaller elements get tighter radii.

| Token | Value | Use |
|-------|-------|-----|
| xs | 4px | Inline code, small badges |
| sm | 6px | Buttons, inputs, small cards |
| md | 8px | Standard cards, alerts, dropdowns |
| lg | 12px | Large cards, modals, panels |
| xl | 16px | Hero sections, page-level containers |
| full | 9999px | Pills, badges, avatar circles |

## Motion
- **Approach:** Intentional — animations aid comprehension and signal state changes. No decorative motion.
- **Easing:** enter(ease-out), exit(ease-in), move(ease-in-out)
- **Duration:**

| Token | Value | Use |
|-------|-------|-----|
| micro | 50-100ms | Hover color changes, focus rings |
| short | 150ms | Button state transitions, toggles |
| normal | 200ms | Slide-in panels, dropdown open |
| medium | 300ms | Page transitions, card entrance |
| long | 400ms | Fade-in-up sequences (stagger 50ms) |

- **Signature animations:**
  - `fade-in-up` — 400ms ease-out, staggered at 50ms intervals for lists
  - `glow-pulse` — 3s ease-in-out infinite teal glow for active elements
  - `amber-pulse` — 2s ease-in-out infinite amber glow for thinking states
  - `shimmer` — 1.5s skeleton loading sweep

## Decoration
- **Glass morphism:** `blur(16px) saturate(1.2)` + subtle white border. For modals, command palette, floating overlays.
- **Accent glow:** Teal glow on hover for cards (gradient border mask + translateY(-1px)). Amber glow for cognitive states.
- **Scrollbars:** Thin (6px), auto-hiding, stone-colored. Appear on hover.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-30 | Initial design system formalized | Documented existing system, identified and proposed refinements via /design-consultation |
| 2026-03-30 | Custom Nova teal (#19A89E) over stock Tailwind teal | Stock Tailwind teal is indistinguishable from every other Tailwind project. Custom hue gives Nova its own color identity. |
| 2026-03-30 | Amber secondary for cognitive states | Teal = operational state, amber = active reasoning. Maps directly to Cortex thinking loop. W&B validated amber-on-dark in this space. |
| 2026-03-30 | Keep Plus Jakarta Sans + Geist Mono | Already better than 90% of the space. Humanist warmth differentiates from Inter/Geist monoculture. |
| 2026-03-30 | Keep stone neutrals | Warm enough for long sessions, neutral enough for data density. No change needed. |
