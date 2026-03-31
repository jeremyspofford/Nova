import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Shield, CheckCircle2, Loader2, ExternalLink, Power, PowerOff,
} from 'lucide-react'
import { getServiceStatus, manageComposeProfile } from '../../api-recovery'
import type { ServiceStatus } from '../../api-recovery'
import { Section, Button } from '../../components/ui'
import { ServiceStatusBadge } from './shared'

function useVaultwardenStatus() {
  return useQuery({
    queryKey: ['vaultwarden-status'],
    queryFn: async (): Promise<{ found: boolean; running: boolean; health: string }> => {
      const services = await getServiceStatus()
      const vw = services.find(
        (s: ServiceStatus) => s.service === 'vaultwarden' || s.container_name?.includes('vaultwarden'),
      )
      if (!vw) return { found: false, running: false, health: 'unknown' }
      const running = vw.status === 'running'
      return { found: true, running, health: vw.health }
    },
    refetchInterval: 10_000,
  })
}

export function VaultwardenSection() {
  const queryClient = useQueryClient()
  const { data: status } = useVaultwardenStatus()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const isRunning = status?.running ?? false
  const isHealthy = status?.health === 'healthy'

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['vaultwarden-status'] })
  }, [queryClient])

  const handleEnable = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      await manageComposeProfile('secrets', 'start')
      // Give the container a moment to start before refreshing status
      setTimeout(refresh, 3000)
    } catch (e: any) {
      setError(e.message || 'Failed to start Vaultwarden')
    } finally {
      setLoading(false)
    }
  }, [refresh])

  const handleDisable = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      await manageComposeProfile('secrets', 'stop')
      setTimeout(refresh, 2000)
    } catch (e: any) {
      setError(e.message || 'Failed to stop Vaultwarden')
    } finally {
      setLoading(false)
    }
  }, [refresh])

  return (
    <Section
      icon={Shield}
      title="Secrets Manager"
      description="Self-hosted Vaultwarden instance for managing secrets and credentials. Bitwarden-compatible."
      collapsible
      defaultOpen={false}
    >
      {isRunning ? (
        <div className="space-y-4">
          <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-4">
            <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 size={18} />
              <span className="font-medium">Vaultwarden is running</span>
            </div>
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
              Your self-hosted secrets manager is active and{' '}
              {isHealthy ? 'healthy' : 'starting up'}.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-neutral-500 dark:text-neutral-500">Status:</span>
            <ServiceStatusBadge configured={true} running={isRunning} />
          </div>

          <div className="flex items-center gap-3">
            <a
              href="http://localhost:8222"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-md border border-teal-600 text-teal-600 dark:text-teal-400 dark:border-teal-600 px-3 py-1.5 text-sm font-medium hover:bg-teal-50 dark:hover:bg-teal-900/20 transition-colors"
            >
              Open Vaultwarden <ExternalLink size={14} />
            </a>

            <Button
              variant="danger"
              size="sm"
              loading={loading}
              onClick={handleDisable}
              icon={<PowerOff size={14} />}
            >
              Disable
            </Button>
          </div>

          <p className="text-xs text-neutral-500 dark:text-neutral-500">
            Web vault available at{' '}
            <code className="bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">
              http://localhost:8222
            </code>
            . Use any Bitwarden-compatible client to connect.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 p-4">
            <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
              Built-in Secrets Manager
            </p>
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
              Vaultwarden is a lightweight, self-hosted, Bitwarden-compatible password and secrets
              manager. Enable it to securely store API keys, credentials, and other sensitive data
              with a familiar Bitwarden interface.
            </p>
            <ul className="mt-2 text-sm text-neutral-600 dark:text-neutral-400 space-y-1">
              <li className="flex items-start gap-2">
                <span className="text-teal-600 dark:text-teal-400 mt-0.5">-</span>
                Full Bitwarden web vault UI
              </li>
              <li className="flex items-start gap-2">
                <span className="text-teal-600 dark:text-teal-400 mt-0.5">-</span>
                Compatible with all Bitwarden browser extensions and mobile apps
              </li>
              <li className="flex items-start gap-2">
                <span className="text-teal-600 dark:text-teal-400 mt-0.5">-</span>
                Data stays on your machine (localhost only, port 8222)
              </li>
            </ul>
          </div>

          <Button
            size="sm"
            loading={loading}
            onClick={handleEnable}
            icon={<Power size={14} />}
          >
            Enable Secrets Manager
          </Button>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </Section>
  )
}
