import { FileCode, ExternalLink } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Section } from './shared'

const SERVICES = [
  { name: 'Orchestrator',   port: 8000, healthPath: '/api/health/live', desc: 'Agent lifecycle, pipeline execution, task queue' },
  { name: 'LLM Gateway',    port: 8001, healthPath: '/v1/health/live',  desc: 'Multi-provider model routing, completions, embeddings' },
  { name: 'Memory Service', port: 8002, healthPath: '/mem/health/live', desc: 'Semantic memory storage and hybrid retrieval' },
  { name: 'Recovery',       port: 8888, healthPath: '/recovery-api/health/live', desc: 'Backup, restore, factory reset, service management' },
] as const

/** Build a direct URL to a service's Swagger docs (bypasses nginx prefix issues). */
function docsUrl(port: number): string {
  return `${window.location.protocol}//${window.location.hostname}:${port}/docs`
}

const ENDPOINTS = [
  { name: 'Orchestrator',   port: 8000, desc: 'Agent lifecycle, pipeline, tasks' },
  { name: 'LLM Gateway',    port: 8001, desc: 'Model routing, completions, embeddings' },
  { name: 'Memory Service', port: 8002, desc: 'Semantic memory, retrieval' },
  { name: 'Chat API',       port: 8080, desc: 'WebSocket streaming bridge' },
  { name: 'Recovery',       port: 8888, desc: 'Backup, restore, factory reset, service management' },
  { name: 'Dashboard',      port: '5173 / 3000', desc: 'Dev (Vite) / Prod (nginx)' },
  { name: 'PostgreSQL',     port: 5432, desc: 'pgvector-enabled database' },
  { name: 'Redis',          port: 6379, desc: 'State, task queue, rate limiting' },
] as const

function useServiceHealth() {
  return useQuery({
    queryKey: ['service-health'],
    queryFn: async () => {
      const results = await Promise.allSettled(
        SERVICES.map(s =>
          fetch(s.healthPath, { signal: AbortSignal.timeout(3000) })
            .then(r => r.ok)
        ),
      )
      return Object.fromEntries(
        SERVICES.map((s, i) => [s.name, results[i].status === 'fulfilled' && (results[i] as PromiseFulfilledResult<boolean>).value])
      ) as Record<string, boolean>
    },
    staleTime: 15_000,
  })
}

export function DeveloperResourcesSection() {
  const { data: health } = useServiceHealth()

  return (
    <Section
      icon={FileCode}
      title="Developer Resources"
      description="API documentation, service health, and endpoint reference."
    >
      {/* Service cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {SERVICES.map(s => {
          const alive = health?.[s.name]
          return (
            <div
              key={s.name}
              className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={
                      'inline-block size-2 rounded-full ' +
                      (health === undefined
                        ? 'bg-neutral-400 dark:bg-neutral-500'
                        : alive ? 'bg-emerald-500' : 'bg-red-500')
                    }
                    title={health === undefined ? 'Checking…' : alive ? 'Healthy' : 'Unreachable'}
                  />
                  <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{s.name}</span>
                </div>
                <span className="text-xs font-mono text-neutral-500 dark:text-neutral-400">:{s.port}</span>
              </div>
              <p className="text-xs text-neutral-500 dark:text-neutral-400">{s.desc}</p>
              <a
                href={docsUrl(s.port)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium text-accent-700 dark:text-accent-400 hover:underline"
              >
                API Docs <ExternalLink size={11} />
              </a>
            </div>
          )
        })}
      </div>

      {/* Endpoint quick-reference */}
      <div>
        <label className="mb-2 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Endpoint Reference</label>
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden text-xs">
          <table className="w-full">
            <thead>
              <tr className="bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400">
                <th className="px-3 py-1.5 text-left font-medium">Service</th>
                <th className="px-3 py-1.5 text-left font-medium font-mono">Port</th>
                <th className="px-3 py-1.5 text-left font-medium">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {ENDPOINTS.map(e => (
                <tr key={e.name} className="text-neutral-700 dark:text-neutral-300">
                  <td className="px-3 py-1.5 font-medium">{e.name}</td>
                  <td className="px-3 py-1.5 font-mono text-neutral-500 dark:text-neutral-400">{e.port}</td>
                  <td className="px-3 py-1.5 text-neutral-500 dark:text-neutral-400">{e.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Section>
  )
}
