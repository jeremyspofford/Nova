import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, RotateCcw, Radio, Wifi, WifiOff, Power } from 'lucide-react'
import { getOllamaStatus, discoverModels, resolveModel, testProvider, type PlatformConfigEntry } from '../../api'
import { Section, ConfigField, useConfigValue } from './shared'

// ── LLM Routing section ──────────────────────────────────────────────────────

const ROUTING_STRATEGIES = [
  { value: 'local-only',  label: 'Local Only',  desc: 'Use Ollama exclusively. Requests fail if offline.' },
  { value: 'local-first', label: 'Local First',  desc: 'Try Ollama, fall back to cloud if offline. WoL wakes remote PC.' },
  { value: 'cloud-only',  label: 'Cloud Only',  desc: 'Skip Ollama entirely. Always use cloud providers.' },
  { value: 'cloud-first', label: 'Cloud First', desc: 'Prefer cloud, use Ollama as backup.' },
] as const

function CloudFallbackModelPicker({
  value,
  onSave,
  saving,
}: {
  value: string
  onSave: (key: string, value: string) => void
  saving: boolean
}) {
  const { data: providers } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
  })
  // Filter to cloud models only from available providers
  const cloudModels = (providers ?? [])
    .filter(p => p.available && p.type !== 'local')
    .flatMap(p => p.models.filter(m => m.registered).map(m => m.id))

  const [draft, setDraft] = useState(value)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setDraft(value)
    setDirty(false)
  }, [value])

  const handleChange = (v: string) => {
    setDraft(v)
    setDirty(v !== value)
  }

  const handleSave = () => onSave('llm.cloud_fallback_model', JSON.stringify(draft))
  const handleReset = () => { setDraft(value); setDirty(false) }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Cloud Fallback Model</label>
        {dirty && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleReset}
              className="flex items-center gap-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300"
            >
              <RotateCcw size={10} /> Reset
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1 rounded-md bg-accent-700 px-2.5 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40"
            >
              <Save size={10} /> {saving ? 'Saving\u2026' : 'Save'}
            </button>
          </div>
        )}
      </div>

      <select
        value={draft}
        onChange={e => handleChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600 transition-colors"
      >
        {/* If current value isn't in the list, still show it */}
        {draft && !cloudModels.includes(draft) && (
          <option value={draft}>{draft}</option>
        )}
        {cloudModels.map(id => (
          <option key={id} value={id}>{id}</option>
        ))}
        {cloudModels.length === 0 && !draft && (
          <option value="">No cloud models available</option>
        )}
      </select>

      <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
        Cloud model used when Ollama is unavailable (local-first/cloud-first strategies).
      </p>
    </div>
  )
}

function DefaultModelPicker({
  onSave,
  saving,
  entries,
}: {
  onSave: (key: string, value: string) => void
  saving: boolean
  entries: PlatformConfigEntry[]
}) {
  const configured = useConfigValue(entries, 'llm.default_chat_model', 'auto')
  const [draft, setDraft] = useState(configured)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setDraft(configured)
    setDirty(false)
  }, [configured])

  const { data: resolved } = useQuery({
    queryKey: ['resolved-model'],
    queryFn: resolveModel,
    staleTime: 30_000,
  })

  const { data: providers } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
  })
  const allModels = (providers ?? [])
    .filter(p => p.available)
    .flatMap(p => p.models.filter(m => m.registered).map(m => m.id))

  const handleChange = (v: string) => {
    setDraft(v)
    setDirty(v !== configured)
  }

  const handleSave = () => onSave('llm.default_chat_model', JSON.stringify(draft))
  const handleReset = () => { setDraft(configured); setDirty(false) }

  return (
    <div className="border-t border-neutral-100 dark:border-neutral-800 pt-4">
      <div className="mb-1 flex items-center justify-between">
        <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Default Chat Model</label>
        {dirty && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleReset}
              className="flex items-center gap-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300"
            >
              <RotateCcw size={10} /> Reset
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1 rounded-md bg-accent-700 px-2.5 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40"
            >
              <Save size={10} /> {saving ? 'Saving\u2026' : 'Save'}
            </button>
          </div>
        )}
      </div>

      <select
        value={draft}
        onChange={e => handleChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600 transition-colors"
      >
        <option value="auto">
          Auto (best available){resolved?.source === 'auto' ? ` \u2014 ${resolved.model}` : ''}
        </option>
        {allModels.map(id => (
          <option key={id} value={id}>{id}</option>
        ))}
        {/* If current explicit value isn't in the list, still show it */}
        {draft !== 'auto' && !allModels.includes(draft) && (
          <option value={draft}>{draft}</option>
        )}
      </select>

      <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
        Model used for chat and pipeline when no override is set. &quot;Auto&quot; picks the best model from your authenticated providers.
      </p>
    </div>
  )
}

