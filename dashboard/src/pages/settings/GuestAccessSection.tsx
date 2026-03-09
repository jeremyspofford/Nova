import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Shield, Save, RotateCcw } from 'lucide-react'
import { Section, useConfigValue, type ConfigSectionProps } from './shared'
import { discoverModels } from '../../api'

export function GuestAccessSection({ entries, onSave, saving }: ConfigSectionProps) {
  const raw = useConfigValue(entries, 'guest_allowed_models')
  const allowedModels: string[] = raw ? JSON.parse(raw) : []

  // Fetch available models from all providers
  const { data: providers } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
  })

  const allModels = (providers ?? [])
    .filter(p => p.available)
    .flatMap(p => p.models.filter(m => m.registered).map(m => m.id))

  const [selected, setSelected] = useState<string[]>(allowedModels)

  useEffect(() => {
    setSelected(raw ? JSON.parse(raw) : [])
  }, [raw])

  const toggle = (modelId: string) => {
    setSelected(prev =>
      prev.includes(modelId)
        ? prev.filter(m => m !== modelId)
        : [...prev, modelId]
    )
  }

  const handleSave = () => {
    onSave('guest_allowed_models', JSON.stringify(selected))
  }

  const handleReset = () => {
    setSelected(raw ? JSON.parse(raw) : [])
  }

  const hasChanges = JSON.stringify([...selected].sort()) !== JSON.stringify([...allowedModels].sort())

  return (
    <Section
      icon={Shield}
      title="Guest Access"
      description="Configure which models are available to guest users. Guests can only chat with models in this list."
    >
      {allModels.length === 0 ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          No models available. Configure providers first.
        </p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
              Allowed Models
            </label>
            {hasChanges && (
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

          <div className="grid gap-2 max-h-64 overflow-y-auto">
            {allModels.map(id => (
              <label key={id} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={selected.includes(id)}
                  onChange={() => toggle(id)}
                  className="rounded border-neutral-300 dark:border-neutral-600"
                />
                <span className="text-neutral-700 dark:text-neutral-300 font-mono text-xs">{id}</span>
              </label>
            ))}
          </div>

          {selected.length > 0 && (
            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              {selected.length} model{selected.length !== 1 ? 's' : ''} selected
            </p>
          )}

          {selected.length === 0 && (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              No models selected — guests will not be able to use any models.
            </p>
          )}
        </div>
      )}
    </Section>
  )
}
