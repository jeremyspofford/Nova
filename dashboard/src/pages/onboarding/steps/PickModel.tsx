import { useEffect, useState } from 'react'
import { Loader2, AlertTriangle } from 'lucide-react'
import { getRecommendedModels, type RecommendedModel } from '../../../api-recovery'
import { Button } from '../../../components/ui'
import clsx from 'clsx'

interface Props {
  backend: string
  maxVramGb: number
  selectedModel: string
  onSelect: (modelId: string) => void
  onNext: () => void
  onBack: () => void
}

export function PickModel({ backend, maxVramGb, selectedModel, onSelect, onNext, onBack }: Props) {
  const [models, setModels] = useState<RecommendedModel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getRecommendedModels(backend, maxVramGb || undefined)
      .then(list => {
        const filtered = list.filter(m => m.category !== 'embedding')
        setModels(filtered)
        if (filtered.length > 0 && !selectedModel) {
          const id = backend === 'ollama' && filtered[0].ollama_id ? filtered[0].ollama_id : filtered[0].id
          onSelect(id)
        }
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [backend, maxVramGb]) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Loader2 className="w-8 h-8 text-accent animate-spin mb-4" />
        <p className="text-compact text-content-secondary">Loading recommended models...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
        <AlertTriangle className="w-10 h-10 text-warning mb-4" />
        <p className="text-compact text-content-secondary mb-4">
          Failed to load models: {error}
        </p>
        <button
          onClick={onBack}
          className="text-compact text-accent hover:text-accent-hover transition-colors"
        >
          Go back
        </button>
      </div>
    )
  }

  if (models.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
        <p className="text-compact text-content-secondary mb-4">
          No compatible models found for this configuration.
        </p>
        <button
          onClick={onBack}
          className="text-compact text-accent hover:text-accent-hover transition-colors"
        >
          Go back and change engine
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center py-12 px-6">
      <h2 className="text-h3 text-content-primary mb-2">
        Pick a Model
      </h2>
      <p className="text-compact text-content-secondary mb-6 text-center max-w-md">
        Choose a model to download. You can always change this later in Settings.
      </p>

      <div className="w-full max-w-sm space-y-3 max-h-80 overflow-y-auto custom-scrollbar">
        {models.map(model => {
          const modelId = backend === 'ollama' && model.ollama_id ? model.ollama_id : model.id
          const isSelected = selectedModel === modelId

          return (
            <button
              key={model.id}
              onClick={() => onSelect(modelId)}
              className={clsx(
                'w-full text-left rounded-lg border p-4 transition-colors',
                isSelected
                  ? 'border-accent bg-accent/5'
                  : 'border-border-subtle hover:border-border',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-compact font-medium text-content-primary truncate">
                    {model.name}
                  </p>
                  <p className="text-caption text-content-secondary mt-1">
                    {model.description}
                  </p>
                </div>
                <span className="text-caption text-content-tertiary shrink-0 mt-0.5">
                  {model.min_vram_gb} GB
                </span>
              </div>
            </button>
          )
        })}
      </div>

      <div className="flex gap-3 mt-8">
        <Button variant="outline" onClick={onBack}>Back</Button>
        <Button onClick={onNext} disabled={!selectedModel}>Continue</Button>
      </div>
    </div>
  )
}
