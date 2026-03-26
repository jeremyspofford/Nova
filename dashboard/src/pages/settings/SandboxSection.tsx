import { useState } from 'react'
import { Shield, ChevronDown, ChevronUp } from 'lucide-react'
import { Section, Badge } from '../../components/ui'
import { useConfigValue, type ConfigSectionProps } from './shared'
import { getPods, updatePod } from '../../api'

// ── Tier definitions ────────────────────────────────────────────────────────

type TierValue = 'workspace' | 'nova' | 'host' | 'isolated'

const TIERS: {
  value: TierValue
  label: string
  tagline: string
  bullets: string[]
  ring: string
  dot: string
}[] = [
  {
    value: 'workspace',
    label: 'Workspace',
    tagline: 'Project-scoped access',
    bullets: [
      'Read & write files in /workspace',
      'Shell commands scoped to workspace',
      'Git operations scoped to workspace',
      'Blocks sudo, curl|sh, privilege escalation',
    ],
    ring: 'ring-emerald-500/60',
    dot: 'bg-emerald-500',
  },
  {
    value: 'nova',
    label: 'Nova',
    tagline: 'Self-modification access',
    bullets: [
      'Read & write Nova source code (/nova)',
      'Shell commands scoped to Nova root',
      'Git operations on Nova repo',
      'Blocks sudo, curl|sh, privilege escalation',
    ],
    ring: 'ring-amber-500/60',
    dot: 'bg-amber-500',
  },
  {
    value: 'host',
    label: 'Host',
    tagline: 'Full system access',
    bullets: [
      'Unrestricted filesystem read & write',
      'Unrestricted shell commands',
      'Unrestricted git operations',
      'Only blocks fork bombs, mkfs, dd, rm -rf /',
    ],
    ring: 'ring-red-500/60',
    dot: 'bg-red-500',
  },
  {
    value: 'isolated',
    label: 'Isolated',
    tagline: 'Pure reasoning mode',
    bullets: [
      'No filesystem access',
      'No shell commands',
      'No git operations',
      'Text responses only',
    ],
    ring: 'ring-stone-400/60 dark:ring-stone-500/60',
    dot: 'bg-stone-400 dark:bg-stone-500',
  },
]

// ── Capability comparison table ─────────────────────────────────────────────

const CAPABILITY_ROWS: { label: string; values: Record<TierValue, string> }[] = [
  { label: 'Filesystem scope', values: { workspace: '/workspace', nova: '/nova', host: '/ (entire system)', isolated: 'None' } },
  { label: 'File read & write', values: { workspace: 'Scoped', nova: 'Scoped', host: 'Unrestricted', isolated: 'Blocked' } },
  { label: 'Shell commands', values: { workspace: 'Scoped', nova: 'Scoped', host: 'Unrestricted', isolated: 'Blocked' } },
  { label: 'Git operations', values: { workspace: 'Scoped', nova: 'Scoped', host: 'Unrestricted', isolated: 'Blocked' } },
  { label: 'sudo / su', values: { workspace: 'Blocked', nova: 'Blocked', host: 'Allowed', isolated: 'N/A' } },
  { label: 'Remote exec (curl|sh)', values: { workspace: 'Blocked', nova: 'Blocked', host: 'Allowed', isolated: 'N/A' } },
  { label: 'Destructive commands', values: { workspace: 'Blocked', nova: 'Blocked', host: 'Blocked', isolated: 'N/A' } },
  { label: 'Best for', values: { workspace: 'Project work', nova: 'Self-update', host: 'Sysadmin', isolated: 'Reasoning' } },
]

function cellColor(value: string): string {
  if (value === 'Blocked' || value === 'None') return 'text-red-600 dark:text-red-400'
  if (value === 'Unrestricted' || value === 'Allowed') return 'text-amber-600 dark:text-amber-400'
  if (value === 'Scoped') return 'text-emerald-600 dark:text-emerald-400'
  if (value === 'N/A') return 'text-content-tertiary'
  return 'text-content-secondary'
}

// ── Component ───────────────────────────────────────────────────────────────

