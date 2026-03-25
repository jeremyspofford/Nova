import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Target, Plus, Trash2, DollarSign,
  TrendingUp, Repeat, Pencil, Zap, Pause, Play,
  ChevronDown, ChevronRight, Check, X as XIcon,
} from 'lucide-react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { apiFetch, getGoals, createGoal, updateGoal, deleteGoal, triggerGoal, getPipelineTasks, getGoalStats, type Goal } from '../api'
import type { PipelineTask } from '../types'
import { TaskDetailSheet } from './Tasks'
import { PageHeader } from '../components/layout/PageHeader'
import {
  Badge, Button, Card, ConfirmDialog, EmptyState, Input,
  Metric, Modal, ProgressBar, Select, Skeleton, StatusDot, Textarea, Toast, Tooltip,
} from '../components/ui'
import { DiscussionThread } from '../components/DiscussionThread'
import type { SemanticColor } from '../lib/design-tokens'

const HELP_ENTRIES = [
  { term: 'Goal', definition: 'An autonomous objective Nova pursues on its own — it plans, executes tasks, and checks progress without human prompting.' },
  { term: 'Iterations', definition: 'Thinking cycles — each iteration Nova re-evaluates the goal, plans next steps, and executes tasks.' },
  { term: 'Check Interval', definition: 'Minutes between autonomous thinking cycles. Lower = more frequent re-evaluation, higher cost.' },
  { term: 'Success Criteria', definition: "Observable, testable conditions Nova checks to measure progress — e.g. 'API response time < 200ms'." },
  { term: 'Cortex', definition: "Nova's autonomous brain — the service that runs thinking loops, manages goals, and tracks budgets." },
]

// ── Status helpers ──────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, SemanticColor> = {
  active: 'success',
  paused: 'warning',
  completed: 'info',
  failed: 'danger',
  cancelled: 'neutral',
}

const MATURATION_COLORS: Record<string, string> = {
  triaging: 'bg-stone-700/40 text-stone-300',
  scoping: 'bg-blue-900/30 text-blue-400',
  speccing: 'bg-purple-900/30 text-purple-400',
  review: 'bg-amber-900/30 text-amber-400',
  building: 'bg-teal-900/30 text-teal-400',
  verifying: 'bg-emerald-900/30 text-emerald-400',
}

type StatusFilter = 'all' | 'active' | 'paused' | 'completed' | 'failed'

const STATUS_FILTERS: { id: StatusFilter; label: string; color: SemanticColor }[] = [
  { id: 'all', label: 'All', color: 'neutral' },
  { id: 'active', label: 'Active', color: 'success' },
  { id: 'paused', label: 'Paused', color: 'warning' },
  { id: 'completed', label: 'Completed', color: 'info' },
  { id: 'failed', label: 'Failed', color: 'danger' },
]

// ── Stats row ───────────────────────────────────────────────────────────────────

function GoalStatsRow() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['goal-stats'],
    queryFn: getGoalStats,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton lines={2} />
          </Card>
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <Card className="p-4">
        <Metric
          label="Active Goals"
          value={stats?.active ?? 0}
          icon={<Target size={12} />}
          tooltip="Goals currently being pursued by the Cortex autonomous brain."
        />
      </Card>
      <Card className="p-4">
        <Metric
          label="Success Rate"
          value={stats ? `${Math.round(stats.success_rate * 100)}%` : '--'}
          icon={<TrendingUp size={12} />}
          tooltip="Percentage of goal iterations that produced useful progress."
        />
      </Card>
      <Card className="p-4">
        <Metric
          label="Avg Iterations"
          value={stats?.avg_iterations?.toFixed(1) ?? '--'}
          icon={<Repeat size={12} />}
          tooltip="Average number of thinking cycles per goal before completion or pause."
        />
      </Card>
      <Card className="p-4">
        <Metric
          label="Total Cost"
          value={stats ? `$${stats.total_cost_usd.toFixed(2)}` : '--'}
          icon={<DollarSign size={12} />}
          tooltip="Cumulative LLM API spend across all goal iterations."
        />
      </Card>
    </div>
  )
}

// ── Create goal modal ─────────────────────────────────────────────────────────

function CreateGoalModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [successCriteria, setSuccessCriteria] = useState('')
  const [priority, setPriority] = useState('3')
  const [maxCost, setMaxCost] = useState('')
  const [maxIterations, setMaxIterations] = useState('')
  const [checkInterval, setCheckInterval] = useState('60')
  const qc = useQueryClient()

  const create = useMutation({
    mutationFn: () =>
      createGoal({
        title,
        description: description || undefined,
        success_criteria: successCriteria || undefined,
        priority: Number(priority),
        max_iterations: maxIterations ? Number(maxIterations) : null,
        max_cost_usd: maxCost ? Number(maxCost) : undefined,
        check_interval_seconds: checkInterval ? Number(checkInterval) * 60 : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      qc.invalidateQueries({ queryKey: ['goal-stats'] })
      resetForm()
      onClose()
    },
  })

  const resetForm = () => {
    setTitle('')
    setDescription('')
    setSuccessCriteria('')
    setPriority('3')
    setMaxCost('')
    setMaxIterations('')
    setCheckInterval('60')
  }

  const handleClose = () => {
    resetForm()
    onClose()
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Create Goal"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose}>Cancel</Button>
          <Button
            onClick={() => create.mutate()}
            disabled={!title.trim()}
            loading={create.isPending}
          >
            Create Goal
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input
          label="Title"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="What should Nova achieve?"
          autoFocus
        />
        <Textarea
          label="Description"
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Describe the objective — what state should Nova work to achieve and maintain?"
          rows={3}
        />
        <Textarea
          label="Success Criteria"
          value={successCriteria}
          onChange={e => setSuccessCriteria(e.target.value)}
          placeholder="How does Nova measure progress? List observable, testable conditions."
          rows={3}
          description="Goals are standing objectives, not one-shot tasks. Describe measurable conditions Nova can check after each iteration."
        />
        <div className="grid grid-cols-2 gap-3">
          <Select
            label="Priority"
            value={priority}
            onChange={e => setPriority(e.target.value)}
            items={[
              { value: '1', label: 'Critical' },
              { value: '2', label: 'High' },
              { value: '3', label: 'Normal' },
              { value: '4', label: 'Low' },
            ]}
          />
          <Input
            label="Budget (USD)"
            type="number"
            value={maxCost}
            onChange={e => setMaxCost(e.target.value)}
            placeholder="No limit"
            description="Optional spending cap"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input
            label="Max Iterations"
            type="number"
            value={maxIterations}
            onChange={e => setMaxIterations(e.target.value)}
            placeholder="No limit"
            description="Leave blank to run indefinitely"
          />
          <Input
            label="Check Interval (min)"
            type="number"
            value={checkInterval}
            onChange={e => setCheckInterval(e.target.value)}
            placeholder="60"
            description="Minutes between thinking cycles"
          />
        </div>
        {create.isError && (
          <p className="text-caption text-danger">Failed to create goal: {String(create.error)}</p>
        )}
      </div>
    </Modal>
  )
}

// ── Edit goal modal ──────────────────────────────────────────────────────────

