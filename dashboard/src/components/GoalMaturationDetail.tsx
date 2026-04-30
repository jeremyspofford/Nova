import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, X as XIcon } from 'lucide-react'
import { apiFetch } from '../api'
import { Button } from './ui/Button'

/**
 * Minimal goal shape needed to render the maturation detail panel. Wider
 * Goal types (e.g. the canonical `Goal` from `../api`) are assignable to this.
 */
export interface SpecChild {
  title: string
  description?: string
  hint?: string
  estimated_cost_usd?: number
  depends_on?: number[]
  estimated_complexity?: string
}

export interface VerificationCommand {
  cmd: string
  cwd?: string | null
  timeout_s?: number
}

export interface SuccessCriterion {
  statement: string
  check: string
  check_arg: string
}

export interface GoalForMaturation {
  id: string
  maturation_status?: string | null
  scope_analysis?: unknown | null
  spec?: string | null
  spec_children?: SpecChild[] | null
  verification_commands?: VerificationCommand[] | null
  success_criteria_structured?: SuccessCriterion[] | null
  review_policy?: string
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
      apiFetch<void>(`/api/v1/goals/${goal.id}/review/approve`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      onSuccess?.('Spec approved.')
    },
    onError: (err) => onError?.(`Failed to approve: ${err}`),
  })

  const reject = useMutation({
    mutationFn: (text: string) =>
      apiFetch<void>(`/api/v1/goals/${goal.id}/review/reject`, {
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
        <div className="space-y-3">
          <div className="text-xs text-content-tertiary">
            <strong className="text-content-secondary">Why review?</strong>{' '}
            {explainPolicy(goal)}
          </div>

          {goal.spec_children && goal.spec_children.length > 0 && (
            <div>
              <div className="text-xs uppercase text-content-tertiary tracking-wide mb-2">Children Cortex plans to spawn</div>
              <div className="space-y-1.5">
                {goal.spec_children.map((c, i) => (
                  <div key={i} className="rounded-md bg-surface-card-hover px-3 py-2 text-xs">
                    <div className="font-mono font-medium text-content-primary">
                      {i + 1}. {c.title}
                    </div>
                    <div className="text-content-tertiary mt-0.5">hint: {c.hint || c.description}</div>
                    <div className="flex items-center gap-2 mt-1 text-content-tertiary">
                      <span>${(c.estimated_cost_usd || 0).toFixed(2)}</span>
                      <span>·</span>
                      <span>{c.estimated_complexity || 'unknown'}</span>
                      {c.depends_on && c.depends_on.length > 0 && (
                        <>
                          <span>·</span>
                          <span>depends on: {c.depends_on.map((d) => `#${d + 1}`).join(', ')}</span>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {goal.verification_commands && goal.verification_commands.length > 0 && (
            <div>
              <div className="text-xs uppercase text-content-tertiary tracking-wide mb-2">Verification commands</div>
              <ul className="text-xs font-mono space-y-1">
                {goal.verification_commands.map((v, i) => (
                  <li key={i} className="text-content-secondary">• {v.cmd}</li>
                ))}
              </ul>
            </div>
          )}
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

function explainPolicy(goal: GoalForMaturation): string {
  const policy = goal.review_policy || 'cost-above-2'
  if (policy === 'all') return 'Review policy: every level requires approval.'
  if (policy === 'scopes-sensitive') {
    const scope = goal.scope_analysis as { affected_scopes?: string[] } | null | undefined
    return `Review policy: scopes-sensitive — affects ${(scope?.affected_scopes || []).join(', ')}.`
  }
  if (policy.startsWith('cost-above-')) {
    const threshold = policy.split('-').pop()
    const cost = goal.spec_children?.reduce((a: number, c) => a + (c.estimated_cost_usd || 0), 0) || 0
    return `Review policy: cost-above-$${threshold} — estimated $${cost.toFixed(2)} ≥ $${threshold}.`
  }
  if (policy === 'top-only') return 'Review policy: top-only — top-level approval, autonomous below.'
  return `Review policy: ${policy}`
}
