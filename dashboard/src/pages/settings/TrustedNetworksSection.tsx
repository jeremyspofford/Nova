import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Shield, CheckCircle, XCircle, Eye, EyeOff, Save } from 'lucide-react'
import { Section, ConfigField, type ConfigSectionProps } from './shared'
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

  // Google OAuth — stored in .env via recovery service
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

        {/* Enforce Authentication toggle */}
        <div className="flex items-center justify-between">
          <div>
            <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Enforce Authentication</label>
            <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
              When enabled, requests from untrusted networks require login. Trusted networks always bypass auth.
            </p>
          </div>
          <button
            onClick={() => onSave('auth.require_auth', JSON.stringify(requireAuthValue !== 'true'))}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
              requireAuthValue === 'true'
                ? 'bg-accent-600'
                : 'bg-neutral-300 dark:bg-neutral-600'
            }`}
          >
            <span className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform duration-200 ${
              requireAuthValue === 'true' ? 'translate-x-5' : 'translate-x-0'
            }`} />
          </button>
        </div>

        {/* Registration Mode */}
        <div>
          <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Registration Mode</label>
          <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5 mb-1.5">
            Controls how new users can create accounts.
          </p>
          <select
            value={regModeValue}
            onChange={e => onSave('auth.registration_mode', JSON.stringify(e.target.value))}
            disabled={saving}
            className="w-full max-w-xs rounded-lg border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
          >
            <option value="invite">Invite only</option>
            <option value="open">Open registration</option>
            <option value="admin">Admin creates accounts</option>
          </select>
        </div>

        {/* Google OAuth */}
        <div className="space-y-2 pt-2 border-t border-neutral-100 dark:border-neutral-800">
          <div>
            <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">Google OAuth</label>
            <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
              Enable "Sign in with Google". Requires a Google Cloud OAuth 2.0 Client ID. Changes require a service restart.
            </p>
          </div>

          <div>
            <label className="text-[11px] text-neutral-500 dark:text-neutral-400">Client ID</label>
            <input
              type="text"
              value={oauthDrafts.id ?? googleClientId}
              onChange={e => setOauthDrafts(prev => ({ ...prev, id: e.target.value }))}
              placeholder="123456789.apps.googleusercontent.com"
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-1.5 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
            />
          </div>

          <div>
            <label className="text-[11px] text-neutral-500 dark:text-neutral-400">Client Secret</label>
            <div className="relative">
              <input
                type={showSecret ? 'text' : 'password'}
                value={oauthDrafts.secret ?? googleClientSecret}
                onChange={e => setOauthDrafts(prev => ({ ...prev, secret: e.target.value }))}
                placeholder="GOCSPX-..."
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-1.5 pr-8 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
              />
              <button
                onClick={() => setShowSecret(!showSecret)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300"
              >
                {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          {oauthDirty && (
            <button
              onClick={handleOauthSave}
              disabled={oauthSaving}
              className="flex items-center gap-1 rounded-md bg-accent-700 px-3 py-1.5 text-xs text-white hover:bg-accent-500 disabled:opacity-40"
            >
              <Save size={12} />
              {oauthSaving ? 'Saving…' : 'Save OAuth Config'}
            </button>
          )}
        </div>
      </Section>

      {/* Trusted Networks section */}
      <Section
        icon={Shield}
        title="Trusted Networks"
        description="IP ranges that bypass authentication. Requests from these networks are treated as admin — no login required."
      >
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
    </>
  )
}
