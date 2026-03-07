import { useQuery } from '@tanstack/react-query'
import { Shield, Activity } from 'lucide-react'
import { getQueueStats, getMCPServers } from '../../api'
import { ServiceStatusSection as RecoveryServiceStatus, BackupSection as RecoveryBackupSection, FactoryResetSection as RecoveryFactoryReset } from '../Recovery'
import { Section } from './shared'

export function RecoverySection() {
  return (
    <Section
      icon={Shield}
      title="Recovery & Services"
      description="Service status, database backups with restore, and factory reset. Recovery service also available directly at port 8888."
    >
      <div className="space-y-6">
        <RecoveryServiceStatus />
        <RecoveryBackupSection />
        <RecoveryFactoryReset />
      </div>
    </Section>
  )
}

function SystemStatus() {
  const { data: queueStats, isError: queueError } = useQuery({
    queryKey: ['queue-stats'],
    queryFn: getQueueStats,
    refetchInterval: 10_000,
    staleTime: 5_000,
    retry: 1,
  })

  const { data: mcpServers = [] } = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: getMCPServers,
    refetchInterval: 15_000,
    staleTime: 10_000,
  })
  const enabledServers = mcpServers.filter((s: any) => s.enabled)
  const connectedServers = mcpServers.filter((s: any) => s.connected)
  const totalTools = connectedServers.reduce((sum: number, s: any) => sum + (s.tool_count ?? 0), 0)

  const orchestratorOk = !queueError && queueStats !== undefined

  const rows = [
    { label: 'Queue Worker', ok: orchestratorOk, detail: queueStats ? `depth ${(queueStats as any).queue_depth}` : undefined },
    { label: 'Reaper', ok: orchestratorOk, detail: 'stale-agent recovery' },
    {
      label: 'MCP Servers',
      ok: enabledServers.length > 0 && connectedServers.length === enabledServers.length,
      detail: enabledServers.length === 0
        ? 'none configured'
        : `${connectedServers.length}/${enabledServers.length} connected · ${totalTools} tools`,
    },
  ]

  return (
    <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
      {rows.map(r => (
        <div key={r.label} className="flex items-center justify-between py-2 first:pt-0 last:pb-0">
          <span className="text-sm text-neutral-700 dark:text-neutral-300">{r.label}</span>
          <div className="flex items-center gap-2">
            {r.detail && <span className="text-xs text-neutral-500 dark:text-neutral-400">{r.detail}</span>}
            <span className={`h-2 w-2 rounded-full ${r.ok ? 'bg-emerald-500' : 'bg-neutral-300 dark:bg-neutral-600'}`} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function SystemStatusSection() {
  return (
    <Section
      icon={Activity}
      title="System Status"
      description="Live status of internal services. Auto-refreshes every 10 seconds."
    >
      <SystemStatus />
    </Section>
  )
}
