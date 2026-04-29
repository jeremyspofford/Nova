import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, RotateCcw, Database, AlertTriangle } from 'lucide-react'
import { apiFetch } from '../../api'
import { Section, Button, Input, StatusDot } from '../../components/ui'
import { useConfigValue, type ConfigSectionProps } from './shared'

// ── Provider presets ────────────────────────────────────────────────────────

const PROVIDERS = [
  { value: 'http://memory-service:8002', label: 'Engram Network', desc: 'Graph-based cognitive memory with spreading activation. Nova\'s default and only production-supported provider.' },
  { value: 'http://baseline-pgvector:8003', label: 'pgvector (benchmark)', desc: 'Naive vector similarity baseline for comparison testing. Requires `docker compose --profile benchmark up`.' },
  { value: 'http://baseline-mem0:8004', label: 'Mem0 (benchmark)', desc: 'mem0 library wrapper for comparison testing. Requires `docker compose --profile benchmark up`.' },
  { value: 'http://baseline-markdown:8005', label: 'Markdown / Context (benchmark)', desc: 'File-based markdown baseline for comparison testing. Requires `docker compose --profile benchmark up`.' },
  { value: 'custom', label: 'Custom URL (advanced)', desc: 'Point at your own service. The orchestrator calls `/api/v1/engrams/*` paths.' },
] as const

const PRESET_URLS: Set<string> = new Set(PROVIDERS.filter(p => p.value !== 'custom').map(p => p.value))

const CONFIG_KEY = 'memory.provider_url'
const DEFAULT_URL = 'http://memory-service:8002'

// ── MemoryProviderSection ───────────────────────────────────────────────────

export function MemoryProviderSection({ entries, onSave, saving }: ConfigSectionProps) {
  const configured = useConfigValue(entries, CONFIG_KEY, DEFAULT_URL)

  // Determine if the configured URL matches a preset or is custom
  const isPreset = PRESET_URLS.has(configured)
  const [selectedPreset, setSelectedPreset] = useState(isPreset ? configured : 'custom')
  const [customUrl, setCustomUrl] = useState(isPreset ? '' : configured)
  const [dirty, setDirty] = useState(false)

  // Sync when external value changes (e.g. after save or refetch)
  useEffect(() => {
    const preset = PRESET_URLS.has(configured)
    setSelectedPreset(preset ? configured : 'custom')
    setCustomUrl(preset ? '' : configured)
    setDirty(false)
  }, [configured])

  // The effective URL that would be saved
  const effectiveUrl = selectedPreset === 'custom' ? customUrl.trim() : selectedPreset

  const handlePresetChange = (value: string) => {
    setSelectedPreset(value)
    if (value !== 'custom') {
      setCustomUrl('')
    }
    const newUrl = value === 'custom' ? customUrl.trim() : value
    setDirty(newUrl !== configured)
  }

  const handleCustomUrlChange = (value: string) => {
    setCustomUrl(value)
    setDirty(value.trim() !== configured)
  }

  const handleSave = () => {
    if (!effectiveUrl) return
    onSave(CONFIG_KEY, JSON.stringify(effectiveUrl))
  }

  const handleReset = () => {
    const preset = PRESET_URLS.has(configured)
    setSelectedPreset(preset ? configured : 'custom')
    setCustomUrl(preset ? '' : configured)
    setDirty(false)
  }

  // Health check — polls /mem/health/ready to check the active memory provider
  const { data: health } = useQuery<{ status: string }>({
    queryKey: ['memory-provider-health'],
    queryFn: () => apiFetch('/mem/health/ready'),
    staleTime: 10_000,
    refetchInterval: 15_000,
    retry: 1,
  })

  const isHealthy = health?.status === 'ok' || health?.status === 'ready'
  const healthStatus: 'success' | 'danger' | 'neutral' = health == null
    ? 'neutral'
    : isHealthy ? 'success' : 'danger'
  const healthLabel = health == null
    ? 'Checking...'
    : isHealthy ? 'Healthy' : 'Unreachable'

  const activeProvider = PROVIDERS.find(p => p.value === configured)

  return (
    <Section
      icon={Database}
      title="Memory Provider"
      description="Memory backend used by the orchestrator. The Engram Network is the default and only production-supported provider. Other options exist for benchmark comparison and do not migrate existing memory."
    >
      {/* Current status */}
      <div className="flex items-center gap-3 mb-1">
        <StatusDot status={healthStatus} pulse={health == null} />
        <span className="text-compact text-content-primary">
          {activeProvider?.label ?? 'Custom'} — {healthLabel}
        </span>
        {!dirty && (
          <span className="text-caption font-mono text-content-tertiary ml-auto">
            {configured}
          </span>
        )}
      </div>

      {selectedPreset !== DEFAULT_URL && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-caption text-amber-700 dark:text-amber-400">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <div className="space-y-1">
            <p className="font-medium">Benchmark / advanced provider selected.</p>
            <p className="text-amber-700/80 dark:text-amber-400/80">
              Switching away from Engram Network will not migrate existing engrams — your assistant starts with empty memory until new context accumulates. Baseline providers additionally require <code className="font-mono">docker compose --profile benchmark up</code> before they will respond.
            </p>
          </div>
        </div>
      )}

      {/* Provider selector */}
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <label className="text-caption font-medium text-content-secondary">Provider</label>
          {dirty && (
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleReset}
                icon={<RotateCcw size={10} />}
              >
                Reset
              </Button>
              <Button
                size="sm"
                onClick={handleSave}
                disabled={saving || !effectiveUrl}
                loading={saving}
                icon={<Save size={10} />}
              >
                Save
              </Button>
            </div>
          )}
        </div>

        <select
          value={selectedPreset}
          onChange={e => handlePresetChange(e.target.value)}
          className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 transition-colors appearance-none"
        >
          {PROVIDERS.map(p => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>

        {/* Description for selected provider */}
        <p className="mt-1 text-caption text-content-tertiary">
          {PROVIDERS.find(p => p.value === selectedPreset)?.desc}
        </p>
      </div>

      {/* Custom URL input */}
      {selectedPreset === 'custom' && (
        <div className="mt-3">
          <label className="mb-1.5 block text-caption font-medium text-content-secondary">
            Custom Endpoint URL
          </label>
          <Input
            value={customUrl}
            onChange={e => handleCustomUrlChange(e.target.value)}
            placeholder="http://my-memory-service:8002"
          />
          <p className="mt-1 text-caption text-content-tertiary">
            Must serve <code className="font-mono">/api/v1/engrams/*</code> paths. The benchmark baselines use <code className="font-mono">/api/v1/memory/*</code> and will not work as drop-in providers without an adapter.
          </p>
        </div>
      )}
    </Section>
  )
}
