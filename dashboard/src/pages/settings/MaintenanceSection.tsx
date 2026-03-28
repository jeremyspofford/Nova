import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Database, RefreshCw, Zap, MessageSquare, ClipboardList, Newspaper, Globe, Wrench,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { apiFetch, reindexMemory, getReindexStatus } from '../../api'
import type { ReindexResponse, ReindexStatusResponse } from '../../api'
import { Section, Card, Badge, Metric, ProgressBar, Button } from '../../components/ui'

// ── Types ────────────────────────────────────────────────────────────────────

interface EngramStats {
  total_engrams: number
  total_edges: number
  total_archived: number
  by_type: Record<string, { total: number; superseded: number }>
  by_relation: Record<string, { count: number; avg_weight: number }>
  by_source_type?: Record<string, number>
}

// ── Maintenance constants ────────────────────────────────────────────────────

const REINDEX_SOURCES = [
  { id: 'chat', label: 'Conversations', icon: MessageSquare, description: 'Re-process all chat history into memory nodes' },
  { id: 'tasks', label: 'Pipeline Tasks', icon: ClipboardList, description: 'Ingest completed task inputs and outputs' },
  { id: 'intel', label: 'Intelligence Feeds', icon: Newspaper, description: 'Re-process RSS/Reddit content with corrected attribution' },
  { id: 'knowledge', label: 'Knowledge Sources', icon: Globe, description: 'Re-crawl configured knowledge sources' },
] as const

// ── MaintenanceSection ───────────────────────────────────────────────────────

