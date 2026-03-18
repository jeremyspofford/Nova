import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Shield, Save, RotateCcw } from 'lucide-react'
import { Section, Button, Checkbox, Badge } from '../../components/ui'
import { useConfigValue, type ConfigSectionProps } from './shared'
import { discoverModels } from '../../api'

export function GuestAccessSection({ entries, onSave, saving }: ConfigSectionProps) {
  const raw = useConfigValue(entries, 'guest_allowed_models')
  const allowedModels: string[] = raw ? JSON.parse(raw) : []

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
        <p className="text-compact text-content-tertiary">
          No models available. Configure providers first.
        </p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-caption font-medium text-content-secondary">
              Allowed Models
            </label>
            {hasChanges && (
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" onClick={handleReset} icon={<RotateCcw size={10} />}>
                  Reset
                </Button>
                <Button size="sm" onClick={handleSave} loading={saving} icon={<Save size={10} />}>
                  Save
                </Button>
              </div>
            )}
          </div>

          <div className="grid gap-2 max-h-64 overflow-y-auto">
            {allModels.map(id => (
              <Checkbox
                key={id}
                label={id}
                checked={selected.includes(id)}
                onChange={() => toggle(id)}
              />
            ))}
          </div>

          {selected.length > 0 && (
            <p className="text-caption text-content-tertiary">
              {selected.length} model{selected.length !== 1 ? 's' : ''} selected
            </p>
          )}

          {selected.length === 0 && (
            <p className="text-caption text-warning">
              No models selected -- guests will not be able to use any models.
            </p>
          )}
        </div>
      )}
    </Section>
  )
}
