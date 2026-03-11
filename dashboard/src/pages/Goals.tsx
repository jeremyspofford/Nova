import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Target, Plus, Pause, Play, Trash2, ChevronRight } from 'lucide-react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { getGoals, createGoal, updateGoal, deleteGoal, type Goal } from '../api'
import Card from '../components/Card'

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  paused: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  completed: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  cancelled: 'bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400',
}

export function Goals() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: goals = [], isFetching } = useQuery({
    queryKey: ['goals', statusFilter],
    queryFn: () => getGoals(statusFilter),
    refetchInterval: 10_000,
  })

  const create = useMutation({
    mutationFn: () => createGoal({ title: newTitle, description: newDescription || undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      setNewTitle('')
      setNewDescription('')
      setShowCreate(false)
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => deleteGoal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  })

  const toggleStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: Goal['status'] }) => updateGoal(id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  })

  const filters = ['all', 'active', 'paused', 'completed', 'failed', 'cancelled']

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Target size={20} className="text-accent-600 dark:text-accent-400" />
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Goals</h1>
          {isFetching && <span className="text-xs text-neutral-400 animate-pulse">updating…</span>}
        </div>
        <button
          onClick={() => setShowCreate(v => !v)}
          className="flex items-center gap-1.5 rounded-lg bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700 transition-colors"
        >
          <Plus size={14} /> New Goal
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <Card className="p-4 space-y-3">
          <input
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            placeholder="Goal title…"
            className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-accent-500"
            autoFocus
          />
          <textarea
            value={newDescription}
            onChange={e => setNewDescription(e.target.value)}
            placeholder="Description (optional)…"
            rows={2}
            className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-accent-500 resize-none"
          />
          <div className="flex gap-2">
            <button
              onClick={() => create.mutate()}
              disabled={!newTitle.trim() || create.isPending}
              className="rounded-lg bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700 disabled:opacity-50 transition-colors"
            >
              {create.isPending ? 'Creating…' : 'Create'}
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </Card>
      )}

      {/* Status filter tabs */}
      <div className="flex gap-1">
        {filters.map(f => (
          <button
            key={f}
            onClick={() => setStatusFilter(f === 'all' ? undefined : f)}
            className={clsx(
              'rounded-md px-3 py-1 text-xs font-medium transition-colors capitalize',
              (f === 'all' ? !statusFilter : statusFilter === f)
                ? 'bg-accent-600/10 text-accent-700 dark:text-accent-400'
                : 'text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800',
            )}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Goals list */}
      <div className="space-y-2">
        {goals.length === 0 && (
          <p className="text-sm text-neutral-400 text-center py-8">No goals yet. Create one to get started.</p>
        )}
        {goals.map((goal: Goal) => (
          <Card key={goal.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <button
                  onClick={() => setExpandedId(expandedId === goal.id ? null : goal.id)}
                  className="flex items-center gap-2 text-left w-full"
                >
                  <ChevronRight
                    size={14}
                    className={clsx('text-neutral-400 transition-transform', expandedId === goal.id && 'rotate-90')}
                  />
                  <span className="font-medium text-sm text-neutral-900 dark:text-neutral-100 truncate">
                    {goal.title}
                  </span>
                  <span className={clsx('shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium', STATUS_COLORS[goal.status] || STATUS_COLORS.cancelled)}>
                    {goal.status}
                  </span>
                </button>
                {/* Progress bar */}
                <div className="mt-2 ml-6 flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-neutral-200 dark:bg-neutral-700 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent-500 transition-all"
                      style={{ width: `${Math.round(goal.progress * 100)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-neutral-400 tabular-nums w-8 text-right">
                    {Math.round(goal.progress * 100)}%
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {goal.status === 'active' && (
                  <button
                    onClick={() => toggleStatus.mutate({ id: goal.id, status: 'paused' })}
                    className="p-1 rounded text-neutral-400 hover:text-amber-500 transition-colors"
                    title="Pause"
                  >
                    <Pause size={14} />
                  </button>
                )}
                {goal.status === 'paused' && (
                  <button
                    onClick={() => toggleStatus.mutate({ id: goal.id, status: 'active' })}
                    className="p-1 rounded text-neutral-400 hover:text-emerald-500 transition-colors"
                    title="Resume"
                  >
                    <Play size={14} />
                  </button>
                )}
                <button
                  onClick={() => remove.mutate(goal.id)}
                  className="p-1 rounded text-neutral-400 hover:text-red-500 transition-colors"
                  title="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>

            {/* Expanded detail */}
            {expandedId === goal.id && (
              <div className="mt-3 ml-6 space-y-2 text-xs text-neutral-500 dark:text-neutral-400">
                {goal.description && <p>{goal.description}</p>}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <div>
                    <span className="text-neutral-400">Priority:</span>{' '}
                    <span className="text-neutral-700 dark:text-neutral-300">{goal.priority}</span>
                  </div>
                  <div>
                    <span className="text-neutral-400">Iterations:</span>{' '}
                    <span className="text-neutral-700 dark:text-neutral-300">
                      {goal.iteration}{goal.max_iterations ? `/${goal.max_iterations}` : ''}
                    </span>
                  </div>
                  <div>
                    <span className="text-neutral-400">Cost:</span>{' '}
                    <span className="text-neutral-700 dark:text-neutral-300">
                      ${goal.cost_so_far_usd.toFixed(2)}
                      {goal.max_cost_usd ? ` / $${goal.max_cost_usd.toFixed(2)}` : ''}
                    </span>
                  </div>
                  <div>
                    <span className="text-neutral-400">Created:</span>{' '}
                    <span className="text-neutral-700 dark:text-neutral-300">
                      {formatDistanceToNow(new Date(goal.created_at), { addSuffix: true })}
                    </span>
                  </div>
                </div>
                <div>
                  <span className="text-neutral-400">Created by:</span>{' '}
                  <span className="text-neutral-700 dark:text-neutral-300">{goal.created_by}</span>
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  )
}
