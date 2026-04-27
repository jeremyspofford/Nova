import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, X as XIcon } from 'lucide-react'
import { apiFetch } from '../api'
import { Button } from './ui/Button'

/**
 * Minimal goal shape needed to render the maturation detail panel. Wider
 * Goal types (e.g. the canonical `Goal` from `../api`) are assignable to this.
 */
export interface GoalForMaturation {
  id: string
  maturation_status?: string | null
  scope_analysis?: unknown | null
  spec?: string | null
}

/**
 * Renders the scope analysis, generated spec, and approve/reject controls
 * for a goal that is currently in the maturation pipeline.
 *
 * - Scope analysis is shown when present (any non-null value).
 * - Spec is shown when present (non-empty string).
 * - Approve/Reject controls are shown only when `maturation_status === 'review'`.
 *
 * Rejection requires non-empty feedback so the maturation loop has signal to
 * re-scope on. Both mutations invalidate the `['goals']` query key so the
 * parent list refetches when the cortex maturation worker advances state.
 */
export function GoalMaturationDetail({
  goal,
  onSuccess,
  onError,
}: {
  goal: GoalForMaturation
  onSuccess?: (message: string) => void
  onError?: (message: string) => void
}) {
  const qc = useQueryClient()
  const [feedback, setFeedback] = useState('')
  const [showRejectForm, setShowRejectForm] = useState(false)

  const approve = useMutation({
    mutationFn: () =>
      apiFetch<void>(`/api/v1/goals/${goal.id}/approve-spec`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      onSuccess?.('Spec approved.')
    },
    onError: (err) => onError?.(`Failed to approve: ${err}`),
  })

  const reject = useMutation({
    mutationFn: (text: string) =>
      apiFetch<void>(`/api/v1/goals/${goal.id}/reject-spec`, {
        method: 'POST',
        body: JSON.stringify({ feedback: text }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      setFeedback('')
      setShowRejectForm(false)
      onSuccess?.('Spec rejected. Goal will re-scope.')
    },
    onError: (err) => onError?.(`Failed to reject: ${err}`),
  })

  const hasScope = goal.scope_analysis != null
  const hasSpec = !!goal.spec
  const inReview = goal.maturation_status === 'review'

  if (!hasScope && !hasSpec && !inReview) return null

  return (
    <div className="space-y-3">
      {hasScope && (
        <div>
          <span className="text-caption font-medium text-content-secondary">Scope Analysis</span>
          <div className="mt-1 p-2.5 rounded-sm bg-surface-elevated text-caption text-content-secondary overflow-x-auto">
            <pre className="whitespace-pre-wrap font-mono text-[11px]">
              {typeof goal.scope_analysis === 'string'
                ? goal.scope_analysis
                : JSON.stringify(goal.scope_analysis, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {hasSpec && (
        <div>
          <span className="text-caption font-medium text-content-secondary">Spec</span>
          <div className="mt-1 p-2.5 rounded-sm bg-surface-elevated text-caption text-content-secondary overflow-x-auto">
            <pre className="whitespace-pre-wrap font-mono text-[11px]">{goal.spec}</pre>
          </div>
        </div>
      )}

      {inReview && (
        <div className="flex items-start gap-2">
          <Button
            variant="primary"
            size="sm"
            icon={<Check size={14} />}
            onClick={() => approve.mutate()}
            loading={approve.isPending}
          >
            Approve Spec
          </Button>
          {!showRejectForm ? (
            <Button
              variant="danger"
              size="sm"
              icon={<XIcon size={14} />}
              onClick={() => setShowRejectForm(true)}
            >
              Reject Spec
            </Button>
          ) : (
            <div className="flex-1 space-y-2">
              <input
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Feedback for rejection..."
                className="h-8 w-full rounded-sm border border-border bg-surface-input px-2.5 text-caption text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
                autoFocus
              />
              <div className="flex gap-1.5">
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => reject.mutate(feedback)}
                  loading={reject.isPending}
                  disabled={!feedback.trim()}
                >
                  Confirm Reject
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowRejectForm(false)
                    setFeedback('')
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
