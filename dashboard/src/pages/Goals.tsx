import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Target, Plus, Pause, Play, Trash2, X, DollarSign,
  BarChart3, TrendingUp, Repeat,
} from 'lucide-react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { getGoals, createGoal, updateGoal, deleteGoal, getGoalStats, type Goal } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import {
  Badge, Button, Card, ConfirmDialog, EmptyState, Input,
  Metric, Modal, ProgressBar, Select, Skeleton, Textarea,
} from '../components/ui'
import type { SemanticColor } from '../lib/design-tokens'

// ── Status helpers ──────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, SemanticColor> = {
  active: 'success',
  paused: 'warning',
  completed: 'info',
  failed: 'danger',
  cancelled: 'neutral',
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
        />
      </Card>
      <Card className="p-4">
        <Metric
          label="Success Rate"
          value={stats ? `${Math.round(stats.success_rate * 100)}%` : '--'}
          icon={<TrendingUp size={12} />}
        />
      </Card>
      <Card className="p-4">
        <Metric
          label="Avg Iterations"
          value={stats?.avg_iterations?.toFixed(1) ?? '--'}
          icon={<Repeat size={12} />}
        />
      </Card>
      <Card className="p-4">
        <Metric
          label="Total Cost"
          value={stats ? `$${stats.total_cost_usd.toFixed(2)}` : '--'}
          icon={<DollarSign size={12} />}
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
  const [priority, setPriority] = useState('3')
  const [maxCost, setMaxCost] = useState('')
  const [maxIterations, setMaxIterations] = useState('')
  const qc = useQueryClient()

  const create = useMutation({
    mutationFn: () =>
      createGoal({
        title,
        description: description || undefined,
        priority: Number(priority),
        max_cost_usd: maxCost ? Number(maxCost) : undefined,
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
    setPriority('3')
    setMaxCost('')
    setMaxIterations('')
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
          placeholder="Describe the goal in detail (optional)..."
          rows={3}
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
        <Input
          label="Max Iterations"
          type="number"
          value={maxIterations}
          onChange={e => setMaxIterations(e.target.value)}
          placeholder="No limit"
          description="Optional iteration cap"
        />
        {create.isError && (
          <p className="text-caption text-danger">Failed to create goal: {String(create.error)}</p>
        )}
      </div>
    </Modal>
  )
}

// ── Goal card ──────────────────────────────────────────────────────────────────

function GoalCard({ goal }: { goal: Goal }) {
  const [expanded, setExpanded] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const qc = useQueryClient()

  const remove = useMutation({
    mutationFn: () => deleteGoal(goal.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      qc.invalidateQueries({ queryKey: ['goal-stats'] })
    },
  })

  const toggleStatus = useMutation({
    mutationFn: (status: Goal['status']) => updateGoal(goal.id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      qc.invalidateQueries({ queryKey: ['goal-stats'] })
    },
  })

  const cancelGoal = useMutation({
    mutationFn: () => updateGoal(goal.id, { status: 'cancelled' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      qc.invalidateQueries({ queryKey: ['goal-stats'] })
    },
  })

  const progressPct = Math.round(goal.progress * 100)
  const color = STATUS_COLOR[goal.status] ?? 'neutral'
  const canPauseResume = goal.status === 'active' || goal.status === 'paused'
  const isTerminal = ['completed', 'failed', 'cancelled'].includes(goal.status)

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
            {goal.status === 'active' && (
              <Button
                variant="ghost"
                size="sm"
                icon={<Pause size={14} />}
                onClick={() => toggleStatus.mutate('paused')}
                loading={toggleStatus.isPending}
                title="Pause goal"
              />
            )}
            {goal.status === 'paused' && (
              <Button
                variant="ghost"
                size="sm"
                icon={<Play size={14} />}
                onClick={() => toggleStatus.mutate('active')}
                loading={toggleStatus.isPending}
                title="Resume goal"
              />
            )}
            {canPauseResume && (
              <Button
                variant="ghost"
                size="sm"
                icon={<X size={14} />}
                onClick={() => cancelGoal.mutate()}
                loading={cancelGoal.isPending}
                title="Cancel goal"
              />
            )}
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
          <span>
            Iter: <span className="text-content-secondary">
              {goal.iteration}{goal.max_iterations ? `/${goal.max_iterations}` : ''}
            </span>
          </span>
          <span>
            Cost: <span className="font-mono text-content-secondary">
              ${goal.cost_so_far_usd.toFixed(2)}
              {goal.max_cost_usd ? ` / $${goal.max_cost_usd.toFixed(2)}` : ''}
            </span>
          </span>
        </div>

        {/* Expanded detail */}
        {expanded && (
          <div className="mt-3 pt-3 border-t border-border-subtle space-y-2 text-caption text-content-tertiary">
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
          </div>
        )}
      </Card>

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
