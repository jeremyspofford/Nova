import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Globe } from 'lucide-react'
import { getRemoteAccessStatus } from '../../api-recovery'
import { CloudflareWizard, TailscaleWizard, StatusBadge as RemoteStatusBadge } from '../RemoteAccess'
import { Section } from './shared'

export function RemoteAccessSection() {
  const [tab, setTab] = useState<'cloudflare' | 'tailscale'>('cloudflare')
  const queryClient = useQueryClient()

  const { data: status } = useQuery({
    queryKey: ['remote-access-status'],
    queryFn: getRemoteAccessStatus,
    refetchInterval: 10_000,
  })

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['remote-access-status'] })
  }, [queryClient])

  const cfStatus = status?.cloudflare ?? { configured: false, container: { name: 'cloudflared', container_name: null, status: 'not_found', health: 'unknown', running: false } }
  const tsStatus = status?.tailscale ?? { configured: false, container: { name: 'tailscale', container_name: null, status: 'not_found', health: 'unknown', running: false } }

  return (
    <Section
      icon={Globe}
      title="Remote Access"
      description="Expose Nova securely to the internet via Cloudflare Tunnel, or access from your devices via Tailscale."
    >
      <div className="flex gap-4 text-sm mb-3">
        <span className="flex items-center gap-1.5 text-neutral-500 dark:text-neutral-400">
          Cloudflare: <RemoteStatusBadge configured={cfStatus.configured} running={cfStatus.container.running} />
        </span>
        <span className="flex items-center gap-1.5 text-neutral-500 dark:text-neutral-400">
          Tailscale: <RemoteStatusBadge configured={tsStatus.configured} running={tsStatus.container.running} />
        </span>
      </div>

      <div className="border-b border-neutral-200 dark:border-neutral-800 mb-4">
        <div className="flex gap-4">
          {([
            { key: 'cloudflare' as const, label: 'Cloudflare Tunnel' },
            { key: 'tailscale' as const, label: 'Tailscale' },
          ]).map(({ key, label }) => (
            <button key={key} onClick={() => setTab(key)}
              className={`pb-2 px-1 text-sm font-medium border-b-2 transition-colors ${
                tab === key
                  ? 'border-teal-600 dark:border-teal-400 text-teal-600 dark:text-teal-400'
                  : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
              }`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-xl">
        {tab === 'cloudflare' && <CloudflareWizard status={cfStatus} onDone={refresh} />}
        {tab === 'tailscale' && <TailscaleWizard status={tsStatus} onDone={refresh} />}
      </div>
    </Section>
  )
}
