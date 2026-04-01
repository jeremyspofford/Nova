import { useQuery } from '@tanstack/react-query'
import { Heart, ExternalLink, Server } from 'lucide-react'
import { useNovaIdentity } from '../hooks/useNovaIdentity'
import { getServiceStatus, type ServiceStatus } from '../api-recovery'
import { Card, StatusDot, DataList, Badge } from '../components/ui'

const VERSION = '0.5.0'

const SERVICE_LABELS: Record<string, string> = {
  postgres:         'PostgreSQL',
  redis:            'Redis',
  orchestrator:     'Orchestrator',
  'llm-gateway':    'LLM Gateway',
  'memory-service': 'Memory Service',
  'chat-api':       'Chat API',
  dashboard:        'Dashboard',
  recovery:         'Recovery',
}

function deriveStatus(svc: ServiceStatus): 'success' | 'warning' | 'danger' | 'neutral' {
  if (svc.status === 'running' && (svc.health === 'healthy' || svc.health === 'none')) return 'success'
  if (svc.status === 'running') return 'warning'
  if (svc.status === 'not_found') return 'neutral'
  return 'danger'
}

function statusLabel(status: 'success' | 'warning' | 'danger' | 'neutral'): string {
  if (status === 'success') return 'Healthy'
  if (status === 'warning') return 'Starting...'
  if (status === 'danger') return 'Down'
  return 'Unknown'
}

export function About() {
  const { name, avatarUrl } = useNovaIdentity()
  const { data: services, isLoading } = useQuery({
    queryKey: ['about-service-health'],
    queryFn: getServiceStatus,
    refetchInterval: 15_000,
  })

  const healthyCount = services?.filter(s => deriveStatus(s) === 'success').length ?? 0
  const totalCount = services?.length ?? 0

  return (
    <div className="flex justify-center py-8 px-4">
      <Card className="w-full max-w-lg p-6 space-y-6">
        {/* Header */}
        <div className="text-center">
          <img src={avatarUrl} alt="Nova" className="mx-auto w-14 h-14 rounded-xl object-cover mb-4" />
          <h1 className="text-h1 text-content-primary">{name}</h1>
          <p className="mt-1 text-mono text-content-secondary">
            Version {VERSION}
          </p>
          <p className="mt-3 text-compact text-content-secondary max-w-sm mx-auto">
            A self-directed autonomous AI platform. Define a goal, and Nova breaks it into subtasks,
            executes them through a coordinated agent pipeline, and re-plans as needed.
          </p>
        </div>

        {/* System info */}
        <DataList
          items={[
            {
              label: 'Services',
              value: isLoading ? 'Checking...' : `${healthyCount} / ${totalCount} healthy`,
            },
            {
              label: 'Version',
              value: VERSION,
              copyable: true,
            },
          ]}
        />

        {/* Service health */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Server size={14} className="text-content-tertiary" />
            <h2 className="text-caption font-medium text-content-tertiary uppercase tracking-wider">
              Service Health
            </h2>
          </div>
          <div className="rounded-lg border border-border-subtle divide-y divide-border-subtle overflow-hidden">
            {isLoading && (
              <div className="px-4 py-3 text-compact text-content-tertiary">Checking services...</div>
            )}
            {services?.map(svc => {
              const status = deriveStatus(svc)
              const label = SERVICE_LABELS[svc.service] ?? svc.service
              return (
                <div key={svc.service} className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-compact text-content-primary">{label}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-caption text-content-tertiary">
                      {statusLabel(status)}
                    </span>
                    <StatusDot status={status} pulse={status === 'warning'} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Links */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <ExternalLink size={14} className="text-content-tertiary" />
            <h2 className="text-caption font-medium text-content-tertiary uppercase tracking-wider">
              Links
            </h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <a
              href="https://arialabs.ai/nova/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-surface-elevated px-3 py-2 text-compact text-content-primary hover:bg-surface-card-hover transition-colors"
            >
              Documentation
              <ExternalLink size={12} className="text-content-tertiary" />
            </a>
            <a
              href="https://github.com/aria-labs/nova"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-surface-elevated px-3 py-2 text-compact text-content-primary hover:bg-surface-card-hover transition-colors"
            >
              GitHub
              <ExternalLink size={12} className="text-content-tertiary" />
            </a>
          </div>
        </div>

        {/* Footer */}
        <p className="flex items-center justify-center gap-1 text-caption text-content-tertiary pt-2">
          Built with <Heart size={10} className="text-danger" /> by Aria Labs
        </p>
      </Card>
    </div>
  )
}
