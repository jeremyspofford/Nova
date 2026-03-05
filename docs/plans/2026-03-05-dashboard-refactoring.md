# Dashboard Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract shared UI primitives, add mobile-first Chat hero card, fix NavBar mobile menu, add table responsive column hiding, and deduplicate formatBytes.

**Architecture:** Create thin wrapper components in `dashboard/src/components/ui/` that encapsulate the repeated Tailwind class strings. Then do a pass across all pages to swap inline classes for the new components. Separately, add a mobile-only Chat card to Overview, expand NavBar's mobile menu, and add progressive column hiding to table-based pages.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, clsx, Lucide React icons. No new dependencies.

---

### Task 1: Create shared utility — `formatBytes`

**Files:**
- Create: `dashboard/src/lib/format.ts`
- Modify: `dashboard/src/pages/Models.tsx:21-26` — remove local `formatBytes`, add import
- Modify: `dashboard/src/pages/Recovery.tsx:18-22` — remove local `formatBytes`, add import
- Modify: `dashboard/src/pages/Settings.tsx:1060-1064` — remove local `formatBytes`, add import

**Step 1: Create the shared utility**

```typescript
// dashboard/src/lib/format.ts
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '\u2014'
  const gb = bytes / 1_073_741_824
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}
```

Note: This is a superset of the three existing implementations. Models.tsx handled 0 and GB; Settings/Recovery handled KB. This covers all cases.

**Step 2: Replace in Models.tsx**

Remove lines 21-26 (the local `function formatBytes`). Add at top of file:
```typescript
import { formatBytes } from '../lib/format'
```

**Step 3: Replace in Recovery.tsx**

Remove lines 18-22 (the local `function formatBytes`). Add at top of file:
```typescript
import { formatBytes } from '../lib/format'
```

**Step 4: Replace in Settings.tsx**

Remove lines 1060-1064 (the local `function formatBytes`). Add at top of file:
```typescript
import { formatBytes } from '../lib/format'
```

**Step 5: Verify build**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

**Step 6: Commit**

```bash
git add dashboard/src/lib/format.ts dashboard/src/pages/Models.tsx dashboard/src/pages/Recovery.tsx dashboard/src/pages/Settings.tsx
git commit -m "refactor: extract shared formatBytes utility"
```

---

### Task 2: Create UI primitives — Input, Label, Select

**Files:**
- Create: `dashboard/src/components/ui/Input.tsx`
- Create: `dashboard/src/components/ui/Label.tsx`
- Create: `dashboard/src/components/ui/Select.tsx`

**Step 1: Create the components directory**

```bash
mkdir -p dashboard/src/components/ui
```

**Step 2: Create Input.tsx**

```tsx
// dashboard/src/components/ui/Input.tsx
import { forwardRef } from 'react'
import clsx from 'clsx'

const BASE =
  'w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none placeholder:text-neutral-400 dark:placeholder:text-neutral-500 focus:border-accent-600'

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  multiline?: false
}

type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  multiline: true
}

type Props = InputProps | TextareaProps

export const Input = forwardRef<HTMLInputElement | HTMLTextAreaElement, Props>(
  ({ className, multiline, ...rest }, ref) => {
    const cls = clsx(BASE, multiline && 'resize-y', className)
    if (multiline) {
      return <textarea ref={ref as React.Ref<HTMLTextAreaElement>} className={cls} {...(rest as React.TextareaHTMLAttributes<HTMLTextAreaElement>)} />
    }
    return <input ref={ref as React.Ref<HTMLInputElement>} className={cls} {...(rest as React.InputHTMLAttributes<HTMLInputElement>)} />
  }
)
Input.displayName = 'Input'
```

**Step 3: Create Label.tsx**

```tsx
// dashboard/src/components/ui/Label.tsx
import clsx from 'clsx'

const BASE = 'mb-1 block text-xs text-neutral-500 dark:text-neutral-400'

export function Label({
  className,
  children,
  ...rest
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label className={clsx(BASE, className)} {...rest}>
      {children}
    </label>
  )
}
```

**Step 4: Create Select.tsx**

```tsx
// dashboard/src/components/ui/Select.tsx
import { forwardRef } from 'react'
import clsx from 'clsx'

const BASE =
  'w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600'

export const Select = forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...rest }, ref) => (
  <select ref={ref} className={clsx(BASE, className)} {...rest}>
    {children}
  </select>
))
Select.displayName = 'Select'
```

**Step 5: Verify build**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

---

### Task 3: Create UI primitives — Button, Badge, barrel export

**Files:**
- Create: `dashboard/src/components/ui/Button.tsx`
- Create: `dashboard/src/components/ui/Badge.tsx`
- Create: `dashboard/src/components/ui/index.ts`

**Step 1: Create Button.tsx**

