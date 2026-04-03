# Engram Detail Modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a floating modal to the chat ContextPanel that shows full engram details when a memory hit is clicked.

**Architecture:** New `EngramDetailModal` component using the existing `Modal.tsx` pattern. Fetches engram detail from `GET /mem/api/v1/engrams/{id}` via TanStack Query. Layered layout: content + source info always visible, numerical metadata in a collapsible section.

**Note:** The `/mem` prefix is a Vite dev proxy / nginx production proxy that strips to `/api/v1/engrams/...` when reaching memory-service:8002. Only the first 8 memory hits are visible in the ContextPanel (existing cap) — the detail button only appears on visible items.

**Tech Stack:** React, TanStack Query, existing Modal component, Tailwind CSS, Lucide icons

---

### Task 1: Add engram detail type and API fetch function

**Files:**
- Modify: `dashboard/src/types.ts` (add `EngramDetail` interface)
- Modify: `dashboard/src/api.ts` (add `getEngramDetail` function)

- [ ] **Step 1: Add the `EngramDetail` type to `types.ts`**

Add at the end of the file:

```typescript
export interface EngramDetail {
  id: string
  type: string
  content: string
  activation: number
  importance: number
  access_count: number
  confidence: number
  source_type: string
  superseded: boolean
  created_at: string | null
  source_ref_id: string | null
}
```

- [ ] **Step 2: Add the fetch function to `api.ts`**

Add near other fetch functions:

```typescript
import type { EngramDetail } from './types'

export const getEngramDetail = (engramId: string) =>
  apiFetch<EngramDetail>(`/mem/api/v1/engrams/${engramId}`)
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /home/jeremy/workspace/arialabs/nova/dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/types.ts dashboard/src/api.ts
git commit -m "feat(dashboard): add engram detail type and API fetch"
```

---

### Task 2: Create the EngramDetailModal component

**Files:**
- Create: `dashboard/src/components/chat/EngramDetailModal.tsx`

- [ ] **Step 1: Create the modal component**

```tsx
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ChevronDown, ChevronRight, Copy, Check } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { getEngramDetail } from '../../api'
import type { EngramDetail } from '../../types'

const TYPE_COLORS: Record<string, string> = {
  fact: 'bg-blue-500/20 text-blue-400',
  episode: 'bg-purple-500/20 text-purple-400',
  concept: 'bg-teal-500/20 text-teal-400',
  procedure: 'bg-amber-500/20 text-amber-400',
  preference: 'bg-rose-500/20 text-rose-400',
  topic: 'bg-emerald-500/20 text-emerald-400',
}

function TypeBadge({ type }: { type: string }) {
  const colors = TYPE_COLORS[type] ?? 'bg-neutral-500/20 text-neutral-400'
  return (
    <span className={`text-micro font-semibold uppercase px-2 py-0.5 rounded-full ${colors}`}>
      {type}
    </span>
  )
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-compact text-content-tertiary w-24 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-border-subtle rounded-full overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="text-mono-sm font-mono text-content-secondary w-12 text-right">
        {value.toFixed(2)}
      </span>
    </div>
  )
}

function CopyableId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1.5 text-mono-sm font-mono text-content-tertiary
                 hover:text-content-secondary transition-colors"
      title="Copy full ID"
    >
      {id}
      {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
    </button>
  )
}

interface Props {
  engramId: string | null
  onClose: () => void
}

export function EngramDetailModal({ engramId, onClose }: Props) {
  const [metaOpen, setMetaOpen] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['engram-detail', engramId],
    queryFn: () => getEngramDetail(engramId!),
    enabled: !!engramId,
    staleTime: 30_000,
    retry: 1,
  })

  if (!engramId) return null

  const title = data
    ? `${data.type.charAt(0).toUpperCase() + data.type.slice(1)}: ${data.content.slice(0, 50)}${data.content.length > 50 ? '...' : ''}`
    : 'Loading...'

  return (
    <Modal open={!!engramId} onClose={onClose} size="md" title={title}>
      {isLoading && (
        <div className="space-y-3 animate-pulse">
          <div className="h-4 bg-border-subtle rounded w-1/4" />
          <div className="h-20 bg-border-subtle rounded" />
          <div className="h-4 bg-border-subtle rounded w-1/2" />
        </div>
      )}

      {error && (
        <div className="text-danger text-compact">
          Failed to load engram details. It may have been pruned or merged.
        </div>
      )}

      {data && (
        <div className="space-y-4">
          {/* Type badge + source */}
          <div className="flex items-center gap-3 flex-wrap">
            <TypeBadge type={data.type} />
            <span className="text-compact text-content-tertiary">
              via {data.source_type.replace(/_/g, ' ')}
            </span>
            {data.superseded && (
              <span className="text-micro font-semibold uppercase px-2 py-0.5 rounded-full
                             bg-warning/20 text-warning">
                Superseded
              </span>
            )}
          </div>

          {/* Full content */}
          <div className="text-body text-content-primary whitespace-pre-wrap leading-relaxed">
            {data.content}
          </div>

          {/* Timestamp + ID */}
          <div className="flex items-center justify-between text-content-tertiary border-t border-border-subtle pt-3">
            <span className="text-compact">
              {data.created_at
                ? new Date(data.created_at).toLocaleString()
                : 'Unknown date'}
            </span>
            <CopyableId id={data.id} />
          </div>

          {/* Collapsible metadata */}
          <div className="border-t border-border-subtle pt-3">
            <button
              onClick={() => setMetaOpen(m => !m)}
              className="flex items-center gap-1.5 text-compact text-content-tertiary
                         hover:text-content-secondary transition-colors w-full text-left"
            >
              {metaOpen
                ? <ChevronDown size={14} />
                : <ChevronRight size={14} />
              }
              <span className="font-medium">Metadata</span>
            </button>
            {metaOpen && (
              <div className="mt-3 space-y-2.5">
                <ScoreBar label="Activation" value={data.activation} />
                <ScoreBar label="Importance" value={data.importance} />
                <ScoreBar label="Confidence" value={data.confidence} />
                <div className="flex items-center gap-3">
                  <span className="text-compact text-content-tertiary w-24 shrink-0">
                    Access count
                  </span>
                  <span className="text-mono-sm font-mono text-content-secondary">
                    {data.access_count}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/jeremy/workspace/arialabs/nova/dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/chat/EngramDetailModal.tsx
git commit -m "feat(dashboard): add EngramDetailModal component"
```

