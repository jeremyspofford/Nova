import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2, CheckCircle2, AlertCircle, HelpCircle, ChevronDown, ChevronRight, RotateCcw } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'
import { Badge } from '../../components/ui/Badge'
import type { SemanticColor } from '../../lib/design-tokens'

export interface DelegationCardProps {
  taskId: string
  description: string
  podName: string
  status:
    | 'submitted'
    | 'queued'
    | 'running'
    | 'context_running'
    | 'task_running'
    | 'guardrail_running'
    | 'review_running'
    | 'complete'
    | 'failed'
    | 'cancelled'
    | 'pending_human_review'
    | 'clarification_needed'
  output?: string
  error?: string
  startedAt?: string
}

type ResolvedState = 'running' | 'complete' | 'failed' | 'needs_input'

function resolveState(status: DelegationCardProps['status']): ResolvedState {
  switch (status) {
    case 'complete':
      return 'complete'
    case 'failed':
    case 'cancelled':
      return 'failed'
    case 'pending_human_review':
    case 'clarification_needed':
      return 'needs_input'
    default:
      return 'running'
  }
}

const stateConfig: Record<
  ResolvedState,
  {
    icon: typeof CheckCircle2
    borderClass: string
    label: string
    badgeColor: SemanticColor
    spin?: boolean
  }
> = {
  running: {
    icon: Loader2,
    borderClass: 'border-stone-600',
    label: 'Working on',
    badgeColor: 'accent',
    spin: true,
  },
  complete: {
    icon: CheckCircle2,
    borderClass: 'border-emerald-600',
    label: 'Completed',
    badgeColor: 'success',
  },
  failed: {
    icon: AlertCircle,
    borderClass: 'border-red-600',
    label: 'Failed',
    badgeColor: 'danger',
  },
  needs_input: {
    icon: HelpCircle,
    borderClass: 'border-amber-600',
    label: 'Needs input',
    badgeColor: 'warning',
  },
}

function truncate(text: string, maxLines: number): string {
  const lines = text.split('\n')
  if (lines.length <= maxLines) return text
  return lines.slice(0, maxLines).join('\n') + '\n...'
}

export function DelegationCard({
  taskId,
  description,
  podName,
  status,
  output,
  error,
  startedAt,
}: DelegationCardProps) {
  const [expanded, setExpanded] = useState(false)
  const state = resolveState(status)
  const config = stateConfig[state]
  const Icon = config.icon

  const hasDetails =
    (state === 'complete' && output) || (state === 'failed' && error)

  const elapsed = startedAt
    ? formatDistanceToNow(new Date(startedAt), { addSuffix: false })
    : null

  return (
    <div
      role="status"
      aria-live="polite"
      className={clsx(
        'bg-surface-card border rounded-lg overflow-hidden transition-colors',
        config.borderClass,
      )}
    >
      {/* Collapsed row -- always visible */}
      <button
        type="button"
        onClick={() => hasDetails && setExpanded(prev => !prev)}
        disabled={!hasDetails}
        className={clsx(
          'flex w-full items-center gap-2 px-3 py-2.5 text-left min-h-[44px]',
          hasDetails && 'cursor-pointer hover:bg-surface-card-hover',
          !hasDetails && 'cursor-default',
        )}
      >
        {hasDetails && (
          <span className="shrink-0 text-content-tertiary">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
        )}

        <Icon
          size={16}
          className={clsx(
            'shrink-0',
            state === 'running' && 'text-content-secondary animate-spin',
            state === 'complete' && 'text-emerald-400',
            state === 'failed' && 'text-red-400',
            state === 'needs_input' && 'text-amber-400',
          )}
        />

        <span className="text-compact text-content-primary truncate">
          {config.label}: {description}
        </span>

        <span className="ml-auto flex shrink-0 items-center gap-2">
          <Badge color={config.badgeColor} size="sm">
            {podName}
          </Badge>
          {elapsed && (
            <span className="font-mono text-mono-sm text-content-tertiary whitespace-nowrap">
              {elapsed}
            </span>
          )}
        </span>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-border-subtle px-3 py-2.5">
          {state === 'complete' && output && (
            <div>
              <pre className="text-compact text-content-secondary whitespace-pre-wrap break-words leading-relaxed">
                {truncate(output, 4)}
              </pre>
              <Link
                to={`/tasks`}
                className="mt-2 inline-block text-caption text-accent hover:text-accent-hover underline underline-offset-2 min-h-[44px] leading-[44px]"
              >
                View full result
              </Link>
            </div>
          )}

          {state === 'failed' && error && (
            <div>
              <p className="text-compact text-red-400 leading-relaxed">
                {error}
              </p>
              <div className="mt-2 flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    /* Retry wiring -- placeholder */
                  }}
                  className="inline-flex items-center gap-1.5 text-caption text-content-secondary hover:text-content-primary min-h-[44px] transition-colors"
                >
                  <RotateCcw size={14} />
                  Retry
                </button>
                <Link
                  to={`/tasks`}
                  className="text-caption text-accent hover:text-accent-hover underline underline-offset-2 min-h-[44px] leading-[44px]"
                >
                  View task
                </Link>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
