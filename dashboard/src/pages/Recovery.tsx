import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, RefreshCw, HardDrive, RotateCcw, Download, Trash2,
  Shield, CheckCircle2, XCircle, Loader2, Server,
  MessageCircle, Send, ChevronDown, ChevronUp, Clock,
} from 'lucide-react'
import { format } from 'date-fns'
import { PageHeader } from '../components/layout/PageHeader'
import { Card, Button, Input, Badge, StatusDot, ConfirmDialog, Checkbox, Metric } from '../components/ui'
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

function deriveStatusDot(status: string, health: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'not_found' || status === 'unknown') return 'neutral'
  const isUp = status === 'running' && (health === 'healthy' || health === 'none')
  if (isUp) return 'success'
  if (status === 'running') return 'warning'
  return 'danger'
}

function statusText(status: string, health: string): string {
  if (status === 'not_found') return 'Not found'
  const isUp = status === 'running' && (health === 'healthy' || health === 'none')
  if (isUp) return 'Healthy'
  if (status === 'running') return `Running (${health})`
  return status.charAt(0).toUpperCase() + status.slice(1)
}

// ── Service Status Section ───────────────────────────────────────────────────

function ServiceStatusSection() {
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
      <div className="px-5 py-3 border-b border-border-subtle flex items-center gap-2">
        <Server size={15} className="text-accent shrink-0" />
        <div>
          <h2 className="text-compact font-semibold text-content-primary">Service Status</h2>
          <p className="text-caption text-content-secondary mt-0.5">Live status of all Nova containers.</p>
        </div>
      </div>
      <div className="px-5 py-4 space-y-3">
        {isLoading ? (
          <p className="text-compact text-content-tertiary">Checking services...</p>
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-compact">
                <thead>
                  <tr className="bg-surface-elevated">
                    <th className="px-4 py-2.5 text-left text-caption font-medium text-content-tertiary">Service</th>
                    <th className="px-4 py-2.5 text-left text-caption font-medium text-content-tertiary">Status</th>
                    <th className="hidden sm:table-cell px-4 py-2.5 text-right text-caption font-medium text-content-tertiary">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {(services ?? []).map((svc: ServiceStatus) => (
                    <tr key={svc.service} className="hover:bg-surface-card-hover transition-colors">
                      <td className="px-4 py-2.5 font-medium text-content-primary">{svc.service}</td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1.5">
                          <StatusDot status={deriveStatusDot(svc.status, svc.health)} />
                          <span className="text-caption text-content-secondary">{statusText(svc.status, svc.health)}</span>
                        </span>
                      </td>
                      <td className="hidden sm:table-cell px-4 py-2.5 text-right">
                        {svc.service !== 'postgres' && svc.service !== 'redis' && svc.status !== 'not_found' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={<RefreshCw size={11} className={restartingService === svc.service ? 'animate-spin' : ''} />}
                            onClick={() => handleRestart(svc.service)}
                            disabled={restartingService === svc.service}
                          >
                            Restart
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Button
              variant="outline"
              className="w-full"
              icon={<RefreshCw size={14} className={restartingAll ? 'animate-spin' : ''} />}
              onClick={handleRestartAll}
              disabled={restartingAll}
            >
              {restartingAll ? 'Restarting...' : 'Restart All Services'}
            </Button>
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
  const [confirmRestore, setConfirmRestore] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [restoringFile, setRestoringFile] = useState<string | null>(null)
  const [deletingFile, setDeletingFile] = useState<string | null>(null)
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
      <div className="px-5 py-3 border-b border-border-subtle flex items-center justify-between">
        <div className="flex items-center gap-2">
          <HardDrive size={15} className="text-accent shrink-0" />
          <div>
            <h2 className="text-compact font-semibold text-content-primary">Backups</h2>
            <p className="text-caption text-content-secondary mt-0.5">Create, restore, or manage database backups.</p>
          </div>
        </div>
        <Button
          size="sm"
          icon={creating ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
          onClick={handleCreate}
          disabled={creating}
        >
          {creating ? 'Creating...' : 'Back Up Now'}
        </Button>
      </div>

      <div className="px-5 py-4 space-y-3">
        {message && (
          <div className={`rounded-lg px-3 py-2 text-caption flex items-center gap-2 ${
            message.type === 'success'
              ? 'bg-success-dim text-emerald-700 dark:text-emerald-400 border border-success/20'
              : 'bg-danger-dim text-red-700 dark:text-red-400 border border-danger/20'
          }`}>
            {message.type === 'success' ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
            {message.text}
          </div>
        )}

        {isLoading ? (
          <p className="text-compact text-content-tertiary">Loading backups...</p>
        ) : (backups ?? []).length === 0 ? (
          <p className="text-compact text-content-tertiary text-center py-6">
            No backups yet. Click "Back Up Now" to create your first backup.
          </p>
        ) : (
          <div className="space-y-2">
            {(backups ?? []).map((b: BackupInfo) => (
              <div
                key={b.filename}
                className="rounded-lg border border-border-subtle bg-surface-elevated p-3"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-compact font-medium text-content-primary font-mono">
                      {b.filename}
                    </p>
                    <p className="text-caption text-content-tertiary mt-0.5">
                      {format(new Date(b.created_at), 'MMM d, yyyy h:mm a')} &middot; {formatBytes(b.size_bytes)}
                    </p>
                  </div>

                  <div className="flex items-center gap-1.5">
                    {confirmRestore === b.filename ? (
                      <div className="flex items-center gap-1.5">
                        <span className="text-caption text-warning">Restore?</span>
                        <Button
                          size="sm"
                          onClick={() => handleRestore(b.filename)}
                          disabled={restoringFile === b.filename}
                          loading={restoringFile === b.filename}
                        >
                          Yes
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirmRestore(null)}>
                          No
                        </Button>
                      </div>
                    ) : confirmDelete === b.filename ? (
                      <div className="flex items-center gap-1.5">
                        <span className="text-caption text-danger">Delete?</span>
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => handleDelete(b.filename)}
                          disabled={deletingFile === b.filename}
                          loading={deletingFile === b.filename}
                        >
                          Yes
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                          No
                        </Button>
                      </div>
                    ) : (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<RotateCcw size={11} />}
                          onClick={() => setConfirmRestore(b.filename)}
                        >
                          Restore
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 size={11} />}
                          onClick={() => setConfirmDelete(b.filename)}
                          className="text-content-tertiary hover:text-danger"
                        />

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
    <Card className="overflow-hidden border-danger/20">
      <div className="px-5 py-3 border-b border-danger/20 bg-danger-dim">
        <div className="flex items-center gap-2">
          <Shield size={15} className="text-danger shrink-0" />
          <div>
            <h2 className="text-compact font-semibold text-content-primary">Factory Reset</h2>
            <p className="text-caption text-content-secondary mt-0.5">Selectively wipe data to return Nova to a clean state.</p>
          </div>
        </div>
      </div>

      <div className="px-5 py-4 space-y-4">
        {isLoading ? (
          <p className="text-compact text-content-tertiary">Loading categories...</p>
        ) : (
          <>
            <div>
              <label className="mb-2 block text-caption font-medium text-content-secondary">
                What do you want to keep?
              </label>
              <div className="space-y-2">
                {(categories ?? []).map((cat: ResetCategory) => (
                  <label
                    key={cat.key}
                    className="flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-elevated px-3 py-2.5 cursor-pointer hover:bg-surface-card-hover transition-colors"
                  >
                    <Checkbox
                      checked={keepSet.has(cat.key)}
                      onChange={() => toggleKeep(cat.key)}
                    />
                    <div>
                      <span className="text-compact text-content-primary">{cat.label}</span>
                      {keepSet.has(cat.key) ? (
                        <Badge color="success" size="sm" className="ml-2">Preserved</Badge>
                      ) : (
                        <Badge color="danger" size="sm" className="ml-2">Will be wiped</Badge>
                      )}
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="border-t border-border-subtle pt-4">
              <label className="mb-2 block text-caption font-medium text-danger">
                Type RESET to confirm
              </label>
              <div className="flex gap-2">
                <Input
                  value={confirmText}
                  onChange={e => setConfirmText(e.target.value)}
                  placeholder="RESET"
                  className="flex-1"
                />
                <Button
                  variant="danger"
                  icon={<Shield size={14} />}
                  onClick={handleReset}
                  disabled={confirmText !== 'RESET' || resetting}
                  loading={resetting}
                >
                  {resetting ? 'Resetting...' : 'Factory Reset'}
                </Button>
              </div>
            </div>

            {result && (
              <div className="rounded-lg border border-success/20 bg-success-dim px-3 py-2.5 text-caption space-y-1">
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

function OverviewBanner() {
  const { data: overview, isLoading, error } = useQuery({
    queryKey: ['recovery-overview'],
    queryFn: getRecoveryOverview,
    refetchInterval: 15_000,
  })

  if (isLoading) {
    return (
      <Card className="border-warning/30 bg-warning-dim p-5">
        <div className="flex items-center gap-2.5">
          <Loader2 size={18} className="text-warning animate-spin" />
          <span className="text-compact text-content-secondary">Checking Nova status...</span>
        </div>
      </Card>
    )
  }

  if (error || !overview) {
    return (
      <Card className="border-danger/30 bg-danger-dim p-5">
        <div className="flex items-center gap-2.5">
          <XCircle size={18} className="text-danger" />
          <h2 className="text-compact font-semibold text-content-primary">Recovery Service Unreachable</h2>
        </div>
        <p className="mt-1 text-compact text-content-secondary">
          Cannot connect to the recovery sidecar. Use the emergency CLI instead:
          <code className="ml-1 rounded-xs bg-danger-dim px-1.5 py-0.5 text-mono-sm font-mono">./scripts/backup.sh</code>
        </p>
      </Card>
    )
  }

  const { services, database, backups } = overview
  const allHealthy = services.down === 0

  return (
    <Card className={`p-5 space-y-4 ${
      allHealthy ? 'border-success/30 bg-success-dim' :
      services.up === 0 ? 'border-danger/30 bg-danger-dim' :
      'border-warning/30 bg-warning-dim'
    }`}>
      <div>
        <div className="flex items-center gap-2.5">
          {allHealthy ? (
            <CheckCircle2 size={18} className="text-success" />
          ) : (
            <AlertTriangle size={18} className="text-warning" />
          )}
          <h2 className="text-h3 text-content-primary">
            {allHealthy
              ? 'All systems operational'
              : services.up === 0
                ? 'All services are down'
                : `${services.down} of ${services.total} services are down`}
          </h2>
        </div>
        <p className="mt-1 text-compact text-content-secondary">
          {allHealthy
            ? 'All services are healthy. Manage backups and recovery options below.'
            : services.up === 0
              ? 'Use the controls below to diagnose and recover.'
              : 'Review the status below.'}
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card className="p-3">
          <Metric
            label="Services"
            value={`${services.up} / ${services.total}`}
          />
          <p className="text-caption text-content-tertiary mt-0.5">
            {services.down > 0 ? `${services.down} down` : 'All up'}
          </p>
        </Card>

        <Card className="p-3">
          <Metric
            label="Database"
            value={database.connected ? (database.size ?? 'Connected') : 'Offline'}
          />
          <p className="text-caption text-content-tertiary mt-0.5">
            {database.connected ? `${database.table_count} tables` : 'Cannot connect'}
          </p>
        </Card>

        <Card className="p-3">
          <Metric label="Backups" value={String(backups.count)} />
          <p className="text-caption text-content-tertiary mt-0.5">
            {backups.count > 0 ? formatBytes(backups.total_size_bytes) + ' total' : 'None yet'}
          </p>
        </Card>

        <Card className="p-3">
          <Metric
            label="Last Backup"
            value={backups.latest ? format(new Date(backups.latest.created_at), 'MMM d') : 'Never'}
          />
          <p className="text-caption text-content-tertiary mt-0.5">
            {backups.latest
              ? <>
                  {format(new Date(backups.latest.created_at), 'h:mm a')}
                  {backups.latest.filename.startsWith('nova-checkpoint-') && (
                    <span className="ml-1 text-accent">(auto)</span>
                  )}
                </>
              : 'Create one below'}
          </p>
        </Card>
      </div>
    </Card>
  )
}

// ── AI Troubleshooter ────────────────────────────────────────────────────────

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
}

function AiTroubleshooter({ suggestedPrompt }: { suggestedPrompt?: string }) {
  const [expanded, setExpanded] = useState(false)
  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [promptApplied, setPromptApplied] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

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
        className="w-full px-5 py-3 border-b border-border-subtle text-left hover:bg-surface-card-hover transition-colors"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageCircle size={15} className="text-accent" />
            <h2 className="text-compact font-semibold text-content-primary">AI Troubleshooter</h2>
          </div>
          {expanded
            ? <ChevronUp size={14} className="text-content-tertiary" />
            : <ChevronDown size={14} className="text-content-tertiary" />}
        </div>
        <p className="mt-0.5 text-caption text-content-secondary">
          Ask an AI to diagnose issues using live service logs and status.
        </p>
      </button>

      {expanded && (
        <div className="px-5 py-4 space-y-3">
          <div
            ref={scrollRef}
            className="h-64 overflow-y-auto custom-scrollbar rounded-lg border border-border-subtle bg-surface-elevated p-3 space-y-3"
          >
            {messages.length === 0 && !loading && (
              <p className="text-caption text-content-tertiary text-center py-8">
                Ask a question like "Why is the orchestrator down?" or "What errors are in the logs?"
              </p>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 text-compact whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'bg-accent text-neutral-950'
                    : 'bg-surface-card text-content-primary border border-border-subtle'
                }`}>
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="rounded-lg bg-surface-card border border-border-subtle px-3 py-2">
                  <Loader2 size={14} className="text-accent animate-spin" />
                </div>
              </div>
            )}
          </div>

          <div className="flex gap-2">
            <Input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
              placeholder="Describe the issue..."
              disabled={loading}
              className="flex-1"
            />
            <Button
              onClick={handleSend}
              disabled={!input.trim() || loading}
              icon={<Send size={14} />}
            />
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

  const suggestedPrompt = (() => {
    if (!overview) return undefined
    const down = overview.services.details
      ?.filter((s: ServiceStatus) => s.status !== 'running' || (s.health !== 'healthy' && s.health !== 'none'))
      .map((s: ServiceStatus) => s.service)
    if (!down?.length) return undefined
    return `These services are having issues: ${down.join(', ')}. What's wrong and how do I fix it?`
  })()

  return (
    <div className="space-y-6">
      <PageHeader title="Recovery" description="Monitor service health, manage backups, and recover from failures." />
      <OverviewBanner />
      <AiTroubleshooter suggestedPrompt={suggestedPrompt} />
      <ServiceStatusSection />
      <BackupSection />
      <FactoryResetSection />
    </div>
  )
}