// ── Intelligent Routing sub-section ──────────────────────────────────────────

const CATEGORY_LABELS: Record<string, string> = {
  general: 'General \u2014 conversation, greetings, opinions',
  code: 'Code \u2014 writing, debugging, reviewing',
  reasoning: 'Reasoning \u2014 math, logic, multi-step analysis',
  creative: 'Creative \u2014 stories, copy, brainstorming',
  quick: 'Quick \u2014 lookups, yes/no, one-word answers',
}

function IntelligentRoutingSection({
  entries,
  onSave,
  saving,
}: {
  entries: PlatformConfigEntry[]
  onSave: (key: string, value: string) => void
  saving: boolean
}) {
  const enabled = useConfigValue(entries, 'llm.intelligent_routing', 'false') === 'true'
  const classifierModel = useConfigValue(entries, 'llm.classifier_model', 'auto')
  const timeoutMs = useConfigValue(entries, 'llm.classifier_timeout_ms', '500')
  const routingMapRaw = useConfigValue(entries, 'llm.model_routing_map', '{}')

  const [expanded, setExpanded] = useState(false)

  // Parse routing map
  let routingMap: Record<string, string[] | null> = {}
  try {
    const parsed = typeof routingMapRaw === 'string' ? JSON.parse(routingMapRaw) : routingMapRaw
    if (typeof parsed === 'object' && parsed !== null) routingMap = parsed
  } catch { /* use empty */ }

  // Classifier model draft
  const [classifierDraft, setClassifierDraft] = useState(classifierModel)
  const [classifierDirty, setClassifierDirty] = useState(false)
  useEffect(() => { setClassifierDraft(classifierModel); setClassifierDirty(false) }, [classifierModel])

  // Timeout draft
  const [timeoutDraft, setTimeoutDraft] = useState(timeoutMs)
  const [timeoutDirty, setTimeoutDirty] = useState(false)
  useEffect(() => { setTimeoutDraft(timeoutMs); setTimeoutDirty(false) }, [timeoutMs])

  // Routing map draft (per-category comma-separated strings)
  const [mapDraft, setMapDraft] = useState<Record<string, string>>({})
  const [mapDirty, setMapDirty] = useState(false)
  useEffect(() => {
    const draft: Record<string, string> = {}
    for (const [cat, models] of Object.entries(routingMap)) {
      draft[cat] = models ? models.join(', ') : ''
    }
    setMapDraft(draft)
    setMapDirty(false)
  }, [routingMapRaw])

  const handleToggle = () => {
    onSave('llm.intelligent_routing', JSON.stringify(!enabled))
  }

  const handleSaveClassifier = () => {
    onSave('llm.classifier_model', JSON.stringify(classifierDraft))
    setClassifierDirty(false)
  }

  const handleSaveTimeout = () => {
    onSave('llm.classifier_timeout_ms', JSON.stringify(timeoutDraft))
    setTimeoutDirty(false)
  }

  const handleSaveMap = () => {
    const result: Record<string, string[] | null> = {}
    for (const [cat, val] of Object.entries(mapDraft)) {
      const trimmed = val.trim()
      result[cat] = trimmed ? trimmed.split(',').map(s => s.trim()).filter(Boolean) : null
    }
    onSave('llm.model_routing_map', JSON.stringify(result))
    setMapDirty(false)
  }

  const { data: providers } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
    enabled: expanded && enabled,
  })
  const allModels = (providers ?? [])
    .filter(p => p.available)
    .flatMap(p => p.models.filter(m => m.registered).map(m => m.id))

  return (
    <div className="border-t border-neutral-100 dark:border-neutral-800 pt-4">
      {/* Toggle */}
      <div className="flex items-center justify-between">
        <div>
          <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Intelligent Model Routing</label>
          <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
            Classifier picks the optimal model per message based on task type.
          </p>
        </div>
        <button
          onClick={handleToggle}
          disabled={saving}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            enabled ? 'bg-accent-700' : 'bg-neutral-300 dark:bg-neutral-600'
          } disabled:opacity-40`}
        >
          <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
            enabled ? 'translate-x-[18px]' : 'translate-x-[2px]'
          }`} />
        </button>
      </div>

      {/* Expanded settings when enabled */}
      {enabled && (
        <div className="mt-3 space-y-3 pl-0">
          {/* Classifier model */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Classifier Model</label>
              {classifierDirty && (
                <div className="flex items-center gap-2">
                  <button onClick={() => { setClassifierDraft(classifierModel); setClassifierDirty(false) }}
                    className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-300">
                    <RotateCcw size={10} /> Reset
                  </button>
                  <button onClick={handleSaveClassifier} disabled={saving}
                    className="flex items-center gap-1 rounded-md bg-accent-700 px-2.5 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40">
                    <Save size={10} /> Save
                  </button>
                </div>
              )}
            </div>
            <select
              value={classifierDraft}
              onChange={e => { setClassifierDraft(e.target.value); setClassifierDirty(e.target.value !== classifierModel) }}
              className="w-full rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600 transition-colors"
            >
              <option value="auto">Auto (local-first cascade)</option>
              {allModels.map(id => <option key={id} value={id}>{id}</option>)}
            </select>
            <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Small fast model used to classify messages. &quot;Auto&quot; tries local Ollama first, then Groq, then Cerebras.
            </p>
          </div>

          {/* Timeout */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
                Classifier Timeout: {timeoutDraft}ms
              </label>
              {timeoutDirty && (
                <div className="flex items-center gap-2">
                  <button onClick={() => { setTimeoutDraft(timeoutMs); setTimeoutDirty(false) }}
                    className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-300">
                    <RotateCcw size={10} /> Reset
                  </button>
                  <button onClick={handleSaveTimeout} disabled={saving}
                    className="flex items-center gap-1 rounded-md bg-accent-700 px-2.5 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40">
                    <Save size={10} /> Save
                  </button>
                </div>
              )}
            </div>
            <input
              type="range"
              min={100}
              max={1000}
              step={50}
              value={timeoutDraft}
              onChange={e => { setTimeoutDraft(e.target.value); setTimeoutDirty(e.target.value !== timeoutMs) }}
              className="w-full accent-accent-700"
            />
            <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Max time to wait for classification. Falls back to default model if exceeded.
            </p>
          </div>

          {/* Category routing map */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:text-accent-700 dark:hover:text-accent-400 flex items-center gap-1"
              >
                Category Model Mapping
                <span className="text-[10px]">{expanded ? '\u25BC' : '\u25B6'}</span>
              </button>
              {mapDirty && (
                <div className="flex items-center gap-2">
                  <button onClick={() => {
                    const draft: Record<string, string> = {}
                    for (const [cat, models] of Object.entries(routingMap)) {
                      draft[cat] = models ? models.join(', ') : ''
                    }
                    setMapDraft(draft); setMapDirty(false)
                  }}
                    className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-300">
                    <RotateCcw size={10} /> Reset
                  </button>
                  <button onClick={handleSaveMap} disabled={saving}
                    className="flex items-center gap-1 rounded-md bg-accent-700 px-2.5 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40">
                    <Save size={10} /> Save
                  </button>
                </div>
              )}
            </div>

            {expanded && (
              <div className="space-y-2 mt-2">
                {Object.keys(CATEGORY_LABELS).map(cat => (
                  <div key={cat}>
                    <label className="text-xs text-neutral-500 dark:text-neutral-400">{CATEGORY_LABELS[cat]}</label>
                    <input
                      type="text"
                      value={mapDraft[cat] ?? ''}
                      onChange={e => {
                        setMapDraft(prev => ({ ...prev, [cat]: e.target.value }))
                        setMapDirty(true)
                      }}
                      placeholder={cat === 'general' ? '(uses default model)' : 'model-1, model-2, ...'}
                      className="w-full rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-1.5 text-xs text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 dark:placeholder:text-neutral-500 outline-none focus:border-accent-600 transition-colors font-mono"
                    />
                  </div>
                ))}
                <p className="text-xs text-neutral-500 dark:text-neutral-400">
                  Comma-separated model preference list per category. First available model wins. Leave empty to use default.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export function LLMRoutingSection({
  entries,
  onSave,
  saving,
}: {
  entries: PlatformConfigEntry[]
  onSave: (key: string, value: string) => void
  saving: boolean
}) {
  const strategy = useConfigValue(entries, 'llm.routing_strategy', 'local-first')
  const ollamaUrl = useConfigValue(entries, 'llm.ollama_url', '')
  const cloudFallback = useConfigValue(entries, 'llm.cloud_fallback_model', 'groq/llama-3.3-70b-versatile')
  const wolMac = useConfigValue(entries, 'llm.wol_mac', '')
  const wolBroadcast = useConfigValue(entries, 'llm.wol_broadcast', '255.255.255.255')

  const [strategySaved, setStrategySaved] = useState(false)

  const usesOllama = strategy !== 'cloud-only'
  const usesCloud = strategy !== 'local-only'

  const { data: ollamaStatus } = useQuery({
    queryKey: ['ollama-status'],
    queryFn: getOllamaStatus,
    staleTime: 10_000,
    refetchInterval: 15_000,
    enabled: usesOllama,
  })

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; latency_ms: number; error?: string } | null>(null)

  const handleTest = useCallback(async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await testProvider('ollama')
      setTestResult(result)
    } catch (e) {
      setTestResult({ ok: false, latency_ms: 0, error: String(e) })
    } finally {
      setTesting(false)
    }
  }, [])

  const handleStrategyChange = (value: string) => {
    onSave('llm.routing_strategy', JSON.stringify(value))
    setStrategySaved(true)
    setTimeout(() => setStrategySaved(false), 1500)
  }

  return (
    <Section
      icon={Radio}
      title="LLM Routing"
      description="Control how requests are routed between local Ollama and cloud providers."
    >
      {/* Strategy selector */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Routing Strategy</label>
          {strategySaved && (
            <span className="text-xs text-emerald-600 dark:text-emerald-400 animate-pulse">Saved</span>
          )}
        </div>
        <div className="inline-flex flex-wrap rounded-lg border border-neutral-200 dark:border-neutral-700 p-0.5">
          {ROUTING_STRATEGIES.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => handleStrategyChange(value)}
              disabled={saving}
              className={
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors ' +
                (strategy === value
                  ? 'bg-accent-700/10 text-accent-700 dark:bg-accent-400/10 dark:text-accent-400'
                  : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300')
              }
            >
              {label}
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-xs text-neutral-500 dark:text-neutral-400">
          {ROUTING_STRATEGIES.find(s => s.value === strategy)?.desc}
        </p>
      </div>

      {/* Ollama settings — hidden when cloud-only */}
      {usesOllama && (
        <>
          {/* Ollama status indicator */}
          <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {ollamaStatus?.healthy ? (
                  <Wifi size={14} className="text-emerald-500" />
                ) : (
                  <WifiOff size={14} className="text-red-500" />
                )}
                <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                  Ollama {ollamaStatus?.healthy ? 'Online' : 'Offline'}
                </span>
              </div>
              <span className="text-xs font-mono text-neutral-500 dark:text-neutral-400">
                {ollamaStatus?.base_url ?? '...'}
              </span>
            </div>

            {ollamaStatus?.wol_configured && (
              <div className="flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
                <Power size={12} />
                <span>
                  WoL {ollamaStatus.wol_last_sent_seconds_ago != null
                    ? `sent ${ollamaStatus.wol_last_sent_seconds_ago}s ago`
                    : 'ready'}
                </span>
              </div>
            )}

            <div className="flex items-center justify-between">
              <button
                onClick={handleTest}
                disabled={testing}
                className="text-xs font-medium text-accent-700 dark:text-accent-400 hover:underline disabled:opacity-40"
              >
                {testing ? 'Testing\u2026' : 'Test Connection'}
              </button>
              {testResult && (
                <span className={`text-xs ${testResult.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                  {testResult.ok ? `${testResult.latency_ms}ms` : testResult.error ?? 'Failed'}
                </span>
              )}
            </div>
          </div>

          {/* Remote Ollama config */}
          <ConfigField
            label="Ollama URL"
            configKey="llm.ollama_url"
            value={ollamaUrl}
            placeholder="http://192.168.1.50:11434"
            description="Remote Ollama base URL. Leave blank to use the OLLAMA_BASE_URL env var. Takes effect within ~5 seconds."
            onSave={onSave}
            saving={saving}
          />

          {/* Wake-on-LAN config */}
          <div className="border-t border-neutral-100 dark:border-neutral-800 pt-4">
            <label className="mb-2 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Wake-on-LAN</label>
            <div className="grid gap-3 sm:grid-cols-2">
              <ConfigField
                label="MAC Address"
                configKey="llm.wol_mac"
                value={wolMac}
                placeholder="AA:BB:CC:DD:EE:FF"
                description="MAC of the remote Ollama host."
                onSave={onSave}
                saving={saving}
              />
              <ConfigField
                label="Broadcast IP"
                configKey="llm.wol_broadcast"
                value={wolBroadcast}
                placeholder="192.168.1.255"
                description="LAN broadcast address."
                onSave={onSave}
                saving={saving}
              />
            </div>
          </div>
        </>
      )}

      {/* Cloud fallback model — hidden when local-only */}
      {usesCloud && (
        <CloudFallbackModelPicker
          value={cloudFallback}
          onSave={onSave}
          saving={saving}
        />
      )}

      {/* Default chat model — auto or explicit */}
      <DefaultModelPicker onSave={onSave} saving={saving} entries={entries} />

      {/* Intelligent routing */}
      <IntelligentRoutingSection entries={entries} onSave={onSave} saving={saving} />
    </Section>
  )
}
