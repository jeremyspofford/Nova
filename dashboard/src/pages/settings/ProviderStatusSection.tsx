import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Eye, EyeOff, Save, AlertTriangle } from 'lucide-react'
import { getProviderStatus, testProvider } from '../../api'
import { getEnvVars, patchEnv } from '../../api-recovery'
import { Section } from './shared'

const TYPE_BADGE: Record<string, { label: string; className: string }> = {
  subscription: { label: 'Subscription', className: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
  free:         { label: 'Free',         className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' },
  paid:         { label: 'Paid',         className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400' },
  local:        { label: 'Local',        className: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400' },
}

/** Maps provider slug → .env key for its API credential */
const PROVIDER_ENV_KEY: Record<string, string> = {
  anthropic:    'ANTHROPIC_API_KEY',
  openai:       'OPENAI_API_KEY',
  groq:         'GROQ_API_KEY',
  gemini:       'GEMINI_API_KEY',
  cerebras:     'CEREBRAS_API_KEY',
  openrouter:   'OPENROUTER_API_KEY',
  github:       'GITHUB_TOKEN',
  'claude-max': 'CLAUDE_CODE_OAUTH_TOKEN',
  chatgpt:      'CHATGPT_ACCESS_TOKEN',
}

export function ProviderStatusSection() {
  const queryClient = useQueryClient()

  const { data: providers, isLoading } = useQuery({
    queryKey: ['provider-status'],
    queryFn: getProviderStatus,
    staleTime: 30_000,
  })

  const { data: envVars } = useQuery({
    queryKey: ['env-vars'],
    queryFn: getEnvVars,
    staleTime: 30_000,
  })

  const [testing, setTesting] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; latency_ms: number; error?: string }>>({})
  const [editing, setEditing] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const [showKey, setShowKey] = useState<Record<string, boolean>>({})
  const [restartHint, setRestartHint] = useState(false)

  const handleTest = useCallback(async (slug: string) => {
    setTesting(slug)
    try {
      const result = await testProvider(slug)
      setTestResults(prev => ({ ...prev, [slug]: result }))
    } catch (e) {
      setTestResults(prev => ({ ...prev, [slug]: { ok: false, latency_ms: 0, error: String(e) } }))
    } finally {
      setTesting(null)
    }
  }, [])

  const handleSaveKey = useCallback(async (slug: string) => {
    const envKey = PROVIDER_ENV_KEY[slug]
    const value = drafts[slug]
    if (!envKey || value === undefined) return

    setSaving(slug)
    try {
      await patchEnv({ [envKey]: value })
      setEditing(null)
      setDrafts(prev => { const n = { ...prev }; delete n[slug]; return n })
      setRestartHint(true)
      queryClient.invalidateQueries({ queryKey: ['env-vars'] })
    } catch (e) {
      console.error('Failed to save API key:', e)
    } finally {
      setSaving(null)
    }
  }, [drafts, queryClient])

  return (
    <Section
      icon={Activity}
      title="Provider Status"
      description="LLM providers configured for this instance. Manage API keys and test connectivity."
    >
      {restartHint && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-sm text-amber-700 dark:text-amber-400">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>API key changes require a service restart to take effect. Restart services from the Recovery section or via <code className="text-xs bg-amber-100 dark:bg-amber-900/50 px-1 rounded">make restart</code>.</span>
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading providers…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {(providers ?? []).map(p => {
            const badge = TYPE_BADGE[p.type] ?? TYPE_BADGE.free
            const result = testResults[p.slug]
            const envKey = PROVIDER_ENV_KEY[p.slug]
            const currentMasked = envKey && envVars ? envVars[envKey] ?? '' : ''
            const isEditing = editing === p.slug
            const hasKey = !!currentMasked && currentMasked !== '****'
            const isLocal = p.type === 'local'

            return (
              <div
                key={p.slug}
                className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-3 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={
                        'inline-block size-2 rounded-full ' +
                        (p.available ? 'bg-emerald-500' : 'bg-red-500')
                      }
                      title={p.available ? 'Configured' : 'Not configured'}
                    />
                    <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{p.name}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {!isLocal && envKey && (
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        hasKey
                          ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                          : 'bg-neutral-200 text-neutral-500 dark:bg-neutral-700 dark:text-neutral-400'
                      }`}>
                        {hasKey ? 'Connected' : 'Not configured'}
                      </span>
                    )}
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${badge.className}`}>
                      {badge.label}
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400">
                  <span>{p.model_count} model{p.model_count !== 1 ? 's' : ''}</span>
                  <span className="font-mono truncate max-w-[140px]" title={p.default_model}>{p.default_model}</span>
                </div>

                {/* API key input (non-local providers only) */}
                {envKey && !isLocal && (
                  <div className="space-y-1.5">
                    {isEditing ? (
                      <div className="flex items-center gap-1.5">
                        <div className="relative flex-1">
                          <input
                            type={showKey[p.slug] ? 'text' : 'password'}
                            value={drafts[p.slug] ?? ''}
                            onChange={e => setDrafts(prev => ({ ...prev, [p.slug]: e.target.value }))}
                            placeholder={`Paste ${envKey}`}
                            className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-900 px-2 py-1 pr-7 text-xs text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
                          />
                          <button
                            onClick={() => setShowKey(prev => ({ ...prev, [p.slug]: !prev[p.slug] }))}
                            className="absolute right-1.5 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300"
                          >
                            {showKey[p.slug] ? <EyeOff size={12} /> : <Eye size={12} />}
                          </button>
                        </div>
                        <button
                          onClick={() => handleSaveKey(p.slug)}
                          disabled={saving === p.slug || !drafts[p.slug]?.trim()}
                          className="flex items-center gap-1 rounded-md bg-accent-700 px-2 py-1 text-xs text-white hover:bg-accent-500 disabled:opacity-40"
                        >
                          <Save size={10} />
                          {saving === p.slug ? '…' : 'Save'}
                        </button>
                        <button
                          onClick={() => { setEditing(null); setDrafts(prev => { const n = { ...prev }; delete n[p.slug]; return n }) }}
                          className="text-xs text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between">
                        {hasKey && (
                          <span className="text-xs font-mono text-neutral-500 dark:text-neutral-400">{currentMasked}</span>
                        )}
                        <button
                          onClick={() => setEditing(p.slug)}
                          className="text-xs font-medium text-accent-700 dark:text-accent-400 hover:underline ml-auto"
                        >
                          {hasKey ? 'Change key' : 'Add key'}
                        </button>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <button
                    onClick={() => handleTest(p.slug)}
                    disabled={!p.available || testing === p.slug}
                    className="text-xs font-medium text-accent-700 dark:text-accent-400 hover:underline disabled:opacity-40 disabled:no-underline"
                  >
                    {testing === p.slug ? 'Testing…' : 'Test'}
                  </button>
                  {result && (
                    <span className={`text-xs ${result.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                      {result.ok ? `${result.latency_ms}ms` : result.error ?? 'Failed'}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Section>
  )
}
