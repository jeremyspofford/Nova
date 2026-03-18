import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Shield, CheckCircle, XCircle, Eye, EyeOff, Save } from 'lucide-react'
import { Section, Button, Input, Select, Toggle } from '../../components/ui'
import { ConfigField, type ConfigSectionProps } from './shared'
import { getEnvVars, patchEnv } from '../../api-recovery'

interface NetworkStatus {
  client_ip: string
  trusted: boolean
}

export function TrustedNetworksSection({ entries, onSave, saving }: ConfigSectionProps) {
  const queryClient = useQueryClient()

  const { data: status } = useQuery<NetworkStatus>({
    queryKey: ['network-status'],
    queryFn: async () => {
      const resp = await fetch('/api/v1/auth/network-status')
      if (!resp.ok) throw new Error('Failed to fetch network status')
      return resp.json()
    },
    refetchInterval: 30_000,
  })

  const { data: envVars } = useQuery({
    queryKey: ['env-vars'],
    queryFn: getEnvVars,
    staleTime: 30_000,
  })

  const trustedNetworks = entries.find(e => e.key === 'trusted_networks')
  const proxyHeader = entries.find(e => e.key === 'trusted_proxy_header')
  const requireAuth = entries.find(e => e.key === 'auth.require_auth')
  const registrationMode = entries.find(e => e.key === 'auth.registration_mode')

  const cidrsValue = trustedNetworks?.value != null ? String(trustedNetworks.value) : ''
  const headerValue = proxyHeader?.value != null ? String(proxyHeader.value) : ''
  const requireAuthValue = requireAuth?.value != null ? String(requireAuth.value) : 'true'
  const regModeValue = registrationMode?.value != null ? String(registrationMode.value) : 'invite'

  // Google OAuth
  const googleClientId = envVars?.GOOGLE_CLIENT_ID ?? ''
  const googleClientSecret = envVars?.GOOGLE_CLIENT_SECRET ?? ''
  const [oauthDrafts, setOauthDrafts] = useState<{ id?: string; secret?: string }>({})
  const [oauthSaving, setOauthSaving] = useState(false)
  const [showSecret, setShowSecret] = useState(false)

  const oauthDirty = (oauthDrafts.id !== undefined && oauthDrafts.id !== googleClientId)
    || (oauthDrafts.secret !== undefined && oauthDrafts.secret !== googleClientSecret)

  const handleOauthSave = useCallback(async () => {
    setOauthSaving(true)
    try {
      const updates: Record<string, string> = {}
      if (oauthDrafts.id !== undefined) updates.GOOGLE_CLIENT_ID = oauthDrafts.id
      if (oauthDrafts.secret !== undefined) updates.GOOGLE_CLIENT_SECRET = oauthDrafts.secret
      await patchEnv(updates)
      setOauthDrafts({})
      queryClient.invalidateQueries({ queryKey: ['env-vars'] })
    } catch (e) {
      console.error('Failed to save OAuth config:', e)
    } finally {
      setOauthSaving(false)
    }
  }, [oauthDrafts, queryClient])

  return (
    <>
      {/* Authentication section */}
      <Section
        icon={Shield}
        title="Authentication"
        description="Control who can access this Nova instance without logging in."
      >
        {status && (
          <div className={`flex items-center gap-2 rounded-sm border px-3 py-2 text-compact ${
            status.trusted
              ? 'border-emerald-200 dark:border-emerald-800 bg-success-dim text-emerald-700 dark:text-emerald-400'
              : 'border-amber-200 dark:border-amber-800 bg-warning-dim text-amber-700 dark:text-amber-400'
          }`}>
            {status.trusted ? <CheckCircle size={14} /> : <XCircle size={14} />}
            <span>
              You are connecting from <code className="font-mono text-caption px-1 py-0.5 rounded-xs bg-surface-elevated">{status.client_ip}</code>
              {' -- '}
              <strong>{status.trusted ? 'trusted' : 'untrusted'}</strong> network
            </span>
          </div>
        )}

        {/* Enforce Authentication toggle */}
        <div className="flex items-center justify-between">
          <div>
            <label className="text-caption font-medium text-content-secondary">Enforce Authentication</label>
            <p className="text-caption text-content-tertiary mt-0.5">
              When enabled, requests from untrusted networks require login. Trusted networks always bypass auth.
            </p>
          </div>
          <Toggle
            checked={requireAuthValue === 'true'}
            onChange={(checked) => onSave('auth.require_auth', JSON.stringify(checked))}
            disabled={saving}
          />
        </div>

        {/* Registration Mode */}
        <Select
          label="Registration Mode"
          description="Controls how new users can create accounts."
          value={regModeValue}
          onChange={e => onSave('auth.registration_mode', JSON.stringify(e.target.value))}
          disabled={saving}
          items={[
            { value: 'invite', label: 'Invite only' },
            { value: 'open', label: 'Open registration' },
            { value: 'admin', label: 'Admin creates accounts' },
          ]}
          className="max-w-xs"
        />

        {/* Google OAuth */}
        <div className="space-y-2 pt-2 border-t border-border-subtle">
          <div>
            <label className="text-caption font-medium text-content-secondary">Google OAuth</label>
            <p className="text-caption text-content-tertiary mt-0.5">
              Enable "Sign in with Google". Requires a Google Cloud OAuth 2.0 Client ID. Changes require a service restart.
            </p>
          </div>

          <Input
            label="Client ID"
            value={oauthDrafts.id ?? googleClientId}
            onChange={e => setOauthDrafts(prev => ({ ...prev, id: e.target.value }))}
            placeholder="123456789.apps.googleusercontent.com"
          />

          <div>
            <label className="mb-1.5 block text-caption font-medium text-content-secondary">Client Secret</label>
            <div className="relative">
              <input
                type={showSecret ? 'text' : 'password'}
                value={oauthDrafts.secret ?? googleClientSecret}
                onChange={e => setOauthDrafts(prev => ({ ...prev, secret: e.target.value }))}
                placeholder="GOCSPX-..."
                className="h-9 w-full rounded-sm border border-border bg-surface-input px-3 pr-8 text-compact text-content-primary placeholder:text-content-tertiary outline-none focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 transition-colors"
              />
              <button
                onClick={() => setShowSecret(!showSecret)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-primary transition-colors"
              >
                {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          {oauthDirty && (
            <Button
              size="sm"
              onClick={handleOauthSave}
              loading={oauthSaving}
              icon={<Save size={12} />}
            >
              Save OAuth Config
            </Button>
          )}
        </div>
      </Section>

      {/* Trusted Networks section */}
      <Section
        icon={Shield}
        title="Trusted Networks"
        description="IP ranges that bypass authentication. Requests from these networks are treated as admin -- no login required."
      >
        <ConfigField
          label="Trusted CIDRs"
          configKey="trusted_networks"
          value={cidrsValue}
          multiline
          placeholder="127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,::1/128"
          description="Comma-separated CIDR ranges. Default includes RFC1918 private networks, Tailscale CGNAT (100.64.0.0/10), and localhost."
          onSave={onSave}
          saving={saving}
        />

        <ConfigField
          label="Proxy header"
          configKey="trusted_proxy_header"
          value={headerValue}
          placeholder="e.g. CF-Connecting-IP, X-Real-IP"
          description="HTTP header containing the real client IP when behind a reverse proxy."
          onSave={onSave}
          saving={saving}
        />
      </Section>
    </>
  )
}
