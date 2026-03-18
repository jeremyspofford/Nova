import { useState, useEffect } from 'react'
import { Save, RotateCcw, CheckCircle2, XCircle } from 'lucide-react'
import { Button, Input, Textarea } from '../../components/ui'
import type { PlatformConfigEntry } from '../../api'

// Re-export the new design system Section so existing section files can migrate gradually
export { Section } from '../../components/ui'

// ── Config entry helper ──────────────────────────────────────────────────────

export function useConfigValue(
  entries: PlatformConfigEntry[],
  key: string,
  defaultValue = '',
): string {
  const entry = entries.find(e => e.key === key)
  if (!entry || entry.value === null || entry.value === '') return defaultValue
  return String(entry.value)
}

// ── Inline editable field ────────────────────────────────────────────────────

export function ConfigField({
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

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label className="text-caption font-medium text-content-secondary">{label}</label>
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
              disabled={saving}
              loading={saving}
              icon={<Save size={10} />}
            >
              Save
            </Button>
          </div>
        )}
      </div>

      {multiline ? (
        <Textarea
          value={draft}
          onChange={e => handleChange(e.target.value)}
          placeholder={placeholder}
          rows={6}
          autoResize={false}
          description={description}
        />
      ) : (
        <Input
          value={draft}
          onChange={e => handleChange(e.target.value)}
          placeholder={placeholder}
          description={description}
        />
      )}
    </div>
  )
}

// ── Service Status Badge ─────────────────────────────────────────────────────
// Used by RemoteAccessSection and ChatIntegrationsSection to show running/stopped/unconfigured state.

export function ServiceStatusBadge({ configured, running }: { configured: boolean; running: boolean }) {
  if (running) return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 px-2 py-0.5 rounded-full">
      <CheckCircle2 size={12} /> Running
    </span>
  )
  if (configured) return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 px-2 py-0.5 rounded-full">
      <XCircle size={12} /> Stopped
    </span>
  )
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-neutral-500 dark:text-neutral-400 bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 rounded-full">
      Not configured
    </span>
  )
}

// ── Common types for section props ───────────────────────────────────────────

export interface ConfigSectionProps {
  entries: PlatformConfigEntry[]
  onSave: (key: string, value: string) => void
  saving: boolean
}
