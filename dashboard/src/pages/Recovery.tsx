import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, RefreshCw, HardDrive, RotateCcw, Download,
  Trash2, Shield, CheckCircle2, XCircle, Loader2, Server,
  MessageCircle, Send, ChevronDown, ChevronUp, Clock,
} from 'lucide-react'
import { format } from 'date-fns'
import Card from '../components/Card'
import { formatBytes } from '../lib/format'
import {
  getServiceStatus, restartService, restartAllServices,
  getBackups, createBackup, restoreBackup, deleteBackup,
  getResetCategories, factoryReset, getRecoveryOverview,
  troubleshootChat,
  type ServiceStatus, type BackupInfo, type ResetCategory, type RecoveryOverview,
  type TroubleshootMessage,
} from '../api-recovery'

// ── Helpers ──────────────────────────────────────────────────────────────────

export function StatusDot({ status, health }: { status: string; health: string }) {
  const isUp = status === 'running' && (health === 'healthy' || health === 'none')
  const color = status === 'not_found' || status === 'unknown'
    ? 'bg-neutral-400'
    : isUp
      ? 'bg-emerald-500'
      : status === 'running'
        ? 'bg-amber-500'
        : 'bg-red-500'
  const label = status === 'not_found'
    ? 'Not found'
    : isUp
      ? 'Healthy'
      : status === 'running'
        ? `Running (${health})`
        : status.charAt(0).toUpperCase() + status.slice(1)
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block size-2.5 rounded-full ${color}`} />
      <span className="text-xs text-neutral-500 dark:text-neutral-400">{label}</span>
    </span>
  )
}

// ── Service Status Section ───────────────────────────────────────────────────

export function ServiceStatusSection() {
  const qc = useQueryClient()
  const { data: services, isLoading } = useQuery({
    queryKey: ['recovery-services'],
    queryFn: getServiceStatus,
    refetchInterval: 10_000,
  })

  const [restartingService, setRestartingService] = useState<string | null>(null)
  const [restartingAll, setRestartingAll] = useState(false)

  const handleRestart = useCallback(async (svc: string) => {
    setRestartingService(svc)
    try {
      await restartService(svc)
      qc.invalidateQueries({ queryKey: ['recovery-services'] })
    } catch { /* silently handled */ }
    setRestartingService(null)
  }, [qc])

  const handleRestartAll = useCallback(async () => {
    setRestartingAll(true)
    try {
      await restartAllServices()
      qc.invalidateQueries({ queryKey: ['recovery-services'] })
    } catch { /* silently handled */ }
    setRestartingAll(false)
  }, [qc])

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-amber-200 dark:border-amber-900/50 bg-amber-50/50 dark:bg-amber-950/20 px-4 py-4 sm:px-5">
        <div className="flex items-center gap-2">
          <Server size={15} className="text-amber-600 dark:text-amber-400" />
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Service Status</h2>
        </div>
        <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">
          Live status of all Nova containers. Restart individual services or all at once.
        </p>
      </div>
      <div className="px-4 py-4 sm:px-5 space-y-3">
        {isLoading ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">Checking services...</p>
        ) : (
          <>
            <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden text-sm">
              <table className="w-full">
                <thead>
                  <tr className="bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400 text-xs">
                    <th className="px-3 py-2 text-left font-medium">Service</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="hidden sm:table-cell px-3 py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                  {(services ?? []).map((svc: ServiceStatus) => (
                    <tr key={svc.service}>
                      <td className="px-3 py-2 font-medium text-neutral-900 dark:text-neutral-100 text-sm">
                        {svc.service}
                      </td>
                      <td className="px-3 py-2">
                        <StatusDot status={svc.status} health={svc.health} />
                      </td>
                      <td className="hidden sm:table-cell px-3 py-2 text-right">
                        {svc.service !== 'postgres' && svc.service !== 'redis' && svc.status !== 'not_found' && (
                          <button
                            onClick={() => handleRestart(svc.service)}
                            disabled={restartingService === svc.service}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30 disabled:opacity-40 transition-colors"
                          >
                            <RefreshCw size={11} className={restartingService === svc.service ? 'animate-spin' : ''} />
                            Restart
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <button
              onClick={handleRestartAll}
              disabled={restartingAll}
              className="w-full rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-4 py-2.5 text-sm font-medium text-amber-700 dark:text-amber-400 hover:bg-amber-100 dark:hover:bg-amber-950/50 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
            >
              <RefreshCw size={14} className={restartingAll ? 'animate-spin' : ''} />
              {restartingAll ? 'Restarting...' : 'Restart All Services'}
            </button>
          </>
        )}
      </div>
    </Card>
  )
}

// ── Backup Section ───────────────────────────────────────────────────────────

export function BackupSection() {
  const qc = useQueryClient()
  const { data: backups, isLoading } = useQuery({
    queryKey: ['recovery-backups'],
    queryFn: getBackups,
  })

  const [creating, setCreating] = useState(false)
  const [restoringFile, setRestoringFile] = useState<string | null>(null)
  const [deletingFile, setDeletingFile] = useState<string | null>(null)
  const [confirmRestore, setConfirmRestore] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null)

  const handleCreate = useCallback(async () => {
    setCreating(true)
    setMessage(null)
    try {
      const result = await createBackup()
      setMessage({ text: `Backup created: ${result.filename}`, type: 'success' })
      qc.invalidateQueries({ queryKey: ['recovery-backups'] })
    } catch (e) {
      setMessage({ text: `Backup failed: ${e}`, type: 'error' })
    }
    setCreating(false)
  }, [qc])

  const handleRestore = useCallback(async (filename: string) => {
    setRestoringFile(filename)
    setMessage(null)
    try {
      await restoreBackup(filename)
      setMessage({ text: `Restored from ${filename}. Restart services to apply.`, type: 'success' })
      setConfirmRestore(null)
    } catch (e) {
      setMessage({ text: `Restore failed: ${e}`, type: 'error' })
    }
    setRestoringFile(null)
  }, [])

  const handleDelete = useCallback(async (filename: string) => {
    setDeletingFile(filename)
    try {
      await deleteBackup(filename)
      qc.invalidateQueries({ queryKey: ['recovery-backups'] })
      setConfirmDelete(null)
    } catch (e) {
      setMessage({ text: `Delete failed: ${e}`, type: 'error' })
    }
    setDeletingFile(null)
  }, [qc])

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-amber-200 dark:border-amber-900/50 bg-amber-50/50 dark:bg-amber-950/20 px-4 py-4 sm:px-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <HardDrive size={15} className="text-amber-600 dark:text-amber-400" />
              <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Backups</h2>
            </div>
            <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">
              Create, restore, or manage database backups.
            </p>
          </div>
          <button
            onClick={handleCreate}
            disabled={creating}
            className="rounded-lg bg-amber-600 dark:bg-amber-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500 dark:hover:bg-amber-600 disabled:opacity-40 transition-colors flex items-center gap-1.5"
          >
            {creating ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
            {creating ? 'Creating...' : 'Back Up Now'}
          </button>
        </div>
      </div>

      <div className="px-4 py-4 sm:px-5 space-y-3">
        {message && (
          <div className={`rounded-lg px-3 py-2 text-xs flex items-center gap-2 ${
            message.type === 'success'
              ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900'
              : 'bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-900'
          }`}>
            {message.type === 'success' ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
            {message.text}
          </div>
        )}

        {isLoading ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading backups...</p>
        ) : (backups ?? []).length === 0 ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400 text-center py-6">
            No backups yet. Click "Back Up Now" to create your first backup.
          </p>
        ) : (
          <div className="space-y-2">
            {(backups ?? []).map((b: BackupInfo) => (
              <div
                key={b.filename}
                className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-3"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100 font-mono">
                      {b.filename}
                    </p>
                    <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
                      {format(new Date(b.created_at), 'MMM d, yyyy h:mm a')} &middot; {formatBytes(b.size_bytes)}
                    </p>
                  </div>

                  <div className="flex items-center gap-1.5">
                    {confirmRestore === b.filename ? (
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-amber-600 dark:text-amber-400">Restore?</span>
                        <button
                          onClick={() => handleRestore(b.filename)}
                          disabled={restoringFile === b.filename}
                          className="rounded-md bg-amber-600 px-2 py-1 text-xs text-white hover:bg-amber-500 disabled:opacity-40"
                        >
                          {restoringFile === b.filename ? 'Restoring...' : 'Yes'}
                        </button>
                        <button
                          onClick={() => setConfirmRestore(null)}
                          className="rounded-md border border-neutral-300 dark:border-neutral-600 px-2 py-1 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700"
                        >
                          No
                        </button>
                      </div>
                    ) : confirmDelete === b.filename ? (
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-red-600 dark:text-red-400">Delete?</span>
                        <button
                          onClick={() => handleDelete(b.filename)}
                          disabled={deletingFile === b.filename}
                          className="rounded-md bg-red-600 px-2 py-1 text-xs text-white hover:bg-red-500 disabled:opacity-40"
                        >
                          {deletingFile === b.filename ? '...' : 'Yes'}
                        </button>
                        <button
                          onClick={() => setConfirmDelete(null)}
                          className="rounded-md border border-neutral-300 dark:border-neutral-600 px-2 py-1 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <>
                        <button
                          onClick={() => setConfirmRestore(b.filename)}
                          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30 transition-colors"
                          title="Restore from this backup"
                        >
                          <RotateCcw size={11} /> Restore
                        </button>
                        <button
                          onClick={() => setConfirmDelete(b.filename)}
                          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                          title="Delete this backup"
                        >
                          <Trash2 size={11} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

// ── Factory Reset Section ────────────────────────────────────────────────────

export function FactoryResetSection() {
  const { data: categories, isLoading } = useQuery({
    queryKey: ['recovery-reset-categories'],
    queryFn: getResetCategories,
  })

  const [keepSet, setKeepSet] = useState<Set<string>>(new Set())
  const [initialized, setInitialized] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [resetting, setResetting] = useState(false)
  const [result, setResult] = useState<{ wiped: string[]; kept: string[] } | null>(null)

  // Initialize keepSet from default_keep values
  if (categories && !initialized) {
    setKeepSet(new Set(categories.filter(c => c.default_keep).map(c => c.key)))
    setInitialized(true)
  }

  const toggleKeep = (key: string) => {
    setKeepSet(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const handleReset = useCallback(async () => {
    setResetting(true)
    try {
      const r = await factoryReset(Array.from(keepSet), confirmText)
      setResult(r)
      setConfirmText('')
    } catch { /* error handled by UI */ }
    setResetting(false)
  }, [keepSet, confirmText])

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-red-200 dark:border-red-900/50 bg-red-50/50 dark:bg-red-950/20 px-4 py-4 sm:px-5">
        <div className="flex items-center gap-2">
          <Shield size={15} className="text-red-600 dark:text-red-400" />
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Factory Reset</h2>
        </div>
        <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">
          Selectively wipe data to return Nova to a clean state. Choose what to keep.
        </p>
      </div>

      <div className="px-4 py-4 sm:px-5 space-y-4">
        {isLoading ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading categories...</p>
        ) : (
          <>
            <div>
              <label className="mb-2 block text-xs font-medium text-neutral-600 dark:text-neutral-400">
                What do you want to keep?
              </label>
              <div className="space-y-2">
                {(categories ?? []).map((cat: ResetCategory) => (
                  <label
                    key={cat.key}
                    className="flex items-center gap-3 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2.5 cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-750 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={keepSet.has(cat.key)}
                      onChange={() => toggleKeep(cat.key)}
                      className="rounded border-neutral-300 dark:border-neutral-600 text-amber-600 focus:ring-amber-500"
                    />
                    <div>
                      <span className="text-sm text-neutral-900 dark:text-neutral-100">{cat.label}</span>
                      {keepSet.has(cat.key) ? (
                        <span className="ml-2 text-xs text-emerald-600 dark:text-emerald-400">Will be preserved</span>
                      ) : (
                        <span className="ml-2 text-xs text-red-600 dark:text-red-400">Will be wiped</span>
                      )}
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="border-t border-neutral-200 dark:border-neutral-700 pt-4">
              <label className="mb-2 block text-xs font-medium text-red-600 dark:text-red-400">
                Type RESET to confirm
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={confirmText}
                  onChange={e => setConfirmText(e.target.value)}
                  placeholder="RESET"
                  className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 outline-none focus:border-red-500"
                />
                <button
                  onClick={handleReset}
                  disabled={confirmText !== 'RESET' || resetting}
                  className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-40 transition-colors flex items-center gap-1.5"
                >
                  <Shield size={14} />
                  {resetting ? 'Resetting...' : 'Factory Reset'}
                </button>
              </div>
            </div>

            {result && (
              <div className="rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/30 px-3 py-2.5 text-xs space-y-1">
                <p className="font-medium text-emerald-700 dark:text-emerald-400">Reset complete</p>
                {result.wiped.length > 0 && (
                  <p className="text-emerald-600 dark:text-emerald-500">Wiped: {result.wiped.join(', ')}</p>
                )}
                {result.kept.length > 0 && (
                  <p className="text-emerald-600 dark:text-emerald-500">Kept: {result.kept.join(', ')}</p>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  )
}

// ── Overview Banner ──────────────────────────────────────────────────────────

export function OverviewBanner() {
  const { data: overview, isLoading, error } = useQuery({
    queryKey: ['recovery-overview'],
    queryFn: getRecoveryOverview,
    refetchInterval: 15_000,
  })

  if (isLoading) {
    return (
      <div className="rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Loader2 size={18} className="text-amber-600 dark:text-amber-400 animate-spin" />
          <span className="text-sm text-neutral-600 dark:text-neutral-400">Checking Nova status...</span>
        </div>
      </div>
    )
  }

  if (error || !overview) {
    return (
      <div className="rounded-xl border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <XCircle size={18} className="text-red-600 dark:text-red-400" />
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Recovery Service Unreachable</h1>
        </div>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          Cannot connect to the recovery sidecar. Use the emergency CLI scripts instead:
          <code className="ml-1 rounded bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-xs font-mono">./scripts/backup.sh</code>
        </p>
      </div>
    )
  }

  const { services, database, backups } = overview
  const allHealthy = services.down === 0
  const borderColor = allHealthy
    ? 'border-emerald-300 dark:border-emerald-800'
    : services.up === 0
      ? 'border-red-300 dark:border-red-800'
      : 'border-amber-300 dark:border-amber-800'
  const bgColor = allHealthy
    ? 'bg-emerald-50 dark:bg-emerald-950/30'
    : services.up === 0
      ? 'bg-red-50 dark:bg-red-950/30'
      : 'bg-amber-50 dark:bg-amber-950/30'
  const HeaderIcon = allHealthy ? CheckCircle2 : AlertTriangle
  const iconColor = allHealthy
    ? 'text-emerald-600 dark:text-emerald-400'
    : 'text-amber-600 dark:text-amber-400'

  return (
    <div className={`rounded-xl border ${borderColor} ${bgColor} px-5 py-4 space-y-4`}>
      {/* Title row */}
      <div>
        <div className="flex items-center gap-2.5">
          <HeaderIcon size={18} className={iconColor} />
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            Nova Recovery
          </h1>
        </div>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          {allHealthy
            ? 'All services are healthy. Manage backups and recovery options below.'
            : services.up === 0
              ? 'All services are down. Use the controls below to diagnose and recover.'
              : `${services.down} of ${services.total} services are down. Review the status below.`}
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* Services */}
        <div className="rounded-lg border border-neutral-200/50 dark:border-neutral-700/50 bg-white/60 dark:bg-neutral-900/40 px-3 py-2.5">
          <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">Services</p>
          <p className="mt-0.5 text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            <span className="text-emerald-600 dark:text-emerald-400">{services.up}</span>
            <span className="text-neutral-400 dark:text-neutral-500 text-sm"> / {services.total}</span>
          </p>
          <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
            {services.down > 0 ? `${services.down} down` : 'All up'}
          </p>
        </div>

        {/* Database */}
        <div className="rounded-lg border border-neutral-200/50 dark:border-neutral-700/50 bg-white/60 dark:bg-neutral-900/40 px-3 py-2.5">
          <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">Database</p>
          <p className="mt-0.5 text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            {database.connected ? (
              <span className="text-emerald-600 dark:text-emerald-400">{database.size}</span>
            ) : (
              <span className="text-red-600 dark:text-red-400">Offline</span>
            )}
          </p>
          <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
            {database.connected ? `${database.table_count} tables` : 'Cannot connect'}
          </p>
        </div>

        {/* Backups */}
        <div className="rounded-lg border border-neutral-200/50 dark:border-neutral-700/50 bg-white/60 dark:bg-neutral-900/40 px-3 py-2.5">
          <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">Backups</p>
          <p className="mt-0.5 text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            {backups.count}
          </p>
          <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
            {backups.count > 0 ? formatBytes(backups.total_size_bytes) + ' total' : 'None yet'}
          </p>
        </div>

        {/* Last Backup */}
        <div className="rounded-lg border border-neutral-200/50 dark:border-neutral-700/50 bg-white/60 dark:bg-neutral-900/40 px-3 py-2.5">
          <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">Last Backup</p>
          {backups.latest ? (
            <>
              <p className="mt-0.5 text-sm font-semibold text-neutral-900 dark:text-neutral-100">
                {format(new Date(backups.latest.created_at), 'MMM d')}
              </p>
              <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
                {format(new Date(backups.latest.created_at), 'h:mm a')}
                {backups.latest.filename.startsWith('nova-checkpoint-') && (
                  <span className="ml-1 text-teal-600 dark:text-teal-400">(auto)</span>
                )}
              </p>
            </>
          ) : (
            <>
              <p className="mt-0.5 text-sm font-semibold text-amber-600 dark:text-amber-400">Never</p>
              <p className="text-[11px] text-neutral-500 dark:text-neutral-400">Create one below</p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── AI Troubleshooter ────────────────────────────────────────────────────────

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
}

export function AiTroubleshooter({ suggestedPrompt }: { suggestedPrompt?: string }) {
  const [expanded, setExpanded] = useState(false)
  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [promptApplied, setPromptApplied] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Prepopulate input when there's a suggested prompt and the user hasn't interacted yet
  useEffect(() => {
    if (suggestedPrompt && !promptApplied && messages.length === 0 && !input) {
      setInput(suggestedPrompt)
      setExpanded(true)
      setPromptApplied(true)
    }
  }, [suggestedPrompt, promptApplied, messages.length, input])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    const userMsg: ChatEntry = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)
    try {
      const history: TroubleshootMessage[] = messages.map(m => ({ role: m.role, content: m.content }))
      const result = await troubleshootChat(text, history)
      setMessages(prev => [...prev, { role: 'assistant', content: result.response }])
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e}` }])
    }
    setLoading(false)
  }, [input, loading, messages])

  return (
    <Card className="overflow-hidden">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full border-b border-teal-200 dark:border-teal-900/50 bg-teal-50/50 dark:bg-teal-950/20 px-4 py-4 sm:px-5 text-left"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageCircle size={15} className="text-teal-600 dark:text-teal-400" />
            <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">AI Troubleshooter</h2>
          </div>
          {expanded
            ? <ChevronUp size={14} className="text-neutral-400" />
            : <ChevronDown size={14} className="text-neutral-400" />}
        </div>
        <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">
          Ask an AI to diagnose issues using live service logs and status.
        </p>
      </button>

      {expanded && (
        <div className="px-4 py-4 sm:px-5 space-y-3">
          {/* Message area */}
          <div
            ref={scrollRef}
            className="h-64 overflow-y-auto rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-3 space-y-3"
          >
            {messages.length === 0 && !loading && (
              <p className="text-xs text-neutral-400 dark:text-neutral-500 text-center py-8">
                Ask a question like "Why is the orchestrator down?" or "What errors are in the logs?"
              </p>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'bg-teal-600 text-white'
                    : 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 border border-neutral-200 dark:border-neutral-600'
                }`}>
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="rounded-lg bg-white dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 px-3 py-2">
                  <Loader2 size={14} className="text-teal-500 animate-spin" />
                </div>
              </div>
            )}
          </div>

          {/* Input */}
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
              placeholder="Describe the issue..."
              disabled={loading}
              className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 outline-none focus:border-teal-500 disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || loading}
              className="rounded-lg bg-teal-600 dark:bg-teal-700 px-3 py-2 text-white hover:bg-teal-500 dark:hover:bg-teal-600 disabled:opacity-40 transition-colors"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
      )}
    </Card>
  )
}

// ── Recovery Page ────────────────────────────────────────────────────────────

export function Recovery() {
  const { data: overview } = useQuery({
    queryKey: ['recovery-overview'],
    queryFn: getRecoveryOverview,
    refetchInterval: 15_000,
  })

  // Build a suggested prompt when services are unhealthy
  const suggestedPrompt = (() => {
    if (!overview) return undefined
    const down = overview.services.details
      ?.filter((s: ServiceStatus) => s.status !== 'running' || (s.health !== 'healthy' && s.health !== 'none'))
      .map((s: ServiceStatus) => s.service)
    if (!down?.length) return undefined
    return `These services are having issues: ${down.join(', ')}. What's wrong and how do I fix it?`
  })()

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      <OverviewBanner />
      <AiTroubleshooter suggestedPrompt={suggestedPrompt} />
      <ServiceStatusSection />
      <BackupSection />
      <FactoryResetSection />
    </div>
  )
}