function EditGoalModal({
  goal,
  open,
  onClose,
}: {
  goal: Goal
  open: boolean
  onClose: () => void
}) {
  const [title, setTitle] = useState(goal.title)
  const [description, setDescription] = useState(goal.description ?? '')
  const [successCriteria, setSuccessCriteria] = useState(goal.success_criteria ?? '')
  const [priority, setPriority] = useState(String(goal.priority))
  const [maxCost, setMaxCost] = useState(goal.max_cost_usd != null ? String(goal.max_cost_usd) : '')
  const [maxIterations, setMaxIterations] = useState(goal.max_iterations != null ? String(goal.max_iterations) : '')
  const [checkInterval, setCheckInterval] = useState(goal.check_interval_seconds != null ? String(Math.round(goal.check_interval_seconds / 60)) : '')
  const qc = useQueryClient()

  const save = useMutation({
    mutationFn: () =>
      updateGoal(goal.id, {
        title,
        description: description || null,
        success_criteria: successCriteria || null,
        priority: Number(priority),
        max_cost_usd: maxCost ? Number(maxCost) : null,
        max_iterations: maxIterations ? Number(maxIterations) : null,
        check_interval_seconds: checkInterval ? Number(checkInterval) * 60 : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      qc.invalidateQueries({ queryKey: ['goal-stats'] })
      onClose()
    },
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Edit Goal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => save.mutate()}
            disabled={!title.trim()}
            loading={save.isPending}
          >
            Save Changes
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input
          label="Title"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="What should Nova achieve?"
          autoFocus
        />
        <Textarea
          label="Description"
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Describe the objective — what state should Nova work to achieve and maintain?"
          rows={3}
        />
        <Textarea
          label="Success Criteria"
          value={successCriteria}
          onChange={e => setSuccessCriteria(e.target.value)}
          placeholder="How does Nova measure progress? List observable, testable conditions."
          rows={3}
          description="Goals are standing objectives, not one-shot tasks. Describe measurable conditions Nova can check after each iteration."
        />
        <div className="grid grid-cols-2 gap-3">
          <Select
            label="Priority"
            value={priority}
            onChange={e => setPriority(e.target.value)}
            items={[
              { value: '1', label: 'Critical' },
              { value: '2', label: 'High' },
              { value: '3', label: 'Normal' },
              { value: '4', label: 'Low' },
            ]}
          />
          <Input
            label="Budget (USD)"
            type="number"
            value={maxCost}
            onChange={e => setMaxCost(e.target.value)}
            placeholder="No limit"
            description="Optional spending cap"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input
            label="Max Iterations"
            type="number"
            value={maxIterations}
            onChange={e => setMaxIterations(e.target.value)}
            placeholder="No limit"
            description="Leave blank to run indefinitely"
          />
          <Input
            label="Check Interval (min)"
            type="number"
            value={checkInterval}
            onChange={e => setCheckInterval(e.target.value)}
            placeholder="60"
            description="Minutes between thinking cycles"
          />
        </div>
        {save.isError && (
          <p className="text-caption text-danger">Failed to save: {String(save.error)}</p>
        )}
      </div>
    </Modal>
  )
}

// ── Goal card ──────────────────────────────────────────────────────────────────

function GoalCard({ goal }: { goal: Goal }) {
  const [expanded, setExpanded] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)
  const [toast, setToast] = useState<{ variant: 'success' | 'error'; message: string } | null>(null)
  const [maturationOpen, setMaturationOpen] = useState(false)
  const [rejectFeedback, setRejectFeedback] = useState('')
  const [showRejectForm, setShowRejectForm] = useState(false)
  const qc = useQueryClient()
  const [selectedTask, setSelectedTask] = useState<PipelineTask | null>(null)

  const remove = useMutation({
    mutationFn: () => deleteGoal(goal.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      qc.invalidateQueries({ queryKey: ['goal-stats'] })
    },
  })

  const trigger = useMutation({
    mutationFn: () => triggerGoal(goal.id),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['goal-tasks', goal.id] })
      qc.invalidateQueries({ queryKey: ['goals'] })
      setToast({
        variant: 'success',
        message: data.task_id
          ? `Task ${data.task_id.slice(0, 8)} dispatched.`
          : 'Goal triggered.',
      })
    },
    onError: (e) => setToast({ variant: 'error', message: `Failed to trigger: ${e}` }),
  })

  const toggleEnabled = useMutation({
    mutationFn: () => {
      const newStatus = goal.status === 'active' ? 'paused' : 'active'
      return updateGoal(goal.id, { status: newStatus })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      qc.invalidateQueries({ queryKey: ['goal-stats'] })
    },
    onError: (e) => setToast({ variant: 'error', message: `Failed to toggle: ${e}` }),
  })

  const approveSpec = useMutation({
    mutationFn: () => apiFetch<void>(`/api/v1/goals/${goal.id}/approve-spec`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      setToast({ variant: 'success', message: 'Spec approved.' })
    },
    onError: (e) => setToast({ variant: 'error', message: `Failed to approve: ${e}` }),
  })

  const rejectSpec = useMutation({
    mutationFn: (feedback: string) =>
      apiFetch<void>(`/api/v1/goals/${goal.id}/reject-spec`, {
        method: 'POST',
        body: JSON.stringify({ feedback }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      setShowRejectForm(false)
      setRejectFeedback('')
      setToast({ variant: 'success', message: 'Spec rejected. Goal will re-scope.' })
    },
    onError: (e) => setToast({ variant: 'error', message: `Failed to reject: ${e}` }),
  })

  const { data: goalTasks } = useQuery({
    queryKey: ['goal-tasks', goal.id],
    queryFn: () => getPipelineTasks({ goal_id: goal.id, limit: 5 }),
    enabled: expanded,
    staleTime: 10_000,
  })

  const progressPct = Math.round(goal.progress * 100)
  const color = STATUS_COLOR[goal.status] ?? 'neutral'

  const priorityLabel = (p: number) => {
    if (p <= 1) return 'Critical'
    if (p <= 2) return 'High'
    if (p <= 3) return 'Normal'
    return 'Low'
  }

  return (
    <>
      <Card
        variant="hoverable"
        className="p-4"
        onClick={() => setExpanded(v => !v)}
      >
        {/* Header row */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className="text-compact font-semibold text-content-primary truncate">
                {goal.title}
              </span>
              <Badge color={color} size="sm">{goal.status}</Badge>
              {goal.maturation_status && (
                <span className={clsx(
                  'inline-flex px-1.5 py-0.5 rounded text-micro font-medium',
                  MATURATION_COLORS[goal.maturation_status] ?? 'bg-neutral-700 text-neutral-300',
                )}>
                  {goal.maturation_status}
                </span>
              )}
              {goal.priority <= 2 && (
                <Badge color={goal.priority <= 1 ? 'danger' : 'warning'} size="sm">
                  {priorityLabel(goal.priority)}
                </Badge>
              )}
            </div>
            {goal.description && (
              <p className="text-caption text-content-secondary line-clamp-2">
                {goal.description}
              </p>
            )}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
            {(goal.status === 'active' || goal.status === 'paused') && (
              <Tooltip content={goal.status === 'active' ? 'Disable goal' : 'Enable goal'}>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={goal.status === 'active' ? <Pause size={14} /> : <Play size={14} />}
                  onClick={() => toggleEnabled.mutate()}
                  loading={toggleEnabled.isPending}
                />
              </Tooltip>
            )}
            {goal.status === 'active' && (
              <Button
                variant="ghost"
                size="sm"
                icon={<Zap size={14} />}
                onClick={() => trigger.mutate()}
                loading={trigger.isPending}
                title="Run now"
              />
            )}
            <Button
              variant="ghost"
              size="sm"
              icon={<Pencil size={14} />}
              onClick={() => setEditing(true)}
              title="Edit goal"
            />
            <Button
              variant="ghost"
              size="sm"
              icon={<Trash2 size={14} />}
              onClick={() => setConfirmDelete(true)}
              title="Delete goal"
            />
          </div>
        </div>

        {/* Progress bar */}
        <div className="mt-3 flex items-center gap-3">
          <ProgressBar value={progressPct} size="sm" className="flex-1" />
          <span className="text-mono-sm text-content-tertiary w-10 text-right">
            {progressPct}%
          </span>
        </div>

        {/* Quick stats */}
        <div className="mt-2 flex items-center gap-4 text-caption text-content-tertiary">
          <Tooltip content="Thinking cycles used out of the maximum allowed.">
            <span>
              Iter: <span className="text-content-secondary">
                {goal.iteration}{goal.max_iterations ? `/${goal.max_iterations}` : ''}
              </span>
            </span>
          </Tooltip>
          <span>
            Cost: <span className="font-mono text-content-secondary">
              ${goal.cost_so_far_usd.toFixed(2)}
              {goal.max_cost_usd ? ` / $${goal.max_cost_usd.toFixed(2)}` : ''}
            </span>
          </span>
          {goal.last_checked_at && (
            <span>
              Last run: <span className="text-content-secondary">
                {formatDistanceToNow(new Date(goal.last_checked_at), { addSuffix: true })}
              </span>
            </span>
          )}
        </div>

        {/* Expanded detail */}
        {expanded && (
          <div className="mt-3 pt-3 border-t border-border-subtle space-y-2 text-caption text-content-tertiary">
            {goal.success_criteria && (
              <div>
                <span className="font-medium text-content-secondary">Success Criteria</span>
                <p className="text-content-secondary whitespace-pre-wrap mt-0.5">{goal.success_criteria}</p>
              </div>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div>
                <span className="text-content-tertiary">Priority</span>
                <p className="text-content-secondary">{priorityLabel(goal.priority)}</p>
              </div>
              <div>
                <span className="text-content-tertiary">Created</span>
                <p className="text-content-secondary">
                  {formatDistanceToNow(new Date(goal.created_at), { addSuffix: true })}
                </p>
              </div>
              <div>
                <span className="text-content-tertiary">Created by</span>
                <p className="text-content-secondary">{goal.created_by}</p>
              </div>
              <div>
                <span className="text-content-tertiary">Last Updated</span>
                <p className="text-content-secondary">
                  {formatDistanceToNow(new Date(goal.updated_at), { addSuffix: true })}
                </p>
              </div>
            </div>
            {goal.check_interval_seconds && (
              <div>
                <span className="text-content-tertiary">Check interval: </span>
                <span className="text-content-secondary">
                  {goal.check_interval_seconds >= 3600
                    ? `${(goal.check_interval_seconds / 3600).toFixed(1)}h`
                    : `${Math.round(goal.check_interval_seconds / 60)}m`}
                </span>
              </div>
            )}

            {/* Current Plan */}
            {(() => {
              const plan = goal.current_plan as Record<string, unknown> | null
              return plan?.plan ? (
                <div className="mt-2 p-2.5 rounded-sm bg-surface-elevated">
                  <span className="text-caption font-medium text-content-secondary">Last Plan</span>
                  <p className="mt-1 text-caption text-content-secondary whitespace-pre-wrap">
                    {String(plan.plan)}
                  </p>
                </div>
              ) : null
            })()}

            {/* Recent Tasks */}
            <div className="mt-2">
              <span className="text-caption font-medium text-content-secondary">Recent Tasks</span>
              {goalTasks && goalTasks.length > 0 ? (
                <div className="mt-1 space-y-1">
                  {goalTasks.map(t => (
                    <div
                      key={t.id}
                      onClick={() => setSelectedTask(t)}
                      className="flex items-center gap-2 text-caption cursor-pointer rounded-sm px-1 -mx-1 py-0.5 hover:bg-surface-card-hover transition-colors"
                    >
                      <StatusDot status={
                        t.status === 'complete' ? 'success'
                        : t.status === 'failed' ? 'danger'
                        : t.status === 'cancelled' ? 'neutral'
                        : 'warning'
                      } />
                      <span className="flex-1 truncate text-content-secondary">{t.user_input.replace(/^\[Cortex goal work\]\s*/, '')}</span>
                      <span className={clsx(
                        'shrink-0 px-1.5 py-0.5 rounded text-micro font-medium',
                        t.status === 'complete' ? 'bg-emerald-900/30 text-emerald-400'
                        : t.status === 'failed' ? 'bg-red-900/30 text-red-400'
                        : 'bg-neutral-700 text-neutral-300',
                      )}>
                        {t.status}
                      </span>
                      {t.queued_at && (
                        <span className="shrink-0 text-content-tertiary">
                          {formatDistanceToNow(new Date(t.queued_at), { addSuffix: true })}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-1 text-caption text-content-tertiary">No tasks dispatched yet.</p>
              )}
            </div>

            {/* Maturation & Discussion */}
            <div className="mt-3 pt-3 border-t border-border-subtle">
              <button
                onClick={(e) => { e.stopPropagation(); setMaturationOpen(v => !v) }}
                className="flex items-center gap-1.5 text-caption font-medium text-content-secondary hover:text-content-primary transition-colors"
              >
                {maturationOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                Maturation & Discussion
                {goal.maturation_status && (
                  <span className={clsx(
                    'ml-1.5 inline-flex px-1.5 py-0.5 rounded text-micro font-medium',
                    MATURATION_COLORS[goal.maturation_status] ?? 'bg-neutral-700 text-neutral-300',
                  )}>
                    {goal.maturation_status}
                  </span>
                )}
              </button>

              {maturationOpen && (
                <div className="mt-3 space-y-3" onClick={e => e.stopPropagation()}>
                  {/* Scope analysis */}
                  {goal.scope_analysis != null && (
                    <div>
                      <span className="text-caption font-medium text-content-secondary">Scope Analysis</span>
                      <div className="mt-1 p-2.5 rounded-sm bg-surface-elevated text-caption text-content-secondary overflow-x-auto">
                        <pre className="whitespace-pre-wrap font-mono text-[11px]">
                          {typeof goal.scope_analysis === 'string'
                            ? goal.scope_analysis
                            : JSON.stringify(goal.scope_analysis, null, 2) as string}
                        </pre>
                      </div>
                    </div>
                  )}

                  {/* Spec */}
                  {goal.spec && (
                    <div>
                      <span className="text-caption font-medium text-content-secondary">Spec</span>
                      <div className="mt-1 p-2.5 rounded-sm bg-surface-elevated text-caption text-content-secondary overflow-x-auto">
                        <pre className="whitespace-pre-wrap font-mono text-[11px]">
                          {goal.spec}
                        </pre>
                      </div>
                    </div>
                  )}

                  {/* Approve/Reject when in review */}
                  {goal.maturation_status === 'review' && (
                    <div className="flex items-start gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<Check size={14} />}
                        onClick={() => approveSpec.mutate()}
                        loading={approveSpec.isPending}
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
                            value={rejectFeedback}
                            onChange={e => setRejectFeedback(e.target.value)}
                            placeholder="Feedback for rejection..."
                            className="h-8 w-full rounded-sm border border-border bg-surface-input px-2.5 text-caption text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
                            autoFocus
                          />
                          <div className="flex gap-1.5">
                            <Button
                              variant="danger"
                              size="sm"
                              onClick={() => rejectSpec.mutate(rejectFeedback)}
                              loading={rejectSpec.isPending}
                              disabled={!rejectFeedback.trim()}
                            >
                              Confirm Reject
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => { setShowRejectForm(false); setRejectFeedback('') }}
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Discussion thread */}
                  <DiscussionThread entityType="goal" entityId={goal.id} />
                </div>
              )}
            </div>
          </div>
        )}
      </Card>

      {/* Task detail modal */}
      <TaskDetailSheet
        task={selectedTask}
        open={!!selectedTask}
        onClose={() => setSelectedTask(null)}
      />

      {/* Confirm delete */}
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete Goal"
        description={`Are you sure you want to delete "${goal.title}"? This action cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={() => {
          remove.mutate()
          setConfirmDelete(false)
        }}
        destructive
      />

      {/* Edit modal */}
      {editing && (
        <EditGoalModal goal={goal} open={editing} onClose={() => setEditing(false)} />
      )}

      {toast && (
        <Toast variant={toast.variant} message={toast.message} onDismiss={() => setToast(null)} />
      )}
    </>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function Goals() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [showCreate, setShowCreate] = useState(false)
  const qc = useQueryClient()

  const apiStatus = statusFilter === 'all' ? undefined : statusFilter

  const { data: goals = [], isFetching } = useQuery({
    queryKey: ['goals', apiStatus],
    queryFn: () => getGoals(apiStatus),
    refetchInterval: 10_000,
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Goals"
        description="Define autonomous objectives for Nova to pursue"
        helpEntries={HELP_ENTRIES}
        actions={
          <Button
            icon={<Plus size={14} />}
            onClick={() => setShowCreate(true)}
          >
            New Goal
          </Button>
        }
      />

      {/* Stats row */}
      <p className="text-caption text-content-tertiary -mb-4">Active goals, iteration throughput, and cumulative LLM spend across all autonomous objectives.</p>
      <GoalStatsRow />

      {/* Status filter pills */}
      <div className="flex items-center gap-1 flex-wrap">
        {STATUS_FILTERS.map(f => (
          <button
            key={f.id}
            onClick={() => setStatusFilter(f.id)}
          >
            <Badge
              color={statusFilter === f.id ? f.color : 'neutral'}
              size="md"
              className={clsx(
                'cursor-pointer transition-opacity',
                statusFilter !== f.id && 'opacity-60 hover:opacity-100',
              )}
            >
              {f.label}
            </Badge>
          </button>
        ))}
        {isFetching && (
          <span className="text-caption text-content-tertiary animate-pulse ml-2">Updating...</span>
        )}
      </div>

      {/* Goals list */}
      {goals.length === 0 ? (
        <EmptyState
          icon={Target}
          title={statusFilter === 'all' ? 'No goals yet' : `No ${statusFilter} goals`}
          description={
            statusFilter === 'all'
              ? 'Create a goal to start autonomous operation.'
              : 'Try selecting a different filter.'
          }
          action={
            statusFilter === 'all'
              ? { label: 'Create Goal', onClick: () => setShowCreate(true) }
              : undefined
          }
        />
      ) : (
        <div className="space-y-3">
          {goals.map((goal: Goal) => (
            <GoalCard key={goal.id} goal={goal} />
          ))}
        </div>
      )}

      {/* Create goal modal */}
      <CreateGoalModal open={showCreate} onClose={() => setShowCreate(false)} />
    </div>
  )
}
