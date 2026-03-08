import { useQuery } from '@tanstack/react-query'
import { Shield, CheckCircle, XCircle } from 'lucide-react'
import { Section, ConfigField, type ConfigSectionProps } from './shared'

interface NetworkStatus {
  client_ip: string
  trusted: boolean
}

export function TrustedNetworksSection({ entries, onSave, saving }: ConfigSectionProps) {
  const { data: status } = useQuery<NetworkStatus>({
    queryKey: ['network-status'],
    queryFn: async () => {
      const resp = await fetch('/api/v1/auth/network-status')
      if (!resp.ok) throw new Error('Failed to fetch network status')
      return resp.json()
    },
    refetchInterval: 30_000,
  })

  const trustedNetworks = entries.find(e => e.key === 'trusted_networks')
  const proxyHeader = entries.find(e => e.key === 'trusted_proxy_header')

  const cidrsValue = trustedNetworks?.value != null ? String(trustedNetworks.value) : ''
  const headerValue = proxyHeader?.value != null ? String(proxyHeader.value) : ''

  return (
    <Section
      icon={Shield}
      title="Trusted Networks"
      description="IP ranges that bypass authentication. Requests from these networks are treated as admin — no login required."
    >
      {status && (
        <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
          status.trusted
            ? 'border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400'
            : 'border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400'
        }`}>
          {status.trusted
            ? <CheckCircle size={14} />
            : <XCircle size={14} />
          }
          <span>
            You are connecting from <code className="font-mono text-xs px-1 py-0.5 rounded bg-neutral-200/50 dark:bg-neutral-700/50">{status.client_ip}</code>
            {' — '}
            <strong>{status.trusted ? 'trusted' : 'untrusted'}</strong> network
          </span>
        </div>
      )}

      <ConfigField
        label="Trusted CIDRs"
        configKey="trusted_networks"
        value={cidrsValue}
        multiline
        placeholder="127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,::1/128"
        description="Comma-separated CIDR ranges. Default includes RFC1918 private networks, Tailscale CGNAT (100.64.0.0/10), and localhost. Set to empty to disable (all requests require normal auth)."
        onSave={onSave}
        saving={saving}
      />

      <ConfigField
        label="Proxy header"
        configKey="trusted_proxy_header"
        value={headerValue}
        placeholder="e.g. CF-Connecting-IP, X-Real-IP"
        description="HTTP header containing the real client IP when behind a reverse proxy. Only set this if you have a trusted proxy (Cloudflare, nginx) in front of Nova. Without one, clients could spoof this header."
        onSave={onSave}
        saving={saving}
      />
    </Section>
  )
}
