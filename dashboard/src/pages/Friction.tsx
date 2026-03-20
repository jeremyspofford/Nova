import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ClipboardX, AlertTriangle, CheckCircle2, Circle,
  Wrench, Trash2, Loader2,
} from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import {
  Card, Badge, StatusDot, Button, Metric, Select,
  Skeleton, EmptyState, ConfirmDialog, Toast,
} from '../components/ui'
import {
  getFrictionEntries, getFrictionStats, fixFrictionEntry,
  updateFrictionEntry, deleteFrictionEntry, getPipelineStats,
  type FrictionEntry,
} from '../api'
import { LogFrictionSheet } from '../components/LogFrictionSheet'

const SEVERITY_COLOR: Record<string, 'danger' | 'warning' | 'info'> = {
  blocker: 'danger',
  annoyance: 'warning',
  idea: 'info',
}

const STATUS_COLOR: Record<string, 'neutral' | 'warning' | 'success'> = {
  open: 'neutral',
  in_progress: 'warning',
  fixed: 'success',
}

export default function Friction() {
  const qc = useQueryClient()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [severityFilter, setSeverityFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [toast, setToast] = useState<{ variant: 'success' | 'error'; message: string } | null>(null)

  const { data: entries, isLoading } = useQuery({
    queryKey: ['friction', severityFilter, statusFilter],
    queryFn: () => getFrictionEntries({
      severity: severityFilter || undefined,
      status: statusFilter || undefined,
    }),
    staleTime: 5_000,
  })

  const { data: stats } = useQuery({
    queryKey: ['friction-stats'],
    queryFn: getFrictionStats,
    staleTime: 10_000,
  })

  const { data: pipelineStats } = useQuery({
    queryKey: ['pipeline-stats'],
    queryFn: getPipelineStats,
    staleTime: 10_000,
  })

  const fixMutation = useMutation({
    mutationFn: fixFrictionEntry,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['friction'] })
      qc.invalidateQueries({ queryKey: ['friction-stats'] })
      setToast({ variant: 'success', message: 'Fix task created' })
    },
    onError: (e) => setToast({ variant: 'error', message: String(e) }),
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateFrictionEntry(id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['friction'] })
      qc.invalidateQueries({ queryKey: ['friction-stats'] })
      setToast({ variant: 'success', message: 'Status updated' })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteFrictionEntry,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['friction'] })
      qc.invalidateQueries({ queryKey: ['friction-stats'] })
      setDeleteTarget(null)
      setToast({ variant: 'success', message: 'Entry deleted' })
    },
  })

  const successRate = pipelineStats
    ? pipelineStats.completed_this_week + (pipelineStats.failed_this_week ?? 0) > 0
      ? Math.round((pipelineStats.completed_this_week / (pipelineStats.completed_this_week + (pipelineStats.failed_this_week ?? 0))) * 100)
      : 0
    : null

  return (
    <div className="space-y-6">
      <PageHeader
        title="Friction Log"
        actions={
          <Button onClick={() => setSheetOpen(true)} icon={<AlertTriangle size={14} />}>
            Log Friction
          </Button>
        }
      />

      {/* Sprint Health */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {pipelineStats ? (
          <>
            <Card className="p-4">
              <Metric label="Success Rate (7d)" value={successRate !== null ? `${successRate}%` : '--'} />
            </Card>
            <Card className="p-4">
              <Metric label="Submitted Today" value={pipelineStats.submitted_today ?? 0} />
            </Card>
            <Card className="p-4">
              <Metric label="Failed Today" value={pipelineStats.failed_today ?? 0} />
            </Card>
            <Card className="p-4">
              <Metric label="Open Friction" value={stats?.open_count ?? 0} />
            </Card>
          </>
        ) : (
          <>
            {[1, 2, 3, 4].map(i => (
              <Card key={i} className="p-4"><Skeleton lines={2} /></Card>
            ))}
          </>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <Select
          value={severityFilter}
          onChange={e => setSeverityFilter(e.target.value)}
        >
          <option value="">All Severities</option>
          <option value="blocker">Blocker</option>
          <option value="annoyance">Annoyance</option>
          <option value="idea">Idea</option>
        </Select>
        <Select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
        >
          <option value="">All Statuses</option>
          <option value="open">Open</option>
          <option value="in_progress">In Progress</option>
          <option value="fixed">Fixed</option>
        </Select>
      </div>

      {/* Entry list */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => <Card key={i} className="p-4"><Skeleton lines={3} /></Card>)}
        </div>
      ) : !entries?.length ? (
        <EmptyState
          icon={ClipboardX}
          title="No friction yet"
          description="Use the Log Friction button to capture issues as you use Nova."
          action={{ label: 'Log Friction', onClick: () => setSheetOpen(true) }}
        />
      ) : (
        <div role="list" aria-label="Friction log entries" className="space-y-3">
          {entries.map(entry => (
            <FrictionEntryCard
              key={entry.id}
              entry={entry}
              onFix={() => fixMutation.mutate(entry.id)}
              onMarkFixed={() => statusMutation.mutate({ id: entry.id, status: 'fixed' })}
              onDelete={() => setDeleteTarget(entry.id)}
              fixing={fixMutation.isPending}
            />
          ))}
        </div>
      )}

      <LogFrictionSheet open={sheetOpen} onOpenChange={setSheetOpen} />

      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete friction entry?"
        description="This cannot be undone."
        confirmLabel="Delete"
        destructive
        onConfirm={() => { if (deleteTarget) deleteMutation.mutate(deleteTarget) }}
        onClose={() => setDeleteTarget(null)}
      />

      {toast && (
        <Toast
          variant={toast.variant}
          message={toast.message}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  )
}


function FrictionEntryCard({
  entry,
  onFix,
  onMarkFixed,
  onDelete,
  fixing,
}: {
  entry: FrictionEntry
  onFix: () => void
  onMarkFixed: () => void
  onDelete: () => void
  fixing: boolean
}) {
  const timeAgo = formatTimeAgo(entry.created_at)

  return (
    <Card role="listitem" className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <StatusDot status={STATUS_COLOR[entry.status] ?? 'neutral'} />
            <span className="text-compact font-medium text-content-primary truncate">
              {entry.description}
            </span>
          </div>
          <div className="flex items-center gap-2 text-caption text-content-tertiary">
            <Badge color={SEVERITY_COLOR[entry.severity] ?? 'neutral'} size="sm">
              {entry.severity}
            </Badge>
            {entry.source === 'auto' && (
              <span title="Automatically logged when a pipeline task failed.">
                <Badge color="info" size="sm">auto</Badge>
              </span>
            )}
            <span>{timeAgo}</span>
            {entry.has_screenshot && <span>(img)</span>}
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {entry.status !== 'fixed' && !entry.task_id && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onFix}
              disabled={fixing}
              icon={fixing ? <Loader2 size={12} className="animate-spin" /> : <Wrench size={12} />}
              aria-label={`Fix friction entry: ${entry.description.slice(0, 30)}`}
            >
              Fix This
            </Button>
          )}
          {entry.status !== 'fixed' && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onMarkFixed}
              icon={<CheckCircle2 size={12} />}
              aria-label={`Mark fixed: ${entry.description.slice(0, 30)}`}
            >
              Fixed
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={onDelete}
            icon={<Trash2 size={12} />}
            aria-label={`Delete friction entry: ${entry.description.slice(0, 30)}`}
          />
        </div>
      </div>
      {/* Inline task status for Fix This */}
      {entry.task_id && (
        <div className="mt-2 text-caption text-content-tertiary flex items-center gap-1.5" aria-live="polite">
          {entry.status === 'in_progress' ? (
            <><Loader2 size={12} className="animate-spin" /> Fix in progress</>
          ) : entry.status === 'fixed' ? (
            <><CheckCircle2 size={12} className="text-emerald-500" /> Fix complete</>
          ) : (
            <><Circle size={12} /> Task {entry.task_id.slice(0, 8)}</>
          )}
          <a href={`/tasks?id=${entry.task_id}`} className="text-accent hover:underline ml-1">
            View task
          </a>
        </div>
      )}
    </Card>
  )
}

function formatTimeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(ms / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