```tsx
// dashboard/src/components/ui/Button.tsx
import { forwardRef } from 'react'
import { Loader2 } from 'lucide-react'
import clsx from 'clsx'

const VARIANTS = {
  primary:
    'bg-accent-700 text-white hover:bg-accent-600 disabled:opacity-40',
  secondary:
    'border border-neutral-300 dark:border-neutral-600 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-100 disabled:opacity-40',
  danger:
    'bg-red-600 text-white hover:bg-red-500 disabled:opacity-40',
} as const

const SIZES = {
  sm: 'rounded-md px-2 py-1 text-xs',
  md: 'rounded-md px-3 py-1.5 text-sm',
} as const

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof VARIANTS
  size?: keyof typeof SIZES
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'sm', loading, className, children, disabled, ...rest }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 font-medium transition-colors',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 size={size === 'sm' ? 12 : 14} className="animate-spin" />}
      {children}
    </button>
  )
)
Button.displayName = 'Button'
```

**Step 2: Create Badge.tsx**

```tsx
// dashboard/src/components/ui/Badge.tsx
import clsx from 'clsx'

const COLORS: Record<string, string> = {
  neutral:  'bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400',
  accent:   'bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-400',
  emerald:  'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  amber:    'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  red:      'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400',
  sky:      'bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400',
  violet:   'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400',
  blue:     'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  purple:   'bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
}

export function Badge({
  color = 'neutral',
  className,
  children,
}: {
  color?: keyof typeof COLORS | (string & {})
  className?: string
  children: React.ReactNode
}) {
  const colorCls = COLORS[color] ?? color
  return (
    <span className={clsx('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', colorCls, className)}>
      {children}
    </span>
  )
}
```

**Step 3: Create barrel export**

```typescript
// dashboard/src/components/ui/index.ts
export { Input } from './Input'
export { Label } from './Label'
export { Select } from './Select'
export { Button } from './Button'
export { Badge } from './Badge'
```

**Step 4: Verify build**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add dashboard/src/components/ui/
git commit -m "feat(dashboard): add shared UI primitives (Input, Label, Button, Badge, Select)"
```

---

### Task 4: Mobile Chat Hero Card on Overview

**Files:**
- Modify: `dashboard/src/pages/Overview.tsx`

**Step 1: Add the ChatHeroCard component and render it**

Add this component inside Overview.tsx (above the `Overview` export), and render it as the first child inside the main `div`, above the summary strips grid:

```tsx
function ChatHeroCard() {
  return (
    <Link to="/chat" className="md:hidden block">
      <Card className="bg-gradient-to-r from-accent-700 to-accent-600 border-accent-600 p-5">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/20">
            <MessageSquare size={20} className="text-white" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white">Chat with Nova</p>
            <p className="text-xs text-white/70">Tap to start a conversation</p>
          </div>
          <ArrowRight size={16} className="ml-auto text-white/60 shrink-0" />
        </div>
      </Card>
    </Link>
  )
}
```

Note: `Link`, `MessageSquare`, and `ArrowRight` are already imported in Overview.tsx. No new imports needed.

In the `Overview` component, insert `<ChatHeroCard />` right after the header `div` (with the title and Refresh button) and before the summary strips grid.

**Step 2: Verify build**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add dashboard/src/pages/Overview.tsx
git commit -m "feat(dashboard): add mobile Chat hero card on Overview"
```

---

### Task 5: NavBar mobile menu — add missing routes

**Files:**
- Modify: `dashboard/src/components/NavBar.tsx`

**Step 1: Add Settings, Recovery, and Remote Access to the links array**

In `NavBar.tsx`, the `links` array (line 6) currently has 10 entries ending with Models. Add three more:

```typescript
const links = [
  { to: '/',         label: 'Overview', icon: Activity         },
  { to: '/chat',     label: 'Chat',     icon: MessageSquare    },
  { to: '/tasks',    label: 'Tasks',    icon: ListTodo         },
  { to: '/pods',     label: 'Pods',     icon: Layers           },
  { to: '/usage',    label: 'Usage',    icon: BarChart2        },
  { to: '/keys',     label: 'Keys',     icon: Key              },
  { to: '/mcp',      label: 'MCP',      icon: Plug             },
  { to: '/agents',   label: 'Agents',   icon: Network          },
  { to: '/memory',   label: 'Memory',   icon: Brain            },
  { to: '/models',   label: 'Models',   icon: Cpu              },
  { to: '/settings', label: 'Settings', icon: Settings         },
  { to: '/recovery', label: 'Recovery', icon: ShieldAlert      },
  { to: '/remote-access', label: 'Remote', icon: Globe         },
]
```

Note: `Settings`, `ShieldAlert`, and `Globe` are already imported in NavBar.tsx. No new imports needed.

