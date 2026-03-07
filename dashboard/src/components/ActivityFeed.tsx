import { useState, useEffect } from 'react'
import { Check, Loader2, ChevronRight } from 'lucide-react'
import type { ActivityStep } from '../stores/chat-store'

interface Props {
  steps: ActivityStep[]
  collapsed: boolean
  isStreaming: boolean
}

function ElapsedTimer({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(id)
  }, [])
  return <span>{((now - startedAt) / 1000).toFixed(1)}s</span>
}

const stepLabels: Record<string, string> = {
  classifying: 'Classified',
  memory: 'Memory retrieval',
  model: 'Selected',
  generating: 'Generating response',
}

function StepRow({ step }: { step: ActivityStep }) {
  const isDone = step.state === 'done'
  const label = stepLabels[step.step] ?? step.step

  return (
    <div className="flex items-center gap-1.5 py-0.5">
      {isDone ? (
        <Check size={12} className="text-emerald-500 shrink-0" />
      ) : (
        <Loader2 size={12} className="text-neutral-400 animate-spin shrink-0" />
      )}
      <span className="text-neutral-500 dark:text-neutral-400">
        {label}{step.detail ? `: ${step.detail}` : ''}
      </span>
      {isDone && step.elapsed_ms != null && (
        <span className="text-neutral-400 dark:text-neutral-600 ml-auto tabular-nums">
          {(step.elapsed_ms / 1000).toFixed(1)}s
        </span>
      )}
      {!isDone && step.startedAt && (
        <span className="text-neutral-400 dark:text-neutral-600 ml-auto tabular-nums">
          <ElapsedTimer startedAt={step.startedAt} />
        </span>
      )}
    </div>
  )
}

export function ActivityFeed({ steps, collapsed, isStreaming }: Props) {
  const [expanded, setExpanded] = useState(false)

  // Build collapsed summary
  const model = steps.find(s => s.step === 'model')?.detail
    ?? steps.find(s => s.step === 'generating')?.model
  const memStep = steps.find(s => s.step === 'memory' && s.state === 'done')
  const totalMs = steps
    .filter(s => s.state === 'done' && s.elapsed_ms != null)
    .reduce((max, s) => Math.max(max, s.elapsed_ms!), 0)

  if (collapsed && !expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="flex items-center gap-1 text-xs text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300 transition-colors mb-1.5"
      >
        <ChevronRight size={11} className="shrink-0" />
        <span className="tabular-nums">
          {[
            model,
            memStep?.detail,
            totalMs > 0 ? `${(totalMs / 1000).toFixed(1)}s` : null,
          ].filter(Boolean).join(' \u00b7 ')}
        </span>
      </button>
    )
  }

  return (
    <div
      className="text-xs mb-1.5 cursor-pointer"
      onClick={collapsed ? () => setExpanded(false) : undefined}
    >
      {steps.map(s => (
        <StepRow key={s.step} step={s} />
      ))}
    </div>
  )
}
