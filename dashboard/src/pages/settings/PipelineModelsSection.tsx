import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Layers, Save, RotateCcw, Download, ChevronDown, ChevronRight } from 'lucide-react'
import { discoverModels, type PlatformConfigEntry } from '../../api'
import { Section, useConfigValue } from './shared'
import { apiFetch } from '../../api'

// ── Constants ────────────────────────────────────────────────────────────────

const STAGES = [
  { role: 'context',     label: 'Context Agent',     hint: 'Curates relevant code context. Mid-tier model recommended.' },
  { role: 'task',        label: 'Task Agent',         hint: 'Core reasoning and code generation. Frontier model recommended.' },
  { role: 'guardrail',   label: 'Guardrail Agent',    hint: 'Security scanning and classification. Fast/cheap model sufficient.' },
  { role: 'code_review', label: 'Code Review Agent',  hint: 'Quality assessment. Mid-tier model recommended.' },
  { role: 'decision',    label: 'Decision Agent',     hint: 'Escalation decisions. Cheap model sufficient.' },
] as const

const COMPLEXITY_LEVELS = ['simple', 'moderate', 'complex'] as const

const DEFAULT_COMPLEXITY_MAP: Record<string, Record<string, string>> = {
  simple: {
    context: 'groq/llama-3.1-8b-instant',
    task: 'groq/llama-3.3-70b-versatile',
    guardrail: 'groq/llama-3.1-8b-instant',
    code_review: 'groq/llama-3.1-8b-instant',
    decision: 'groq/llama-3.1-8b-instant',
  },
  moderate: {
    context: '',
    task: '',
    guardrail: 'groq/llama-3.1-8b-instant',
    code_review: '',
    decision: 'groq/llama-3.1-8b-instant',
  },
  complex: {
    context: '',
    task: '',
    guardrail: 'groq/llama-3.1-8b-instant',
    code_review: '',
    decision: '',
  },
}

// ── Toggle component ─────────────────────────────────────────────────────────

function Toggle({
  enabled,
  onToggle,
  disabled,
}: {
  enabled: boolean
  onToggle: () => void
  disabled?: boolean
}) {
  return (
    <button
      onClick={onToggle}
      disabled={disabled}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        enabled ? 'bg-accent-700' : 'bg-neutral-300 dark:bg-neutral-600'
      } disabled:opacity-40`}
    >
      <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
        enabled ? 'translate-x-[18px]' : 'translate-x-[2px]'
      }`} />
    </button>
  )
}

// ── Model picker (reusable) ──────────────────────────────────────────────────

function ModelPicker({
  value,
  onChange,
  models,
  placeholder = '(use default)',
}: {
  value: string
  onChange: (v: string) => void
  models: string[]
  placeholder?: string
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-1.5 text-xs text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600 transition-colors"
    >
      <option value="">{placeholder}</option>
      {models.map(id => (
        <option key={id} value={id}>{id}</option>
      ))}
      {value && !models.includes(value) && value !== '' && (
        <option value={value}>{value}</option>
      )}
    </select>
  )
}

// ── Per-Stage Model Defaults ─────────────────────────────────────────────────

