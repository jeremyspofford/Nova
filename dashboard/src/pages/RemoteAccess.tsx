import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Globe, Cloud, Shield, CheckCircle2, XCircle, Loader2, ArrowRight, ArrowLeft, Trash2, ExternalLink } from 'lucide-react'
import { getRemoteAccessStatus, patchEnv, manageComposeProfile } from '../api-recovery'
import { updatePlatformConfig } from '../api'
import type { RemoteAccessStatus } from '../api-recovery'
import * as cf from '../lib/cloudflare-api'
import * as ts from '../lib/tailscale-api'

// ── Types ────────────────────────────────────────────────────────────────────

type Tab = 'cloudflare' | 'tailscale'

interface CfWizardState {
  step: number // 0=token, 1=select, 2=provisioning, 3=success
  token: string
  accounts: cf.CfAccount[]
  zones: cf.CfZone[]
  selectedAccount: string
  selectedZone: string
  selectedZoneName: string
  subdomain: string
  tunnelUrl: string
  error: string
  loading: boolean
}

interface TsWizardState {
  step: number // 0=key, 1=provisioning, 2=success
  apiKey: string
  error: string
  loading: boolean
}

const initialCfState: CfWizardState = {
  step: 0, token: '', accounts: [], zones: [],
  selectedAccount: '', selectedZone: '', selectedZoneName: '',
  subdomain: 'nova', tunnelUrl: '', error: '', loading: false,
}

const initialTsState: TsWizardState = {
  step: 0, apiKey: '', error: '', loading: false,
}

// ── Status Badge ─────────────────────────────────────────────────────────────

export function StatusBadge({ configured, running }: { configured: boolean; running: boolean }) {
  if (running) return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 px-2 py-0.5 rounded-full">
      <CheckCircle2 size={12} /> Running
    </span>
  )
  if (configured) return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 px-2 py-0.5 rounded-full">
      <XCircle size={12} /> Stopped
    </span>
  )
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-neutral-500 dark:text-neutral-400 bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 rounded-full">
      Not configured
    </span>
  )
}

// ── Cloudflare Wizard ────────────────────────────────────────────────────────

