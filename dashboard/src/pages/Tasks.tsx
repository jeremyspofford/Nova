import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Send, RefreshCw, X, CheckCircle, AlertCircle, Clock,
  ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, Loader2,
} from 'lucide-react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import {
  getPipelineTasks, submitPipelineTask, cancelPipelineTask,
  reviewPipelineTask, getQueueStats, getPods, getModels,
} from '../api'
import type { PipelineTask, TaskStatus } from '../types'

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

// ── Status badge ───────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { label: string; className: string; pulse?: boolean }> = {
  queued:              { label: 'Queued',        className: 'bg-stone-200 text-stone-700' },
  running:             { label: 'Running',       className: 'bg-amber-100 text-amber-700', pulse: true },
  context_running:     { label: 'Context',       className: 'bg-amber-100 text-amber-700', pulse: true },
  task_running:        { label: 'Task',          className: 'bg-amber-100 text-amber-700', pulse: true },
  guardrail_running:   { label: 'Guardrail',     className: 'bg-amber-100 text-amber-700', pulse: true },
  code_review_running: { label: 'Code Review',   className: 'bg-amber-100 text-amber-700', pulse: true },
  decision_running:    { label: 'Decision',      className: 'bg-amber-100 text-amber-700', pulse: true },
  complete:            { label: 'Complete',      className: 'bg-emerald-100 text-emerald-700' },
  failed:              { label: 'Failed',        className: 'bg-red-100 text-red-600' },
  cancelled:           { label: 'Cancelled',     className: 'bg-stone-400/30 text-stone-400' },
  pending_human_review:{ label: 'Needs Review',  className: 'bg-purple-100 text-purple-700', pulse: true },
}

