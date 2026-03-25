import clsx from 'clsx'
import { Check, Clock, FileText, Brain, MessageSquare } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import type { IntelRecommendation } from '../../api'
import { Button } from '../ui/Button'
import { RecommendationDetail } from './RecommendationDetail'

const GRADE_STYLES: Record<string, { border: string; bg: string; text: string }> = {
  A: { border: 'border-l-green-500', bg: 'bg-green-500/15', text: 'text-green-400' },
  B: { border: 'border-l-amber-500', bg: 'bg-amber-500/15', text: 'text-amber-400' },
  C: { border: 'border-l-red-500', bg: 'bg-red-500/15', text: 'text-red-400' },
}

interface Props {
  rec: IntelRecommendation
  expanded: boolean
  onToggle: () => void
  onStatusChange: (status: string) => void
}

export function RecommendationCard({ rec, expanded, onToggle, onStatusChange }: Props) {
  const grade = GRADE_STYLES[rec.grade] ?? GRADE_STYLES.C
  const confidencePct = Math.round(rec.confidence * 100)

  return (
    <div
      className={clsx(
        'border-l-4 rounded-lg bg-surface-card border border-border-subtle',
        'dark:bg-surface-card/80 dark:backdrop-blur-md dark:border-white/[0.06]',
        grade.border,
      )}
    >
      {/* Clickable summary row */}
      <div
        className="p-4 cursor-pointer hover:bg-surface-card-hover transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-start justify-between gap-3">
          {/* Left: grade badge + info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              {/* Grade badge */}
              <span className={clsx(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded-xs text-caption font-bold',
                grade.bg, grade.text,
              )}>
                {rec.grade} <span className="font-normal text-micro opacity-80">{confidencePct}%</span>
              </span>
              {/* Category tag */}
              {rec.category && (
                <span className="text-micro px-1.5 py-0.5 rounded-xs bg-surface-elevated text-content-tertiary font-medium">
                  {rec.category}
                </span>
              )}
              {/* Truncated ID */}
              <span className="text-micro text-content-tertiary font-mono">
                {rec.id.slice(0, 8)}
              </span>
            </div>

            {/* Title */}
            <div className="text-sm font-semibold text-content-primary truncate">
              {rec.title}
            </div>

            {/* Summary */}
            <p className="text-caption text-content-secondary line-clamp-2 mt-0.5">
              {rec.summary}
            </p>

            {/* Bottom row: badges + time */}
            <div className="flex items-center gap-3 mt-2 text-micro text-content-tertiary">
              {(rec.source_count ?? 0) > 0 && (
                <span className="inline-flex items-center gap-1">
                  <FileText size={10} />
                  {rec.source_count} sources
                </span>
              )}
              {(rec.memory_count ?? 0) > 0 && (
                <span className="inline-flex items-center gap-1">
                  <Brain size={10} />
                  {rec.memory_count} memories
                </span>
              )}
              {(rec.comment_count ?? 0) > 0 && (
                <span className="inline-flex items-center gap-1">
                  <MessageSquare size={10} />
                  {rec.comment_count}
                </span>
              )}
              <span className="inline-flex items-center gap-1">
                <Clock size={10} />
                {formatDistanceToNow(new Date(rec.created_at), { addSuffix: true })}
              </span>
            </div>
          </div>

          {/* Right: action buttons (pending only) */}
          {rec.status === 'pending' && (
            <div
              className="flex items-center gap-1 shrink-0"
              onClick={e => e.stopPropagation()}
            >
              <Button
                variant="ghost"
                size="sm"
                icon={<Check size={14} />}
                onClick={() => onStatusChange('approved')}
              >
                Approve
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<Clock size={14} />}
                onClick={() => onStatusChange('deferred')}
              >
                Defer
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-border-subtle">
          <RecommendationDetail id={rec.id} onStatusChange={onStatusChange} />
        </div>
      )}
    </div>
  )
}
