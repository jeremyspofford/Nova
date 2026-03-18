import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  MessageSquare, CheckCircle2, Loader2, Trash2,
  ExternalLink, ArrowRight, ArrowLeft, AlertTriangle,
} from 'lucide-react'
import { getChatIntegrationsStatus, patchEnv, manageComposeProfile, restartService } from '../../api-recovery'
import type { ChatIntegrationsStatus } from '../../api-recovery'
import { Section, Tabs } from '../../components/ui'
import { ServiceStatusBadge } from './shared'

// ── Telegram Setup ────────────────────────────────────────────────────────────

interface TelegramState {
  token: string
  loading: boolean
  error: string
}

function TelegramSetup({
  status,
  slackConfigured,
  onDone,
}: {
  status: ChatIntegrationsStatus['telegram']
  slackConfigured: boolean
  onDone: () => void
}) {
  const [s, setS] = useState<TelegramState>({ token: '', loading: false, error: '' })
  const set = (patch: Partial<TelegramState>) => setS(prev => ({ ...prev, ...patch }))

  const handleConnect = useCallback(async () => {
    set({ loading: true, error: '' })
    try {
      await patchEnv({ TELEGRAM_BOT_TOKEN: s.token.trim() })
      await manageComposeProfile('bridges', 'start')
      set({ token: '', loading: false })
      onDone()
    } catch (e: any) {
      set({ error: e.message || 'Failed to connect', loading: false })
    }
  }, [s.token, onDone])

  const handleDisconnect = useCallback(async () => {
    set({ loading: true, error: '' })
    try {
      await patchEnv({ TELEGRAM_BOT_TOKEN: '' })
      if (slackConfigured) {
        await restartService('chat-bridge')
      } else {
        await manageComposeProfile('bridges', 'stop')
      }
      set({ token: '', loading: false })
      onDone()
    } catch (e: any) {
      set({ error: e.message || 'Failed to disconnect', loading: false })
    }
  }, [slackConfigured, onDone])

  if (status.container.running && status.configured) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-4">
          <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 size={18} />
            <span className="font-medium">Telegram bot is active</span>
          </div>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Your Telegram bot is connected and relaying messages to Nova.
          </p>
        </div>
        <button onClick={handleDisconnect} disabled={s.loading}
          className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors disabled:opacity-50">
          {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
          Disconnect Bot
        </button>
        {s.error && <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Create a Telegram bot via{' '}
        <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer"
          className="text-teal-600 dark:text-teal-400 hover:underline inline-flex items-center gap-1">
          @BotFather <ExternalLink size={12} />
        </a>
        {' '}and paste the bot token below.
      </p>
      <input
        type="password"
        placeholder="Telegram bot token"
        value={s.token}
        onChange={e => set({ token: e.target.value, error: '' })}
        className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm"
      />
      <button onClick={handleConnect} disabled={!s.token.trim() || s.loading}
        className="flex items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50 transition-colors">
        {s.loading ? <Loader2 size={14} className="animate-spin" /> : null}
        Connect
      </button>
      <p className="text-xs text-neutral-500 dark:text-neutral-500">
        The token is stored in your Nova <code className="bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">.env</code> file.
      </p>
      {s.error && <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>}
    </div>
  )
}

// ── Slack Setup Wizard ────────────────────────────────────────────────────────

interface SlackWizardState {
  step: number // 0=create app, 1=bot token, 2=app token + connect, 3=success
  botToken: string
  appToken: string
  loading: boolean
  error: string
}

const initialSlackState: SlackWizardState = {
  step: 0, botToken: '', appToken: '', loading: false, error: '',
}

function SlackSetup({
  status,
  telegramConfigured,
  onDone,
}: {
  status: ChatIntegrationsStatus['slack']
  telegramConfigured: boolean
  onDone: () => void
}) {
  const [s, setS] = useState<SlackWizardState>(initialSlackState)
  const set = (patch: Partial<SlackWizardState>) => setS(prev => ({ ...prev, ...patch }))

  const handleConnect = useCallback(async () => {
    set({ loading: true, error: '' })
    try {
      await patchEnv({
        SLACK_BOT_TOKEN: s.botToken.trim(),
        SLACK_APP_TOKEN: s.appToken.trim(),
      })
      await manageComposeProfile('bridges', 'start')
      set({ step: 3, loading: false })
      onDone()
    } catch (e: any) {
      set({ error: e.message || 'Failed to connect', loading: false })
    }
  }, [s.botToken, s.appToken, onDone])

  const handleDisconnect = useCallback(async () => {
    set({ loading: true, error: '' })
    try {
      await patchEnv({ SLACK_BOT_TOKEN: '', SLACK_APP_TOKEN: '' })
      if (telegramConfigured) {
        await restartService('chat-bridge')
      } else {
        await manageComposeProfile('bridges', 'stop')
      }
      setS(initialSlackState)
      onDone()
    } catch (e: any) {
      set({ error: e.message || 'Failed to disconnect', loading: false })
    }
  }, [telegramConfigured, onDone])

  if (status.container.running && status.configured && s.step !== 3) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-4">
          <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 size={18} />
            <span className="font-medium">Slack bot is active</span>
          </div>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Your Slack bot is connected and relaying messages to Nova.
          </p>
        </div>
        <button onClick={handleDisconnect} disabled={s.loading}
          className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors disabled:opacity-50">
          {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
          Disconnect Bot
        </button>
        {s.error && <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3">
        <div className="flex items-start gap-2">
          <AlertTriangle size={16} className="text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
          <p className="text-sm text-amber-800 dark:text-amber-300">
            Slack adapter is in early access. You can configure tokens now — the bridge will activate them once the adapter is fully implemented.
          </p>
        </div>
      </div>

      {s.step === 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Step 1: Create a Slack App</p>
          <ol className="text-sm text-neutral-600 dark:text-neutral-400 space-y-2 list-decimal list-inside">
            <li>
              Go to{' '}
              <a href="https://api.slack.com/apps" target="_blank" rel="noopener noreferrer"
                className="text-teal-600 dark:text-teal-400 hover:underline inline-flex items-center gap-1">
                api.slack.com/apps <ExternalLink size={12} />
              </a>
              {' '}and click <strong>Create New App</strong> → <strong>From scratch</strong>
            </li>
            <li>Name it (e.g. "Nova") and select your workspace</li>
            <li>
              Under <strong>OAuth &amp; Permissions</strong>, add bot scopes:{' '}
              <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">chat:write</code>,{' '}
              <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">app_mentions:read</code>,{' '}
              <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">im:history</code>,{' '}
              <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">im:read</code>,{' '}
              <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">im:write</code>
            </li>
            <li>Install the app to your workspace</li>
            <li>Under <strong>Socket Mode</strong>, enable it and create an app-level token with{' '}
              <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">connections:write</code> scope</li>
          </ol>
          <button onClick={() => set({ step: 1 })}
            className="flex items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 transition-colors">
            <ArrowRight size={14} />
            I've created the app
          </button>
        </div>
      )}

      {s.step === 1 && (
        <div className="space-y-3">
          <button onClick={() => set({ step: 0 })} className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300">
            <ArrowLeft size={12} /> Back
          </button>
          <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Step 2: Bot Token</p>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Copy the <strong>Bot User OAuth Token</strong> from <strong>OAuth &amp; Permissions</strong>. It starts with{' '}
            <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">xoxb-</code>.
          </p>
          <input
            type="password"
            placeholder="xoxb-..."
            value={s.botToken}
            onChange={e => set({ botToken: e.target.value, error: '' })}
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm"
          />
          <button onClick={() => set({ step: 2 })} disabled={!s.botToken.trim()}
            className="flex items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50 transition-colors">
            <ArrowRight size={14} />
            Next
          </button>
        </div>
      )}

      {s.step === 2 && (
        <div className="space-y-3">
          <button onClick={() => set({ step: 1 })} className="flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300">
            <ArrowLeft size={12} /> Back
          </button>
          <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Step 3: App-Level Token</p>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Copy the <strong>App-Level Token</strong> from <strong>Basic Information → App-Level Tokens</strong>. It starts with{' '}
            <code className="text-xs bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">xapp-</code>.
          </p>
          <input
            type="password"
            placeholder="xapp-..."
            value={s.appToken}
            onChange={e => set({ appToken: e.target.value, error: '' })}
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm"
          />
          <button onClick={handleConnect} disabled={!s.appToken.trim() || s.loading}
            className="flex items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50 transition-colors">
            {s.loading ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            Connect to Slack
          </button>
          <p className="text-xs text-neutral-500 dark:text-neutral-500">
            Both tokens are stored in your Nova <code className="bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 rounded">.env</code> file.
          </p>
        </div>
      )}

      {s.step === 3 && (
        <div className="space-y-3">
          <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-4">
            <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 size={18} />
              <span className="font-medium">Slack tokens saved!</span>
            </div>
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
              Tokens are configured. The Slack adapter will activate once fully implemented in the chat-bridge.
            </p>
          </div>
          <button onClick={handleDisconnect} disabled={s.loading}
            className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors disabled:opacity-50">
            {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            Remove Tokens
          </button>
        </div>
      )}

      {s.error && <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>}
    </div>
  )
}

// ── Section ───────────────────────────────────────────────────────────────────

export function ChatIntegrationsSection() {
  const [tab, setTab] = useState('telegram')
  const queryClient = useQueryClient()

  const { data: status } = useQuery({
    queryKey: ['chat-integrations-status'],
    queryFn: getChatIntegrationsStatus,
    refetchInterval: 10_000,
  })

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['chat-integrations-status'] })
  }, [queryClient])

  const defaultAdapter = { configured: false, container: { name: 'chat-bridge', container_name: null, status: 'not_found', health: 'unknown', running: false } }
  const tgStatus = status?.telegram ?? defaultAdapter
  const slackStatus = status?.slack ?? defaultAdapter

  return (
    <Section
      icon={MessageSquare}
      title="Chat Integrations"
      description={<>Connect Nova to external chat platforms. Messages are relayed through the chat-bridge service. <a href="https://arialabs.ai/nova/docs/services/chat-bridge/" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">Setup guide <ExternalLink size={12} /></a></>}
    >
      <div className="flex gap-4 text-compact mb-3">
        <span className="flex items-center gap-1.5 text-content-tertiary">
          Telegram: <ServiceStatusBadge configured={tgStatus.configured} running={tgStatus.container.running} />
        </span>
        <span className="flex items-center gap-1.5 text-content-tertiary">
          Slack: <ServiceStatusBadge configured={slackStatus.configured} running={slackStatus.container.running} />
        </span>
      </div>

      <Tabs
        tabs={[
          { id: 'telegram', label: 'Telegram' },
          { id: 'slack', label: 'Slack' },
        ]}
        activeTab={tab}
        onChange={setTab}
        className="mb-4"
      />

      <div className="max-w-xl">
        {tab === 'telegram' && <TelegramSetup status={tgStatus} slackConfigured={slackStatus.configured} onDone={refresh} />}
        {tab === 'slack' && <SlackSetup status={slackStatus} telegramConfigured={tgStatus.configured} onDone={refresh} />}
      </div>
    </Section>
  )
}
