import { useState } from 'react'
import { Shield } from 'lucide-react'
import { Section, Badge } from '../../components/ui'
import { useConfigValue, type ConfigSectionProps } from './shared'

const SANDBOX_TIERS = [
  {
    value: 'workspace',
    label: 'Workspace',
    desc: 'Agents can only access the mounted workspace directory. Best for working on your projects.',
    color: 'success' as const,
  },
  {
    value: 'nova',
    label: 'Nova',
    desc: 'Agents can access Nova\'s own source code for self-modification. Use when Nova needs to update itself.',
    color: 'warning' as const,
  },
  {
    value: 'host',
    label: 'Host',
    desc: 'Full filesystem access — no path restrictions. Only use for system administration tasks.',
    color: 'danger' as const,
  },
  {
    value: 'isolated',
    label: 'Isolated',
    desc: 'No filesystem or shell access. Agents can only respond with text — pure reasoning mode.',
    color: 'neutral' as const,
  },
] as const

export function SandboxSection({ entries, onSave, saving }: ConfigSectionProps) {
  const current = useConfigValue(entries, 'shell.sandbox', 'workspace')
  const [saved, setSaved] = useState(false)

  const handleChange = (value: string) => {
    onSave('shell.sandbox', JSON.stringify(value))
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  const currentTier = SANDBOX_TIERS.find(t => t.value === current) ?? SANDBOX_TIERS[0]

  return (
    <Section
      icon={Shield}
      title="Sandbox"
      description="Control what Nova's agents can access on the filesystem. Changes apply to new messages immediately."
    >
      <div>
        <div className="mb-2 flex items-center gap-2">
          <label className="text-caption font-medium text-content-secondary">Access Tier</label>
          {saved && <Badge color="success" size="sm">Saved</Badge>}
        </div>
        <div className="inline-flex flex-wrap rounded-sm border border-border p-0.5">
          {SANDBOX_TIERS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => handleChange(value)}
              disabled={saving}
              className={
                'rounded-xs px-3 py-1.5 text-caption font-medium transition-colors ' +
                (current === value
                  ? 'bg-surface-elevated text-accent'
                  : 'text-content-tertiary hover:text-content-secondary')
              }
            >
              {label}
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-caption text-content-tertiary">
          {currentTier.desc}
        </p>
      </div>
    </Section>
  )
}
