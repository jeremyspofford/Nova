import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Send, RefreshCw, X, CheckCircle, AlertCircle, Clock,
  ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, Loader2, Trash2,
  ShieldAlert, FileSearch, AlertTriangle, Copy, Check, MessageSquare,
} from 'lucide-react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import {
  getPipelineTasks, submitPipelineTask, cancelPipelineTask,
  reviewPipelineTask, getQueueStats, getPods, discoverModels,
  deletePipelineTask, bulkDeletePipelineTasks,
  getTaskFindings, getTaskReviews,
} from '../api'
import type { PipelineTask, TaskStatus, GuardrailFinding, CodeReviewVerdict } from '../types'
import { ACTIVE_TASK_STATUSES, TASK_STATUS_CONFIG } from '../constants'
import { useChatStore } from '../stores/chat-store'
import Card from '../components/Card'
import { Textarea } from '../components/ui'

// ── Copyable task ID ──────────────────────────────────────────────────────────

function CopyableId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [id])

  return (
    <button
      onClick={handleCopy}
      title={copied ? 'Copied!' : `Copy task ID: ${id}`}
      className={clsx(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-mono transition-all',
        copied
          ? 'border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'
          : 'border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 hover:border-accent-400 dark:hover:border-accent-600 hover:text-accent-600 dark:hover:text-accent-400',
      )}
    >
      <span className="text-[10px] font-sans font-medium uppercase tracking-wider opacity-60">ID</span>
      {id.slice(0, 8)}
      {copied
        ? <Check size={10} className="text-emerald-500 dark:text-emerald-400" />
        : <Copy size={10} className="opacity-40 group-hover:opacity-70" />
      }
    </button>
  )
}

// ── Task context builder for chat ─────────────────────────────────────────────

function inferReviewPrompt(task: PipelineTask): string {
  const escalation = (task.metadata?.escalation_message as string | undefined) ?? ''

  // Agent failure (on_failure=escalate pattern: "Agent 'role' failed: ...")
  if (escalation.match(/^Agent '.+' failed:/)) {
    return (
      'This task was escalated because an agent failed during execution. ' +
      'What went wrong, and is it safe to retry? Should I adjust the task input, ' +
      'change the agent configuration, or reject this task entirely?'
    )
  }

  // Guardrail block (findings with severity >= threshold)
  if (escalation.toLowerCase().includes('guardrail') || escalation.toLowerCase().includes('finding')) {
    return (
      'The guardrail agent flagged this task with security or safety findings. ' +
      'Analyze the findings — are they genuine risks or false positives? ' +
      'What would you recommend: approve with modifications, or reject?'
    )
  }

  // Decision agent escalation (most common path)
  if (escalation.toLowerCase().includes('escalat') || escalation.toLowerCase().includes('review')) {
    return (
      'The pipeline escalated this task for human review after the decision agent evaluated it. ' +
      'Summarize what was attempted, explain the concerns that triggered escalation, ' +
      'and recommend whether I should approve or reject — and why.'
    )
  }

  // Completed or failed tasks opened via "Discuss" (not in review)
  if (task.status === 'complete') {
    return 'This task completed successfully. Review the output and let me know if it achieved the intended goal.'
  }
  if (task.status === 'failed') {
    return 'This task failed. Analyze the error and suggest how to fix or retry it.'
  }

  // Generic fallback
  return (
    'Explain the current state of this task — what has been completed, ' +
    'what issues were found, and what you would recommend as next steps.'
  )
}

function buildTaskContext(task: PipelineTask): string {
  const parts = [
    `I want to discuss pipeline task ${task.id.slice(0, 8)} (full ID: ${task.id}).`,
    '',
    `**Status:** ${task.status}`,
    `**Input:** ${task.user_input}`,
  ]
  if (task.output) parts.push(`**Output:** ${task.output.slice(0, 500)}${task.output.length > 500 ? '…' : ''}`)
  if (task.error) parts.push(`**Error:** ${task.error}`)
  const escalation = task.metadata?.escalation_message as string | undefined
  if (escalation) parts.push(`**Escalation reason:** ${escalation}`)
  if (task.current_stage) parts.push(`**Last stage:** ${task.current_stage}`)
  parts.push('', inferReviewPrompt(task))
  return parts.join('\n')
}

// ── Stage pipeline definition ──────────────────────────────────────────────────

