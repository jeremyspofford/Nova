import { useQuery } from '@tanstack/react-query'
import { Heart, ExternalLink, Server } from 'lucide-react'
import { useNovaIdentity } from '../hooks/useNovaIdentity'
import { getServiceStatus, type ServiceStatus } from '../api-recovery'

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

type HealthStatus = 'healthy' | 'unhealthy' | 'starting' | 'loading'

function deriveStatus(svc: ServiceStatus): HealthStatus {
  if (svc.status === 'running' && (svc.health === 'healthy' || svc.health === 'none')) return 'healthy'
  if (svc.status === 'running') return 'starting'
  return 'unhealthy'
}

function StatusDot({ status }: { status: HealthStatus }) {
  const color =
    status === 'healthy' ? 'bg-emerald-500' :
    status === 'starting' ? 'bg-amber-500 animate-pulse' :
    status === 'unhealthy' ? 'bg-red-500' :
    'bg-neutral-400 animate-pulse'
  return <span className={`block size-2.5 rounded-full ${color}`} />
}

function statusLabel(status: HealthStatus): string {
  if (status === 'healthy') return 'Healthy'
  if (status === 'starting') return 'Starting...'
  if (status === 'unhealthy') return 'Down'
  return 'Checking...'
}

export function About() {
  const { name } = useNovaIdentity()
  const { data: services, isLoading } = useQuery({
    queryKey: ['about-service-health'],
    queryFn: getServiceStatus,
    refetchInterval: 15_000,
  })

  return (
    <div className="p-6 sm:p-10 space-y-8 max-w-2xl">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">{name}</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Version {VERSION}
        </p>
      </div>

      {/* Service health */}
      <section>
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-neutral-500 dark:text-neutral-400 mb-3">
          <Server size={14} />
          Service Health
        </h2>
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 divide-y divide-neutral-100 dark:divide-neutral-800">
          {isLoading && (
            <div className="px-4 py-3 text-sm text-neutral-400">Checking services...</div>
          )}
          {services?.map(svc => {
            const status = deriveStatus(svc)
            const label = SERVICE_LABELS[svc.service] ?? svc.service
            return (
              <div key={svc.service} className="flex items-center justify-between px-4 py-3">
                <span className="text-sm text-neutral-700 dark:text-neutral-300">{label}</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-neutral-400 dark:text-neutral-500">
                    {statusLabel(status)}
                  </span>
                  <StatusDot status={status} />
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* Links */}
      <section>
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-neutral-500 dark:text-neutral-400 mb-3">
          <ExternalLink size={14} />
          Links
        </h2>
        <div className="flex flex-wrap gap-3">
          <a
            href="https://arialabs.ai/nova/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
          >
            Documentation
            <ExternalLink size={12} className="text-neutral-400" />
          </a>
          <a
            href="https://github.com/aria-labs/nova"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
          >
            GitHub
            <ExternalLink size={12} className="text-neutral-400" />
          </a>
        </div>
      </section>

      {/* Footer */}
      <p className="flex items-center gap-1 text-xs text-neutral-400 dark:text-neutral-500">
        Built with <Heart size={10} className="text-red-400" /> by Aria Labs
      </p>
    </div>
  )
}
