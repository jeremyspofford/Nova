import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, RotateCcw, Bot, Sliders } from 'lucide-react'
import { getPlatformConfig, updatePlatformConfig, type PlatformConfigEntry } from '../api'

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
    <div className="rounded-xl border border-stone-200 bg-white overflow-hidden">
      <div className="border-b border-stone-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <Icon size={15} className="text-teal-700" />
          <h2 className="text-sm font-semibold text-stone-900">{title}</h2>
        </div>
        <p className="mt-0.5 text-xs text-stone-400">{description}</p>
      </div>
      <div className="px-5 py-4 space-y-4">{children}</div>
    </div>
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
    'w-full rounded-lg border border-stone-300 bg-stone-50 px-3 py-2 text-sm text-stone-900 ' +
    'placeholder:text-stone-400 outline-none focus:border-teal-600 disabled:opacity-50 transition-colors'

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-xs font-medium text-stone-600">{label}</label>
        {dirty && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleReset}
              className="flex items-center gap-1 text-xs text-stone-400 hover:text-stone-700"
            >
              <RotateCcw size={10} /> Reset
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-1 rounded-md bg-teal-700 px-2.5 py-1 text-xs text-white hover:bg-teal-500 disabled:opacity-40"
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
        <p className="mt-1 text-xs text-stone-400">{description}</p>
      )}
    </div>
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

  if (isLoading) return <div className="p-6 text-sm text-stone-400">Loading…</div>
  if (error)     return <div className="p-6 text-sm text-red-600">{String(error)}</div>

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-stone-900">Platform Settings</h1>
        <p className="mt-1 text-sm text-stone-400">
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

      {saveMutation.isError && (
        <p className="text-sm text-red-600">{String(saveMutation.error)}</p>
      )}
    </div>
  )
}
