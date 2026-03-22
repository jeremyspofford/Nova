import { Bug } from 'lucide-react'
import { Section } from '../../components/ui'
import { useDebug, type DebugLevel } from '../../stores/debug-store'

const LEVELS: { value: DebugLevel; label: string; description: string }[] = [
  { value: 'off', label: 'Off', description: 'Production mode — no debug features' },
  { value: 'verbose', label: 'Verbose', description: 'Friction logger, request tracing, timing overlays' },
]

export function DebugSection() {
  const { level, setLevel } = useDebug()

  return (
    <Section title="Debug" icon={Bug} description="Developer and dogfooding tools. Off by default in production.">
      <div className="space-y-2">
        {LEVELS.map(opt => (
          <label
            key={opt.value}
            className="flex items-start gap-3 p-3 rounded-lg border border-border cursor-pointer transition-colors duration-fast hover:bg-surface-card-hover has-[:checked]:border-accent has-[:checked]:bg-accent-dim"
          >
            <input
              type="radio"
              name="debug-level"
              value={opt.value}
              checked={level === opt.value}
              onChange={() => setLevel(opt.value)}
              className="mt-0.5 accent-[var(--accent-600)]"
            />
            <div>
              <div className="text-compact font-medium text-content-primary">{opt.label}</div>
              <div className="text-caption text-content-tertiary">{opt.description}</div>
            </div>
          </label>
        ))}
      </div>
    </Section>
  )
}
