import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Layers, Save, RotateCcw, Download, ChevronDown, ChevronRight } from 'lucide-react'
import { discoverModels, type PlatformConfigEntry } from '../../api'
import { Section, Button, Toggle, Select, Badge } from '../../components/ui'
import { useConfigValue } from './shared'
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

// ── Model picker (reusable) ──────────────────────────────────────────────────

function StagePicker({
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
      className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 transition-colors appearance-none"
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
          <label className="text-caption font-medium text-content-secondary">Per-Stage Model Defaults</label>
          <p className="text-caption text-content-tertiary mt-0.5">
            Assign different models to each pipeline stage. Only Task Agent needs a frontier model.
          </p>
        </div>
        <Toggle checked={enabled} onChange={handleToggle} disabled={saving} />
      </div>

      {enabled && (
        <div className="mt-3 space-y-3">
          {dirty && (
            <div className="flex items-center justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={handleReset} icon={<RotateCcw size={10} />}>Reset</Button>
              <Button size="sm" onClick={handleSaveAll} loading={saving} icon={<Save size={10} />}>Save All</Button>
            </div>
          )}

          {STAGES.map(({ role, label, hint }) => (
            <div key={role}>
              <label className="text-caption font-medium text-content-secondary">{label}</label>
              <StagePicker
                value={drafts[role] ?? ''}
                onChange={v => handleDraftChange(role, v)}
                models={models}
              />
              <p className="mt-0.5 text-micro text-content-tertiary">{hint}</p>
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

  let userMap: Record<string, Record<string, string>> = {}
  try {
    const parsed = typeof mapRaw === 'string' ? JSON.parse(mapRaw) : mapRaw
    if (typeof parsed === 'object' && parsed !== null) userMap = parsed
  } catch { /* use empty */ }

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
    setDirty(true)
  }

  return (
    <div className="border-t border-border-subtle pt-4">
      <div className="flex items-center justify-between">
        <div>
          <label className="text-caption font-medium text-content-secondary">Complexity Routing</label>
          <p className="text-caption text-content-tertiary mt-0.5">
            Auto-classify task complexity and route to appropriate model tiers.
          </p>
        </div>
        <Toggle checked={enabled} onChange={handleToggle} disabled={saving} />
      </div>

      {enabled && (
        <div className="mt-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded(!expanded)}
            icon={expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          >
            Model Map ({COMPLEXITY_LEVELS.length} levels x {STAGES.length} stages)
          </Button>

          {expanded && (
            <div className="mt-2 space-y-4">
              {dirty && (
                <div className="flex items-center justify-end gap-2">
                  <Button variant="ghost" size="sm" onClick={handleReset} icon={<RotateCcw size={10} />}>Defaults</Button>
                  <Button size="sm" onClick={handleSaveMap} loading={saving} icon={<Save size={10} />}>Save</Button>
                </div>
              )}

              {COMPLEXITY_LEVELS.map(level => (
                <div key={level}>
                  <label className="text-caption font-semibold text-content-primary capitalize">{level}</label>
                  <div className="mt-1 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {STAGES.map(({ role, label }) => (
                      <div key={role}>
                        <label className="text-micro text-content-tertiary">{label}</label>
                        <StagePicker
                          value={drafts[level]?.[role] ?? ''}
                          onChange={v => handleChange(level, role, v)}
                          models={models}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ))}

              <p className="text-caption text-content-tertiary">
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
    const url = `/api/v1/training-data/export?${params}`
    window.open(url, '_blank')
  }

  return (
    <div className="border-t border-border-subtle pt-4">
      <div className="flex items-center justify-between">
        <div>
          <label className="text-caption font-medium text-content-secondary">Training Data Collection</label>
          <p className="text-caption text-content-tertiary mt-0.5">
            Log full prompt/response pairs for future SLM fine-tuning.
          </p>
        </div>
        <Toggle checked={enabled} onChange={handleToggle} disabled={saving} />
      </div>

      {enabled && (
        <div className="mt-3 space-y-3">
          {countData && (
            <div className="rounded-sm border border-border-subtle bg-surface-elevated px-3 py-2">
              <span className="text-compact font-medium text-content-primary">
                {countData.count.toLocaleString()}
              </span>
              <span className="text-caption text-content-tertiary ml-1.5">
                training entries logged
              </span>
            </div>
          )}

          <div className="flex items-center gap-2">
            <select
              value={exportRole}
              onChange={e => setExportRole(e.target.value)}
              className="h-9 rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 transition-colors appearance-none"
            >
              <option value="">All roles</option>
              {STAGES.map(({ role, label }) => (
                <option key={role} value={role}>{label}</option>
              ))}
            </select>
            <Button size="sm" onClick={handleExport} icon={<Download size={12} />}>
              Export JSONL
            </Button>
          </div>

          <p className="text-caption text-content-tertiary">
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
      description="Configure which models each pipeline stage uses. Cheap models suffice for most stages -- reserve frontier models for the Task Agent."
    >
      <StageDefaultsSubsection entries={entries} onSave={onSave} saving={saving} models={allModels} />
      <ComplexityRoutingSubsection entries={entries} onSave={onSave} saving={saving} models={allModels} />
      <TrainingDataSubsection entries={entries} onSave={onSave} saving={saving} />
    </Section>
  )
}