function StageDefaultsSubsection({
  entries,
  onSave,
  saving,
  models,
}: {
  entries: PlatformConfigEntry[]
  onSave: (key: string, value: string) => void
  saving: boolean
  models: string[]
}) {
  const enabled = useConfigValue(entries, 'pipeline.stage_defaults_enabled', 'false') === 'true'

  // Stage model drafts
  const stageValues: Record<string, string> = {}
  for (const { role } of STAGES) {
    stageValues[role] = useConfigValue(entries, `pipeline.stage_model.${role}`, '')
  }

  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setDrafts({ ...stageValues })
    setDirty(false)
  }, [entries])

  const handleToggle = () => {
    onSave('pipeline.stage_defaults_enabled', JSON.stringify(!enabled))
  }

  const handleDraftChange = (role: string, value: string) => {
    setDrafts(prev => ({ ...prev, [role]: value }))
    setDirty(true)
  }

  const handleSaveAll = () => {
    for (const { role } of STAGES) {
      const val = drafts[role] ?? ''
      onSave(`pipeline.stage_model.${role}`, val ? JSON.stringify(val) : JSON.stringify(null))
    }
    setDirty(false)
  }

  const handleReset = () => {
    setDrafts({ ...stageValues })
    setDirty(false)
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Per-Stage Model Defaults</label>
          <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
            Assign different models to each pipeline stage. Only Task Agent needs a frontier model.
          </p>
        </div>
        <Toggle enabled={enabled} onToggle={handleToggle} disabled={saving} />
      </div>

      {enabled && (
        <div className="mt-3 space-y-3">
          {dirty && (
            <div className="flex items-center justify-end gap-2">
              <button onClick={handleReset}
                className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-300">
                <RotateCcw size={10} /> Reset
              </button>
              <button onClick={handleSaveAll} disabled={saving}
                className="flex items-center gap-1 rounded-md bg-accent-700 px-2.5 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40">
                <Save size={10} /> Save All
              </button>
            </div>
          )}

          {STAGES.map(({ role, label, hint }) => (
            <div key={role}>
              <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">{label}</label>
              <ModelPicker
                value={drafts[role] ?? ''}
                onChange={v => handleDraftChange(role, v)}
                models={models}
              />
              <p className="mt-0.5 text-[11px] text-neutral-400 dark:text-neutral-500">{hint}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Complexity Routing ───────────────────────────────────────────────────────

function ComplexityRoutingSubsection({
  entries,
  onSave,
  saving,
  models,
}: {
  entries: PlatformConfigEntry[]
  onSave: (key: string, value: string) => void
  saving: boolean
  models: string[]
}) {
  const enabled = useConfigValue(entries, 'pipeline.complexity_routing_enabled', 'false') === 'true'
  const mapRaw = useConfigValue(entries, 'pipeline.complexity_model_map', '{}')
  const [expanded, setExpanded] = useState(false)

  // Parse user map
  let userMap: Record<string, Record<string, string>> = {}
  try {
    const parsed = typeof mapRaw === 'string' ? JSON.parse(mapRaw) : mapRaw
    if (typeof parsed === 'object' && parsed !== null) userMap = parsed
  } catch { /* use empty */ }

  // Merge defaults with user overrides for display
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({})
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    const merged: Record<string, Record<string, string>> = {}
    for (const level of COMPLEXITY_LEVELS) {
      merged[level] = {}
      for (const { role } of STAGES) {
        merged[level][role] = userMap[level]?.[role] ?? DEFAULT_COMPLEXITY_MAP[level]?.[role] ?? ''
      }
    }
    setDrafts(merged)
    setDirty(false)
  }, [mapRaw])

  const handleToggle = () => {
    onSave('pipeline.complexity_routing_enabled', JSON.stringify(!enabled))
  }

  const handleChange = (level: string, role: string, value: string) => {
    setDrafts(prev => ({
      ...prev,
      [level]: { ...prev[level], [role]: value },
    }))
    setDirty(true)
  }

  const handleSaveMap = () => {
    // Only include non-default values
    const result: Record<string, Record<string, string | null>> = {}
    for (const level of COMPLEXITY_LEVELS) {
      result[level] = {}
      for (const { role } of STAGES) {
        const val = drafts[level]?.[role] ?? ''
        result[level][role] = val || null
      }
    }
    onSave('pipeline.complexity_model_map', JSON.stringify(result))
    setDirty(false)
  }

  const handleReset = () => {
    const merged: Record<string, Record<string, string>> = {}
    for (const level of COMPLEXITY_LEVELS) {
      merged[level] = {}
      for (const { role } of STAGES) {
        merged[level][role] = DEFAULT_COMPLEXITY_MAP[level]?.[role] ?? ''
      }
    }
    setDrafts(merged)
    setDirty(true) // dirty because we're resetting to defaults, not saved values
  }

  return (
    <div className="border-t border-neutral-100 dark:border-neutral-800 pt-4">
      <div className="flex items-center justify-between">
        <div>
          <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Complexity Routing</label>
          <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
            Auto-classify task complexity and route to appropriate model tiers.
          </p>
        </div>
        <Toggle enabled={enabled} onToggle={handleToggle} disabled={saving} />
      </div>

      {enabled && (
        <div className="mt-3">
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:text-accent-700 dark:hover:text-accent-400 flex items-center gap-1"
          >
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            Model Map ({COMPLEXITY_LEVELS.length} levels × {STAGES.length} stages)
          </button>

          {expanded && (
            <div className="mt-2 space-y-4">
              {dirty && (
                <div className="flex items-center justify-end gap-2">
                  <button onClick={handleReset}
                    className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-300">
                    <RotateCcw size={10} /> Defaults
                  </button>
                  <button onClick={handleSaveMap} disabled={saving}
                    className="flex items-center gap-1 rounded-md bg-accent-700 px-2.5 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40">
                    <Save size={10} /> Save
                  </button>
                </div>
              )}

              {COMPLEXITY_LEVELS.map(level => (
                <div key={level}>
                  <label className="text-xs font-semibold text-neutral-700 dark:text-neutral-300 capitalize">{level}</label>
                  <div className="mt-1 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {STAGES.map(({ role, label }) => (
                      <div key={role}>
                        <label className="text-[11px] text-neutral-500 dark:text-neutral-400">{label}</label>
                        <ModelPicker
                          value={drafts[level]?.[role] ?? ''}
                          onChange={v => handleChange(level, role, v)}
                          models={models}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ))}

              <p className="text-xs text-neutral-500 dark:text-neutral-400">
                Empty = use stage default or pod default. Simple tasks use cheap models everywhere; complex tasks reserve frontier for Task + Code Review.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Training Data Collection ─────────────────────────────────────────────────

function TrainingDataSubsection({
  entries,
  onSave,
  saving,
}: {
  entries: PlatformConfigEntry[]
  onSave: (key: string, value: string) => void
  saving: boolean
}) {
  const enabled = useConfigValue(entries, 'pipeline.training_log_enabled', 'false') === 'true'
  const [exportRole, setExportRole] = useState('')

  const { data: countData } = useQuery({
    queryKey: ['training-data-count'],
    queryFn: () => apiFetch<{ count: number }>('/api/v1/training-data/count'),
    staleTime: 30_000,
    enabled,
  })

  const handleToggle = () => {
    onSave('pipeline.training_log_enabled', JSON.stringify(!enabled))
  }

  const handleExport = () => {
    const params = new URLSearchParams({ format: 'jsonl' })
    if (exportRole) params.set('role', exportRole)
    // Open in new tab — admin headers are handled by the browser via cookie/session
    // For API key auth, we need to use fetch + blob
    const url = `/api/v1/training-data/export?${params}`
    window.open(url, '_blank')
  }

  return (
    <div className="border-t border-neutral-100 dark:border-neutral-800 pt-4">
      <div className="flex items-center justify-between">
        <div>
          <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Training Data Collection</label>
          <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
            Log full prompt/response pairs for future SLM fine-tuning.
          </p>
        </div>
        <Toggle enabled={enabled} onToggle={handleToggle} disabled={saving} />
      </div>

      {enabled && (
        <div className="mt-3 space-y-3">
          {countData && (
            <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2">
              <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                {countData.count.toLocaleString()}
              </span>
              <span className="text-xs text-neutral-500 dark:text-neutral-400 ml-1.5">
                training entries logged
              </span>
            </div>
          )}

          <div className="flex items-center gap-2">
            <select
              value={exportRole}
              onChange={e => setExportRole(e.target.value)}
              className="rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-2 py-1.5 text-xs text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600 transition-colors"
            >
              <option value="">All roles</option>
              {STAGES.map(({ role, label }) => (
                <option key={role} value={role}>{label}</option>
              ))}
            </select>
            <button
              onClick={handleExport}
              className="flex items-center gap-1 rounded-md bg-accent-700 px-3 py-1.5 text-xs text-white hover:bg-accent-500"
            >
              <Download size={12} /> Export JSONL
            </button>
          </div>

          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            Exports in OpenAI fine-tuning format (JSONL). Each line contains the full messages array and model response.
          </p>
        </div>
      )}
    </div>
  )
}

// ── Main section ─────────────────────────────────────────────────────────────

export function PipelineModelsSection({
  entries,
  onSave,
  saving,
}: {
  entries: PlatformConfigEntry[]
  onSave: (key: string, value: string) => void
  saving: boolean
}) {
  const { data: providers } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
  })
  const allModels = (providers ?? [])
    .filter(p => p.available)
    .flatMap(p => p.models.filter(m => m.registered).map(m => m.id))

  return (
    <Section
      icon={Layers}
      title="Pipeline Stage Models"
      description="Configure which models each pipeline stage uses. Cheap models suffice for most stages — reserve frontier models for the Task Agent."
    >
      <StageDefaultsSubsection entries={entries} onSave={onSave} saving={saving} models={allModels} />
      <ComplexityRoutingSubsection entries={entries} onSave={onSave} saving={saving} models={allModels} />
      <TrainingDataSubsection entries={entries} onSave={onSave} saving={saving} />
    </Section>
  )
}