---

### Task 3: Wire EngramDetailModal into ContextPanel

**Files:**
- Modify: `dashboard/src/components/chat/ContextPanel.tsx`

- [ ] **Step 1: Add state and import**

Add to the imports at the top of `ContextPanel.tsx`:

```typescript
import { Eye } from 'lucide-react'
import { EngramDetailModal } from './EngramDetailModal'
```

Add state inside the `ContextPanel` component (after the `memoryItems` derivation, around line 74):

```typescript
const [selectedEngramId, setSelectedEngramId] = useState<string | null>(null)
```

- [ ] **Step 2: Add a detail button to `EngramRow`**

Update the `EngramRow` component to accept an `onViewDetail` callback and render a clickable icon:

Replace the `EngramRow` function signature (line 22):

```typescript
function EngramRow({ engram, onViewDetail }: { engram: EngramSummary; onViewDetail: (id: string) => void }) {
```

Replace only the `<button>` element (lines 28-40). Keep the `{expanded && ...}` block at lines 41-54 intact:

```tsx
<button
  onClick={() => setExpanded(e => !e)}
  className="flex items-start gap-1.5 py-1.5 w-full text-left hover:bg-surface-card-hover/50
             rounded-xs transition-colors duration-fast group"
>
  {expanded
    ? <ChevronDown size={12} className="text-content-tertiary mt-0.5 shrink-0" />
    : <ChevronRight size={12} className="text-content-tertiary mt-0.5 shrink-0" />
  }
  <span className="text-compact text-content-primary leading-snug flex-1 min-w-0 line-clamp-2">
    {engram.preview || 'Untitled engram'}
  </span>
  <span
    role="button"
    tabIndex={0}
    onClick={(e) => { e.stopPropagation(); onViewDetail(engram.id) }}
    onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onViewDetail(engram.id) } }}
    className="opacity-0 group-hover:opacity-100 shrink-0 p-0.5 rounded-xs
               hover:bg-surface-elevated transition-opacity duration-fast text-content-tertiary hover:text-content-secondary"
    title="View details"
  >
    <Eye size={12} />
  </span>
</button>
```

- [ ] **Step 3: Pass the callback and render the modal**

Update the `EngramRow` usage in the ContextPanel JSX (around line 164-166):

```tsx
<EngramRow key={engram.id} engram={engram} onViewDetail={setSelectedEngramId} />
```

Add the modal render just before the closing `</aside>` tag (before line 205):

```tsx
<EngramDetailModal
  engramId={selectedEngramId}
  onClose={() => setSelectedEngramId(null)}
/>
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd /home/jeremy/workspace/arialabs/nova/dashboard && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Manual QA**

1. Start the dashboard dev server: `cd dashboard && npm run dev`
2. Open chat, send a message that triggers memory retrieval
3. Verify the eye icon appears on hover over each memory hit
4. Click the eye icon — modal should open over the chat area
5. Verify: type badge, full content, source type, timestamp, copyable ID all render
6. Click "Metadata" — scores and access count expand
7. Close via X, Escape, or backdrop click
8. Verify no console errors

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/chat/ContextPanel.tsx
git commit -m "feat(dashboard): wire engram detail modal into context panel"
```