**Step 2: Verify build**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add dashboard/src/components/NavBar.tsx
git commit -m "feat(dashboard): add Settings, Recovery, Remote Access to mobile nav menu"
```

---

### Task 6: Table responsiveness — Models.tsx

**Files:**
- Modify: `dashboard/src/pages/Models.tsx:200-207`

**Step 1: Add progressive column hiding to the pulled models table**

Replace the `<thead>` section with responsive classes:

```tsx
<thead>
  <tr className="text-xs text-neutral-500 dark:text-neutral-400 border-b border-neutral-100 dark:border-neutral-800">
    <th className="text-left px-4 py-2 font-medium">Model</th>
    <th className="hidden sm:table-cell text-left px-4 py-2 font-medium">Parameters</th>
    <th className="hidden sm:table-cell text-left px-4 py-2 font-medium">Quant</th>
    <th className="text-right px-4 py-2 font-medium">Size</th>
    <th className="w-10" />
  </tr>
</thead>
```

Then also check the `PulledModelRow` component and add matching `hidden sm:table-cell` to the Parameters and Quant `<td>` cells (they must match the header hiding).

**Step 2: Verify build**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add dashboard/src/pages/Models.tsx
git commit -m "fix(dashboard): hide Models table columns on mobile for responsive layout"
```

---

### Task 7: Table responsiveness — Recovery.tsx

**Files:**
- Modify: `dashboard/src/pages/Recovery.tsx:96-102`

**Step 1: Add progressive column hiding to the service status table**

The service status table has 3 columns: Service, Status, Actions. On mobile, hide Actions (the restart button can still be reached by tapping the row or via "Restart All"):

```tsx
<thead>
  <tr className="bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400 text-xs">
    <th className="px-3 py-2 text-left font-medium">Service</th>
    <th className="px-3 py-2 text-left font-medium">Status</th>
    <th className="hidden sm:table-cell px-3 py-2 text-right font-medium">Actions</th>
  </tr>
</thead>
```

And add `hidden sm:table-cell` to the Actions `<td>` at line 113:

```tsx
<td className="hidden sm:table-cell px-3 py-2 text-right">
```

**Step 2: Verify build**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add dashboard/src/pages/Recovery.tsx
git commit -m "fix(dashboard): hide Recovery table Actions column on mobile"
```

---

### Task 8: Swap inline classes for UI primitives across pages

This is the largest task — replace raw className strings with the new shared components across all pages that use them. Work through pages alphabetically.

**Files to modify** (replace raw input/label classNames with `<Input>`, `<Label>`, `<Select>` imports from `../components/ui`):
- `dashboard/src/pages/AgentEndpoints.tsx` — ~7 labels, ~7 inputs
- `dashboard/src/pages/Keys.tsx` — ~2 inputs
- `dashboard/src/pages/MCP.tsx` — ~6 labels, ~6 inputs
- `dashboard/src/pages/MemoryInspector.tsx` — ~2 labels, ~2 inputs
- `dashboard/src/pages/Tasks.tsx` — ~1 input

**For each file, the pattern is:**

1. Add import: `import { Input, Label } from '../components/ui'`
2. Replace `<label className="mb-1 block text-xs text-neutral-500 dark:text-neutral-400">Foo</label>` with `<Label>Foo</Label>`
3. Replace `<input className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none ... focus:border-accent-600" ... />` with `<Input ... />`
4. For textareas with the same pattern, use `<Input multiline ... />`
5. For selects with the same pattern, use `<Select ... />`

**Important:** Some inputs have additional classes beyond the base (e.g., `font-mono`, `flex-1` instead of `w-full`). Pass these as `className` prop:
```tsx
<Input className="font-mono" value={...} />
```

**Step 1: Replace in AgentEndpoints.tsx**

This page has the most replacements (~7 labels, ~7 inputs). Add `import { Input, Label } from '../components/ui'` and replace each matching pattern.

**Step 2: Replace in Keys.tsx**

Add import, replace ~2 inputs.

**Step 3: Replace in MCP.tsx**

Add import, replace ~6 labels, ~6 inputs.

**Step 4: Replace in MemoryInspector.tsx**

Add import, replace ~2 labels, ~2 inputs.

**Step 5: Replace in Tasks.tsx**

Add import, replace ~1 textarea input.

**Step 6: Verify build**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

**Step 7: Commit**

```bash
git add dashboard/src/pages/AgentEndpoints.tsx dashboard/src/pages/Keys.tsx dashboard/src/pages/MCP.tsx dashboard/src/pages/MemoryInspector.tsx dashboard/src/pages/Tasks.tsx
git commit -m "refactor(dashboard): replace inline input/label classes with shared UI components"
```

---

### Task 9: Final build verification

**Step 1: Full TypeScript check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: No errors

**Step 2: Production build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds with no errors

**Step 3: Commit any remaining fixes if needed**