const STAGES = ['context', 'task', 'guardrail', 'code_review', 'decision'] as const
type Stage = typeof STAGES[number]

const STAGE_LABELS: Record<Stage, string> = {
  context:     'Context',
  task:        'Task',
  guardrail:   'Guardrail',
  code_review: 'Code Review',
  decision:    'Decision',
}

/**
 * Returns { completedUpTo, activeIndex } based on task status + current_stage.
 * completedUpTo: all stages with index < this value are done (green)
 * activeIndex: the stage currently running (-1 = none)
 */
function resolveStageState(task: PipelineTask): { completedUpTo: number; activeIndex: number } {
  if (task.status === 'complete') return { completedUpTo: STAGES.length, activeIndex: -1 }
  if (task.status === 'failed' || task.status === 'cancelled') return { completedUpTo: 0, activeIndex: -1 }

  const stageName = task.current_stage as Stage | null
  if (!stageName) return { completedUpTo: 0, activeIndex: -1 }

  const idx = STAGES.indexOf(stageName)
  if (idx === -1) return { completedUpTo: 0, activeIndex: -1 }
  return { completedUpTo: idx, activeIndex: idx }
}

// ── Task status badge (distinct from agent StatusBadge in components/) ────────

function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const cfg = TASK_STATUS_CONFIG[status] ?? { label: status, className: 'bg-neutral-200 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300' }
  return (
    <span className={clsx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium', cfg.className)}>
      {cfg.pulse && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {cfg.label}
    </span>
  )
}

// ── Stage progress bar ─────────────────────────────────────────────────────────

function StageProgress({ task }: { task: PipelineTask }) {
  const { completedUpTo, activeIndex } = resolveStageState(task)

  return (
    <div className="flex items-center gap-0">
      {STAGES.map((stage, i) => {
        const done    = i < completedUpTo
        const active  = i === activeIndex
        const failed  = task.status === 'failed' && i === activeIndex

        return (
          <div key={stage} className="flex items-center">
            {i > 0 && (
              <div className={clsx('h-px w-3 sm:w-5', done ? 'bg-emerald-500' : 'bg-neutral-200 dark:bg-neutral-700')} />
            )}
            <div className="flex flex-col items-center gap-0.5" title={STAGE_LABELS[stage]}>
              <div
                className={clsx(
                  'flex size-5 sm:size-6 items-center justify-center rounded-full text-[10px] font-bold border transition-all',
                  done   && 'bg-emerald-100 dark:bg-emerald-900/30 border-emerald-600 text-emerald-700 dark:text-emerald-400',
                  active && !failed && 'border-amber-400 text-amber-700 dark:text-amber-400 animate-pulse bg-amber-50 dark:bg-amber-900/30',
                  failed && 'border-red-500 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30',
                  !done && !active && 'border-neutral-300 dark:border-neutral-600 text-neutral-500 dark:text-neutral-400 bg-card dark:bg-neutral-900',
                )}
              >
                {done ? '✓' : i + 1}
              </div>
              <span className={clsx(
                'text-[9px] leading-none font-medium hidden sm:block',
                done   && 'text-emerald-600 dark:text-emerald-400',
                active && !failed && 'text-amber-600 dark:text-amber-400',
                failed && 'text-red-500 dark:text-red-400',
                !done && !active && 'text-neutral-400 dark:text-neutral-500',
              )}>
                {STAGE_LABELS[stage]}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Severity badge ────────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400',
  high:     'bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-400',
  medium:   'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400',
  low:      'bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400',
}

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={clsx('rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase', SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.low)}>
      {severity}
    </span>
  )
}

// ── Findings section ──────────────────────────────────────────────────────────

function FindingsSection({ findings }: { findings: GuardrailFinding[] }) {
  if (findings.length === 0) return null
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-orange-700 dark:text-orange-400">
        <ShieldAlert size={13} /> Guardrail Findings ({findings.length})
      </div>
      {findings.map(f => (
        <div key={f.id} className="rounded-md border border-orange-200 dark:border-orange-800/50 bg-orange-50 dark:bg-orange-900/20 p-2.5 text-xs space-y-1">
          <div className="flex items-center gap-2">
            <SeverityBadge severity={f.severity} />
            <span className="font-medium text-neutral-700 dark:text-neutral-300 capitalize">{f.finding_type.replace(/_/g, ' ')}</span>
          </div>
          <p className="text-neutral-600 dark:text-neutral-400">{f.description}</p>
          {f.evidence && (
            <pre className="mt-1 rounded bg-orange-100 dark:bg-orange-900/30 px-2 py-1 text-[11px] text-orange-800 dark:text-orange-300 whitespace-pre-wrap break-words">
              {f.evidence}
            </pre>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Code review section ───────────────────────────────────────────────────────

function CodeReviewSection({ reviews }: { reviews: CodeReviewVerdict[] }) {
  if (reviews.length === 0) return null
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-blue-700 dark:text-blue-400">
        <FileSearch size={13} /> Code Review ({reviews.length} {reviews.length === 1 ? 'iteration' : 'iterations'})
      </div>
      {reviews.map(r => (
        <div key={r.id} className="rounded-md border border-blue-200 dark:border-blue-800/50 bg-blue-50 dark:bg-blue-900/20 p-2.5 text-xs space-y-1.5">
          <div className="flex items-center gap-2">
            <span className={clsx(
              'rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase',
              r.verdict === 'pass' && 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400',
              r.verdict === 'needs_refactor' && 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400',
              r.verdict === 'reject' && 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400',
            )}>
              {r.verdict.replace(/_/g, ' ')}
            </span>
            <span className="text-neutral-500 dark:text-neutral-400">Iteration {r.iteration}</span>
          </div>
          {r.summary && <p className="text-neutral-600 dark:text-neutral-400">{r.summary}</p>}
          {r.issues?.length > 0 && (
            <ul className="space-y-1 pl-2 border-l-2 border-blue-200 dark:border-blue-800">
              {r.issues.map((iss, j) => (
                <li key={j} className="text-neutral-600 dark:text-neutral-400">
                  <SeverityBadge severity={iss.severity} />{' '}
                  {iss.description}
                  {iss.file && <span className="text-neutral-400 dark:text-neutral-500"> ({iss.file}{iss.line ? `:${iss.line}` : ''})</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Review panel (for pending_human_review tasks) ──────────────────────────────

function ReviewPanel({ task, onDone }: { task: PipelineTask; onDone: () => void }) {
  const [comment, setComment] = useState('')
  const qc = useQueryClient()

  const { data: findings = [], isLoading: findingsLoading } = useQuery({
    queryKey: ['task-findings', task.id],
    queryFn: () => getTaskFindings(task.id),
    staleTime: 10_000,
  })

  const { data: reviews = [], isLoading: reviewsLoading } = useQuery({
    queryKey: ['task-reviews', task.id],
    queryFn: () => getTaskReviews(task.id),
    staleTime: 10_000,
  })

  const review = useMutation({
    mutationFn: ({ decision }: { decision: 'approve' | 'reject' }) =>
      reviewPipelineTask(task.id, decision, comment || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })
      onDone()
    },
  })

  const escalationMsg = task.metadata?.escalation_message as string | undefined
  const isLoading = findingsLoading || reviewsLoading

  return (
    <div className="mt-3 rounded-lg border border-purple-200 dark:border-purple-800 bg-purple-50/50 dark:bg-purple-900/20 p-4 space-y-4">
      {/* Escalation reason */}
      <div>
        <div className="flex items-center gap-1.5 mb-1.5 text-xs font-semibold text-purple-700 dark:text-purple-400">
          <AlertTriangle size={13} /> Why This Needs Review
        </div>
        <p className="text-sm text-neutral-700 dark:text-neutral-300">
          {escalationMsg || 'This task was escalated for human review.'}
        </p>
      </div>

      {/* Task output (what the pipeline produced) */}
      {task.output && (
        <div>
          <p className="mb-1 text-xs font-medium text-neutral-600 dark:text-neutral-400">Pipeline Output</p>
          <pre className="max-h-48 overflow-y-auto custom-scrollbar whitespace-pre-wrap break-words rounded-md bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 p-3 text-xs text-neutral-700 dark:text-neutral-300">
            {task.output}
          </pre>
        </div>
      )}

      {/* Guardrail findings & code reviews */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
          <Loader2 size={12} className="animate-spin" /> Loading review context…
        </div>
      ) : (
        <>
          <FindingsSection findings={findings} />
          <CodeReviewSection reviews={reviews} />
        </>
      )}

      {/* Decision area */}
      <div className="border-t border-purple-200 dark:border-purple-700 pt-3 space-y-2">
        <p className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Your Decision</p>
        <textarea
          rows={2}
          placeholder="Optional comment…"
          value={comment}
          onChange={e => setComment(e.target.value)}
          className="w-full resize-none rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-900 px-2.5 py-1.5 text-xs text-neutral-900 dark:text-neutral-100 outline-none focus:border-purple-500"
        />
        <div className="flex gap-2">
          <button
            onClick={() => review.mutate({ decision: 'approve' })}
            disabled={review.isPending}
            className="flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            <ThumbsUp size={12} /> Approve
          </button>
          <button
            onClick={() => review.mutate({ decision: 'reject' })}
            disabled={review.isPending}
            className="flex items-center gap-1.5 rounded-md bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50"
          >
            <ThumbsDown size={12} /> Reject
          </button>
          {review.isPending && <Loader2 size={14} className="animate-spin self-center text-neutral-500 dark:text-neutral-400" />}
          {review.isError && <span className="self-center text-xs text-red-600 dark:text-red-400">Failed — try again</span>}
        </div>
      </div>
    </div>
  )
}

// ── Task card ──────────────────────────────────────────────────────────────────

function TaskCard({ task }: { task: PipelineTask }) {
  const needsReview = task.status === 'pending_human_review'
  const [expanded, setExpanded] = useState(needsReview)
  const [reviewing, setReviewing] = useState(needsReview)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { setPrefillInput } = useChatStore()

  const handleDiscuss = useCallback(() => {
    setPrefillInput(buildTaskContext(task))
    navigate('/chat')
  }, [task, setPrefillInput, navigate])

  const cancelMutation = useMutation({
    mutationFn: () => cancelPipelineTask(task.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pipeline-tasks'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deletePipelineTask(task.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pipeline-tasks'] }),
  })

  const isActive    = ACTIVE_TASK_STATUSES.has(task.status)
  const isTerminal  = ['complete','failed','cancelled'].includes(task.status)

  const relativeTime = task.queued_at
    ? formatDistanceToNow(new Date(task.queued_at), { addSuffix: true })
    : '—'

  return (
    <div className={clsx(
      'rounded-xl border bg-card dark:bg-neutral-900 p-4 transition-all',
      needsReview ? 'border-purple-200 dark:border-purple-800' : 'border-neutral-200 dark:border-neutral-800',
    )}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <TaskStatusBadge status={task.status} />
            <CopyableId id={task.id} />
            {task.pod_name && (
              <span className="rounded-full bg-accent-50 dark:bg-accent-900/30 px-2 py-0.5 text-xs text-accent-700 dark:text-accent-400">
                {task.pod_name}
              </span>
            )}
            <span className="text-xs text-neutral-500 dark:text-neutral-400">{relativeTime}</span>
          </div>
          <p className="truncate text-sm text-neutral-700 dark:text-neutral-300">{task.user_input}</p>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {isActive && !needsReview && (
            <button
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              title="Cancel task"
              className="rounded-md p-1 text-neutral-500 dark:text-neutral-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-40"
            >
              <X size={14} />
            </button>
          )}
          {isTerminal && (
            <button
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              title="Delete task"
              className="rounded-md p-1 text-neutral-400 dark:text-neutral-500 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-40"
            >
              <Trash2 size={14} />
            </button>
          )}
          <button
            onClick={handleDiscuss}
            title="Discuss this task with Nova"
            className="flex items-center gap-1 rounded-md border border-accent-200 dark:border-accent-800 bg-accent-50 dark:bg-accent-900/30 px-2 py-1 text-xs font-medium text-accent-700 dark:text-accent-400 hover:bg-accent-100 dark:hover:bg-accent-900/50 hover:border-accent-300 dark:hover:border-accent-700 transition-colors"
          >
            <MessageSquare size={12} />
            <span className="hidden sm:inline">Discuss</span>
          </button>
          <button
            onClick={() => setExpanded(e => !e)}
            className="rounded-md p-1 text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300"
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {/* Stage progress — always visible */}
      <div className="mt-3">
        <StageProgress task={task} />
      </div>

      {/* Human review trigger */}
      {needsReview && !reviewing && (
        <button
          onClick={() => { setExpanded(true); setReviewing(true) }}
          className="mt-2 text-xs text-purple-400 dark:text-purple-300 hover:text-purple-700 dark:hover:text-purple-200 underline"
        >
          Open review panel →
        </button>
      )}

      {/* Expanded detail */}
      {expanded && (
        <div className="mt-3 space-y-2 border-t border-neutral-200 dark:border-neutral-800 pt-3">
          {/* Retry + timing info */}
          <div className="flex flex-wrap gap-x-4 text-xs text-neutral-500 dark:text-neutral-400">
            <span>Retries: {task.retry_count}/{task.max_retries}</span>
            {task.started_at && <span>Started: {formatDistanceToNow(new Date(task.started_at), { addSuffix: true })}</span>}
            {task.completed_at && <span>Completed: {formatDistanceToNow(new Date(task.completed_at), { addSuffix: true })}</span>}
          </div>

          {/* Full user input */}
          <div>
            <p className="mb-1 text-xs font-medium text-neutral-500 dark:text-neutral-400">Input</p>
            <p className="text-sm text-neutral-500 dark:text-neutral-400 whitespace-pre-wrap break-words">{task.user_input}</p>
          </div>

          {/* Output */}
          {task.output && (
            <div>
              <p className="mb-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">Output</p>
              <pre className="max-h-64 overflow-y-auto custom-scrollbar whitespace-pre-wrap break-words rounded-md bg-neutral-50 dark:bg-neutral-800 p-3 text-xs text-neutral-700 dark:text-neutral-300">
                {task.output}
              </pre>
            </div>
          )}

          {/* Error */}
          {task.error && (
            <div>
              <p className="mb-1 text-xs font-medium text-red-600 dark:text-red-400">Error</p>
              <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-red-50 dark:bg-red-900/30 p-3 text-xs text-red-600 dark:text-red-400">
                {task.error}
              </pre>
            </div>
          )}

          {/* Review panel */}
          {reviewing && needsReview && (
            <ReviewPanel task={task} onDone={() => { setReviewing(false); setExpanded(false) }} />
          )}
        </div>
      )}
    </div>
  )
}

// ── Submit form ────────────────────────────────────────────────────────────────

function SubmitForm() {
  const [input, setInput]       = useState('')
  const [podName, setPodName]   = useState('')
  const [modelId, setModelId]   = useState('')
  const qc = useQueryClient()

  const { data: pods }        = useQuery({ queryKey: ['pods'],   queryFn: getPods,      staleTime: 30_000 })
  const { data: providers }   = useQuery({ queryKey: ['model-catalog'], queryFn: () => discoverModels(), staleTime: 60_000 })
  const models = (providers ?? []).filter(p => p.available).flatMap(p => p.models.filter(m => m.registered).map(m => ({ id: m.id })))

  const submit = useMutation({
    mutationFn: () => submitPipelineTask(
      input.trim(),
      podName || undefined,
      modelId || undefined,
    ),
    onSuccess: () => {
      setInput('')
      qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })
    },
  })

  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-semibold text-neutral-900 dark:text-neutral-100">Submit Task</h2>
      <div className="space-y-2">
        <Textarea
          rows={3}
          placeholder="Describe what you want the agent pipeline to do…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && input.trim()) submit.mutate()
          }}
        />
        <div className="flex flex-wrap gap-2">
          {/* Pod selector */}
          <select
            value={podName}
            onChange={e => setPodName(e.target.value)}
            className="max-w-[160px] rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-2 py-1.5 text-sm text-neutral-700 dark:text-neutral-300 outline-none focus:border-accent-600"
          >
            <option value="">Default pod</option>
            {pods?.map(p => (
              <option key={p.id} value={p.name}>{p.name}</option>
            ))}
          </select>

          {/* Model override selector */}
          <select
            value={modelId}
            onChange={e => setModelId(e.target.value)}
            className="max-w-[160px] rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-2 py-1.5 text-sm text-neutral-700 dark:text-neutral-300 outline-none focus:border-accent-600"
            title="Override the model for this task (leaves agent defaults intact)"
          >
            <option value="">Default model</option>
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.id}</option>
            ))}
          </select>

          <button
            onClick={() => submit.mutate()}
            disabled={!input.trim() || submit.isPending}
            className="ml-auto flex items-center gap-1.5 rounded-md bg-accent-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-accent-500 disabled:opacity-40"
          >
            {submit.isPending
              ? <><Loader2 size={14} className="animate-spin" /> Submitting…</>
              : <><Send size={14} /> Submit<span className="hidden sm:inline"> (⌘↵)</span></>
            }
          </button>
        </div>
        {submit.isError && (
          <p className="text-xs text-red-600 dark:text-red-400">Failed to submit: {String(submit.error)}</p>
        )}
      </div>
    </Card>
  )
}

// ── Queue stats banner ─────────────────────────────────────────────────────────

function QueueStats() {
  const { data } = useQuery({
    queryKey: ['queue-stats'],
    queryFn: getQueueStats,
    refetchInterval: 5_000,
  })

  if (!data) return null

  return (
    <div className="hidden sm:flex gap-4 text-xs text-neutral-500 dark:text-neutral-400">
      <span>Queue depth: <strong className="text-neutral-700 dark:text-neutral-300">{data.queue_depth}</strong></span>
      <span>Dead-letter: <strong className={data.dead_letter_depth > 0 ? 'text-red-600 dark:text-red-400' : 'text-neutral-700 dark:text-neutral-300'}>{data.dead_letter_depth}</strong></span>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

type Tab = 'active' | 'review' | 'history'

export function Tasks() {
  const [tab, setTab] = useState<Tab>('active')
  const qc = useQueryClient()

  const [confirmClear, setConfirmClear] = useState(false)

  const { data: tasks = [], isFetching } = useQuery({
    queryKey: ['pipeline-tasks'],
    queryFn: () => getPipelineTasks({ limit: 100 }),
    // Poll aggressively when on active/review tabs; slow down for history
    refetchInterval: tab === 'history' ? 30_000 : 3_000,
  })

  const bulkDelete = useMutation({
    mutationFn: () => bulkDeletePipelineTasks(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })
      setConfirmClear(false)
    },
  })

  // Partition into tabs
  const activeTasks  = tasks.filter(t => ACTIVE_TASK_STATUSES.has(t.status))
  const reviewTasks  = tasks.filter(t => t.status === 'pending_human_review')
  const historyTasks = tasks.filter(t => ['complete','failed','cancelled'].includes(t.status))

  const tabTasks: Record<Tab, PipelineTask[]> = {
    active: activeTasks,
    review: reviewTasks,
    history: historyTasks,
  }

  const tabDef: { key: Tab; label: string; count?: number; alert?: boolean }[] = [
    { key: 'active',  label: 'Active',        count: activeTasks.length },
    { key: 'review',  label: 'Review Queue',  count: reviewTasks.length, alert: reviewTasks.length > 0 },
    { key: 'history', label: 'History',       count: historyTasks.length },
  ]

  return (
    <div className="space-y-6 px-4 py-8 sm:px-6">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Pipeline Tasks</h1>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 truncate">Submit and monitor async agent tasks</p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <QueueStats />
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })}
            disabled={isFetching}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-100 disabled:opacity-40"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <SubmitForm />

      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-neutral-200 dark:border-neutral-800 overflow-x-auto">
        {tabDef.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              'flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors -mb-px',
              tab === t.key
                ? 'border-accent-600 text-accent-700 dark:text-accent-400'
                : 'border-transparent text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300',
            )}
          >
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className={clsx(
                'rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
                t.alert ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400' : 'bg-neutral-200 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400',
              )}>
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Task list */}
      <div className="space-y-3">
        {tab === 'history' && historyTasks.length > 0 && (
          <div className="flex justify-end">
            {confirmClear ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-neutral-500 dark:text-neutral-400">Delete all history?</span>
                <button
                  onClick={() => bulkDelete.mutate()}
                  disabled={bulkDelete.isPending}
                  className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50"
                >
                  {bulkDelete.isPending ? 'Deleting...' : 'Confirm'}
                </button>
                <button
                  onClick={() => setConfirmClear(false)}
                  className="rounded-md px-3 py-1.5 text-xs text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmClear(true)}
                className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-neutral-500 dark:text-neutral-400 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 dark:hover:text-red-400"
              >
                <Trash2 size={12} /> Clear All History
              </button>
            )}
          </div>
        )}

        {tabTasks[tab].length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-16 text-neutral-500 dark:text-neutral-400">
            {tab === 'active'  && <><Clock size={24} /><p className="text-sm">No active tasks</p></>}
            {tab === 'review'  && <><CheckCircle size={24} /><p className="text-sm">No tasks awaiting review</p></>}
            {tab === 'history' && <><AlertCircle size={24} /><p className="text-sm">No completed tasks yet</p></>}
          </div>
        ) : (
          tabTasks[tab].map(task => <TaskCard key={task.id} task={task} />)
        )}
      </div>
    </div>
  )
}
