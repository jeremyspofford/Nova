/**
 * StartupScreen — shown while Nova services are still coming up.
 *
 * Polls the recovery service for live status and shows each service
 * ticking from red → green. Once all core services are healthy,
 * calls onReady() so the parent can switch to the normal UI.
 */
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { getRecoveryOverview, type ServiceStatus } from '../api-recovery'

const SERVICE_LABELS: Record<string, string> = {
  postgres:         'PostgreSQL',
  redis:            'Redis',
  'llm-gateway':    'LLM Gateway',
  'memory-service': 'Memory Service',
  orchestrator:     'Orchestrator',
  'chat-api':       'Chat API',
  dashboard:        'Dashboard',
}

// These must be healthy before we consider Nova "ready"
const REQUIRED_SERVICES = ['postgres', 'redis', 'orchestrator', 'llm-gateway', 'memory-service']

function ServiceRow({ svc }: { svc: ServiceStatus }) {
  const isUp = svc.status === 'running' && (svc.health === 'healthy' || svc.health === 'none')
  const isStarting = svc.status === 'running' && svc.health !== 'healthy' && svc.health !== 'none'
  const label = SERVICE_LABELS[svc.service] ?? svc.service

  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="relative flex items-center justify-center w-5 h-5">
        {isStarting ? (
          <Loader2 size={14} className="text-amber-500 animate-spin" />
        ) : (
          <span className={`block size-2.5 rounded-full transition-colors duration-500 ${
            isUp ? 'bg-emerald-500' : svc.status === 'not_found' ? 'bg-neutral-400' : 'bg-red-500'
          }`} />
        )}
      </div>
      <span className={`text-sm transition-colors duration-500 ${
        isUp
          ? 'text-emerald-600 dark:text-emerald-400'
          : isStarting
            ? 'text-amber-600 dark:text-amber-400'
            : 'text-neutral-500 dark:text-neutral-400'
      }`}>
        {label}
      </span>
      <span className="ml-auto text-xs text-neutral-400 dark:text-neutral-500">
        {isUp ? 'Ready' : isStarting ? 'Starting...' : svc.status === 'not_found' ? '' : 'Waiting'}
      </span>
    </div>
  )
}

export function StartupScreen({ onReady }: { onReady: () => void }) {
  const { data: overview } = useQuery({
    queryKey: ['startup-status'],
    queryFn: getRecoveryOverview,
    refetchInterval: 2_000,
    retry: true,
    retryDelay: 1_000,
  })

  const services = overview?.services.details ?? []
  const allReady = REQUIRED_SERVICES.every(name => {
    const svc = services.find(s => s.service === name)
    return svc && svc.status === 'running' && (svc.health === 'healthy' || svc.health === 'none')
  })

  useEffect(() => {
    if (allReady) {
      // Brief delay so user sees the "all green" state before transition
      const timer = setTimeout(onReady, 800)
      return () => clearTimeout(timer)
    }
  }, [allReady, onReady])

  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950 flex items-center justify-center">
      <div className="w-full max-w-sm px-6">
        {/* Logo / title */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-semibold tracking-widest text-accent-700 dark:text-accent-400 uppercase">
            Nova
          </h1>
          <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
            {services.length === 0 ? 'Connecting...' : allReady ? 'Ready' : 'Starting up...'}
          </p>
        </div>

        {/* Service list */}
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-5 py-4 shadow-sm">
          {services.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-4">
              <Loader2 size={16} className="text-neutral-400 animate-spin" />
              <span className="text-sm text-neutral-500 dark:text-neutral-400">
                Waiting for recovery service...
              </span>
            </div>
          ) : (
            <div className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {services.map(svc => (
                <ServiceRow key={svc.service} svc={svc} />
              ))}
            </div>
          )}
        </div>

        {/* Progress bar */}
        {services.length > 0 && (
          <div className="mt-4">
            <div className="h-1.5 w-full rounded-full bg-neutral-200 dark:bg-neutral-800 overflow-hidden">
              <div
                className="h-full rounded-full bg-accent-600 dark:bg-accent-500 transition-all duration-700 ease-out"
                style={{ width: `${(overview?.services.up ?? 0) / (overview?.services.total ?? 1) * 100}%` }}
              />
            </div>
            <p className="mt-1.5 text-center text-xs text-neutral-400 dark:text-neutral-500">
              {overview?.services.up ?? 0} of {overview?.services.total ?? 0} services ready
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