function StatusBadge({ status }: { status: TaskStatus }) {
  const cfg = STATUS_CONFIG[status] ?? { label: status, className: 'bg-stone-200 text-stone-700' }
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
    <div className="flex items-center gap-0.5 sm:gap-1">
      {STAGES.map((stage, i) => {
        const done    = i < completedUpTo
        const active  = i === activeIndex
        const failed  = task.status === 'failed' && i === activeIndex

        return (
          <div key={stage} className="flex items-center gap-0.5 sm:gap-1">
            {i > 0 && (
              <div className={clsx('h-px flex-1 w-3 sm:w-5', done ? 'bg-emerald-500' : 'bg-stone-200')} />
            )}
            <div
              title={STAGE_LABELS[stage]}
              className={clsx(
                'flex size-5 sm:size-6 items-center justify-center rounded-full text-[10px] font-bold border transition-all',
                done   && 'bg-emerald-100 border-emerald-600 text-emerald-700',
                active && !failed && 'border-amber-400 text-amber-700 animate-pulse bg-amber-50',
                failed && 'border-red-500 text-red-600 bg-red-50',
                !done && !active && 'border-stone-300 text-stone-400 bg-white',
              )}
            >
              {done   ? '✓' : i + 1}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Review panel (for pending_human_review tasks) ──────────────────────────────

function ReviewPanel({ task, onDone }: { task: PipelineTask; onDone: () => void }) {
  const [comment, setComment] = useState('')
  const qc = useQueryClient()

  const review = useMutation({
    mutationFn: ({ decision }: { decision: 'approve' | 'reject' }) =>
      reviewPipelineTask(task.id, decision, comment || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })
      onDone()
    },
  })

  return (
    <div className="mt-3 rounded-lg border border-purple-200 bg-purple-50 p-3">
      <p className="mb-2 text-xs font-medium text-purple-700">Human Review Required</p>
      <textarea
        rows={2}
        placeholder="Optional comment…"
        value={comment}
        onChange={e => setComment(e.target.value)}
        className="mb-2 w-full resize-none rounded-md border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-900 outline-none focus:border-purple-500"
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
        {review.isPending && <Loader2 size={14} className="animate-spin self-center text-stone-500" />}
        {review.isError && <span className="self-center text-xs text-red-600">Failed — try again</span>}
      </div>
    </div>
  )
}

// ── Task card ──────────────────────────────────────────────────────────────────

function TaskCard({ task }: { task: PipelineTask }) {
  const [expanded, setExpanded] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const qc = useQueryClient()

  const cancelMutation = useMutation({
    mutationFn: () => cancelPipelineTask(task.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pipeline-tasks'] }),
  })

  const isActive    = ['queued','running','context_running','task_running',
                        'guardrail_running','code_review_running','decision_running'].includes(task.status)
  const needsReview = task.status === 'pending_human_review'
  const isTerminal  = ['complete','failed','cancelled'].includes(task.status)

  const relativeTime = task.queued_at
    ? formatDistanceToNow(new Date(task.queued_at), { addSuffix: true })
    : '—'

  return (
    <div className={clsx(
      'rounded-xl border bg-white p-4 transition-all',
      needsReview ? 'border-purple-200' : 'border-stone-200',
    )}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <StatusBadge status={task.status} />
            {task.pod_name && (
              <span className="rounded-full bg-teal-50 px-2 py-0.5 text-xs text-teal-700">
                {task.pod_name}
              </span>
            )}
            <span className="text-xs text-stone-400">{relativeTime}</span>
          </div>
          <p className="truncate text-sm text-stone-700">{task.user_input}</p>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {isActive && !needsReview && (
            <button
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              title="Cancel task"
              className="rounded-md p-1 text-stone-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
            >
              <X size={14} />
            </button>
          )}
          <button
            onClick={() => setExpanded(e => !e)}
            className="rounded-md p-1 text-stone-400 hover:text-stone-700"
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
          className="mt-2 text-xs text-purple-400 hover:text-purple-700 underline"
        >
          Open review panel →
        </button>
      )}

      {/* Expanded detail */}
      {expanded && (
        <div className="mt-3 space-y-2 border-t border-stone-200 pt-3">
          {/* Task ID + retry info */}
          <div className="flex flex-wrap gap-x-4 text-xs text-stone-400">
            <span>ID: <code className="text-stone-400">{task.id.slice(0, 8)}…</code></span>
            <span>Retries: {task.retry_count}/{task.max_retries}</span>
            {task.started_at && <span>Started: {formatDistanceToNow(new Date(task.started_at), { addSuffix: true })}</span>}
            {task.completed_at && <span>Completed: {formatDistanceToNow(new Date(task.completed_at), { addSuffix: true })}</span>}
          </div>

          {/* Full user input */}
          <div>
            <p className="mb-1 text-xs font-medium text-stone-400">Input</p>
            <p className="text-sm text-stone-500 whitespace-pre-wrap break-words">{task.user_input}</p>
          </div>

          {/* Output */}
          {task.output && (
            <div>
              <p className="mb-1 text-xs font-medium text-emerald-700">Output</p>
              <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-stone-50 p-3 text-xs text-stone-700">
                {task.output}
              </pre>
            </div>
          )}

          {/* Error */}
          {task.error && (
            <div>
              <p className="mb-1 text-xs font-medium text-red-600">Error</p>
              <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-red-50 p-3 text-xs text-red-600">
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
  const { data: modelsData }  = useQuery({ queryKey: ['models'], queryFn: getModels,    staleTime: 60_000 })
  const models = modelsData?.data ?? []

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
    <div className="rounded-xl border border-stone-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold text-stone-900">Submit Task</h2>
      <div className="space-y-2">
        <textarea
          rows={3}
          placeholder="Describe what you want the agent pipeline to do…"
          value={input}
          onChange={e => setInput(e.target.value)}
          className="w-full resize-none rounded-md border border-stone-300 bg-stone-100 px-3 py-2 text-sm text-stone-900 outline-none placeholder:text-stone-400 focus:border-teal-600"
          onKeyDown={e => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && input.trim()) submit.mutate()
          }}
        />
        <div className="flex flex-wrap gap-2">
          {/* Pod selector */}
          <select
            value={podName}
            onChange={e => setPodName(e.target.value)}
            className="rounded-md border border-stone-300 bg-stone-100 px-2 py-1.5 text-sm text-stone-700 outline-none focus:border-teal-600"
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
            className="rounded-md border border-stone-300 bg-stone-100 px-2 py-1.5 text-sm text-stone-700 outline-none focus:border-teal-600"
            title="Override the model for this task (leaves agent defaults intact)"
          >
            <option value="">Pod default model</option>
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.id}</option>
            ))}
          </select>

          <button
            onClick={() => submit.mutate()}
            disabled={!input.trim() || submit.isPending}
            className="ml-auto flex items-center gap-1.5 rounded-md bg-teal-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-40"
          >
            {submit.isPending
              ? <><Loader2 size={14} className="animate-spin" /> Submitting…</>
              : <><Send size={14} /> Submit (⌘↵)</>
            }
          </button>
        </div>
        {submit.isError && (
          <p className="text-xs text-red-600">Failed to submit: {String(submit.error)}</p>
        )}
      </div>
    </div>
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
    <div className="flex gap-4 text-xs text-stone-400">
      <span>Queue depth: <strong className="text-stone-700">{data.queue_depth}</strong></span>
      <span>Dead-letter: <strong className={data.dead_letter_depth > 0 ? 'text-red-600' : 'text-stone-700'}>{data.dead_letter_depth}</strong></span>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

type Tab = 'active' | 'review' | 'history'

const ACTIVE_STATUSES = new Set([
  'queued', 'running', 'context_running', 'task_running',
  'guardrail_running', 'code_review_running', 'decision_running',
])

export function Tasks() {
  const [tab, setTab] = useState<Tab>('active')
  const qc = useQueryClient()

  const { data: tasks = [], isFetching } = useQuery({
    queryKey: ['pipeline-tasks'],
    queryFn: () => getPipelineTasks({ limit: 100 }),
    // Poll aggressively when on active/review tabs; slow down for history
    refetchInterval: tab === 'history' ? 30_000 : 3_000,
  })

  // Partition into tabs
  const activeTasks  = tasks.filter(t => ACTIVE_STATUSES.has(t.status))
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-stone-900">Pipeline Tasks</h1>
          <p className="text-sm text-stone-400">Submit and monitor async agent tasks</p>
        </div>
        <div className="flex items-center gap-3">
          <QueueStats />
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })}
            disabled={isFetching}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-stone-500 hover:bg-stone-100 hover:text-stone-900 disabled:opacity-40"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <SubmitForm />

      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-stone-200">
        {tabDef.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              'flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors -mb-px',
              tab === t.key
                ? 'border-teal-600 text-teal-700'
                : 'border-transparent text-stone-400 hover:text-stone-700',
            )}
          >
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className={clsx(
                'rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
                t.alert ? 'bg-purple-100 text-purple-700' : 'bg-stone-200 text-stone-500',
              )}>
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Task list */}
      <div className="space-y-3">
        {tabTasks[tab].length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-16 text-stone-400">
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
