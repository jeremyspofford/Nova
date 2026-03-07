import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, RotateCcw, Bot, Sliders, Palette, Moon, Sun, Monitor, FileCode, ExternalLink, Activity, Gauge, ShieldCheck, Radio, Wifi, WifiOff, Power, Loader2, Globe, Shield } from 'lucide-react'
import { getPlatformConfig, updatePlatformConfig, getProviderStatus, testProvider, getAdminSecret, setAdminSecret, getOllamaStatus, discoverModels, resolveModel, getQueueStats, getMCPServers, type PlatformConfigEntry, type ProviderStatus } from '../api'
import { getRemoteAccessStatus } from '../api-recovery'
import { useTheme } from '../stores/theme-store'
import { accentPalettes, themePresets } from '../lib/color-palettes'
import Card from '../components/Card'
import { ServiceStatusSection as RecoveryServiceStatus, BackupSection as RecoveryBackupSection, FactoryResetSection as RecoveryFactoryReset } from './Recovery'
import { CloudflareWizard, TailscaleWizard, StatusBadge as RemoteStatusBadge } from './RemoteAccess'

// ── Helper: config entry hook ─────────────────────────────────────────────────

/**
 * Returns the string value of a config key from the loaded entries.
 * Falls back to `defaultValue` if the key is missing or the value is null/empty.
 */
function useConfigValue(
  entries: PlatformConfigEntry[],
  key: string,
  defaultValue = '',
): string {
  const entry = entries.find(e => e.key === key)
  if (!entry || entry.value === null || entry.value === '') return defaultValue
  return String(entry.value)
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: React.ElementType
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-neutral-100 dark:border-neutral-800 px-4 py-4 sm:px-5">
        <div className="flex items-center gap-2">
          <Icon size={15} className="text-accent-700 dark:text-accent-400" />
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{title}</h2>
        </div>
        <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">{description}</p>
      </div>
      <div className="px-4 py-4 sm:px-5 space-y-4">{children}</div>
    </Card>
  )
}

// ── Inline editable field ─────────────────────────────────────────────────────

function ConfigField({
  label,
  configKey,
  value,
  description,
  multiline = false,
  placeholder = '',
  onSave,
  saving,
}: {
  label: string
  configKey: string
  value: string
  description?: string
  multiline?: boolean
  placeholder?: string
  onSave: (key: string, value: string) => void
  saving: boolean
}) {
  const [draft, setDraft] = useState(value)
  const [dirty, setDirty] = useState(false)

  // Sync if external value changes (e.g. after save)
  useEffect(() => {
    setDraft(value)
    setDirty(false)
  }, [value])

  const handleChange = (v: string) => {
    setDraft(v)
    setDirty(v !== value)
  }

  const handleSave = () => onSave(configKey, JSON.stringify(draft))
  const handleReset = () => { setDraft(value); setDirty(false) }

  const inputClass =
    'w-full rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 ' +
    'placeholder:text-neutral-400 dark:placeholder:text-neutral-500 outline-none focus:border-accent-600 disabled:opacity-50 transition-colors'

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">{label}</label>
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
              <Save size={10} /> {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        )}
      </div>

      {multiline ? (
        <textarea
          value={draft}
          onChange={e => handleChange(e.target.value)}
          placeholder={placeholder}
          rows={6}
          className={`${inputClass} resize-y`}
        />
      ) : (
        <input
          type="text"
          value={draft}
          onChange={e => handleChange(e.target.value)}
          placeholder={placeholder}
          className={inputClass}
        />
      )}

      {description && (
        <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{description}</p>
      )}
    </div>
  )
}

// ── Appearance section ────────────────────────────────────────────────────────

/** Preview swatch: accent-700 color for each preset (used for the color dot) */
const PRESET_ACCENT_PREVIEW: Record<string, string> = {
  default:          'rgb(15 118 110)',  // teal-700
  ocean:            'rgb(29 78 216)',   // blue-700
  forest:           'rgb(4 120 87)',    // emerald-700
  sunset:           'rgb(190 18 60)',   // rose-700
  nord:             'rgb(94 129 172)',  // nord frost
  'ctp-mocha':      'rgb(137 180 250)',// catppuccin blue
  'ctp-latte':      'rgb(30 102 245)', // catppuccin latte blue
  dracula:          'rgb(189 147 249)',// dracula purple
  'tokyo-night':    'rgb(122 162 247)',// tokyo blue
  gruvbox:          'rgb(254 128 25)', // gruvbox orange
  'solarized-dark': 'rgb(42 161 152)', // solarized cyan
  'one-dark':       'rgb(97 175 239)', // one blue
  custom:           'rgb(120 113 108)',
}

