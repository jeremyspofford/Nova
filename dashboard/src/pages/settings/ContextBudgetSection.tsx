import { useState, useEffect } from 'react'
import { Save, RotateCcw, Gauge } from 'lucide-react'
import { Section, Slider, Button } from '../../components/ui'
import type { ConfigSectionProps } from './shared'

const BUDGET_SLICES = [
  { key: 'context.system_pct',  label: 'System',  color: 'bg-info' },
  { key: 'context.tools_pct',   label: 'Tools',   color: 'bg-warning' },
  { key: 'context.memory_pct',  label: 'Memory',  color: 'bg-success' },
  { key: 'context.history_pct', label: 'History', color: 'bg-accent' },
  { key: 'context.working_pct', label: 'Working', color: 'bg-danger' },
] as const

export function ContextBudgetSection({
  entries,
  onSave,
  saving,
}: ConfigSectionProps) {
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
        <div className="flex h-4 w-full overflow-hidden rounded-full border border-border">
          {BUDGET_SLICES.map(s => (
            <div
              key={s.key}
              className={`${s.color} transition-all`}
              style={{ width: `${(drafts[s.key] ?? 0) * 100}%` }}
              title={`${s.label}: ${Math.round((drafts[s.key] ?? 0) * 100)}%`}
            />
          ))}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-micro text-content-tertiary">
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
          <Slider
            key={s.key}
            label={s.label}
            min={0}
            max={100}
            step={5}
            value={Math.round((drafts[s.key] ?? 0) * 100)}
            onChange={val => handleSlider(s.key, val / 100)}
          />
        ))}

        {/* Compaction threshold */}
        <Slider
          label="Compaction Threshold"
          min={50}
          max={100}
          step={5}
          value={Math.round(compaction * 100)}
          onChange={val => { setCompaction(val / 100); setDirty(true) }}
        />
        <p className="text-caption text-content-tertiary">
          Trigger context compaction when total usage exceeds this fraction of the context window.
        </p>
      </div>

      {/* Validation + save */}
      <div className="flex items-center justify-between">
        <span className={`text-caption font-medium ${isValid ? 'text-success' : 'text-danger'}`}>
          Total: {totalPct}% {!isValid && '(must be 100%)'}
        </span>
        {dirty && (
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={handleReset} icon={<RotateCcw size={10} />}>
              Reset
            </Button>
            <Button size="sm" onClick={handleSaveAll} disabled={!isValid} loading={saving} icon={<Save size={10} />}>
              Save
            </Button>
          </div>
        )}
      </div>
    </Section>
  )
}
