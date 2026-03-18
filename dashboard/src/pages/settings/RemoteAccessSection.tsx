import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Globe, ExternalLink } from 'lucide-react'
import { getRemoteAccessStatus } from '../../api-recovery'
import { CloudflareWizard, TailscaleWizard, StatusBadge as RemoteStatusBadge } from '../RemoteAccess'
import { Section, Tabs } from '../../components/ui'

export function RemoteAccessSection() {
  const [tab, setTab] = useState('cloudflare')
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
      description={<>Expose Nova securely to the internet via Cloudflare Tunnel, or access from your devices via Tailscale. <a href="https://arialabs.ai/nova/docs/remote-access/" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">Setup guide <ExternalLink size={12} /></a></>}
    >
      <div className="flex gap-4 text-compact mb-3">
        <span className="flex items-center gap-1.5 text-content-tertiary">
          Cloudflare: <RemoteStatusBadge configured={cfStatus.configured} running={cfStatus.container.running} />
        </span>
        <span className="flex items-center gap-1.5 text-content-tertiary">
          Tailscale: <RemoteStatusBadge configured={tsStatus.configured} running={tsStatus.container.running} />
        </span>
      </div>

      <Tabs
        tabs={[
          { id: 'cloudflare', label: 'Cloudflare Tunnel' },
          { id: 'tailscale', label: 'Tailscale' },
        ]}
        activeTab={tab}
        onChange={setTab}
        className="mb-4"
      />

      <div className="max-w-xl">
        {tab === 'cloudflare' && <CloudflareWizard status={cfStatus} onDone={refresh} />}
        {tab === 'tailscale' && <TailscaleWizard status={tsStatus} onDone={refresh} />}
      </div>
    </Section>
  )
}
