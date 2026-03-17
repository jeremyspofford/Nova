# Nova Dashboard Ground-Up Redesign — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete visual redesign of Nova's React dashboard with a new design system, 35-component library, sidebar navigation, 7 new backend aggregation endpoints, and 16 rebuilt pages.

**Architecture:** Design System First (Approach A). Build tokens → components → layout shell → backend endpoints → pages, in that order. Each phase produces working, testable software. The design system uses semantic CSS variable aliases on top of the existing RGB triplet palette system, preserving all current theme-switching capabilities.

**Tech Stack:** React 18, TypeScript, Tailwind CSS 3.4, TanStack Query 5, Lucide React icons, Plus Jakarta Sans + Geist Mono fonts, Recharts, D3 (for graph viz). Backend: FastAPI, asyncpg, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-03-16-dashboard-redesign-design.md`

---

## File Structure

### New Files (Design System + Components)
```
dashboard/
├── src/
│   ├── components/
│   │   ├── ui/                          # Component library (replaces existing ui/)
│   │   │   ├── index.ts                 # Barrel exports (update existing)
│   │   │   ├── Button.tsx               # Rewrite: 5 variants × 3 sizes
│   │   │   ├── Input.tsx                # Rewrite: with label/desc/error/prefix/suffix
│   │   │   ├── Textarea.tsx             # New: auto-resize, char count
│   │   │   ├── Select.tsx               # Rewrite: native + custom searchable
│   │   │   ├── Checkbox.tsx             # New
│   │   │   ├── Toggle.tsx               # New
│   │   │   ├── Radio.tsx                # New
│   │   │   ├── Slider.tsx               # New
│   │   │   ├── Badge.tsx                # Rewrite: 6 semantic variants + sizes
│   │   │   ├── Avatar.tsx               # New
│   │   │   ├── StatusDot.tsx            # New: pulse animation
│   │   │   ├── Code.tsx                 # New: inline + block
│   │   │   ├── CopyableId.tsx           # New: monospace + click-to-copy
│   │   │   ├── Metric.tsx              # New: stat value + label + trend
│   │   │   ├── ProgressBar.tsx          # New: determinate/indeterminate/segmented
│   │   │   ├── PipelineStages.tsx       # New: 5-stage pipeline indicator
│   │   │   ├── Table.tsx                # New: sortable/selectable
│   │   │   ├── DataList.tsx             # New: key-value pairs
│   │   │   ├── Card.tsx                 # Rewrite: variants + header/footer
│   │   │   ├── Section.tsx              # New: settings section wrapper (from shared.tsx)
│   │   │   ├── Modal.tsx                # New: sizes + focus trap
│   │   │   ├── Sheet.tsx                # New: slide-out right panel
│   │   │   ├── Tabs.tsx                 # New
│   │   │   ├── Accordion.tsx            # New
│   │   │   ├── EmptyState.tsx           # New
│   │   │   ├── Skeleton.tsx             # New: shimmer loading
│   │   │   ├── Toast.tsx                # New: variants + auto-dismiss
│   │   │   ├── Tooltip.tsx              # New
│   │   │   ├── Popover.tsx              # New
│   │   │   ├── ConfirmDialog.tsx        # New: destructive confirmation
│   │   │   ├── SearchInput.tsx          # New: debounced
│   │   │   └── ModelPicker.tsx          # Rewrite (from components/)
│   │   ├── layout/                      # New directory
│   │   │   ├── Sidebar.tsx              # New: main sidebar nav
│   │   │   ├── AppShell.tsx             # New: sidebar + content wrapper
│   │   │   ├── PageHeader.tsx           # New: title + description
│   │   │   └── MobileNav.tsx            # New: bottom tab bar + drawer
│   │   ├── CommandPalette.tsx           # New: Cmd+K search
│   │   └── ToastProvider.tsx            # New: toast context + renderer
│   ├── lib/
│   │   └── design-tokens.ts            # New: typed token constants
│   └── pages/
│       └── dev/
│           └── ComponentGallery.tsx     # New: dev-only component showcase
```

### New Files (Backend)
```
orchestrator/app/
├── migrations/
│   └── XXX_dashboard_redesign.sql      # activity_events table + api_keys expires_at
```

### Modified Files
```
dashboard/
├── index.html                          # Google Fonts link + Geist Mono import
├── tailwind.config.js                  # New semantic color tokens, font families
├── package.json                        # New deps: geist, d3-force, d3-selection
├── src/
│   ├── index.css                       # Semantic CSS variables, new global styles
│   ├── App.tsx                         # New AppShell layout, updated routing
│   ├── api.ts                          # 7 new fetch functions + query hooks
│   ├── stores/theme-store.tsx          # Semantic token generation in applyTheme
│   ├── lib/color-palettes.ts           # Add semantic mapping function
│   └── components/ui/index.ts          # Updated barrel exports
orchestrator/app/
├── router.py                           # New stats/health/activity/routing endpoints
├── pipeline_router.py                  # New latency stats endpoint
├── goals_router.py                     # Activity event emission
├── pipeline/executor.py                # Activity events + usage metadata
├── agents/runner.py                    # Usage metadata (category/fallback)
```

### Deleted Files (after page rebuilds complete)
```
dashboard/src/components/NavBar.tsx       # Replaced by layout/Sidebar.tsx
dashboard/src/components/StatusBadge.tsx   # Replaced by ui/Badge.tsx + ui/StatusDot.tsx
dashboard/src/pages/ChatIntegrations.tsx   # Absorbed into Settings
dashboard/src/pages/RemoteAccess.tsx       # Absorbed into Settings
dashboard/src/pages/settings/shared.tsx    # Replaced by ui/Section.tsx + ui/Input.tsx
```

---

## Phase 1: Design System Foundation

### Task 1: Install Dependencies and Configure Fonts

**Files:**
- Modify: `dashboard/package.json`
- Modify: `dashboard/index.html`

- [ ] **Step 1: Install new dependencies**

```bash
cd dashboard && npm install geist d3-force d3-selection @types/d3-force @types/d3-selection
```

- [ ] **Step 2: Add Plus Jakarta Sans to index.html**

In `dashboard/index.html`, add inside `<head>` before the existing `<link>` tags:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
```

- [ ] **Step 3: Import Geist Mono in index.css**

At the top of `dashboard/src/index.css`, add:

```css
@import 'geist/font/mono';
```

- [ ] **Step 4: Verify fonts load**

```bash
cd dashboard && npm run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/package.json dashboard/package-lock.json dashboard/index.html dashboard/src/index.css
git commit -m "chore: install Plus Jakarta Sans + Geist Mono fonts for redesign"
```

---

### Task 2: Update Tailwind Config + CSS Custom Properties (Atomic)

> **IMPORTANT:** This task must be done atomically — the Tailwind config references CSS variables that must exist in index.css at the same time, or the build breaks.

**Files:**
- Modify: `dashboard/tailwind.config.js`
- Modify: `dashboard/src/index.css`

- [ ] **Step 1: First, add the semantic CSS variables to index.css**

After the `@tailwind utilities;` line and before the existing `:root` block, add:

```css
/* Semantic design tokens — mapped from palette scale by theme-store */
:root {
  --surface-root: var(--neutral-50);
  --surface-default: 255 255 255;
  --surface-card: var(--card, 255 255 255);
  --surface-card-hover: var(--neutral-100);
  --surface-elevated: var(--neutral-100);
  --surface-input: 255 255 255;
  --text-primary: var(--neutral-900);
  --text-secondary: var(--neutral-500);
  --text-tertiary: var(--neutral-400);
  --text-disabled: var(--neutral-300);
  --border-default: var(--neutral-200);
  --border-subtle: var(--neutral-100);
  --border-focus: var(--accent-500);
}

html.dark {
  --surface-root: var(--neutral-950);
  --surface-default: var(--neutral-900);
  --surface-card: var(--card, var(--neutral-900));
  --surface-card-hover: var(--neutral-800);
  --surface-elevated: var(--neutral-800);
  --surface-input: var(--neutral-900);
  --text-primary: var(--neutral-50);
  --text-secondary: var(--neutral-400);
  --text-tertiary: var(--neutral-500);
  --text-disabled: var(--neutral-700);
  --border-default: var(--neutral-800);
  --border-subtle: var(--neutral-800);
  --border-focus: var(--accent-400);
}
```