export function MaintenanceSection() {
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set())
  const [lastResult, setLastResult] = useState<ReindexResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Poll status — detects in-progress reindex even after page refresh
  const { data: status, refetch: refetchStatus } = useQuery<ReindexStatusResponse>({
    queryKey: ['reindex-status'],
    queryFn: getReindexStatus,
    refetchInterval: (query) => query.state.data?.active ? 2000 : 15000,
  })

  const { data: stats } = useQuery<EngramStats>({
    queryKey: ['engram-stats'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/stats'),
    refetchInterval: status?.active ? 5000 : 30000,
  })

  const isRunning = status?.active ?? false

  const toggleSource = (id: string) => {
    setSelectedSources(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAll = () => setSelectedSources(new Set(['chat', 'tasks', 'intel', 'knowledge']))
  const selectNone = () => setSelectedSources(new Set())

  const handleDryRun = async () => {
    if (selectedSources.size === 0) return
    setError(null)
    try {
      const result = await reindexMemory([...selectedSources], true)
      setLastResult(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to estimate reindex')
    }
  }

  const handleReindex = async () => {
    if (selectedSources.size === 0) return
    setError(null)
    try {
      const result = await reindexMemory([...selectedSources], false)
      setLastResult(result)
      refetchStatus()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start reindex')
    }
  }

  return (
    <Section icon={Wrench} title="Maintenance" description="Re-process historical content through the memory pipeline. Useful after changing the decomposition model or to catch up on missed context.">
      <div className="space-y-6">
        {/* Reindex card */}
        <Card>
          <div className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-subtitle font-medium text-content-primary">Reindex Memory</h3>
                <p className="text-caption text-content-tertiary mt-0.5">
                  Re-process historical content through the memory pipeline. Useful after changing the
                  decomposition model or to catch up on missed context. Existing memories are deduplicated automatically.
                </p>
              </div>
              <Database size={20} className="text-content-quaternary" />
            </div>

            {/* Source selection */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-caption font-medium text-content-secondary">Sources to reindex</span>
                <div className="flex gap-2">
                  <button onClick={selectAll} className="text-xs text-accent-primary hover:underline">Select all</button>
                  <button onClick={selectNone} className="text-xs text-content-tertiary hover:underline">Clear</button>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {REINDEX_SOURCES.map(source => {
                  const Icon = source.icon
                  const selected = selectedSources.has(source.id)
                  return (
                    <button
                      key={source.id}
                      onClick={() => toggleSource(source.id)}
                      className={`flex items-start gap-3 p-3 rounded-sm border text-left transition-colors ${
                        selected
                          ? 'border-accent-primary bg-accent-primary/5'
                          : 'border-border-subtle hover:border-border-default'
                      }`}
                    >
                      <Icon size={16} className={selected ? 'text-accent-primary mt-0.5' : 'text-content-quaternary mt-0.5'} />
                      <div>
                        <span className={`text-sm font-medium ${selected ? 'text-content-primary' : 'text-content-secondary'}`}>
                          {source.label}
                        </span>
                        <p className="text-xs text-content-tertiary mt-0.5">{source.description}</p>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2">
              <Button
                onClick={handleDryRun}
                disabled={selectedSources.size === 0 || isRunning}
                variant="secondary"
              >
                Preview Counts
              </Button>
              <Button
                onClick={handleReindex}
                disabled={selectedSources.size === 0 || isRunning}
                icon={isRunning ? <RefreshCw size={14} className="animate-spin" /> : <Zap size={14} />}
              >
                {isRunning ? 'Reindexing...' : 'Reindex Now'}
              </Button>
            </div>

            {/* Error */}
            {error && (
              <div className="p-3 rounded-sm bg-red-500/10 border border-red-500/20 text-sm text-red-400">
                {error}
              </div>
            )}

            {/* Results */}
            {lastResult && (
              <div className="p-3 rounded-sm bg-surface-elevated border border-border-subtle space-y-2">
                <div className="flex items-center gap-2">
                  <Badge color={lastResult.dry_run ? 'neutral' : 'success'}>
                    {lastResult.dry_run ? 'Preview' : 'Queued'}
                  </Badge>
                  <span className="text-sm text-content-secondary">{lastResult.message}</span>
                </div>
                <div className="flex gap-4">
                  {Object.entries(lastResult.queued).map(([source, count]) => (
                    <div key={source} className="text-center">
                      <div className="text-lg font-mono font-medium text-content-primary">{count}</div>
                      <div className="text-xs text-content-tertiary">{source}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* Queue status card */}
        <Card>
          <div className="p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-subtitle font-medium text-content-primary">Ingestion Queue</h3>
              {isRunning && (
                <Badge color="accent">
                  <RefreshCw size={10} className="animate-spin mr-1 inline" />
                  Reindexing
                </Badge>
              )}
            </div>
            <div className="flex gap-6">
              <Metric label="Queue depth" value={status?.queue_depth ?? '...'} />
              <Metric label="Total engrams" value={stats?.total_engrams ?? '...'} />
              <Metric label="Total edges" value={stats?.total_edges ?? '...'} />
            </div>
            {status && status.total_queued > 0 && status.queue_depth > 0 && (
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs text-content-tertiary">
                  <span>
                    {status.sources.length > 0 && `Sources: ${status.sources.join(', ')}`}
                  </span>
                  <span>{status.processed} / {status.total_queued} processed</span>
                </div>
                <ProgressBar value={status.progress_pct} size="sm" />
                <div className="text-xs text-content-quaternary">
                  {status.queue_depth} remaining in queue
                  {status.started_at && ` — started ${formatDistanceToNow(new Date(status.started_at), { addSuffix: true })}`}
                </div>
              </div>
            )}
            {!isRunning && status?.queue_depth === 0 && status?.total_queued === 0 && (
              <p className="text-xs text-content-quaternary">Queue idle — no active reindex job.</p>
            )}
            {stats?.by_source_type && (
              <div className="flex gap-4 pt-1">
                {Object.entries(stats.by_source_type).map(([source, count]) => (
                  <span key={source} className="inline-flex items-center gap-1.5 text-xs text-content-tertiary">
                    <span className="font-medium text-content-secondary">{count}</span> from {source}
                  </span>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>
    </Section>
  )
}
