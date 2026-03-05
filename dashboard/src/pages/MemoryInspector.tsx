import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, Trash2, ChevronDown, ChevronRight, Plus, X } from 'lucide-react'
import {
  browseMemoriesV2,
  searchMemories,
  deleteMemory,
  saveFact,
  type BrowseMemoryItem,
  type MemoryTier,
} from '../api'
import Card from '../components/Card'
import { Input, Label } from '../components/ui'

// ── Tier badge ────────────────────────────────────────────────────────────────

const TIER_COLORS: Record<MemoryTier, string> = {
  semantic:   'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  procedural: 'bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
  episodic:   'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  working:    'bg-neutral-100 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400',
}

function TierBadge({ tier }: { tier: MemoryTier }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TIER_COLORS[tier] ?? TIER_COLORS.working}`}>
      {tier}
    </span>
  )
}

// ── Confidence bar ────────────────────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.min(Math.max(value, 0), 1) * 100)
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-400' : 'bg-red-400'
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 rounded-full bg-neutral-200 dark:bg-neutral-700">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-neutral-500 dark:text-neutral-400">{pct}%</span>
    </div>
  )
}

// ── Memory card ───────────────────────────────────────────────────────────────

function MemoryCard({
  item,
  onDelete,
}: {
  item: BrowseMemoryItem
  onDelete: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const isFact = item.tier === 'semantic' && item.project_id != null

  return (
    <Card className="overflow-hidden">
      <div
        className="flex items-start gap-3 px-4 py-3 cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
        onClick={() => setExpanded(v => !v)}
      >
        <div className="shrink-0 mt-0.5">
          {expanded ? <ChevronDown size={13} className="text-neutral-400" /> : <ChevronRight size={13} className="text-neutral-400" />}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <TierBadge tier={item.tier} />
            {isFact && (
              <span className="text-xs text-neutral-500 dark:text-neutral-400 font-mono">
                {item.project_id}/{item.category}/{item.key}
              </span>
            )}
          </div>
          <p className="text-sm text-neutral-800 dark:text-neutral-200 line-clamp-2 leading-snug">
            {item.content}
          </p>
          <div className="mt-1.5 flex items-center gap-3 flex-wrap">
            <span className="text-xs text-neutral-400 dark:text-neutral-500">
              {new Date(item.created_at).toLocaleString()}
            </span>
            {item.effective_confidence != null && (
              <ConfidenceBar value={item.effective_confidence} />
            )}
          </div>
        </div>

        <button
          onClick={e => { e.stopPropagation(); onDelete() }}
          title="Delete memory"
          className="shrink-0 text-neutral-400 hover:text-red-600 dark:hover:text-red-400 transition-colors"
        >
          <Trash2 size={13} />
        </button>
      </div>

      {expanded && (
        <div className="border-t border-neutral-100 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-800 px-4 py-3 space-y-2 text-xs">
          <div className="text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap break-words leading-relaxed">
            {item.content}
          </div>
          {isFact && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-neutral-500 dark:text-neutral-400 border-t border-neutral-200 dark:border-neutral-700 pt-2 mt-2">
              <span>Project: <span className="text-neutral-700 dark:text-neutral-300">{item.project_id}</span></span>
              <span>Category: <span className="text-neutral-700 dark:text-neutral-300">{item.category}</span></span>
              <span>Key: <span className="text-neutral-700 dark:text-neutral-300">{item.key}</span></span>
              <span>Base confidence: <span className="text-neutral-700 dark:text-neutral-300">{item.base_confidence?.toFixed(2)}</span></span>
              {item.last_accessed_at && (
                <span className="col-span-2">
                  Last accessed: <span className="text-neutral-700 dark:text-neutral-300">{new Date(item.last_accessed_at).toLocaleString()}</span>
                </span>
              )}
            </div>
          )}
          {Object.keys(item.metadata ?? {}).length > 0 && (
            <div className="border-t border-neutral-200 dark:border-neutral-700 pt-2 mt-2">
              <p className="text-neutral-400 dark:text-neutral-500 mb-1">Metadata:</p>
              <pre className="text-neutral-600 dark:text-neutral-400 text-xs overflow-auto max-h-24">
                {JSON.stringify(item.metadata, null, 2)}
              </pre>
            </div>
          )}
          <div className="text-neutral-400 dark:text-neutral-500 border-t border-neutral-200 dark:border-neutral-700 pt-2 mt-2">
            ID: <span className="font-mono">{item.id}</span>
          </div>
        </div>
      )}
    </Card>
  )
}

// ── Add Fact form ─────────────────────────────────────────────────────────────

function AddFactForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({
    project_id: '',
    category: '',
    key: '',
    content: '',
    base_confidence: '1.0',
  })

  const mutation = useMutation({
    mutationFn: () => saveFact({
      agent_id: 'nova',
      project_id: form.project_id.trim(),
      category: form.category.trim(),
      key: form.key.trim(),
      content: form.content.trim(),
      base_confidence: parseFloat(form.base_confidence) || 1.0,
    }),
    onSuccess: onDone,
  })

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))
  const isValid = form.project_id.trim() && form.category.trim() && form.key.trim() && form.content.trim()

  return (
    <Card className="p-5 space-y-4">
      <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
        Add / Update Fact
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {(['project_id', 'category', 'key'] as const).map(field => (
          <div key={field}>
            <Label className="capitalize">
              {field.replace('_', ' ')} *
            </Label>
            <Input
              value={form[field]}
              onChange={e => set(field, e.target.value)}
              placeholder={field === 'project_id' ? 'e.g. nova' : field === 'category' ? 'e.g. codebase' : 'e.g. auth_pattern'}
            />
          </div>
        ))}
      </div>

      <div>
        <Label>Content *</Label>
        <Input
          multiline
          value={form.content}
          onChange={e => set('content', e.target.value)}
          rows={3}
          placeholder="The fact to store — updated in-place if (project_id, category, key) already exists."
        />
      </div>

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-t border-neutral-100 dark:border-neutral-800 pt-3">
        <div className="flex items-center gap-2">
          <label className="text-xs text-neutral-500 dark:text-neutral-400">Confidence</label>
          <input
            type="number"
            min="0"
            max="1"
            step="0.1"
            value={form.base_confidence}
            onChange={e => set('base_confidence', e.target.value)}
            className="w-20 rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-2 py-1.5 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
          />
        </div>
        <div className="flex gap-2">
          <button onClick={onDone} className="rounded-md px-3 py-1.5 text-sm text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100">
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!isValid || mutation.isPending}
            className="flex items-center gap-1.5 rounded-md bg-accent-700 px-4 py-1.5 text-sm text-white hover:bg-accent-500 disabled:opacity-40"
          >
            <Plus size={13} />
            {mutation.isPending ? 'Saving…' : 'Save Fact'}
          </button>
        </div>
      </div>

      {mutation.isError && (
        <p className="text-xs text-red-600 dark:text-red-400">{String(mutation.error)}</p>
      )}
      {mutation.isSuccess && (
        <p className="text-xs text-emerald-600 dark:text-emerald-400">
          Fact {mutation.data?.is_new ? 'created' : 'updated'} (v{mutation.data?.version})
        </p>
      )}
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TIERS: { value: MemoryTier | 'all'; label: string }[] = [
  { value: 'all',       label: 'All' },
  { value: 'semantic',  label: 'Semantic' },
  { value: 'procedural',label: 'Procedural' },
  { value: 'episodic',  label: 'Episodic' },
  { value: 'working',   label: 'Working' },
]

export function MemoryInspector() {
  const qc = useQueryClient()
  const [tierFilter, setTierFilter] = useState<MemoryTier | 'all'>('all')
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [showAddFact, setShowAddFact] = useState(false)

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  // Debounce the search query
  const handleQueryChange = (val: string) => {
    setQuery(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setDebouncedQuery(val), 400)
  }

  const isSearching = debouncedQuery.trim().length > 0

  // Browse (no query)
  const browseQuery = useQuery({
    queryKey: ['memories-browse', tierFilter],
    queryFn: () => browseMemoriesV2(
      tierFilter === 'all' ? undefined : tierFilter,
      undefined,
      100,
    ),
    enabled: !isSearching,
    staleTime: 10_000,
  })

  // Search (with query)
  const searchQuery = useQuery({
    queryKey: ['memories-search', debouncedQuery, tierFilter],
    queryFn: () => searchMemories(
      debouncedQuery,
      'nova',
      tierFilter === 'all' ? ['semantic', 'procedural', 'episodic'] : [tierFilter as MemoryTier],
      50,
    ),
    enabled: isSearching,
    staleTime: 10_000,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteMemory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memories-browse'] })
      qc.invalidateQueries({ queryKey: ['memories-search'] })
    },
  })

  const handleAddFactDone = () => {
    setShowAddFact(false)
    qc.invalidateQueries({ queryKey: ['memories-browse'] })
  }

  // Normalise results from both endpoints into BrowseMemoryItem shape
  const items: BrowseMemoryItem[] = isSearching
    ? (searchQuery.data?.results ?? []).map(r => ({
        id: String(r.id),
        content: r.content,
        tier: r.tier,
        agent_id: 'nova',
        metadata: r.metadata,
        created_at: String(r.created_at),
        updated_at: null,
        project_id: null,
        category: null,
        key: null,
        base_confidence: null,
        effective_confidence: null,
        last_accessed_at: null,
      }))
    : (browseQuery.data?.items ?? [])

  const isLoading = isSearching ? searchQuery.isLoading : browseQuery.isLoading
  const error = isSearching ? searchQuery.error : browseQuery.error
  const total = isSearching ? searchQuery.data?.total_found : browseQuery.data?.total

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Memory Inspector</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400 max-w-2xl">
          Browse and search Nova's long-term memory. Semantic and procedural memories are written
          after each pipeline run and read by the Planning Agent in Phase 7.
          Facts support structured upsert — the same key always overwrites the previous value.
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
          <input
            value={query}
            onChange={e => handleQueryChange(e.target.value)}
            placeholder="Hybrid search (vector + keyword)…"
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 pl-8 pr-8 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
          />
          {query && (
            <button
              onClick={() => { setQuery(''); setDebouncedQuery('') }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
            >
              <X size={13} />
            </button>
          )}
        </div>

        {/* Tier filter */}
        <div className="flex gap-1.5 flex-wrap">
          {TIERS.map(t => (
            <button
              key={t.value}
              onClick={() => setTierFilter(t.value)}
              className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
                tierFilter === t.value
                  ? 'bg-accent-700 text-white'
                  : 'bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Add fact */}
        <button
          onClick={() => setShowAddFact(v => !v)}
          className="flex items-center gap-1.5 rounded-md bg-accent-700 px-4 py-2 text-sm text-white hover:bg-accent-500 transition-colors shrink-0"
        >
          <Plus size={14} />
          {showAddFact ? 'Cancel' : 'Add Fact'}
        </button>
      </div>

      {showAddFact && <AddFactForm onDone={handleAddFactDone} />}

      {/* Stats */}
      {total != null && !isLoading && (
        <p className="text-xs text-neutral-400 dark:text-neutral-500">
          {isSearching ? `${total} result${total !== 1 ? 's' : ''} for "${debouncedQuery}"` : `${total} total memories`}
        </p>
      )}

      {/* List */}
      {isLoading && <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading…</p>}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{String(error)}</p>}

      <div className="space-y-2">
        {items.map(item => (
          <MemoryCard
            key={item.id}
            item={item}
            onDelete={() => {
              if (confirm('Delete this memory? This cannot be undone.')) {
                deleteMutation.mutate(item.id)
              }
            }}
          />
        ))}

        {!isLoading && items.length === 0 && (
          <Card className="p-10 text-center">
            <p className="text-sm font-medium text-neutral-500 dark:text-neutral-400">
              {isSearching ? 'No memories matched your query.' : 'No memories stored yet.'}
            </p>
            <p className="mt-1 text-xs text-neutral-300 dark:text-neutral-600">
              {isSearching
                ? 'Try different keywords or clear the search to browse all.'
                : 'Memories are written automatically after each pipeline run completes.'}
            </p>
          </Card>
        )}
      </div>
    </div>
  )
}
