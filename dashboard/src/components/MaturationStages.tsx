import clsx from 'clsx'
import { Check } from 'lucide-react'

const STAGES = ['triaging', 'scoping', 'speccing', 'review', 'building', 'waiting', 'verifying'] as const
type Stage = typeof STAGES[number]

interface Props {
  current: Stage | null | undefined
  compact?: boolean
}

const LABEL: Record<Stage, string> = {
  triaging: 'Triage',
  scoping: 'Scope',
  speccing: 'Spec',
  review: 'Review',
  building: 'Build',
  waiting: 'Wait',
  verifying: 'Verify',
}

export function MaturationStages({ current, compact = false }: Props) {
  const currentIdx = current ? STAGES.indexOf(current) : -1

  return (
    <div className={clsx('flex items-center gap-1', compact ? 'text-[10px]' : 'text-xs')}>
      {STAGES.map((stage, idx) => {
        const done = idx < currentIdx
        const active = idx === currentIdx
        return (
          <div key={stage} className="flex items-center gap-1">
            <span
              className={clsx(
                'inline-flex items-center justify-center rounded-full',
                compact ? 'h-3 w-3 text-[8px]' : 'h-5 w-5 text-[10px]',
                done && 'bg-emerald-500 text-white',
                active && 'bg-amber-400 text-stone-900 animate-pulse',
                !done && !active && 'bg-stone-700 text-stone-400',
              )}
            >
              {done ? <Check className="h-2.5 w-2.5" /> : idx + 1}
            </span>
            {!compact && <span className={clsx(active ? 'text-content-primary font-medium' : 'text-content-tertiary')}>{LABEL[stage]}</span>}
            {idx < STAGES.length - 1 && <span className="text-stone-700">{compact ? '·' : '→'}</span>}
          </div>
        )
      })}
    </div>
  )
}
