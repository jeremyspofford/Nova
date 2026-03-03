import { useQuery } from '@tanstack/react-query'
import { getModels } from '../api'

// Group models by the provider prefix (everything before the first '/')
function groupByProvider(ids: string[]): Record<string, string[]> {
  const groups: Record<string, string[]> = {}
  for (const id of ids) {
    const provider = id.includes('/') ? id.split('/')[0] : 'local'
    ;(groups[provider] ??= []).push(id)
  }
  return groups
}

export function Models() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['models'],
    queryFn: getModels,
    staleTime: 60_000,   // model list rarely changes — cache for 1 min
  })

  const models = data?.data ?? []
  const groups = groupByProvider(models.map(m => m.id))
  const providerOrder = ['claude-max', 'openai', 'chatgpt', 'groq', 'gemini', 'cerebras', 'openrouter', 'github']
  const sorted = [
    ...providerOrder.filter(p => groups[p]),
    ...Object.keys(groups).filter(p => !providerOrder.includes(p)).sort(),
  ]

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      <div className="flex items-baseline gap-3">
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Models</h1>
        {models.length > 0 && (
          <span className="text-sm text-neutral-500 dark:text-neutral-400">{models.length} registered</span>
        )}
      </div>

      {isLoading && <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading…</p>}
      {error && <p className="text-sm text-red-600 dark:text-red-400">Failed to load models: {String(error)}</p>}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sorted.map(provider => (
          <div key={provider} className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-accent-700 dark:text-accent-400">{provider}</p>
            <ul className="space-y-1.5">
              {groups[provider].map(id => (
                <li key={id} className="font-mono text-xs text-neutral-500 dark:text-neutral-400 truncate" title={id}>
                  {id}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  )
}
