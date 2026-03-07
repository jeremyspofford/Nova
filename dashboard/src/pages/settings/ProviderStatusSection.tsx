import { useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'
import { getProviderStatus, testProvider } from '../../api'
import { Section } from './shared'

const TYPE_BADGE: Record<string, { label: string; className: string }> = {
  subscription: { label: 'Subscription', className: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
  free:         { label: 'Free',         className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' },
  paid:         { label: 'Paid',         className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400' },
  local:        { label: 'Local',        className: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400' },
}

export function ProviderStatusSection() {
  const { data: providers, isLoading } = useQuery({
    queryKey: ['provider-status'],
    queryFn: getProviderStatus,
    staleTime: 30_000,
  })

  const [testing, setTesting] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; latency_ms: number; error?: string }>>({})

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

  return (
    <Section
      icon={Activity}
      title="Provider Status"
      description="LLM providers configured for this instance. Test connectivity with each provider."
    >
      {isLoading ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading providers…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {(providers ?? []).map(p => {
            const badge = TYPE_BADGE[p.type] ?? TYPE_BADGE.free
            const result = testResults[p.slug]
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
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${badge.className}`}>
                    {badge.label}
                  </span>
                </div>

                <div className="flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400">
                  <span>{p.model_count} model{p.model_count !== 1 ? 's' : ''}</span>
                  <span className="font-mono truncate max-w-[140px]" title={p.default_model}>{p.default_model}</span>
                </div>

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