export function CloudflareWizard({ status, onDone }: { status: RemoteAccessStatus['cloudflare']; onDone: () => void }) {
  const [s, setS] = useState<CfWizardState>(initialCfState)
  const set = (patch: Partial<CfWizardState>) => setS(prev => ({ ...prev, ...patch }))

  const handleVerifyToken = useCallback(async () => {
    set({ loading: true, error: '' })
    try {
      const valid = await cf.verifyToken(s.token.trim())
      if (!valid) { set({ error: 'Invalid API token', loading: false }); return }
      const accounts = await cf.listAccounts(s.token.trim())
      if (accounts.length === 0) { set({ error: 'No accounts found for this token', loading: false }); return }
      set({ accounts, step: 1, loading: false })
      if (accounts.length === 1) {
        set({ selectedAccount: accounts[0].id })
        const zones = await cf.listZones(s.token.trim(), accounts[0].id)
        set({ zones })
      }
    } catch (e: any) {
      set({ error: e.message || 'Failed to verify token', loading: false })
    }
  }, [s.token])

  const handleSelectAccount = useCallback(async (accountId: string) => {
    set({ selectedAccount: accountId, loading: true, error: '' })
    try {
      const zones = await cf.listZones(s.token, accountId)
      set({ zones, loading: false })
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  }, [s.token])

  const handleProvision = useCallback(async () => {
    set({ step: 2, loading: true, error: '' })
    try {
      // 1. Create tunnel
      const tunnel = await cf.createTunnel(s.token, s.selectedAccount, `nova-${s.subdomain}`)

      // 2. Configure route
      const fqdn = s.subdomain ? `${s.subdomain}.${s.selectedZoneName}` : s.selectedZoneName
      await cf.configureTunnelRoute(s.token, s.selectedAccount, tunnel.id, fqdn)

      // 3. Create DNS CNAME
      await cf.createDnsRecord(s.token, s.selectedZone, tunnel.id, s.subdomain, s.selectedZoneName)

      // 4. Get tunnel token and save to .env
      // Also enable auth + trusted proxy header so public traffic requires login
      // while LAN/Tailscale traffic bypasses it automatically
      const tunnelToken = await cf.getTunnelToken(s.token, s.selectedAccount, tunnel.id)
      await patchEnv({
        CLOUDFLARE_TUNNEL_TOKEN: tunnelToken,
        REQUIRE_AUTH: 'true',
        TRUSTED_PROXY_HEADER: 'CF-Connecting-IP',
      })

      // 4b. Also update platform_config so dynamic middleware picks up changes
      await Promise.all([
        updatePlatformConfig('trusted_proxy_header', JSON.stringify('CF-Connecting-IP')),
        updatePlatformConfig('auth.require_auth', JSON.stringify(true)),
      ])

      // 5. Start cloudflared container
      await manageComposeProfile('cloudflare-tunnel', 'start')

      set({ step: 3, tunnelUrl: `https://${fqdn}`, loading: false })
      onDone()
    } catch (e: any) {
      set({ error: e.message || 'Provisioning failed', loading: false })
    }
  }, [s.token, s.selectedAccount, s.selectedZone, s.selectedZoneName, s.subdomain, onDone])

  const handleDisconnect = useCallback(async () => {
    set({ loading: true, error: '' })
    try {
      await manageComposeProfile('cloudflare-tunnel', 'stop')
      await patchEnv({ CLOUDFLARE_TUNNEL_TOKEN: '', TRUSTED_PROXY_HEADER: '' })
      // Clear proxy header in platform_config so middleware stops using it
      await updatePlatformConfig('trusted_proxy_header', JSON.stringify(''))
      setS(initialCfState)
      onDone()
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  }, [onDone])

  // Already running — show status
  if (status.container.running && s.step !== 3) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-4">
          <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 size={18} />
            <span className="font-medium">Cloudflare Tunnel is active</span>
          </div>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Your Nova instance is accessible via Cloudflare Tunnel.
          </p>
        </div>
        <button onClick={handleDisconnect} disabled={s.loading}
          className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors disabled:opacity-50">
          {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
          Disconnect Tunnel
        </button>
        {s.error && <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Step 0: Token */}
      {s.step === 0 && (
        <div className="space-y-3">
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Create a Cloudflare API token at{' '}
            <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" rel="noopener noreferrer"
              className="text-teal-600 dark:text-teal-400 hover:underline inline-flex items-center gap-1">
              dash.cloudflare.com <ExternalLink size={12} />
            </a>
            {' '}with permissions: <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">Account:Cloudflare Tunnel:Edit</code>,{' '}
            <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">Zone:DNS:Edit</code>.
          </p>
          <input type="password" placeholder="Cloudflare API token" value={s.token}
            onChange={e => set({ token: e.target.value, error: '' })}
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm" />
          <button onClick={handleVerifyToken} disabled={!s.token.trim() || s.loading}
            className="flex items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50 transition-colors">
            {s.loading ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            Verify &amp; Continue
          </button>
          <p className="text-xs text-neutral-500 dark:text-neutral-500">
            Your API token is used in the browser only and is never sent to Nova's backend.
          </p>
        </div>
      )}

      {/* Step 1: Select account + zone + subdomain */}
      {s.step === 1 && (
        <div className="space-y-3">
          <button onClick={() => set({ step: 0 })} className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300">
            <ArrowLeft size={12} /> Back
          </button>

          {s.accounts.length > 1 && (
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Account</label>
              <select value={s.selectedAccount} onChange={e => handleSelectAccount(e.target.value)}
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                <option value="">Select account...</option>
                {s.accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
          )}

          {s.zones.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Zone (domain)</label>
              <select value={s.selectedZone}
                onChange={e => {
                  const zone = s.zones.find(z => z.id === e.target.value)
                  set({ selectedZone: e.target.value, selectedZoneName: zone?.name || '' })
                }}
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                <option value="">Select zone...</option>
                {s.zones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
              </select>
            </div>
          )}

          {s.selectedZone && (
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Subdomain</label>
              <div className="flex items-center gap-2">
                <input type="text" value={s.subdomain} onChange={e => set({ subdomain: e.target.value })}
                  className="flex-1 rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm"
                  placeholder="nova" />
                <span className="text-sm text-neutral-500">.{s.selectedZoneName}</span>
              </div>
            </div>
          )}

          <button onClick={handleProvision} disabled={!s.selectedZone || !s.subdomain.trim() || s.loading}
            className="flex items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50 transition-colors">
            {s.loading ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            Create Tunnel
          </button>
        </div>
      )}

      {/* Step 2: Provisioning */}
      {s.step === 2 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-neutral-600 dark:text-neutral-400">
            <Loader2 size={16} className="animate-spin text-teal-600" />
            Provisioning tunnel...
          </div>
          <p className="text-xs text-neutral-500">Creating tunnel, configuring routes, setting up DNS, starting container...</p>
        </div>
      )}

      {/* Step 3: Success */}
      {s.step === 3 && (
        <div className="space-y-3">
          <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-4">
            <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 size={18} />
              <span className="font-medium">Tunnel created successfully!</span>
            </div>
            <p className="mt-2 text-sm">
              Your Nova instance is now accessible at:{' '}
              <a href={s.tunnelUrl} target="_blank" rel="noopener noreferrer"
                className="text-teal-600 dark:text-teal-400 font-medium hover:underline inline-flex items-center gap-1">
                {s.tunnelUrl} <ExternalLink size={12} />
              </a>
            </p>
            <p className="mt-1 text-xs text-neutral-500">It may take a minute for DNS to propagate.</p>
          </div>
          <button onClick={handleDisconnect} disabled={s.loading}
            className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors disabled:opacity-50">
            {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            Disconnect Tunnel
          </button>
        </div>
      )}

      {s.error && <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>}
    </div>
  )
}

// ── Tailscale Wizard ─────────────────────────────────────────────────────────

export function TailscaleWizard({ status, onDone }: { status: RemoteAccessStatus['tailscale']; onDone: () => void }) {
  const [s, setS] = useState<TsWizardState>(initialTsState)
  const set = (patch: Partial<TsWizardState>) => setS(prev => ({ ...prev, ...patch }))

  const handleProvision = useCallback(async () => {
    set({ step: 1, loading: true, error: '' })
    try {
      // 1. Create pre-authorized auth key
      const authKey = await ts.createAuthKey(s.apiKey.trim())

      // 2. Save to .env and start container
      await patchEnv({ TAILSCALE_AUTHKEY: authKey.key })
      await manageComposeProfile('tailscale', 'start')

      set({ step: 2, loading: false })
      onDone()
    } catch (e: any) {
      // If CORS blocked, show helpful message
      const msg = e.message?.includes('Failed to fetch')
        ? 'Tailscale API blocked the request (CORS). You may need to create an auth key manually at login.tailscale.com/admin/settings/keys and paste the TAILSCALE_AUTHKEY in Settings.'
        : e.message || 'Provisioning failed'
      set({ error: msg, loading: false, step: 0 })
    }
  }, [s.apiKey, onDone])

  const handleDisconnect = useCallback(async () => {
    set({ loading: true, error: '' })
    try {
      await manageComposeProfile('tailscale', 'stop')
      await patchEnv({ TAILSCALE_AUTHKEY: '' })
      setS(initialTsState)
      onDone()
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  }, [onDone])

  // Already running
  if (status.container.running && s.step !== 2) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-4">
          <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 size={18} />
            <span className="font-medium">Tailscale is connected</span>
          </div>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Your Nova instance is available on your tailnet as <code className="bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded text-xs">nova</code> via MagicDNS.
          </p>
        </div>
        <button onClick={handleDisconnect} disabled={s.loading}
          className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors disabled:opacity-50">
          {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
          Disconnect Tailscale
        </button>
        {s.error && <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Step 0: API Key */}
      {s.step === 0 && (
        <div className="space-y-3">
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Create a Tailscale API key at{' '}
            <a href="https://login.tailscale.com/admin/settings/keys" target="_blank" rel="noopener noreferrer"
              className="text-teal-600 dark:text-teal-400 hover:underline inline-flex items-center gap-1">
              login.tailscale.com <ExternalLink size={12} />
            </a>
            . The key needs permission to create auth keys.
          </p>
          <input type="password" placeholder="Tailscale API key (tskey-api-...)" value={s.apiKey}
            onChange={e => set({ apiKey: e.target.value, error: '' })}
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm" />
          <button onClick={handleProvision} disabled={!s.apiKey.trim() || s.loading}
            className="flex items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50 transition-colors">
            {s.loading ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            Connect to Tailnet
          </button>
          <p className="text-xs text-neutral-500 dark:text-neutral-500">
            Your API key is used in the browser only. Only the generated auth key is saved to Nova.
          </p>
        </div>
      )}

      {/* Step 1: Provisioning */}
      {s.step === 1 && (
        <div className="flex items-center gap-2 text-sm text-neutral-600 dark:text-neutral-400">
          <Loader2 size={16} className="animate-spin text-teal-600" />
          Creating auth key and starting Tailscale...
        </div>
      )}

      {/* Step 2: Success */}
      {s.step === 2 && (
        <div className="space-y-3">
          <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-4">
            <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 size={18} />
              <span className="font-medium">Tailscale connected!</span>
            </div>
            <p className="mt-2 text-sm">
              Nova is now available on your tailnet via MagicDNS at{' '}
              <code className="bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded text-xs font-medium">nova</code>
            </p>
          </div>
          <button onClick={handleDisconnect} disabled={s.loading}
            className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors disabled:opacity-50">
            {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            Disconnect Tailscale
          </button>
        </div>
      )}

      {s.error && <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export function RemoteAccess() {
  const [tab, setTab] = useState<Tab>('cloudflare')
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
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Globe size={22} className="text-teal-600 dark:text-teal-400" />
        <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">Remote Access</h1>
      </div>

      <p className="text-sm text-neutral-600 dark:text-neutral-400 max-w-2xl">
        Expose your Nova instance securely to the internet via Cloudflare Tunnel, or access it from your personal devices via Tailscale.
      </p>

      {/* Status banner */}
      <div className="flex gap-4">
        <div className="flex items-center gap-2 text-sm">
          <Cloud size={14} className="text-neutral-500" /> Cloudflare: <StatusBadge configured={cfStatus.configured} running={cfStatus.container.running} />
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Shield size={14} className="text-neutral-500" /> Tailscale: <StatusBadge configured={tsStatus.configured} running={tsStatus.container.running} />
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-neutral-200 dark:border-neutral-800">
        <div className="flex gap-4">
          {([
            { key: 'cloudflare' as Tab, label: 'Cloudflare Tunnel', icon: Cloud },
            { key: 'tailscale' as Tab, label: 'Tailscale', icon: Shield },
          ]).map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => setTab(key)}
              className={`flex items-center gap-2 pb-2 px-1 text-sm font-medium border-b-2 transition-colors ${
                tab === key
                  ? 'border-teal-600 dark:border-teal-400 text-teal-600 dark:text-teal-400'
                  : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
              }`}>
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Wizard content */}
      <div className="max-w-xl">
        {tab === 'cloudflare' && <CloudflareWizard status={cfStatus} onDone={refresh} />}
        {tab === 'tailscale' && <TailscaleWizard status={tsStatus} onDone={refresh} />}
      </div>
    </div>
  )
}