Also add after existing `.card-glow` / `.custom-scrollbar` classes:

```css
.skeleton {
  background: linear-gradient(90deg, rgb(var(--neutral-200)) 25%, rgb(var(--neutral-100)) 50%, rgb(var(--neutral-200)) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}
html.dark .skeleton {
  background: linear-gradient(90deg, rgb(var(--neutral-800)) 25%, rgb(var(--neutral-700)) 50%, rgb(var(--neutral-800)) 75%);
  background-size: 200% 100%;
}
.focus-ring {
  @apply outline-none ring-2 ring-accent-500/40 ring-offset-2 ring-offset-surface-root;
}
```

- [ ] **Step 2: Now replace the Tailwind config**

Replace the entire `dashboard/tailwind.config.js` with:

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"Geist Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        // Semantic surface tokens (reference CSS custom properties)
        surface: {
          root: 'rgb(var(--surface-root) / <alpha-value>)',
          DEFAULT: 'rgb(var(--surface-default) / <alpha-value>)',
          card: 'rgb(var(--surface-card) / <alpha-value>)',
          'card-hover': 'rgb(var(--surface-card-hover) / <alpha-value>)',
          elevated: 'rgb(var(--surface-elevated) / <alpha-value>)',
          input: 'rgb(var(--surface-input) / <alpha-value>)',
        },
        // Semantic border tokens
        border: {
          DEFAULT: 'rgb(var(--border-default) / <alpha-value>)',
          subtle: 'rgb(var(--border-subtle) / <alpha-value>)',
          focus: 'rgb(var(--border-focus) / <alpha-value>)',
        },
        // Semantic text tokens
        content: {
          primary: 'rgb(var(--text-primary) / <alpha-value>)',
          secondary: 'rgb(var(--text-secondary) / <alpha-value>)',
          tertiary: 'rgb(var(--text-tertiary) / <alpha-value>)',
          disabled: 'rgb(var(--text-disabled) / <alpha-value>)',
        },
        // Accent (preserves existing accent-50..950 scale)
        accent: {
          DEFAULT: 'rgb(var(--accent-500) / <alpha-value>)',
          hover: 'rgb(var(--accent-300) / <alpha-value>)',
          muted: 'rgb(var(--accent-600) / <alpha-value>)',
          dim: 'rgb(var(--accent-500) / 0.12)',
          glow: 'rgb(var(--accent-500) / 0.06)',
          50: 'rgb(var(--accent-50) / <alpha-value>)',
          100: 'rgb(var(--accent-100) / <alpha-value>)',
          200: 'rgb(var(--accent-200) / <alpha-value>)',
          300: 'rgb(var(--accent-300) / <alpha-value>)',
          400: 'rgb(var(--accent-400) / <alpha-value>)',
          500: 'rgb(var(--accent-500) / <alpha-value>)',
          600: 'rgb(var(--accent-600) / <alpha-value>)',
          700: 'rgb(var(--accent-700) / <alpha-value>)',
          800: 'rgb(var(--accent-800) / <alpha-value>)',
          900: 'rgb(var(--accent-900) / <alpha-value>)',
          950: 'rgb(var(--accent-950) / <alpha-value>)',
        },
        // Neutral (preserves existing neutral-50..950 scale)
        neutral: {
          50: 'rgb(var(--neutral-50) / <alpha-value>)',
          100: 'rgb(var(--neutral-100) / <alpha-value>)',
          200: 'rgb(var(--neutral-200) / <alpha-value>)',
          300: 'rgb(var(--neutral-300) / <alpha-value>)',
          400: 'rgb(var(--neutral-400) / <alpha-value>)',
          500: 'rgb(var(--neutral-500) / <alpha-value>)',
          600: 'rgb(var(--neutral-600) / <alpha-value>)',
          700: 'rgb(var(--neutral-700) / <alpha-value>)',
          800: 'rgb(var(--neutral-800) / <alpha-value>)',
          900: 'rgb(var(--neutral-900) / <alpha-value>)',
          950: 'rgb(var(--neutral-950) / <alpha-value>)',
        },
        // Status colors
        success: {
          DEFAULT: '#34d399',
          dim: 'rgba(52, 211, 153, 0.12)',
        },
        warning: {
          DEFAULT: '#fbbf24',
          dim: 'rgba(251, 191, 36, 0.12)',
        },
        danger: {
          DEFAULT: '#f87171',
          dim: 'rgba(248, 113, 113, 0.12)',
        },
        info: {
          DEFAULT: '#60a5fa',
          dim: 'rgba(96, 165, 250, 0.12)',
        },
        // Backward compat
        card: 'rgb(var(--surface-card) / <alpha-value>)',
      },
      borderRadius: {
        xs: '4px',
        sm: '6px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
      fontSize: {
        display: ['28px', { lineHeight: '1.2', fontWeight: '700' }],
        h1: ['22px', { lineHeight: '1.3', fontWeight: '700' }],
        h2: ['18px', { lineHeight: '1.3', fontWeight: '600' }],
        h3: ['16px', { lineHeight: '1.4', fontWeight: '600' }],
        h4: ['14px', { lineHeight: '1.4', fontWeight: '600' }],
        body: ['14px', { lineHeight: '1.5' }],
        compact: ['13px', { lineHeight: '1.5' }],
        caption: ['12px', { lineHeight: '1.4' }],
        micro: ['11px', { lineHeight: '1.3' }],
        mono: ['13px', { lineHeight: '1.4', fontFamily: '"Geist Mono", monospace' }],
        'mono-sm': ['11px', { lineHeight: '1.3', fontFamily: '"Geist Mono", monospace' }],
      },
      boxShadow: {
        sm: '0 1px 2px rgba(0,0,0,0.05)',
        md: '0 4px 12px rgba(0,0,0,0.08)',
        lg: '0 8px 24px rgba(0,0,0,0.12)',
        glow: '0 0 20px rgb(var(--accent-500) / 0.06)',
        'dark-sm': '0 1px 2px rgba(0,0,0,0.3)',
        'dark-md': '0 4px 12px rgba(0,0,0,0.4)',
        'dark-lg': '0 8px 24px rgba(0,0,0,0.5)',
      },
      transitionDuration: {
        fast: '150ms',
        normal: '200ms',
        slow: '300ms',
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'shimmer': 'shimmer 1.5s ease-in-out infinite',
        'slide-in-right': 'slideInRight 200ms ease',
        'slide-out-right': 'slideOutRight 200ms ease',
        'fade-in': 'fadeIn 150ms ease',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        slideOutRight: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(100%)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 2: Verify build succeeds**

```bash
cd dashboard && npm run build
```

Expected: Build succeeds. Existing pages may look different (font change) — that's expected.

- [ ] **Step 3: Commit**

```bash
git add dashboard/tailwind.config.js
git commit -m "feat: update Tailwind config with design system tokens"
```

---

### Task 3: Create Design Tokens TypeScript File

**Files:**
- Create: `dashboard/src/lib/design-tokens.ts`

- [ ] **Step 1: Create typed token constants**

```typescript
// Design tokens for programmatic access (charts, dynamic styles, etc.)
// These mirror the CSS custom properties defined in index.css

export const radius = {
  xs: '4px',
  sm: '6px',
  md: '8px',
  lg: '12px',
  xl: '16px',
  full: '9999px',
} as const

export const transition = {
  fast: '150ms ease',
  normal: '200ms ease',
  slow: '300ms ease',
  spring: '300ms cubic-bezier(0.34, 1.56, 0.64, 1)',
} as const

export const statusColors = {
  success: { DEFAULT: '#34d399', dim: 'rgba(52, 211, 153, 0.12)' },
  warning: { DEFAULT: '#fbbf24', dim: 'rgba(251, 191, 36, 0.12)' },
  danger: { DEFAULT: '#f87171', dim: 'rgba(248, 113, 113, 0.12)' },
  info: { DEFAULT: '#60a5fa', dim: 'rgba(96, 165, 250, 0.12)' },
} as const

export const breakpoints = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
} as const

// Pipeline stage names (used by PipelineStages component)
export const PIPELINE_STAGES = ['context', 'task', 'guardrail', 'code_review', 'decision'] as const
export type PipelineStage = typeof PIPELINE_STAGES[number]

// Badge/status semantic color map
export type SemanticColor = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info'
```

- [ ] **Step 2: Verify build**

```bash
cd dashboard && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/lib/design-tokens.ts
git commit -m "feat: add typed design tokens for programmatic access"
```

---

## Phase 2: Component Library

> Each component task follows TDD: create the component, add it to the barrel export, verify it builds, then add it to the component gallery for visual verification. The gallery is built in Task 5 and incrementally populated.

### Task 5: Create Component Gallery (Dev Route)

**Files:**
- Create: `dashboard/src/pages/dev/ComponentGallery.tsx`
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Create a minimal gallery page**

Create `dashboard/src/pages/dev/ComponentGallery.tsx`:

```tsx
export default function ComponentGallery() {
  return (
    <div className="min-h-screen bg-surface-root p-10">
      <h1 className="font-sans text-h1 text-content-primary mb-8">
        Component Gallery
      </h1>
      <p className="text-body text-content-secondary mb-12">
        Visual reference for all design system components. Dev-only route.
      </p>
      {/* Components will be added here as they are built */}
      <section className="space-y-12">
        <div>
          <h2 className="text-h2 text-content-primary mb-4">Fonts Test</h2>
          <p className="font-sans text-body text-content-primary">Plus Jakarta Sans — body text</p>
          <p className="font-mono text-compact text-content-secondary">Geist Mono — technical data</p>
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 2: Add dev route to App.tsx**

In `dashboard/src/App.tsx`, import and add a route (inside the `<Routes>` block, before the catch-all):

```tsx
import ComponentGallery from './pages/dev/ComponentGallery'
// ...
<Route path="/dev/components" element={<ComponentGallery />} />
```

- [ ] **Step 3: Verify the route works**

```bash
cd dashboard && npm run build
```

Expected: Build succeeds. Navigate to `/dev/components` in browser to see fonts rendering.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/dev/ComponentGallery.tsx dashboard/src/App.tsx
git commit -m "feat: add dev-only component gallery route"
```

---

### Task 6: Primitive Components — Button, Input, Textarea

**Files:**
- Rewrite: `dashboard/src/components/ui/Button.tsx`
- Rewrite: `dashboard/src/components/ui/Input.tsx`
- Create: `dashboard/src/components/ui/Textarea.tsx`

- [ ] **Step 1: Rewrite Button with 5 variants × 3 sizes**

Replace `dashboard/src/components/ui/Button.tsx` entirely:

```tsx
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import clsx from 'clsx'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline'
export type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: ReactNode
  children?: ReactNode
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-neutral-950 hover:bg-accent-hover font-semibold',
  secondary: 'bg-surface-elevated text-content-primary hover:bg-surface-card-hover border border-border-subtle',
  ghost: 'text-content-secondary hover:text-content-primary hover:bg-surface-elevated',
  danger: 'bg-danger text-white hover:bg-red-400 font-semibold',
  outline: 'border border-border text-content-primary hover:bg-surface-elevated',
}

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-7 px-2.5 text-caption gap-1.5 rounded-sm',
  md: 'h-9 px-3.5 text-compact gap-2 rounded-md',
  lg: 'h-11 px-5 text-body gap-2 rounded-md',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', loading, icon, children, className, disabled, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center font-medium transition-colors duration-fast',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface-root',
        'disabled:opacity-50 disabled:pointer-events-none',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      {...props}
    >
      {loading ? (
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : icon ? (
        <span className="shrink-0">{icon}</span>
      ) : null}
      {children && <span>{children}</span>}
    </button>
  ),
)
Button.displayName = 'Button'
```

- [ ] **Step 2: Rewrite Input with label/description/error support**

Replace `dashboard/src/components/ui/Input.tsx` entirely:

```tsx
import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import clsx from 'clsx'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  description?: string
  error?: string
  prefix?: ReactNode
  suffix?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, description, error, prefix, suffix, className, id, ...props }, ref) => {
    const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined)
    return (
      <div className="space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="block text-caption font-medium text-content-secondary">
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {prefix && (
            <span className="absolute left-3 text-content-tertiary">{prefix}</span>
          )}
          <input
            ref={ref}
            id={inputId}
            className={clsx(
              'w-full h-9 rounded-sm border bg-surface-input px-3 text-compact text-content-primary',
              'placeholder:text-content-tertiary',
              'transition-colors duration-fast',
              'focus:outline-none focus:ring-2 focus:ring-accent-500/40 focus:border-border-focus',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              error
                ? 'border-danger focus:ring-danger/40'
                : 'border-border',
              prefix && 'pl-9',
              suffix && 'pr-9',
              className,
            )}
            {...props}
          />
          {suffix && (
            <span className="absolute right-3 text-content-tertiary">{suffix}</span>
          )}
        </div>
        {description && !error && (
          <p className="text-micro text-content-tertiary">{description}</p>
        )}
        {error && (
          <p className="text-micro text-danger">{error}</p>
        )}
      </div>
    )
  },
)
Input.displayName = 'Input'
```

- [ ] **Step 3: Create Textarea**

Create `dashboard/src/components/ui/Textarea.tsx`:

```tsx
import { forwardRef, useRef, useEffect, type TextareaHTMLAttributes } from 'react'
import clsx from 'clsx'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  description?: string
  error?: string
  maxHeight?: number
  showCount?: boolean
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, description, error, maxHeight = 200, showCount, maxLength, className, id, value, ...props }, ref) => {
    const innerRef = useRef<HTMLTextAreaElement>(null)
    const textareaRef = (ref as React.RefObject<HTMLTextAreaElement>) || innerRef
    const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

    useEffect(() => {
      const el = textareaRef.current
      if (!el) return
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
    }, [value, maxHeight, textareaRef])

    const charCount = typeof value === 'string' ? value.length : 0

    return (
      <div className="space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="block text-caption font-medium text-content-secondary">
            {label}
          </label>
        )}
        <textarea
          ref={textareaRef}
          id={inputId}
          value={value}
          maxLength={maxLength}
          className={clsx(
            'w-full rounded-sm border bg-surface-input px-3 py-2 text-compact text-content-primary resize-y',
            'placeholder:text-content-tertiary',
            'transition-colors duration-fast',
            'focus:outline-none focus:ring-2 focus:ring-accent-500/40 focus:border-border-focus',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            error ? 'border-danger focus:ring-danger/40' : 'border-border',
            className,
          )}
          {...props}
        />
        <div className="flex justify-between">
          {description && !error && (
            <p className="text-micro text-content-tertiary">{description}</p>
          )}
          {error && <p className="text-micro text-danger">{error}</p>}
          {showCount && maxLength && (
            <p className={clsx('text-micro ml-auto', charCount > maxLength * 0.9 ? 'text-warning' : 'text-content-tertiary')}>
              {charCount}/{maxLength}
            </p>
          )}
        </div>
      </div>
    )
  },
)
Textarea.displayName = 'Textarea'
```

- [ ] **Step 4: Update barrel export**

In `dashboard/src/components/ui/index.ts`, replace contents with:

```typescript
export { Button } from './Button'
export type { ButtonVariant, ButtonSize } from './Button'
export { Input } from './Input'
export { Textarea } from './Textarea'
export { Select } from './Select'
export { Badge } from './Badge'
export { Label } from './Label'
```

- [ ] **Step 5: Migrate existing `<Input multiline>` usages to `<Textarea>`**

Search for all `<Input multiline` or `multiline={true}` usages across the codebase and replace them with `<Textarea>`. The old Input component supported `multiline` — the new one does not. Also update imports.

```bash
grep -r "multiline" dashboard/src/pages/ dashboard/src/components/ --include="*.tsx" -l
```

For each file found: replace `<Input multiline ...>` with `<Textarea ...>`, update imports to include `Textarea` from `../components/ui`.

- [ ] **Step 6: Verify build**

```bash
cd dashboard && npm run build
```

Expected: Build succeeds. Fix any remaining TypeScript errors from changed component APIs.

- [ ] **Step 7: Add to component gallery**

Update `ComponentGallery.tsx` to add Button and Input showcase sections.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/components/ui/Button.tsx dashboard/src/components/ui/Input.tsx dashboard/src/components/ui/Textarea.tsx dashboard/src/components/ui/index.ts dashboard/src/pages/dev/ComponentGallery.tsx
git commit -m "feat: rewrite Button + Input, add Textarea component"
```

---

### Task 7: Primitive Components — Select, Checkbox, Toggle, Radio, Slider

**Files:**
- Rewrite: `dashboard/src/components/ui/Select.tsx`
- Create: `dashboard/src/components/ui/Checkbox.tsx`
- Create: `dashboard/src/components/ui/Toggle.tsx`
- Create: `dashboard/src/components/ui/Radio.tsx`
- Create: `dashboard/src/components/ui/Slider.tsx`

- [ ] **Step 1: Rewrite Select** — Native select with same styling as Input (label, description, error support). Add `items: Array<{value: string, label: string}>` prop. Style: `h-9 rounded-sm border bg-surface-input`.

- [ ] **Step 2: Create Checkbox** — `checked`, `onChange`, `label`, `description` props. Square with checkmark SVG, accent color when checked.

- [ ] **Step 3: Create Toggle** — Switch component. `checked`, `onChange`, `label`, `size: 'sm' | 'md'`. Accent bg when on, neutral when off. Smooth 150ms transition.

- [ ] **Step 4: Create Radio** — `RadioGroup` wrapper with `options: Array<{value: string, label: string, description?: string}>`, `value`, `onChange`. Circle indicators.

- [ ] **Step 5: Create Slider** — Range input with `min`, `max`, `step`, `value`, `onChange`, `label`. Accent track fill, neutral track background. Value display.

- [ ] **Step 6: Update barrel exports** — Add all new components to `index.ts`.

- [ ] **Step 7: Verify build**

```bash
cd dashboard && npm run build
```

- [ ] **Step 8: Add to gallery and commit**

```bash
git add dashboard/src/components/ui/
git commit -m "feat: add Select, Checkbox, Toggle, Radio, Slider components"
```

---

### Task 8: Data Display Components — Badge, Avatar, StatusDot, Code, CopyableId

**Files:**
- Rewrite: `dashboard/src/components/ui/Badge.tsx`
- Create: `dashboard/src/components/ui/Avatar.tsx`
- Create: `dashboard/src/components/ui/StatusDot.tsx`
- Create: `dashboard/src/components/ui/Code.tsx`
- Create: `dashboard/src/components/ui/CopyableId.tsx`

- [ ] **Step 1: Rewrite Badge** — Props: `color: SemanticColor`, `size: 'sm' | 'md'`, `dot?: boolean`, `children`. Use dim/full color pairs from tokens. Each variant has its own bg + text color.

- [ ] **Step 2: Create Avatar** — Props: `src?`, `name`, `size: 'xs' | 'sm' | 'md' | 'lg'`, `status?: 'online' | 'offline' | 'busy'`. Initials fallback from name. Status dot in bottom-right corner.

- [ ] **Step 3: Create StatusDot** — Props: `status: 'success' | 'warning' | 'danger' | 'neutral'`, `pulse?: boolean`, `size: 'sm' | 'md' | 'lg'`. Pulse animation uses `animate-pulse-slow` for running states.

- [ ] **Step 4: Create Code** — Props: `inline?: boolean`, `children`, `copyable?: boolean`. Inline: `font-mono bg-surface-elevated px-1 py-0.5 rounded-xs`. Block: dark bg, copy button in top-right.

- [ ] **Step 5: Create CopyableId** — Props: `id: string`, `truncate?: number`. Monospace, subtle bg pill, click-to-copy with 2s checkmark feedback using local state.

- [ ] **Step 6: Update barrel exports, verify build, add to gallery, commit**

```bash
git add dashboard/src/components/ui/
git commit -m "feat: add Badge, Avatar, StatusDot, Code, CopyableId components"
```

---

### Task 9: Data Display Components — Metric, ProgressBar, PipelineStages, Table, DataList

**Files:**
- Create: `dashboard/src/components/ui/Metric.tsx`
- Create: `dashboard/src/components/ui/ProgressBar.tsx`
- Create: `dashboard/src/components/ui/PipelineStages.tsx`
- Create: `dashboard/src/components/ui/Table.tsx`
- Create: `dashboard/src/components/ui/DataList.tsx`

- [ ] **Step 1: Create Metric** — Props: `label: string`, `value: string | number`, `change?: { value: string, direction: 'up' | 'down' }`, `className?`. Large mono value, uppercase caption label, colored change indicator.

- [ ] **Step 2: Create ProgressBar** — Props: `value?: number` (0-100), `variant: 'determinate' | 'indeterminate'`, `segments?: Array<{value: number, color: string}>`, `size: 'sm' | 'md'`. Rounded bar with accent fill.

- [ ] **Step 3: Create PipelineStages** — Props: `stages: Array<'done' | 'active' | 'pending' | 'failed'>`, `compact?: boolean`. Import `PIPELINE_STAGES` from design-tokens. 5 small rectangles. Active stage uses `animate-pulse-slow`. Labels shown in non-compact mode.

- [ ] **Step 4: Create Table** — Generic table component. Props: `columns: Array<{key: string, header: string, sortable?: boolean, render?: (row) => ReactNode}>`, `data: T[]`, `onSort?: (key, direction) => void`, `selectable?: boolean`, `onSelect?: (selected: T[]) => void`, `emptyMessage?: string`. Sticky header, hover rows.

- [ ] **Step 5: Create DataList** — Props: `items: Array<{label: string, value: ReactNode, copyable?: boolean}>`. Two-column layout with caption labels and body values.

- [ ] **Step 6: Update barrel exports, verify build, add to gallery, commit**

```bash
git add dashboard/src/components/ui/
git commit -m "feat: add Metric, ProgressBar, PipelineStages, Table, DataList components"
```

---

### Task 10: Layout Components — Card, Section, Modal, Sheet

**Files:**
- Rewrite: `dashboard/src/components/ui/Card.tsx`
- Create: `dashboard/src/components/ui/Section.tsx`
- Create: `dashboard/src/components/ui/Modal.tsx`
- Create: `dashboard/src/components/ui/Sheet.tsx`

- [ ] **Step 1: Rewrite Card** — Props: `variant: 'default' | 'hoverable' | 'outlined'`, `header?: { title: string, action?: ReactNode }`, `footer?: ReactNode`, `children`, `className?`, `glow?: boolean`. Base: `bg-surface-card border border-border-subtle rounded-lg`. Hoverable adds `hover:border-border hover:bg-surface-card-hover transition-colors`.

- [ ] **Step 2: Create Section** — Migrate from `settings/shared.tsx` pattern. Props: `icon: React.ElementType`, `title: string`, `description: ReactNode`, `children`, `id?`, `collapsible?: boolean`, `defaultOpen?: boolean`. Card wrapper with header (icon + title + description) separated by border.

- [ ] **Step 3: Create Modal** — Props: `open: boolean`, `onClose: () => void`, `size: 'sm' | 'md' | 'lg'`, `title: string`, `children`, `footer?: ReactNode`. Backdrop (black/60), focus trap (trap focus inside modal), Escape to close, click-outside to close. Entrance animation: `animate-fade-in` + scale.

- [ ] **Step 4: Create Sheet** — Props: `open: boolean`, `onClose: () => void`, `width: 'default' | 'wide' | 'half'`, `title: string`, `children`. Slide-in from right (`animate-slide-in-right`). Overlay on `< xl` screens. Same close behavior as Modal.

- [ ] **Step 5: Update barrel exports, verify build, add to gallery, commit**

```bash
git add dashboard/src/components/ui/
git commit -m "feat: add Card, Section, Modal, Sheet layout components"
```

---

### Task 11: Layout Components — Tabs, Accordion, EmptyState, Skeleton

**Files:**
- Create: `dashboard/src/components/ui/Tabs.tsx`
- Create: `dashboard/src/components/ui/Accordion.tsx`
- Create: `dashboard/src/components/ui/EmptyState.tsx`
- Create: `dashboard/src/components/ui/Skeleton.tsx`

- [ ] **Step 1: Create Tabs** — Props: `tabs: Array<{id: string, label: string}>`, `activeTab: string`, `onChange: (id: string) => void`. Horizontal bar with accent underline on active tab. Scrollable when overflow.

- [ ] **Step 2: Create Accordion** — Props: `items: Array<{id: string, title: string, content: ReactNode}>`, `multiple?: boolean`. Chevron indicator, smooth height transition using grid-template-rows trick.

- [ ] **Step 3: Create EmptyState** — Props: `icon: React.ElementType`, `title: string`, `description: string`, `action?: { label: string, onClick: () => void }`. Centered vertically, muted icon, action renders as Button.

- [ ] **Step 4: Create Skeleton** — Props: `variant: 'text' | 'rect' | 'circle'`, `width?`, `height?`, `lines?: number`. Uses `.skeleton` class from CSS for shimmer animation.

- [ ] **Step 5: Update barrel exports, verify build, add to gallery, commit**

```bash
git add dashboard/src/components/ui/
git commit -m "feat: add Tabs, Accordion, EmptyState, Skeleton components"
```

---

### Task 12: Feedback Components — Toast, Tooltip, Popover, ConfirmDialog

**Files:**
- Create: `dashboard/src/components/ui/Toast.tsx`
- Create: `dashboard/src/components/ToastProvider.tsx`
- Create: `dashboard/src/components/ui/Tooltip.tsx`
- Create: `dashboard/src/components/ui/Popover.tsx`
- Create: `dashboard/src/components/ui/ConfirmDialog.tsx`

- [ ] **Step 1: Create Toast component + ToastProvider** — Toast: `variant: 'success' | 'error' | 'warning' | 'info'`, `message`, `action?`. ToastProvider: React context with `addToast(opts)` function. Renders toast stack in bottom-right. Auto-dismiss: 5s (success/info), 8s (warning), manual (error). Slide-up entrance.

- [ ] **Step 2: Create Tooltip** — Wrap children, show tooltip on hover (300ms delay). Props: `content: string`, `side: 'top' | 'bottom' | 'left' | 'right'`. Dark bg in both modes. Position with `absolute` relative to wrapper.

- [ ] **Step 3: Create Popover** — Click-triggered dropdown. Props: `trigger: ReactNode`, `children` (content), `align: 'start' | 'center' | 'end'`. Click-outside to close. Uses `absolute` positioning.

- [ ] **Step 4: Create ConfirmDialog** — Extends Modal. Props: `title`, `description`, `confirmLabel`, `onConfirm`, `onCancel`, `destructive?: boolean`, `confirmText?: string` (type-to-confirm). Danger button variant when destructive.

- [ ] **Step 5: Update barrel exports, verify build, add to gallery, commit**

```bash
git add dashboard/src/components/ui/ dashboard/src/components/ToastProvider.tsx
git commit -m "feat: add Toast, Tooltip, Popover, ConfirmDialog feedback components"
```

---

### Task 13: Form Components — SearchInput, ModelPicker

**Files:**
- Create: `dashboard/src/components/ui/SearchInput.tsx`
- Create: `dashboard/src/components/ui/ModelPicker.tsx` (new location, rewrite)

- [ ] **Step 1: Create SearchInput** — Props: `value`, `onChange`, `placeholder`, `debounceMs?: number` (default 300), `shortcutHint?: string`. Input with Search icon prefix, X clear button suffix. Debounces onChange.

- [ ] **Step 2: Rewrite ModelPicker** — Move from `components/ModelPicker.tsx` to `components/ui/ModelPicker.tsx`. Props: `value`, `onChange`, `models: Array<{id: string, provider: string, context_window?: number}>`, `showAuto?: boolean`. Custom dropdown showing model name + provider icon + context window. "Auto" option at top with resolved model name.

- [ ] **Step 3: Update barrel exports, verify build, commit**

```bash
git add dashboard/src/components/ui/SearchInput.tsx dashboard/src/components/ui/ModelPicker.tsx dashboard/src/components/ui/index.ts
git commit -m "feat: add SearchInput, rewrite ModelPicker component"
```

---

### Task 14: Breadcrumb Component

**Files:**
- Create: `dashboard/src/components/ui/Breadcrumb.tsx`

- [ ] **Step 1: Create Breadcrumb** — Props: `items: Array<{label: string, to?: string}>`. Last item rendered as current (no link, primary text). Separator: `/` between items. Items with `to` rendered as `<Link>` from react-router-dom. Style: `text-caption text-content-tertiary`, links have `hover:text-content-primary`.

- [ ] **Step 2: Update barrel exports, verify build, commit**

```bash
git add dashboard/src/components/ui/Breadcrumb.tsx dashboard/src/components/ui/index.ts
git commit -m "feat: add Breadcrumb navigation component"
```

---

### Task 15: Fix Existing Consumer Breakage

> **CRITICAL:** This task ensures the build still passes after the component rewrites. The new Button, Input, Badge, Card, and Select APIs differ from the old ones. This task fixes all TypeScript errors before moving to the layout shell.

**Files:** Various existing page/component files

- [ ] **Step 1: Run build and collect all errors**

```bash
cd dashboard && npm run build 2>&1 | head -100
```

- [ ] **Step 2: Fix all TypeScript errors caused by changed component APIs**

Common fixes:
- `<Input multiline ...>` → `<Textarea ...>` (should be done in Task 6, but catch any remaining)
- `import Card from '../components/Card'` (default export) → `import { Card } from '../components/ui'` (named export) — update all ~12 files importing from `components/Card`
- Old Button variant/size props that no longer match → update to new API
- Old Badge `color` prop values → map to new `SemanticColor` values
- `import { Section, ConfigField, useConfigValue } from './shared'` — leave these as-is for now (shared.tsx still exists, will be migrated in Phase 5 Task 30)

- [ ] **Step 3: Verify build passes cleanly**

```bash
cd dashboard && npm run build
```

Expected: Zero TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/
git commit -m "fix: update existing consumers for new component APIs"
```

---

## Phase 3: Layout Shell

### Task 16: Sidebar Navigation Component

**Files:**
- Create: `dashboard/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Build Sidebar component**

Props: `collapsed: boolean`, `onToggle: () => void`. Internal structure:
- Logo section: logo mark (gradient square with "N") + "Nova" text (hidden when collapsed)
- Nav sections: Core (Chat, Tasks, Goals, Memory), Configure (Pods, Models, Keys, Integrations), Monitor (Usage), System (Settings, Recovery, Users)
- Each nav item: icon (Lucide), label, optional badge, active state (accent-dim bg + left bar)
- Role filtering: use `hasMinRole` from existing `lib/roles.ts`
- User card at bottom: avatar + name + role + dropdown trigger
- Collapse toggle button
- Store `collapsed` in localStorage key `'nova-sidebar-collapsed'`

Nav items definition:

```typescript
const navSections = [
  {
    items: [
      { to: '/chat', label: 'Chat', icon: MessageSquare, minRole: 'guest' as const },
      { to: '/tasks', label: 'Tasks', icon: ListTodo, minRole: 'member' as const, badge: 'tasks' },
      { to: '/goals', label: 'Goals', icon: Target, minRole: 'member' as const },
      { to: '/engrams', label: 'Memory', icon: Brain, minRole: 'member' as const },
    ],
  },
  {
    label: 'Configure',
    items: [
      { to: '/pods', label: 'Pods', icon: Boxes, minRole: 'admin' as const },
      { to: '/models', label: 'Models', icon: Monitor, minRole: 'member' as const },
      { to: '/keys', label: 'Keys', icon: Shield, minRole: 'admin' as const },
      { to: '/mcp', label: 'Integrations', icon: Plug, minRole: 'admin' as const },
    ],
  },
  {
    label: 'Monitor',
    items: [
      { to: '/usage', label: 'Usage', icon: BarChart3, minRole: 'member' as const },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/settings', label: 'Settings', icon: Settings, minRole: 'admin' as const },
      { to: '/recovery', label: 'Recovery', icon: HeartPulse, minRole: 'admin' as const },
      { to: '/users', label: 'Users', icon: Users, minRole: 'admin' as const },
    ],
  },
]
```

- [ ] **Step 2: Verify build**

```bash
cd dashboard && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/layout/Sidebar.tsx
git commit -m "feat: build sidebar navigation component"
```

---

### Task 15: AppShell, PageHeader, MobileNav

**Files:**
- Create: `dashboard/src/components/layout/AppShell.tsx`
- Create: `dashboard/src/components/layout/PageHeader.tsx`
- Create: `dashboard/src/components/layout/MobileNav.tsx`

- [ ] **Step 1: Create AppShell** — Layout wrapper: `flex h-screen`. Sidebar on left, main content area on right (`flex-1 overflow-y-auto`). Renders MobileNav on `< md` screens. Manages sidebar collapsed state.

- [ ] **Step 2: Create PageHeader** — Props: `title: string`, `description?: string`, `actions?: ReactNode`. Renders h1 title + description paragraph + right-aligned action buttons.

- [ ] **Step 3: Create MobileNav** — Bottom tab bar showing 5 icons: Chat, Tasks, Goals, Memory, More. "More" button opens a full-screen drawer with all nav items. Uses same nav section data as Sidebar.

- [ ] **Step 4: Verify build and commit**

```bash
git add dashboard/src/components/layout/
git commit -m "feat: add AppShell, PageHeader, MobileNav layout components"
```

---

### Task 16: Integrate AppShell into App.tsx

**Files:**
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Replace NavBar with AppShell**

Update `App.tsx` to:
1. Replace `<NavBar />` + vertical flex layout with `<AppShell>`
2. Wrap route content in AppShell's children
3. Chat route gets `fullWidth` prop on AppShell (no max-w constraint)
4. Other routes wrap in `<div className="mx-auto max-w-[1200px] w-full px-6 py-8">`
5. Keep all existing gates (AuthGate, OnboardingGate)
6. Add ToastProvider to the provider stack
7. Keep the existing NavBar import as unused for now (will remove after all pages are rebuilt)

**Routes EXCLUDED from AppShell** (these render standalone, no sidebar):
- `/login` — Login page (centered card)
- `/onboarding` — Full-screen wizard
- `/invite/:code` — Invite acceptance
- `/expired` — Token expiry notice
- `/recovery` — Recovery page (bypasses auth gate, must work even if orchestrator is down)
- `/dev/components` — Component gallery (dev-only)

- [ ] **Step 2: Verify build and visual check**

```bash
cd dashboard && npm run build
```

Navigate to the app — sidebar should appear, pages should render in the content area.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/App.tsx
git commit -m "feat: integrate AppShell layout with sidebar navigation"
```

---

### Task 17: Command Palette

**Files:**
- Create: `dashboard/src/components/CommandPalette.tsx`

- [ ] **Step 1: Build CommandPalette** — Triggered by Cmd+K / Ctrl+K. Modal overlay with search input. Searches: pages (nav items), recent tasks (from TanStack Query cache if available), settings sections. Keyboard navigation (arrows + enter). Groups results by category. Closes on Escape or selection.

- [ ] **Step 2: Add to AppShell** — Render CommandPalette inside AppShell. Register global keydown listener.

- [ ] **Step 3: Verify build and commit**

```bash
git add dashboard/src/components/CommandPalette.tsx dashboard/src/components/layout/AppShell.tsx
git commit -m "feat: add Cmd+K command palette"
```

---

## Phase 4: Backend Endpoints

### Task 18: Database Migration — Activity Events + API Key Expiry

**Files:**
- Create: `orchestrator/app/migrations/XXX_dashboard_redesign.sql`

- [ ] **Step 1: Determine next migration number**

```bash
ls orchestrator/app/migrations/*.sql | tail -1
```

Use the next sequential number.

- [ ] **Step 2: Write migration**

```sql
-- Dashboard redesign: activity events + API key expiry

-- Activity events table for real-time activity feed
CREATE TABLE IF NOT EXISTS activity_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    service TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    summary TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_activity_events_created ON activity_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_events_type ON activity_events(event_type);

-- API key expiry support
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
```

- [ ] **Step 3: Verify migration applies**

```bash
docker compose exec orchestrator python -c "print('migration file exists')"
```

The migration runs automatically on orchestrator startup.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/migrations/
git commit -m "feat: add activity_events table + api_keys expires_at column"
```

---

### Task 19: Pipeline Stats + Usage Summary Endpoints

**Files:**
- Modify: `orchestrator/app/router.py`

- [ ] **Step 1: Add GET /api/v1/pipeline/stats endpoint**

Add to `router.py`. Queries the `tasks` table:
- `active_count`: COUNT WHERE status IN ('running', 'context_running', 'task_running', 'guardrail_running', 'review_running')
- `queued_count`: COUNT WHERE status = 'queued'
- `completed_today`: COUNT WHERE status = 'complete' AND completed_at >= CURRENT_DATE
- `completed_this_week`: COUNT WHERE status = 'complete' AND completed_at >= NOW() - INTERVAL '7 days'
- `failed_today`: COUNT WHERE status = 'failed' AND completed_at >= CURRENT_DATE
- `success_rate_7d`: complete / (complete + failed) over 7 days
- `avg_duration_ms`: AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000) over 7 days

- [ ] **Step 2: Add GET /api/v1/usage/summary endpoint**

Query param: `period` (day, week, month, year). Aggregates `usage_events`:
- `total_cost_usd`, `total_requests`, `total_input_tokens`, `total_output_tokens`
- `by_model`: GROUP BY model, SUM cost/requests/tokens
- `by_day`: GROUP BY DATE(created_at), SUM cost/requests
- `vs_previous_period_pct`: compare current vs previous period totals

- [ ] **Step 3: Write integration tests**

Add to `tests/test_pipeline_stats.py`:
```python
async def test_pipeline_stats(client):
    resp = await client.get("/api/v1/pipeline/stats", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "active_count" in data
    assert "avg_duration_ms" in data
```

- [ ] **Step 4: Run tests**

```bash
make test
```

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/router.py tests/
git commit -m "feat: add pipeline stats + usage summary endpoints"
```

---

### Task 20: Health Overview + Activity Feed + Latency + Goal Stats + Routing Stats Endpoints

**Files:**
- Modify: `orchestrator/app/router.py`
- Modify: `orchestrator/app/pipeline_router.py`
- Modify: `orchestrator/app/goals_router.py`

- [ ] **Step 1: Add GET /api/v1/health/overview** — Orchestrator pings `/health/ready` on each service with timing. Returns service array + avg latency + overall status.

- [ ] **Step 2: Add GET /api/v1/activity** — Query `activity_events` table, ordered by created_at DESC, with limit/offset pagination.

- [ ] **Step 3: Add GET /api/v1/pipeline/stats/latency** — Aggregate `agent_sessions` table by role. Compute avg/p50/p95 from (completed_at - started_at). Group by stage.

- [ ] **Step 4: Add GET /api/v1/goals/stats** — Aggregate `goals` table: count by status, success rate, avg iterations, avg/total cost.

- [ ] **Step 5: Add GET /api/v1/models/routing-stats** — Aggregate `usage_events` with metadata->>'category' and metadata->>'was_fallback' groupings. Returns by_model, fallback_rate, category_distribution.

- [ ] **Step 6: Write integration tests for each endpoint**

- [ ] **Step 7: Run tests**

```bash
make test
```

- [ ] **Step 8: Commit**

```bash
git add orchestrator/app/router.py orchestrator/app/pipeline_router.py orchestrator/app/goals_router.py tests/
git commit -m "feat: add health overview, activity feed, latency, goal stats, routing stats endpoints"
```

---

### Task 21: Activity Event Emission from Pipeline + Goals

**Files:**
- Modify: `orchestrator/app/pipeline/executor.py`
- Modify: `orchestrator/app/goals_router.py`
- Modify: `orchestrator/app/agents/runner.py`
- Modify: `orchestrator/app/router.py` (config PATCH)

- [ ] **Step 1: Create helper function for emitting activity events**

In `orchestrator/app/router.py` or a shared utility:
```python
async def emit_activity(pool, event_type: str, service: str, summary: str, severity: str = "info", metadata: dict = None):
    await pool.execute(
        "INSERT INTO activity_events (event_type, service, severity, summary, metadata) VALUES ($1, $2, $3, $4, $5)",
        event_type, service, severity, summary, json.dumps(metadata or {}),
    )
```

- [ ] **Step 2: Emit events in pipeline executor** — On task_completed, task_failed, guardrail_finding, review_needed.

- [ ] **Step 3: Emit events in goals router** — On goal status changes (completed, failed, paused).

- [ ] **Step 4: Populate category + was_fallback in usage_events metadata** — In `runner.py` (chat path) and `executor.py` (pipeline path), when writing usage events, include the model classifier's category and whether a fallback model was used.

- [ ] **Step 5: Emit config_change events** — In the config PATCH handler, emit an activity event when a config value is changed.

- [ ] **Step 6: Run tests**

```bash
make test
```

- [ ] **Step 7: Commit**

```bash
git add orchestrator/app/
git commit -m "feat: emit activity events from pipeline, goals, and config changes"
```

---

### Task 22: Dashboard API Layer — New Query Hooks

**Files:**
- Modify: `dashboard/src/api.ts`

- [ ] **Step 1: Add fetch functions for all 7 new endpoints**

```typescript
export function getPipelineStats() { return apiFetch<PipelineStats>('/api/v1/pipeline/stats') }
export function getUsageSummary(period: string) { return apiFetch<UsageSummary>(`/api/v1/usage/summary?period=${period}`) }
export function getHealthOverview() { return apiFetch<HealthOverview>('/api/v1/health/overview') }
export function getActivityFeed(limit = 20) { return apiFetch<ActivityEvent[]>(`/api/v1/activity?limit=${limit}`) }
export function getPipelineLatency() { return apiFetch<PipelineLatency>('/api/v1/pipeline/stats/latency') }
export function getGoalStats() { return apiFetch<GoalStats>('/api/v1/goals/stats') }
export function getRoutingStats(period = '7d') { return apiFetch<RoutingStats>(`/api/v1/models/routing-stats?period=${period}`) }
```

- [ ] **Step 2: Add TypeScript interfaces for each response shape** (matching the backend endpoint spec).

- [ ] **Step 3: Verify build**

```bash
cd dashboard && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/api.ts
git commit -m "feat: add API functions + types for new dashboard endpoints"
```

---

## Phase 5: Page Rebuilds

> Each page rebuild follows the same pattern:
> 1. Create the new page component using the design system components
> 2. Update App.tsx routing if the path changes
> 3. Verify build
> 4. Commit
>
> Pages are rebuilt in priority order. The old page files are replaced in-place.
> During the transition, both old NavBar and new Sidebar will coexist briefly.

### Task 23: Rebuild Login Page

**Files:** Modify `dashboard/src/pages/Login.tsx`

- [ ] **Step 1: Rewrite Login** — Centered card on bg-surface-root (no sidebar for login). Nova logo + name. Input fields (email, password with reveal). Button (primary, full width). Google OAuth button (outline). Invite code accordion. Register link.

- [ ] **Step 2: Verify build + visual check, commit**

```bash
git add dashboard/src/pages/Login.tsx
git commit -m "feat: redesign Login page with new design system"
```

---

### Task 24: Rebuild Chat Page

**Files:** Modify `dashboard/src/pages/chat/ChatPage.tsx` and chat sub-components

- [ ] **Step 1: Redesign ChatPage layout** — Full-width in AppShell. Collapsible conversation sidebar (280px) on left. Message stream center. Updated message bubbles (user: right-aligned accent-dim bg, nova: left-aligned card bg). Message footer: model, tokens, latency in mono. Streaming activity steps.

- [ ] **Step 2: Redesign ChatInput** — Bottom-anchored, auto-resize textarea, attachment + voice buttons (left), send button + model selector (right), option pills above.

- [ ] **Step 3: Redesign ConversationSidebar** — SearchInput at top, "New Chat" button, conversations grouped by date, right-click context menu.

- [ ] **Step 4: Update MessageBubble** — New styling with design system tokens. Code blocks with copy button. Markdown rendering.

- [ ] **Step 5: Verify build + visual check, commit**

```bash
git add dashboard/src/pages/chat/ dashboard/src/components/ConversationSidebar.tsx
git commit -m "feat: redesign Chat page with new design system"
```

---

### Task 25: Rebuild Tasks Page

**Files:** Modify `dashboard/src/pages/Tasks.tsx`

- [ ] **Step 1: Rewrite Tasks page** — Stats row using Metric components (active, completed today, cost today, avg latency — from `usePipelineStats()` + `usePipelineLatency()` hooks). Filter bar with status pills + SearchInput + pod dropdown. Task list using Card + PipelineStages. Sheet for task detail with tabs (Output, Findings, Reviews, Artifacts). Bulk actions.

- [ ] **Step 2: Verify build + visual check, commit**

```bash
git add dashboard/src/pages/Tasks.tsx
git commit -m "feat: redesign Tasks page with stats, pipeline stages, and detail sheet"
```

---

### Task 26: Rebuild Goals Page

**Files:** Modify `dashboard/src/pages/Goals.tsx`

- [ ] **Step 1: Rewrite Goals page** — PageHeader with "New Goal" button. Status filter pills. Goal cards with progress visualization, status badge, iteration count, cost. Create goal modal. Click-to-expand detail with plan viewer, iteration timeline, subtask list.

- [ ] **Step 2: Verify build + visual check, commit**

```bash
git add dashboard/src/pages/Goals.tsx
git commit -m "feat: redesign Goals page with progress tracking and detail view"
```

---

### Task 27: Rebuild Models Page

**Files:** Modify `dashboard/src/pages/Models.tsx`

- [ ] **Step 1: Rewrite Models page** — Provider grid (cards with status dots, model count, test button). Installed models table. Pull model SearchInput. GPU stats card (if available). Routing strategy visualization using routing stats endpoint.

- [ ] **Step 2: Verify build + visual check, commit**

```bash
git add dashboard/src/pages/Models.tsx
git commit -m "feat: redesign Models page with provider grid and routing stats"
```

---

### Task 28: Rebuild Pods Page

**Files:** Modify `dashboard/src/pages/Pods.tsx`

- [ ] **Step 1: Rewrite Pods page** — Pod cards showing agent pipeline as connected stages (PipelineStages-style but with agent names). Enable/disable toggle. Click pod → show agents. Agent config in Sheet (model picker, system prompt textarea, tools multi-select, failure behavior radio). Create/delete pod modals.

- [ ] **Step 2: Verify build + visual check, commit**

```bash
git add dashboard/src/pages/Pods.tsx
git commit -m "feat: redesign Pods page with visual pipeline and agent config sheet"
```

---

### Task 29: Rebuild Memory (Engrams) Page

**Files:** Modify `dashboard/src/pages/EngramExplorer.tsx`

- [ ] **Step 1: Rewrite EngramExplorer** — Stats bar with engram/edge counts and type distribution. Tabs: Explorer (search + type-filtered list + detail sheet), Graph (D3 force-directed visualization), Self-Model (formatted text + bootstrap button), Consolidation Log (table of consolidation runs).

- [ ] **Step 2: Verify build + visual check, commit**

```bash
git add dashboard/src/pages/EngramExplorer.tsx
git commit -m "feat: redesign Memory page with graph visualization and consolidation log"
```

---

### Task 30: Rebuild Settings Page

**Files:** Modify `dashboard/src/pages/Settings.tsx` + all settings section files

- [ ] **Step 1: Restructure Settings layout** — Replace top tabs with sidebar sub-navigation (within the main content area, not the app sidebar). Hash-based routing preserved. Each section uses the new Section component.

- [ ] **Step 2: Restyle all 15 settings sections** — Update each section file to use new Input, Select, Toggle, Button, Badge components. Replace ConfigField usage with new Input + local dirty state pattern. Update AppearanceSection theme editor with color swatches.

- [ ] **Step 3: Verify build + visual check, commit**

```bash
git add dashboard/src/pages/settings/
git commit -m "feat: redesign Settings page with sidebar sub-nav and new components"
```

---

### Task 31: Rebuild Remaining Pages

**Files:** Modify Keys, Usage, Recovery, Users, MCP, AgentEndpoints, About, Onboarding pages

- [ ] **Step 1: Rebuild Keys page** — Table component, create key Modal, CopyableId for prefixes.

- [ ] **Step 2: Rebuild Usage page** — Date range selector (Tabs), Metric summary cards, Recharts bar/line charts with design system colors.

- [ ] **Step 3: Rebuild Recovery page** — Service health grid (Card + StatusDot + latency), backup timeline, restart ConfirmDialog, factory reset danger zone.

- [ ] **Step 4: Rebuild Users page** — Table with Avatar + role Badge, invite Modal, role dropdown.

- [ ] **Step 5: Rebuild MCP/Integrations page** — Marketplace-style card grid, config Sheet per integration, tool browser Accordion.

- [ ] **Step 6: Rebuild AgentEndpoints page** — Table + CRUD modals.

- [ ] **Step 7: Rebuild About page** — Centered Card, system info DataList.

- [ ] **Step 8: Rebuild Onboarding** — Full-screen wizard with step progress bar, new Identity step, merged download progress.

- [ ] **Step 9: Verify build for each, commit after each page**

```bash
git add dashboard/src/pages/Keys.tsx && git commit -m "feat: redesign Keys page"
git add dashboard/src/pages/Usage.tsx && git commit -m "feat: redesign Usage page"
git add dashboard/src/pages/Recovery.tsx && git commit -m "feat: redesign Recovery page"
git add dashboard/src/pages/Users.tsx && git commit -m "feat: redesign Users page"
git add dashboard/src/pages/MCP.tsx && git commit -m "feat: redesign Integrations page"
git add dashboard/src/pages/AgentEndpoints.tsx && git commit -m "feat: redesign Agent Endpoints page"
git add dashboard/src/pages/About.tsx && git commit -m "feat: redesign About page"
git add dashboard/src/pages/onboarding/ && git commit -m "feat: redesign Onboarding wizard"
```

---

## Phase 6: Cleanup & Polish

### Task 32: Remove Old Components and Fix Imports

**Files:**
- Delete: `dashboard/src/components/NavBar.tsx`
- Delete: `dashboard/src/components/StatusBadge.tsx`
- Delete: `dashboard/src/pages/ChatIntegrations.tsx`
- Delete: `dashboard/src/pages/RemoteAccess.tsx`
- Modify: Any files still importing old components

- [ ] **Step 1: Remove deleted files and fix all imports**

```bash
cd dashboard && npm run build
```

Fix any remaining import errors. Remove old NavBar from App.tsx if still referenced.

- [ ] **Step 2: Remove old routes for deleted pages**

- [ ] **Step 3: Verify build and commit**

```bash
git add dashboard/src/components/ dashboard/src/pages/ dashboard/src/App.tsx
git commit -m "chore: remove old NavBar, StatusBadge, and absorbed standalone pages"
```

---

### Task 33: Loading Skeletons for Every Page

**Files:** Modify all page components

- [ ] **Step 1: Add Skeleton loading states** — Each page that fetches data shows Skeleton components matching the content layout while loading. Use TanStack Query's `isLoading` state.

- [ ] **Step 2: Verify and commit**

```bash
git add dashboard/src/pages/
git commit -m "feat: add loading skeletons to all pages"
```

---

### Task 34: Empty States for All Lists

**Files:** Modify all pages with lists/tables

- [ ] **Step 1: Add EmptyState components** — Contextual messaging for each empty list (e.g., Tasks: "No tasks yet — submit your first pipeline task", Goals: "No goals — create one to start autonomous operation").

- [ ] **Step 2: Verify and commit**

```bash
git add dashboard/src/pages/
git commit -m "feat: add contextual empty states to all list pages"
```

---

### Task 35: Mobile Responsive Pass

**Files:** All page and component files

- [ ] **Step 1: Test all pages at 375px width** — Fix any overflow, truncation, or layout issues.

- [ ] **Step 2: Ensure sidebar → bottom tab bar transition works**

- [ ] **Step 3: Verify Sheet components go fullscreen on mobile**

- [ ] **Step 4: Test chat page mobile layout** — Input area, conversation sidebar drawer, message bubbles.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/
git commit -m "fix: mobile responsive pass for all pages and components"
```

---

### Task 36: Final Verification

- [ ] **Step 1: Full build check**

```bash
cd dashboard && npm run build
```

Expected: Zero TypeScript errors, zero warnings.

- [ ] **Step 2: Integration tests**

```bash
make test
```

Expected: All existing tests pass. New backend endpoints return data.

- [ ] **Step 3: Health check**

```bash
make test-quick
```

Expected: All services healthy.

- [ ] **Step 4: Visual walkthrough** — Navigate every page in the dashboard. Verify dark mode, light mode, mobile viewport.

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add dashboard/src/ orchestrator/app/ && git commit -m "fix: final polish from verification walkthrough"
```
