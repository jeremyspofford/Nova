import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, RotateCcw, Bot, Sliders, Palette, Moon, Sun, Monitor, FileCode, ExternalLink, Activity, Gauge, ShieldCheck } from 'lucide-react'
import { getPlatformConfig, updatePlatformConfig, getProviderStatus, testProvider, getAdminSecret, setAdminSecret, type PlatformConfigEntry, type ProviderStatus } from '../api'
import { useTheme } from '../stores/theme-store'
import { accentPalettes, themePresets } from '../lib/color-palettes'
import Card from '../components/Card'

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

// ── Developer Resources section ───────────────────────────────────────────────

const SERVICES = [
  { name: 'Orchestrator',   port: 8000, healthPath: '/api/health/live', desc: 'Agent lifecycle, pipeline execution, task queue' },
  { name: 'LLM Gateway',    port: 8001, healthPath: '/v1/health/live',  desc: 'Multi-provider model routing, completions, embeddings' },
  { name: 'Memory Service', port: 8002, healthPath: '/mem/health/live', desc: 'Semantic memory storage and hybrid retrieval' },
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
      <div className="grid gap-3 sm:grid-cols-3">
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

// ── Settings page ─────────────────────────────────────────────────────────────

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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['platform-config'] }),
  })

  const handleSave = (key: string, value: string) =>
    saveMutation.mutate({ key, value })

  const novaName    = useConfigValue(entries, 'nova.name', 'Nova')
  const novaPersona = useConfigValue(entries, 'nova.persona', '')
  const novaGreeting = useConfigValue(entries, 'nova.greeting', '')
  const defaultModel = useConfigValue(entries, 'nova.default_model', '')

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
          label="Default model override"
          configKey="nova.default_model"
          value={defaultModel}
          placeholder="Leave blank to use the NOVA_DEFAULT_MODEL env var"
          description="When set, overrides the NOVA_DEFAULT_MODEL environment variable without a restart. Use the exact model ID from the Models page (e.g. claude-sonnet-4-5)."
          onSave={handleSave}
          saving={saveMutation.isPending}
        />
      </Section>

      {/* ── Provider Status ──────────────────────────────────────────────── */}
      <ProviderStatusSection />

      {/* ── Context Budgets ────────────────────────────────────────────────── */}
      <ContextBudgetSection entries={entries} onSave={handleSave} saving={saveMutation.isPending} />

      {/* ── Admin Secret ──────────────────────────────────────────────────── */}
      <AdminSecretSection />

      {/* ── Appearance ────────────────────────────────────────────────────── */}
      <AppearanceSection />

      {/* ── Developer Resources ────────────────────────────────────────────── */}
      <DeveloperResourcesSection />

      {saveMutation.isError && (
        <p className="text-sm text-red-600 dark:text-red-400">{String(saveMutation.error)}</p>
      )}
    </div>
  )
}