/** Preview swatch: neutral-900 background for each preset (dark bg preview) */
const PRESET_BG_PREVIEW: Record<string, string> = {
  default:          'rgb(28 25 23)',
  ocean:            'rgb(15 23 42)',
  forest:           'rgb(28 25 23)',
  sunset:           'rgb(24 24 27)',
  nord:             'rgb(46 52 64)',
  'ctp-mocha':      'rgb(30 30 46)',
  'ctp-latte':      'rgb(239 241 245)',
  dracula:          'rgb(40 42 54)',
  'tokyo-night':    'rgb(26 27 38)',
  gruvbox:          'rgb(40 40 40)',
  'solarized-dark': 'rgb(0 43 54)',
  'one-dark':       'rgb(40 44 52)',
  custom:           'rgb(28 25 23)',
}

const ACCENT_SWATCHES: Record<string, string> = {
  teal:    'rgb(15 118 110)',
  blue:    'rgb(29 78 216)',
  purple:  'rgb(126 34 206)',
  rose:    'rgb(190 18 60)',
  indigo:  'rgb(67 56 202)',
  cyan:    'rgb(14 116 144)',
  orange:  'rgb(194 65 12)',
  emerald: 'rgb(4 120 87)',
}

function PresetCard({ id, label, active, onClick }: {
  id: string; label: string; active: boolean; onClick: () => void
}) {
  const accent = PRESET_ACCENT_PREVIEW[id]
  const bg = PRESET_BG_PREVIEW[id]
  return (
    <button onClick={onClick} className={
      'group flex flex-col items-center gap-1.5 rounded-lg border p-2 text-[11px] font-medium transition-all ' +
      (active
        ? 'border-accent-600 ring-2 ring-accent-600/30 text-accent-700 dark:text-accent-400'
        : 'border-neutral-200 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 hover:border-neutral-400 dark:hover:border-neutral-500')
    }>
      {/* Mini swatch: dark bg + accent stripe */}
      <span className="relative flex h-6 w-full overflow-hidden rounded-md border border-neutral-200 dark:border-neutral-700">
        <span className="flex-1" style={{ background: bg }} />
        <span className="w-2" style={{ background: accent }} />
      </span>
      <span className="truncate max-w-full">{label}</span>
    </button>
  )
}

function AccentPicker({ activeAccent, onSelect }: {
  activeAccent: string
  onSelect: (name: string) => void
}) {
  return (
    <div className="mt-2">
      <label className="mb-1.5 block text-xs text-neutral-500 dark:text-neutral-400">Accent Color</label>
      <div className="flex flex-wrap gap-2">
        {Object.entries(ACCENT_SWATCHES).map(([name, color]) => (
          <button
            key={name}
            onClick={() => onSelect(name)}
            title={name}
            className={
              'size-8 rounded-full border-2 transition-transform hover:scale-110 ' +
              (activeAccent === name
                ? 'border-accent-600 ring-2 ring-accent-200 dark:ring-accent-800 scale-110'
                : 'border-neutral-300 dark:border-neutral-600')
            }
            style={{ background: color }}
          />
        ))}
      </div>
    </div>
  )
}

const MODE_OPTIONS: { value: 'light' | 'system' | 'dark'; label: string; icon: React.ElementType }[] = [
  { value: 'light',  label: 'Light',  icon: Sun     },
  { value: 'system', label: 'System', icon: Monitor  },
  { value: 'dark',   label: 'Dark',   icon: Moon    },
]

