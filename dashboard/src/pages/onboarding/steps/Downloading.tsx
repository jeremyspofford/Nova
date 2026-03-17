import { useEffect, useState, useRef, useCallback } from 'react'
import { Loader2, Check, AlertTriangle, RotateCcw } from 'lucide-react'
import { recoveryFetch, getBackendStatus, type BackendStatus } from '../../../api-recovery'

interface Props {
  backend: string
  model: string
  onNext: () => void
}

type Phase = 'starting' | 'downloading' | 'loading' | 'ready' | 'error'

const phaseLabels: Record<Phase, string> = {
  starting: 'Starting backend...',
  downloading: 'Downloading model...',
  loading: 'Loading model into memory...',
  ready: 'Ready!',
  error: 'Something went wrong',
}

const phaseOrder: Phase[] = ['starting', 'downloading', 'loading', 'ready']

function mapStateToPhase(status: BackendStatus): Phase {
  const state = status.state?.toLowerCase() ?? ''
  const step = status.switch_progress?.step?.toLowerCase() ?? ''

  if (state === 'ready') return 'ready'
  if (step.includes('download') || step.includes('pull')) return 'downloading'
  if (step.includes('load') || state === 'loading') return 'loading'
  if (state === 'starting' || state === 'pulling' || step.includes('start')) return 'starting'
  if (state === 'error' || state === 'failed') return 'error'
  return 'starting'
}

export function Downloading({ backend, model, onNext }: Props) {
  const [phase, setPhase] = useState<Phase>('starting')
  const [detail, setDetail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const retry = useCallback(() => {
    setError(null)
    setPhase('starting')
    setDetail('')
    setAttempt(a => a + 1)
  }, [])

  useEffect(() => {
    async function startBackend() {
      try {
        // For cloud-only, just complete immediately
        if (backend === 'cloud') {
          setPhase('ready')
          return
        }

        // Start the backend (returns 202 immediately)
        await recoveryFetch(`/api/v1/recovery/inference/backend/${backend}/start`, {
          method: 'POST',
        })

        // For Ollama, trigger model pull after backend accepts
        if (backend === 'ollama') {
          setPhase('downloading')
          setDetail(`Pulling ${model}...`)
          try {
            await recoveryFetch(`/api/v1/recovery/inference/backend/${backend}/switch-model`, {
              method: 'POST',
              body: JSON.stringify({ model }),
            })
          } catch {
            // switch-model may return before completion; polling will track progress
          }
        }

        // For vLLM, the start already handles model loading via env var
        if (backend === 'vllm') {
          setPhase('downloading')
          setDetail(`Loading ${model}...`)
        }

        // Start polling
        pollRef.current = setInterval(async () => {
          try {
            const status = await getBackendStatus()
            const newPhase = mapStateToPhase(status)
            setPhase(newPhase)
            if (status.switch_progress?.detail) {
              setDetail(status.switch_progress.detail)
            }
            if (newPhase === 'ready') {
              if (pollRef.current) clearInterval(pollRef.current)
            }
            if (newPhase === 'error') {
              if (pollRef.current) clearInterval(pollRef.current)
              setError(status.switch_progress?.detail ?? 'Backend failed to start')
            }
          } catch {
            // Ignore transient poll failures
          }
        }, 2000)
      } catch (e) {
        setPhase('error')
        setError(e instanceof Error ? e.message : 'Failed to start backend')
      }
    }

    startBackend()

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [backend, model, attempt])

  // Auto-advance when ready
  useEffect(() => {
    if (phase === 'ready') {
      const t = setTimeout(onNext, 1500)
      return () => clearTimeout(t)
    }
  }, [phase, onNext])

  return (
    <div className="flex flex-col items-center py-16 px-4">
      <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-2">
        Setting Up
      </h2>
      <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-10 text-center max-w-md">
        {backend === 'cloud' ? 'Configuring cloud providers...' : `Installing ${model} via ${backend}...`}
      </p>

      {/* Progress steps */}
      <div className="w-full max-w-xs space-y-4">
        {phaseOrder.map((p, i) => {
          const currentIdx = phaseOrder.indexOf(phase)
          const isDone = i < currentIdx || phase === 'ready'
          const isCurrent = i === currentIdx && phase !== 'ready' && phase !== 'error'

          return (
            <div key={p} className="flex items-center gap-3">
              <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
                isDone
                  ? 'bg-teal-500'
                  : isCurrent
                    ? 'bg-teal-500/20'
                    : 'bg-neutral-200 dark:bg-neutral-800'
              }`}>
                {isDone ? (
                  <Check className="w-3.5 h-3.5 text-white" />
                ) : isCurrent ? (
                  <Loader2 className="w-3.5 h-3.5 text-teal-500 animate-spin" />
                ) : (
                  <div className="w-2 h-2 rounded-full bg-neutral-400 dark:bg-neutral-600" />
                )}
              </div>
              <span className={`text-sm ${
                isDone
                  ? 'text-neutral-500 dark:text-neutral-400'
                  : isCurrent
                    ? 'text-neutral-900 dark:text-neutral-100 font-medium'
                    : 'text-neutral-400 dark:text-neutral-600'
              }`}>
                {phaseLabels[p]}
              </span>
            </div>
          )
        })}
      </div>

      {/* Detail text */}
      {detail && phase !== 'ready' && phase !== 'error' && (
        <p className="mt-6 text-xs text-neutral-400 dark:text-neutral-500 text-center max-w-sm truncate">
          {detail}
        </p>
      )}

      {/* Error state */}
      {error && (
        <div className="mt-6 flex flex-col items-center">
          <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400 mb-2">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-sm font-medium">Error</span>
          </div>
          <p className="text-xs text-neutral-500 dark:text-neutral-400 text-center max-w-sm mb-4">
            {error}
          </p>
          <button
            onClick={retry}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Retry
          </button>
        </div>
      )}
    </div>
  )
}
