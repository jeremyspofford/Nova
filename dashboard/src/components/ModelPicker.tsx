/**
 * ModelPicker — shared component for selecting a primary model + ordered fallback list.
 *
 * Stateless: the parent holds the current values and receives changes via onChange.
 * Used in both Pods (pod agent edit) and Overview (primary agent edit).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowUp, ArrowDown, X, Plus } from 'lucide-react'
import { discoverModels } from '../api'

interface ModelPickerProps {
  /** Currently selected primary model. null = inherit from pod/service default. */
  primaryModel: string | null
  /** Ordered fallback model IDs, tried in sequence when the primary fails. */
  fallbackModels: string[]
  /** Called whenever either value changes. Parent should update its own state. */
  onChange: (primary: string | null, fallbacks: string[]) => void
  /** Pod-level default model to display in the "inherit" option label. */
  podDefaultModel?: string | null
}

export function ModelPicker({
  primaryModel,
  fallbackModels,
  onChange,
  podDefaultModel,
}: ModelPickerProps) {
  const [addingFallback, setAddingFallback] = useState(false)

  const { data: providers } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
  })
  const allModelIds = (providers ?? [])
    .filter(p => p.available)
    .flatMap(p => p.models.filter(m => m.registered).map(m => m.id))

  // Models that can still be added as fallbacks
  const available = allModelIds.filter(
    id => id !== primaryModel && !fallbackModels.includes(id),
  )

  const removeFallback = (idx: number) =>
    onChange(primaryModel, fallbackModels.filter((_, i) => i !== idx))

  const moveUp = (idx: number) => {
    if (idx === 0) return
    const next = [...fallbackModels]
    ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
    onChange(primaryModel, next)
  }

  const moveDown = (idx: number) => {
    if (idx === fallbackModels.length - 1) return
    const next = [...fallbackModels]
    ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
    onChange(primaryModel, next)
  }

  const inheritLabel = podDefaultModel
    ? `Inherit from pod (${podDefaultModel.split('/').pop()})`
    : 'Inherit from pod / service default'

  return (
    <div className="space-y-3">
      {/* ── Primary model ──────────────────────────────────────────────── */}
      <div>
        <label className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
          Primary model
        </label>
        <select
          value={primaryModel ?? ''}
          onChange={e => onChange(e.target.value || null, fallbackModels)}
          className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-1.5 text-xs text-neutral-800 dark:text-neutral-200 outline-none focus:border-accent-600 focus:ring-2 focus:ring-accent-100 dark:focus:ring-accent-900"
        >
          <option value="">{inheritLabel}</option>
          {allModelIds.map(id => (
            <option key={id} value={id}>{id}</option>
          ))}
        </select>
      </div>

      {/* ── Fallback list ──────────────────────────────────────────────── */}
      <div>
        <label className="mb-1.5 block text-[10px] font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
          Fallback models{' '}
          <span className="normal-case text-neutral-300 dark:text-neutral-600">(tried in order on failure)</span>
        </label>

        {fallbackModels.length === 0 && !addingFallback && (
          <p className="mb-1.5 text-[11px] italic text-neutral-500 dark:text-neutral-400">
            No fallbacks — task will fail if primary model is unavailable
          </p>
        )}

        <div className="space-y-1">
          {fallbackModels.map((fb, i) => (
            <div
              key={fb}
              className="flex items-center gap-1.5 rounded-md border border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 px-2 py-1"
            >
              <span className="w-4 shrink-0 text-center text-[10px] font-semibold text-neutral-500 dark:text-neutral-400">
                {i + 1}
              </span>
              <span className="flex-1 truncate font-mono text-xs text-neutral-700 dark:text-neutral-300">{fb}</span>
              <button
                onClick={() => moveUp(i)}
                disabled={i === 0}
                title="Move up"
                className="rounded p-0.5 text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300 disabled:opacity-20"
              >
                <ArrowUp size={11} />
              </button>
              <button
                onClick={() => moveDown(i)}
                disabled={i === fallbackModels.length - 1}
                title="Move down"
                className="rounded p-0.5 text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300 disabled:opacity-20"
              >
                <ArrowDown size={11} />
              </button>
              <button
                onClick={() => removeFallback(i)}
                title="Remove"
                className="rounded p-0.5 text-neutral-500 dark:text-neutral-400 hover:text-red-500"
              >
                <X size={11} />
              </button>
            </div>
          ))}
        </div>

        {addingFallback ? (
          <select
            className="mt-1.5 w-full rounded-md border border-accent-400 dark:border-accent-600 bg-card dark:bg-neutral-900 px-3 py-1.5 text-xs text-neutral-800 dark:text-neutral-200 outline-none ring-2 ring-accent-100 dark:ring-accent-900 focus:border-accent-600"
            defaultValue=""
            autoFocus
            onBlur={() => setAddingFallback(false)}
            onChange={e => {
              if (e.target.value) {
                onChange(primaryModel, [...fallbackModels, e.target.value])
              }
              setAddingFallback(false)
            }}
          >
            <option value="">Select a fallback model…</option>
            {available.map(id => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        ) : available.length > 0 ? (
          <button
            onClick={() => setAddingFallback(true)}
            className="mt-1.5 flex items-center gap-1 text-[11px] text-accent-700 dark:text-accent-400 hover:text-accent-600 dark:hover:text-accent-300"
          >
            <Plus size={11} /> Add fallback
          </button>
        ) : null}
      </div>
    </div>
  )
}