function AppearanceSection() {
  const {
    modePreference, setModePreference,
    lightPreset, setLightPreset,
    darkPreset, setDarkPreset,
    customLightAccent, setCustomLightAccent,
    customDarkAccent, setCustomDarkAccent,
  } = useTheme()

  const allPresets = Object.entries(themePresets)

  return (
    <Section
      icon={Palette}
      title="Appearance"
      description="Configure the look and feel of this dashboard."
    >
      {/* Mode Preference */}
      <div>
        <label className="mb-2 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Mode</label>
        <div className="inline-flex rounded-lg border border-neutral-200 dark:border-neutral-700 p-0.5">
          {MODE_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              onClick={() => setModePreference(value)}
              className={
                'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ' +
                (modePreference === value
                  ? 'bg-accent-700/10 text-accent-700 dark:bg-accent-400/10 dark:text-accent-400'
                  : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300')
              }
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Light Theme */}
      <div>
        <label className="mb-2 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Light Theme</label>
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
          {allPresets.map(([key, p]) => (
            <PresetCard key={key} id={key} label={p.label} active={lightPreset === key} onClick={() => setLightPreset(key)} />
          ))}
        </div>
        {lightPreset === 'custom' && (
          <AccentPicker activeAccent={customLightAccent} onSelect={setCustomLightAccent} />
        )}
      </div>

      {/* Dark Theme */}
      <div>
        <label className="mb-2 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Dark Theme</label>
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
          {allPresets.map(([key, p]) => (
            <PresetCard key={key} id={key} label={p.label} active={darkPreset === key} onClick={() => setDarkPreset(key)} />
          ))}
        </div>
        {darkPreset === 'custom' && (
          <AccentPicker activeAccent={customDarkAccent} onSelect={setCustomDarkAccent} />
        )}
      </div>
    </Section>
  )
}

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
              <Save size={10} /> {saving ? 'Saving…' : 'Save'}
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
              <Save size={10} /> {saving ? 'Saving…' : 'Save'}
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
          Auto (best available){resolved?.source === 'auto' ? ` — ${resolved.model}` : ''}
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

function LLMRoutingSection({
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
                {testing ? 'Testing…' : 'Test Connection'}
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

// ── Intelligent Routing sub-section ──────────────────────────────────────────

const CATEGORY_LABELS: Record<string, string> = {
  general: 'General — conversation, greetings, opinions',
  code: 'Code — writing, debugging, reviewing',
  reasoning: 'Reasoning — math, logic, multi-step analysis',
  creative: 'Creative — stories, copy, brainstorming',
  quick: 'Quick — lookups, yes/no, one-word answers',
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
                <span className="text-[10px]">{expanded ? '▼' : '▶'}</span>
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

// ── Provider Status section ───────────────────────────────────────────────────

const TYPE_BADGE: Record<string, { label: string; className: string }> = {
  subscription: { label: 'Subscription', className: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
  free:         { label: 'Free',         className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' },
  paid:         { label: 'Paid',         className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400' },
  local:        { label: 'Local',        className: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400' },
}

function ProviderStatusSection() {
  const { data: providers, isLoading } = useQuery({
    queryKey: ['provider-status'],
    queryFn: getProviderStatus,
    staleTime: 30_000,
  })

  const [testing, setTesting] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; latency_ms: number; error?: string }>>({})

  const handleTest = useCallback(async (slug: string) => {
    setTesting(slug)
    try {
      const result = await testProvider(slug)
      setTestResults(prev => ({ ...prev, [slug]: result }))
    } catch (e) {
      setTestResults(prev => ({ ...prev, [slug]: { ok: false, latency_ms: 0, error: String(e) } }))
    } finally {
      setTesting(null)
    }
  }, [])

  return (
    <Section
      icon={Activity}
      title="Provider Status"
      description="LLM providers configured for this instance. Test connectivity with each provider."
    >
      {isLoading ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading providers…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {(providers ?? []).map(p => {
            const badge = TYPE_BADGE[p.type] ?? TYPE_BADGE.free
            const result = testResults[p.slug]
            return (
              <div
                key={p.slug}
                className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-3 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={
                        'inline-block size-2 rounded-full ' +
                        (p.available ? 'bg-emerald-500' : 'bg-red-500')
                      }
                      title={p.available ? 'Configured' : 'Not configured'}
                    />
                    <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{p.name}</span>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${badge.className}`}>
                    {badge.label}
                  </span>
                </div>

                <div className="flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400">
                  <span>{p.model_count} model{p.model_count !== 1 ? 's' : ''}</span>
                  <span className="font-mono truncate max-w-[140px]" title={p.default_model}>{p.default_model}</span>
                </div>

                <div className="flex items-center justify-between">
                  <button
                    onClick={() => handleTest(p.slug)}
                    disabled={!p.available || testing === p.slug}
                    className="text-xs font-medium text-accent-700 dark:text-accent-400 hover:underline disabled:opacity-40 disabled:no-underline"
                  >
                    {testing === p.slug ? 'Testing…' : 'Test'}
                  </button>
                  {result && (
                    <span className={`text-xs ${result.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                      {result.ok ? `${result.latency_ms}ms` : result.error ?? 'Failed'}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Section>
  )
}

// ── Context Budget section ───────────────────────────────────────────────────

const BUDGET_SLICES = [
  { key: 'context.system_pct',  label: 'System',  color: 'bg-sky-500' },
  { key: 'context.tools_pct',   label: 'Tools',   color: 'bg-amber-500' },
  { key: 'context.memory_pct',  label: 'Memory',  color: 'bg-emerald-500' },
  { key: 'context.history_pct', label: 'History', color: 'bg-purple-500' },
  { key: 'context.working_pct', label: 'Working', color: 'bg-rose-500' },
] as const

function ContextBudgetSection({
  entries,
  onSave,
  saving,
}: {
  entries: PlatformConfigEntry[]
  onSave: (key: string, value: string) => void
  saving: boolean
}) {
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
              <Save size={10} /> {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        )}
      </div>
    </Section>
  )
}

// ── Admin Secret section ──────────────────────────────────────────────────────

function AdminSecretSection() {
  const [secret, setSecret] = useState(getAdminSecret)
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    setAdminSecret(secret)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <Section
      icon={ShieldCheck}
      title="Admin Secret"
      description="The password this browser sends with admin requests (Pods, Keys, Usage)."
    >
      <div className="space-y-2">
        <input
          type="password"
          value={secret}
          onChange={e => { setSecret(e.target.value); setSaved(false) }}
          placeholder="Paste your ADMIN_SECRET from .env"
          className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
        />
        <p className="text-xs text-neutral-500 dark:text-neutral-400">
          Must match the <code className="rounded bg-neutral-100 dark:bg-neutral-700 px-1 text-neutral-600 dark:text-neutral-300">ADMIN_SECRET</code> value
          in your server's <code className="rounded bg-neutral-100 dark:bg-neutral-700 px-1 text-neutral-600 dark:text-neutral-300">.env</code> file.
          Stored in localStorage only.
        </p>
        <button
          onClick={handleSave}
          className="rounded-md bg-accent-700 px-3 py-1.5 text-sm text-white hover:bg-accent-500"
        >
          {saved ? 'Saved' : 'Save'}
        </button>
      </div>
    </Section>
  )
}

// ── Notifications section ─────────────────────────────────────────────────────

function NotificationsSection() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem('nova-notifications-enabled') === 'true')
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(
    'Notification' in window ? Notification.permission : 'unsupported'
  )

  const toggle = async () => {
    if (!enabled) {
      // Enabling — request permission first
      if ('Notification' in window && Notification.permission !== 'granted') {
        const result = await Notification.requestPermission()
        setPermission(result)
        if (result !== 'granted') return
      }
      localStorage.setItem('nova-notifications-enabled', 'true')
      setEnabled(true)
    } else {
      localStorage.setItem('nova-notifications-enabled', 'false')
      setEnabled(false)
    }
  }

  return (
    <Section
      icon={Radio}
      title="Notifications"
      description="Desktop notifications for task completion (coming soon)"
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-stone-700 dark:text-stone-300">Enable notifications</p>
          <p className="text-xs text-stone-500 dark:text-stone-400">
            {permission === 'unsupported' ? 'Not supported in this browser' :
             permission === 'denied' ? 'Blocked by browser — check site permissions' :
             'Push notifications will be available when async tasks are implemented'}
          </p>
        </div>
        <button
          onClick={toggle}
          disabled={permission === 'unsupported' || permission === 'denied'}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            enabled ? 'bg-accent-600' : 'bg-stone-300 dark:bg-stone-600'
          } ${(permission === 'unsupported' || permission === 'denied') ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            enabled ? 'translate-x-6' : 'translate-x-1'
          }`} />
        </button>
      </div>
    </Section>
  )
}

// ── Developer Resources section ───────────────────────────────────────────────

const SERVICES = [
  { name: 'Orchestrator',   port: 8000, healthPath: '/api/health/live', desc: 'Agent lifecycle, pipeline execution, task queue' },
  { name: 'LLM Gateway',    port: 8001, healthPath: '/v1/health/live',  desc: 'Multi-provider model routing, completions, embeddings' },
  { name: 'Memory Service', port: 8002, healthPath: '/mem/health/live', desc: 'Semantic memory storage and hybrid retrieval' },
  { name: 'Recovery',       port: 8888, healthPath: '/recovery-api/health/live', desc: 'Backup, restore, factory reset, service management' },
] as const

/** Build a direct URL to a service's Swagger docs (bypasses nginx prefix issues). */
function docsUrl(port: number): string {
  return `${window.location.protocol}//${window.location.hostname}:${port}/docs`
}

const ENDPOINTS = [
  { name: 'Orchestrator',   port: 8000, desc: 'Agent lifecycle, pipeline, tasks' },
  { name: 'LLM Gateway',    port: 8001, desc: 'Model routing, completions, embeddings' },
  { name: 'Memory Service', port: 8002, desc: 'Semantic memory, retrieval' },
  { name: 'Chat API',       port: 8080, desc: 'WebSocket streaming bridge' },
  { name: 'Recovery',       port: 8888, desc: 'Backup, restore, factory reset, service management' },
  { name: 'Dashboard',      port: '5173 / 3000', desc: 'Dev (Vite) / Prod (nginx)' },
  { name: 'PostgreSQL',     port: 5432, desc: 'pgvector-enabled database' },
  { name: 'Redis',          port: 6379, desc: 'State, task queue, rate limiting' },
] as const

function useServiceHealth() {
  return useQuery({
    queryKey: ['service-health'],
    queryFn: async () => {
      const results = await Promise.allSettled(
        SERVICES.map(s =>
          fetch(s.healthPath, { signal: AbortSignal.timeout(3000) })
            .then(r => r.ok)
        ),
      )
      return Object.fromEntries(
        SERVICES.map((s, i) => [s.name, results[i].status === 'fulfilled' && (results[i] as PromiseFulfilledResult<boolean>).value])
      ) as Record<string, boolean>
    },
    staleTime: 15_000,
  })
}

function DeveloperResourcesSection() {
  const { data: health } = useServiceHealth()

  return (
    <Section
      icon={FileCode}
      title="Developer Resources"
      description="API documentation, service health, and endpoint reference."
    >
      {/* Service cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {SERVICES.map(s => {
          const alive = health?.[s.name]
          return (
            <div
              key={s.name}
              className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={
                      'inline-block size-2 rounded-full ' +
                      (health === undefined
                        ? 'bg-neutral-400 dark:bg-neutral-500'
                        : alive ? 'bg-emerald-500' : 'bg-red-500')
                    }
                    title={health === undefined ? 'Checking…' : alive ? 'Healthy' : 'Unreachable'}
                  />
                  <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{s.name}</span>
                </div>
                <span className="text-xs font-mono text-neutral-500 dark:text-neutral-400">:{s.port}</span>
              </div>
              <p className="text-xs text-neutral-500 dark:text-neutral-400">{s.desc}</p>
              <a
                href={docsUrl(s.port)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium text-accent-700 dark:text-accent-400 hover:underline"
              >
                API Docs <ExternalLink size={11} />
              </a>
            </div>
          )
        })}
      </div>

      {/* Endpoint quick-reference */}
      <div>
        <label className="mb-2 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Endpoint Reference</label>
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden text-xs">
          <table className="w-full">
            <thead>
              <tr className="bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400">
                <th className="px-3 py-1.5 text-left font-medium">Service</th>
                <th className="px-3 py-1.5 text-left font-medium font-mono">Port</th>
                <th className="px-3 py-1.5 text-left font-medium">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {ENDPOINTS.map(e => (
                <tr key={e.name} className="text-neutral-700 dark:text-neutral-300">
                  <td className="px-3 py-1.5 font-medium">{e.name}</td>
                  <td className="px-3 py-1.5 font-mono text-neutral-500 dark:text-neutral-400">{e.port}</td>
                  <td className="px-3 py-1.5 text-neutral-500 dark:text-neutral-400">{e.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Section>
  )
}

// ── Remote Access section ─────────────────────────────────────────────────────

function RemoteAccessSection() {
  const [tab, setTab] = useState<'cloudflare' | 'tailscale'>('cloudflare')
  const queryClient = useQueryClient()

  const { data: status } = useQuery({
    queryKey: ['remote-access-status'],
    queryFn: getRemoteAccessStatus,
    refetchInterval: 10_000,
  })

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['remote-access-status'] })
  }, [queryClient])

  const cfStatus = status?.cloudflare ?? { configured: false, container: { name: 'cloudflared', container_name: null, status: 'not_found', health: 'unknown', running: false } }
  const tsStatus = status?.tailscale ?? { configured: false, container: { name: 'tailscale', container_name: null, status: 'not_found', health: 'unknown', running: false } }

  return (
    <Section
      icon={Globe}
      title="Remote Access"
      description="Expose Nova securely to the internet via Cloudflare Tunnel, or access from your devices via Tailscale."
    >
      <div className="flex gap-4 text-sm mb-3">
        <span className="flex items-center gap-1.5 text-neutral-500 dark:text-neutral-400">
          Cloudflare: <RemoteStatusBadge configured={cfStatus.configured} running={cfStatus.container.running} />
        </span>
        <span className="flex items-center gap-1.5 text-neutral-500 dark:text-neutral-400">
          Tailscale: <RemoteStatusBadge configured={tsStatus.configured} running={tsStatus.container.running} />
        </span>
      </div>

      <div className="border-b border-neutral-200 dark:border-neutral-800 mb-4">
        <div className="flex gap-4">
          {([
            { key: 'cloudflare' as const, label: 'Cloudflare Tunnel' },
            { key: 'tailscale' as const, label: 'Tailscale' },
          ]).map(({ key, label }) => (
            <button key={key} onClick={() => setTab(key)}
              className={`pb-2 px-1 text-sm font-medium border-b-2 transition-colors ${
                tab === key
                  ? 'border-teal-600 dark:border-teal-400 text-teal-600 dark:text-teal-400'
                  : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
              }`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-xl">
        {tab === 'cloudflare' && <CloudflareWizard status={cfStatus} onDone={refresh} />}
        {tab === 'tailscale' && <TailscaleWizard status={tsStatus} onDone={refresh} />}
      </div>
    </Section>
  )
}

// ── Recovery section ─────────────────────────────────────────────────────────

function RecoverySection() {
  return (
    <Section
      icon={Shield}
      title="Recovery & Services"
      description="Service status, database backups with restore, and factory reset. Recovery service also available directly at port 8888."
    >
      <div className="space-y-6">
        <RecoveryServiceStatus />
        <RecoveryBackupSection />
        <RecoveryFactoryReset />
      </div>
    </Section>
  )
}

// ── Settings page ─────────────────────────────────────────────────────────────

function SystemStatus() {
  const { data: queueStats, isError: queueError } = useQuery({
    queryKey: ['queue-stats'],
    queryFn: getQueueStats,
    refetchInterval: 10_000,
    staleTime: 5_000,
    retry: 1,
  })

  const { data: mcpServers = [] } = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: getMCPServers,
    refetchInterval: 15_000,
    staleTime: 10_000,
  })
  const enabledServers = mcpServers.filter((s: any) => s.enabled)
  const connectedServers = mcpServers.filter((s: any) => s.connected)
  const totalTools = connectedServers.reduce((sum: number, s: any) => sum + (s.tool_count ?? 0), 0)

  const orchestratorOk = !queueError && queueStats !== undefined

  const rows = [
    { label: 'Queue Worker', ok: orchestratorOk, detail: queueStats ? `depth ${(queueStats as any).queue_depth}` : undefined },
    { label: 'Reaper', ok: orchestratorOk, detail: 'stale-agent recovery' },
    {
      label: 'MCP Servers',
      ok: enabledServers.length > 0 && connectedServers.length === enabledServers.length,
      detail: enabledServers.length === 0
        ? 'none configured'
        : `${connectedServers.length}/${enabledServers.length} connected · ${totalTools} tools`,
    },
  ]

  return (
    <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
      {rows.map(r => (
        <div key={r.label} className="flex items-center justify-between py-2 first:pt-0 last:pb-0">
          <span className="text-sm text-neutral-700 dark:text-neutral-300">{r.label}</span>
          <div className="flex items-center gap-2">
            {r.detail && <span className="text-xs text-neutral-500 dark:text-neutral-400">{r.detail}</span>}
            <span className={`h-2 w-2 rounded-full ${r.ok ? 'bg-emerald-500' : 'bg-neutral-300 dark:bg-neutral-600'}`} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function Settings() {
  const qc = useQueryClient()

  const { data: entries = [], isLoading, error } = useQuery({
    queryKey: ['platform-config'],
    queryFn: getPlatformConfig,
    staleTime: 30_000,
  })

  const saveMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      updatePlatformConfig(key, value),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-config'] })
      qc.invalidateQueries({ queryKey: ['nova-identity'] })
    },
  })

  const handleSave = (key: string, value: string) =>
    saveMutation.mutate({ key, value })

  const novaName    = useConfigValue(entries, 'nova.name', 'Nova')
  const novaPersona = useConfigValue(entries, 'nova.persona', '')
  const novaGreeting = useConfigValue(entries, 'nova.greeting', '')
  const retentionDays = useConfigValue(entries, 'task_history_retention_days', '')

  if (isLoading) return <div className="px-4 py-6 sm:px-6 text-sm text-neutral-500 dark:text-neutral-400">Loading…</div>
  if (error)     return <div className="px-4 py-6 sm:px-6 text-sm text-red-600 dark:text-red-400">{String(error)}</div>

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Platform Settings</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Runtime configuration for this Nova instance. Changes take effect immediately —
          no restart required.
        </p>
      </div>

      {/* ── Nova Identity ─────────────────────────────────────────────────── */}
      <Section
        icon={Bot}
        title="Nova Identity"
        description="How Nova presents itself. Changes appear in the next Chat session."
      >
        <ConfigField
          label="Name"
          configKey="nova.name"
          value={novaName}
          placeholder="Nova"
          description="Shown in the dashboard header and chat UI."
          onSave={handleSave}
          saving={saveMutation.isPending}
        />

        <ConfigField
          label="Greeting message"
          configKey="nova.greeting"
          value={novaGreeting}
          placeholder="Hello! I'm Nova…"
          description="The first message shown in the Chat page before the user types anything."
          onSave={handleSave}
          saving={saveMutation.isPending}
        />

        {/* ── PERSONA — USER CONTRIBUTION POINT ────────────────────────── */}
        <ConfigField
          label="Persona / Soul"
          configKey="nova.persona"
          value={novaPersona}
          multiline
          placeholder={
            'e.g.\n' +
            'You are Nova, a focused engineering assistant. You are direct and precise — ' +
            'you never pad responses with affirmations or filler phrases. You prefer ' +
            'showing code over explaining it. When you are uncertain, you say so plainly. ' +
            'You treat the user as a peer engineer, not a customer.'
          }
          description="Personality guidelines appended to every system prompt. Defines communication style, tone, and character. Distinct from the operational system prompt — this is the 'how you talk', not 'what you do'."
          onSave={handleSave}
          saving={saveMutation.isPending}
        />
      </Section>

      {/* ── Platform Defaults ─────────────────────────────────────────────── */}
      <Section
        icon={Sliders}
        title="Platform Defaults"
        description="Fallback values used when a task or agent has no explicit configuration."
      >
        <ConfigField
          label="Task history retention (days)"
          configKey="task_history_retention_days"
          value={retentionDays}
          placeholder="0 (keep forever)"
          description="Automatically delete completed/failed/cancelled tasks older than this many days. Set to 0 or leave blank to keep forever. Common values: 7, 30, 60, 90."
          onSave={handleSave}
          saving={saveMutation.isPending}
        />
      </Section>

      {/* ── LLM Routing ─────────────────────────────────────────────────── */}
      <LLMRoutingSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />

      {/* ── Provider Status ──────────────────────────────────────────────── */}
      <ProviderStatusSection />

      {/* ── Context Budgets ────────────────────────────────────────────────── */}
      <ContextBudgetSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />

      {/* ── Admin Secret ──────────────────────────────────────────────────── */}
      <AdminSecretSection />

      {/* ── Remote Access ──────────────────────────────────────────────── */}
      <RemoteAccessSection />

      {/* ── Recovery & Services ──────────────────────────────────────────── */}
      <RecoverySection />

      {/* ── System Status ──────────────────────────────────────────────────── */}
      <Section
        icon={Activity}
        title="System Status"
        description="Live status of internal services. Auto-refreshes every 10 seconds."
      >
        <SystemStatus />
      </Section>

      {/* ── Appearance ────────────────────────────────────────────────────── */}
      <AppearanceSection />

      {/* ── Notifications ──────────────────────────────────────────────────── */}
      <NotificationsSection />

      {/* ── Developer Resources ────────────────────────────────────────────── */}
      <DeveloperResourcesSection />

      {saveMutation.isError && (
        <p className="text-sm text-red-600 dark:text-red-400">{String(saveMutation.error)}</p>
      )}
    </div>
  )
}
