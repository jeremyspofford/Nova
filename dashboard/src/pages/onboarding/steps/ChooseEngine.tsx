import { Server, Cloud, Cpu } from 'lucide-react'
import type { HardwareInfo } from '../../../api-recovery'

type Engine = 'vllm' | 'ollama' | 'cloud'

interface Props {
  hardware: HardwareInfo
  selected: Engine
  onSelect: (engine: Engine) => void
  onNext: () => void
  onBack: () => void
}

const engines: Array<{
  id: Engine
  label: string
  description: string
  icon: typeof Server
  requiresGpu: boolean
  minVram?: number
}> = [
  {
    id: 'vllm',
    label: 'vLLM',
    description: 'High-performance GPU inference. Best throughput for NVIDIA GPUs.',
    icon: Server,
    requiresGpu: true,
    minVram: 8,
  },
  {
    id: 'ollama',
    label: 'Ollama',
    description: 'Easy local inference. Works on CPU and GPU. Great for getting started.',
    icon: Cpu,
    requiresGpu: false,
  },
  {
    id: 'cloud',
    label: 'Cloud Only',
    description: 'Use cloud LLM providers (Anthropic, OpenAI, etc). No local setup needed.',
    icon: Cloud,
    requiresGpu: false,
  },
]

function getRecommended(hardware: HardwareInfo): Engine {
  const totalVram = hardware.gpus.reduce((s, g) => s + g.vram_gb, 0)
  if (totalVram >= 8) return 'vllm'
  return 'ollama'
}

export function ChooseEngine({ hardware, selected, onSelect, onNext, onBack }: Props) {
  const recommended = getRecommended(hardware)
  const hasGpu = hardware.gpus.length > 0
  const totalVram = hardware.gpus.reduce((s, g) => s + g.vram_gb, 0)

  const available = engines.filter(e => {
    if (e.requiresGpu && !hasGpu) return false
    if (e.minVram && totalVram < e.minVram) return false
    return true
  })

  return (
    <div className="flex flex-col items-center py-12 px-4">
      <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-2">
        Choose Your Engine
      </h2>
      <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-6 text-center max-w-md">
        Select how Nova should run AI models.
      </p>

      <div className="w-full max-w-sm space-y-3">
        {available.map(engine => {
          const isSelected = selected === engine.id
          const isRecommended = engine.id === recommended
          const Icon = engine.icon

          return (
            <button
              key={engine.id}
              onClick={() => onSelect(engine.id)}
              className={`w-full text-left rounded-lg border p-4 transition-colors ${
                isSelected
                  ? 'border-teal-500 bg-teal-500/5'
                  : 'border-neutral-200 dark:border-neutral-800 hover:border-neutral-300 dark:hover:border-neutral-700'
              }`}
            >
              <div className="flex items-start gap-3">
                <Icon className={`w-5 h-5 mt-0.5 shrink-0 ${isSelected ? 'text-teal-500' : 'text-neutral-400'}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                      {engine.label}
                    </span>
                    {isRecommended && (
                      <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-teal-500/10 text-teal-600 dark:text-teal-400">
                        Recommended
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                    {engine.description}
                  </p>
                </div>
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
          className="px-6 py-2.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium transition-colors"
        >
          Continue
        </button>
      </div>
    </div>
  )
}