export function SandboxSection({ entries, onSave, saving }: ConfigSectionProps) {
  const current = useConfigValue(entries, 'shell.sandbox', 'workspace') as TierValue
  const [saved, setSaved] = useState(false)
  const [showTable, setShowTable] = useState(false)

  const handleSelect = async (value: TierValue) => {
    // Save global platform config (used by Chat API path)
    onSave('shell.sandbox', JSON.stringify(value))

    // Also sync to all pods so the pipeline executor picks it up.
    // NOTE(2026-03-26): The pipeline reads pod.sandbox, not platform_config.
    // This bridges the gap until per-pod sandbox controls exist in the Dashboard.
    // TODO: Other Claude sessions may also be addressing this — once per-pod
    // sandbox UI exists, this bulk-sync may need to become pod-specific.
    try {
      const pods = await getPods()
      await Promise.all(pods.map((pod) => updatePod(pod.id, { sandbox: value })))
    } catch {
      // Pod sync failed — global config still saved, executor fallback handles it
    }

    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <Section
      icon={Shield}
      title="Agent Sandbox"
      description="Control what Nova's agents can access on the filesystem. Changes apply to new messages immediately."
    >
      {/* ── Mode cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {TIERS.map((tier) => {
          const isSelected = current === tier.value
          return (
            <button
              key={tier.value}
              onClick={() => handleSelect(tier.value)}
              disabled={saving}
              className={
                'relative rounded-md border p-3 text-left transition-all ' +
                (isSelected
                  ? `ring-2 ${tier.ring} border-transparent bg-surface-elevated`
                  : 'border-border bg-surface-card hover:bg-surface-card-hover')
              }
            >
              <div className="mb-1.5 flex items-center gap-2">
                <span className={`h-2 w-2 shrink-0 rounded-full ${tier.dot}`} />
                <span className="text-compact font-semibold text-content-primary">{tier.label}</span>
                {isSelected && <Badge color="success" size="sm">Active</Badge>}
              </div>
              <p className="mb-2 text-caption text-content-tertiary">{tier.tagline}</p>
              <ul className="space-y-1">
                {tier.bullets.map((b) => (
                  <li key={b} className="flex items-start gap-1.5 text-caption text-content-secondary">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-content-tertiary" />
                    {b}
                  </li>
                ))}
              </ul>
            </button>
          )
        })}
      </div>

      {saved && (
        <p className="mt-2 text-caption text-emerald-600 dark:text-emerald-400">
          Sandbox tier saved. New messages will use this setting.
        </p>
      )}

      {/* ── Comparison table toggle ────────────────────────────────── */}
      <button
        onClick={() => setShowTable(!showTable)}
        className="mt-4 flex items-center gap-1.5 text-caption font-medium text-content-tertiary hover:text-content-secondary transition-colors"
      >
        {showTable ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        Compare all capabilities
      </button>

      {showTable && (
        <div className="mt-2 overflow-x-auto rounded-md border border-border">
          <table className="w-full text-caption">
            <thead>
              <tr className="border-b border-border bg-surface-elevated">
                <th className="px-3 py-2 text-left font-medium text-content-tertiary">Capability</th>
                {TIERS.map((t) => (
                  <th
                    key={t.value}
                    className={
                      'px-3 py-2 text-center font-medium ' +
                      (current === t.value ? 'text-accent' : 'text-content-tertiary')
                    }
                  >
                    <span className="flex items-center justify-center gap-1.5">
                      <span className={`h-1.5 w-1.5 rounded-full ${t.dot}`} />
                      {t.label}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CAPABILITY_ROWS.map((row, i) => (
                <tr key={row.label} className={i % 2 === 0 ? '' : 'bg-surface-elevated/50'}>
                  <td className="px-3 py-1.5 font-medium text-content-secondary whitespace-nowrap">{row.label}</td>
                  {TIERS.map((t) => {
                    const val = row.values[t.value]
                    return (
                      <td
                        key={t.value}
                        className={
                          'px-3 py-1.5 text-center whitespace-nowrap ' +
                          cellColor(val) +
                          (current === t.value ? ' bg-accent/5' : '')
                        }
                      >
                        {val}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  )
}
