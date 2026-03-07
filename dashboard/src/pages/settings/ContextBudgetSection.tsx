import { useState, useEffect } from 'react'
import { Save, RotateCcw, Gauge } from 'lucide-react'
import { Section } from './shared'
import type { ConfigSectionProps } from './shared'
import type { PlatformConfigEntry } from '../../api'

const BUDGET_SLICES = [
  { key: 'context.system_pct',  label: 'System',  color: 'bg-sky-500' },
  { key: 'context.tools_pct',   label: 'Tools',   color: 'bg-amber-500' },
  { key: 'context.memory_pct',  label: 'Memory',  color: 'bg-emerald-500' },
  { key: 'context.history_pct', label: 'History', color: 'bg-purple-500' },
  { key: 'context.working_pct', label: 'Working', color: 'bg-rose-500' },
] as const

export function ContextBudgetSection({
  entries,
  onSave,
  saving,
}: ConfigSectionProps) {
  // Read current values from config entries
  const getVal = (key: string, fallback: number) => {
    const e = entries.find(en => en.key === key)
    if (e && e.value !== null && e.value !== '') return Number(e.value)
    return fallback
  }

  const defaults = { 'context.system_pct': 0.10, 'context.tools_pct': 0.15, 'context.memory_pct': 0.40, 'context.history_pct': 0.20, 'context.working_pct': 0.15 }
  const [drafts, setDrafts] = useState<Record<string, number>>(() =>
    Object.fromEntries(BUDGET_SLICES.map(s => [s.key, getVal(s.key, defaults[s.key as keyof typeof defaults])]))
  )
  const [compaction, setCompaction] = useState(() => getVal('context.compaction_threshold', 0.80))
  const [dirty, setDirty] = useState(false)

  // Sync on entries change
  useEffect(() => {
    setDrafts(Object.fromEntries(BUDGET_SLICES.map(s => [s.key, getVal(s.key, defaults[s.key as keyof typeof defaults])])))
    setCompaction(getVal('context.compaction_threshold', 0.80))
    setDirty(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries])

  const total = Object.values(drafts).reduce((a, b) => a + b, 0)
  const totalPct = Math.round(total * 100)
  const isValid = totalPct === 100

  const handleSlider = (key: string, val: number) => {
    setDrafts(prev => ({ ...prev, [key]: val }))
    setDirty(true)
  }

  const handleSaveAll = () => {
    for (const s of BUDGET_SLICES) {
      onSave(s.key, JSON.stringify(drafts[s.key]))
    }
    onSave('context.compaction_threshold', JSON.stringify(compaction))
    setDirty(false)
  }

  const handleReset = () => {
    setDrafts(Object.fromEntries(BUDGET_SLICES.map(s => [s.key, getVal(s.key, defaults[s.key as keyof typeof defaults])])))
    setCompaction(getVal('context.compaction_threshold', 0.80))
    setDirty(false)
  }

  return (
    <Section
      icon={Gauge}
      title="Context Budgets"
      description="How the context window is allocated across content categories. Must sum to 100%."
    >
      {/* Stacked color bar */}
      <div>
        <div className="flex h-4 w-full overflow-hidden rounded-full border border-neutral-200 dark:border-neutral-700">
          {BUDGET_SLICES.map(s => (
            <div
              key={s.key}
              className={`${s.color} transition-all`}
              style={{ width: `${(drafts[s.key] ?? 0) * 100}%` }}
              title={`${s.label}: ${Math.round((drafts[s.key] ?? 0) * 100)}%`}
            />
          ))}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-neutral-500 dark:text-neutral-400">
          {BUDGET_SLICES.map(s => (
            <span key={s.key} className="flex items-center gap-1">
              <span className={`inline-block size-2 rounded-full ${s.color}`} />
              {s.label} {Math.round((drafts[s.key] ?? 0) * 100)}%
            </span>
          ))}
        </div>
      </div>

      {/* Sliders */}
      <div className="space-y-3">
        {BUDGET_SLICES.map(s => (
          <div key={s.key}>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">{s.label}</label>
              <span className="text-xs font-mono text-neutral-500 dark:text-neutral-400">{Math.round((drafts[s.key] ?? 0) * 100)}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={Math.round((drafts[s.key] ?? 0) * 100)}
              onChange={e => handleSlider(s.key, Number(e.target.value) / 100)}
              className="w-full accent-accent-700 dark:accent-accent-400"
            />
          </div>
        ))}

        {/* Compaction threshold */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Compaction Threshold</label>
            <span className="text-xs font-mono text-neutral-500 dark:text-neutral-400">{Math.round(compaction * 100)}%</span>
          </div>
          <input
            type="range"
            min={50}
            max={100}
            step={5}
            value={Math.round(compaction * 100)}
            onChange={e => { setCompaction(Number(e.target.value) / 100); setDirty(true) }}
            className="w-full accent-accent-700 dark:accent-accent-400"
          />
          <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            Trigger context compaction when total usage exceeds this fraction of the context window.
          </p>
        </div>
      </div>

      {/* Validation + save */}
      <div className="flex items-center justify-between">
        <span className={`text-xs font-medium ${isValid ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
          Total: {totalPct}% {!isValid && '(must be 100%)'}
        </span>
        {dirty && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleReset}
              className="flex items-center gap-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300"
            >
              <RotateCcw size={10} /> Reset
            </button>
            <button
              onClick={handleSaveAll}
              disabled={!isValid || saving}
              className="flex items-center gap-1 rounded-md bg-accent-700 px-2.5 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40"
            >
              <Save size={10} /> {saving ? 'Saving\u2026' : 'Save'}
            </button>
          </div>
        )}
      </div>
    </Section>
  )
}
