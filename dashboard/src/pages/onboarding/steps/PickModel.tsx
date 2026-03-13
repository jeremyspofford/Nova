import { useEffect, useState } from 'react'
import { Loader2, AlertTriangle } from 'lucide-react'
import { getRecommendedModels, type RecommendedModel } from '../../../api-recovery'

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
        // Filter out embedding models
        const filtered = list.filter(m => m.category !== 'embedding')
        setModels(filtered)
        // Pre-select first model if nothing selected
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
        <Loader2 className="w-8 h-8 text-teal-500 animate-spin mb-4" />
        <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading recommended models...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
        <AlertTriangle className="w-10 h-10 text-amber-500 mb-4" />
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          Failed to load models: {error}
        </p>
        <button
          onClick={onBack}
          className="text-sm text-teal-600 hover:text-teal-700"
        >
          Go back
        </button>
      </div>
    )
  }

  if (models.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          No compatible models found for this configuration.
        </p>
        <button
          onClick={onBack}
          className="text-sm text-teal-600 hover:text-teal-700"
        >
          Go back and change engine
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center py-12 px-4">
      <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-2">
        Pick a Model
      </h2>
      <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-6 text-center max-w-md">
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
              className={`w-full text-left rounded-lg border p-4 transition-colors ${
                isSelected
                  ? 'border-teal-500 bg-teal-500/5'
                  : 'border-neutral-200 dark:border-neutral-800 hover:border-neutral-300 dark:hover:border-neutral-700'
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate">
                    {model.name}
                  </p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                    {model.description}
                  </p>
                </div>
                <span className="text-xs text-neutral-400 shrink-0 mt-0.5">
                  {model.min_vram_gb} GB
                </span>
              </div>
            </button>
          )
        })}
      </div>

      <div className="flex gap-3 mt-8">
        <button
          onClick={onBack}
          className="px-5 py-2.5 rounded-lg border border-neutral-200 dark:border-neutral-800 text-sm text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-900 transition-colors"
        >
          Back
        </button>
        <button
          onClick={onNext}
          disabled={!selectedModel}
          className="px-6 py-2.5 rounded-lg bg-teal-600 hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
        >
          Continue
        </button>
      </div>
    </div>
  )
}
