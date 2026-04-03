import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FlaskConical, Trophy, Clock, Hash, ChevronDown } from 'lucide-react'
import { apiFetch } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import { Card, EmptyState, Select } from '../components/ui'
import clsx from 'clsx'

// ── Types ────────────────────────────────────────────────────────────────────

type QueryTypeBreakdown = {
  precision_at_5: number
  mrr: number
  avg_latency_ms: number
  n: number
}

type BenchmarkSummary = {
  type: 'summary'
  provider: string
  precision_at_5: number
  mrr: number
  avg_latency_ms: number
  total_tokens: number
  by_query_type: Record<string, QueryTypeBreakdown>
}

type BenchmarkRun = {
  file: string
  summaries: BenchmarkSummary[]
  per_query: unknown[]
}

type BenchmarkResponse = {
  runs: BenchmarkRun[]
  latest: BenchmarkRun | null
}

// ── Provider colors ──────────────────────────────────────────────────────────

const PROVIDER_COLORS: Record<string, { bg: string; text: string; bar: string }> = {
  engram:   { bg: 'bg-teal-500/15',    text: 'text-teal-700 dark:text-teal-400',    bar: 'bg-teal-500' },
  pgvector: { bg: 'bg-stone-500/15',   text: 'text-stone-700 dark:text-stone-400',  bar: 'bg-stone-500' },
  mem0:     { bg: 'bg-amber-500/15',   text: 'text-amber-700 dark:text-amber-400',  bar: 'bg-amber-500' },
  markdown: { bg: 'bg-emerald-500/15', text: 'text-emerald-700 dark:text-emerald-400', bar: 'bg-emerald-500' },
}

const DEFAULT_COLOR = { bg: 'bg-blue-500/15', text: 'text-blue-700 dark:text-blue-400', bar: 'bg-blue-500' }

function getProviderColor(name: string) {
  return PROVIDER_COLORS[name.toLowerCase()] ?? DEFAULT_COLOR
}

// ── Help entries ─────────────────────────────────────────────────────────────

const HELP_ENTRIES = [
  { term: 'Precision@5', definition: 'Fraction of the top 5 retrieved results that are relevant. Higher is better (max 1.0).' },
  { term: 'MRR', definition: 'Mean Reciprocal Rank — measures how early the first relevant result appears. 1.0 means it is always first.' },
  { term: 'Latency', definition: 'Average response time in milliseconds for the memory provider to return results.' },
  { term: 'Tokens', definition: 'Total LLM tokens consumed by the judge for scoring results during the benchmark.' },
  { term: 'Query Types', definition: 'Test cases are grouped by type: factual (facts), preference (user preferences), multi_session (cross-session), temporal (time-sensitive).' },
]

// ── Query type labels ────────────────────────────────────────────────────────

const QUERY_TYPE_LABELS: Record<string, string> = {
  factual: 'Factual',
  preference: 'Preference',
  multi_session: 'Multi-Session',
  temporal: 'Temporal',
}

// ── Component ────────────────────────────────────────────────────────────────

export function Benchmarks() {
  const [selectedRun, setSelectedRun] = useState(0)

  const { data, isLoading, error } = useQuery({
    queryKey: ['benchmark-results'],
    queryFn: () => apiFetch<BenchmarkResponse>('/api/v1/benchmarks/results'),
  })

  const runs = data?.runs ?? []
  const currentRun = runs[selectedRun] ?? null
  const summaries = currentRun?.summaries ?? []

  // Find the winner (highest precision@5)
  const winnerProvider = summaries.length > 0
    ? summaries.reduce((best, s) => s.precision_at_5 > best.precision_at_5 ? s : best).provider
    : null

  // Collect all query types across all summaries
  const allQueryTypes = Array.from(
    new Set(summaries.flatMap(s => Object.keys(s.by_query_type))),
  ).sort()

  // Max precision for scaling bars
  const maxPrecision = Math.max(
    ...summaries.flatMap(s =>
      Object.values(s.by_query_type).map(qt => qt.precision_at_5),
    ),
    0.01, // avoid division by zero
  )

  return (
    <div className="space-y-6">
      <PageHeader
        title="Benchmarks"
        description="Memory provider benchmark results. Compare retrieval quality across providers."
        helpEntries={HELP_ENTRIES}
        actions={
          runs.length > 1 ? (
            <Select
              label=""
              value={String(selectedRun)}
              onChange={(e) => setSelectedRun(Number(e.target.value))}
              items={runs.map((r, i) => ({
                value: String(i),
                label: r.file.replace('.jsonl', '').replace('benchmark-', 'Run '),
              }))}
              className="w-48"
            />
          ) : undefined
        }
      />

      {isLoading && (
        <Card className="p-8">
          <p className="text-center text-compact text-content-tertiary">Loading benchmark results...</p>
        </Card>
      )}

      {error && (
        <Card className="p-8">
          <p className="text-center text-compact text-danger">
            Failed to load benchmarks: {String(error)}
          </p>
        </Card>
      )}

      {!isLoading && !error && summaries.length === 0 && (
        <Card>
          <EmptyState
            icon={FlaskConical}
            title="No benchmark results yet"
            description="Run the benchmark harness to compare memory providers. Results will appear here automatically."
          />
          <div className="px-6 pb-6 -mt-4">
            <div className="mx-auto max-w-lg rounded-sm border border-border bg-surface-elevated p-4">
              <p className="text-caption font-medium text-content-secondary mb-2">How to run benchmarks:</p>
              <pre className="text-mono-sm text-content-tertiary overflow-x-auto whitespace-pre-wrap">{[
                'python -m benchmarks.benchmark \\',
                '  --providers "engram=http://localhost:8002" \\',
                '  --test-cases benchmarks/test_cases.jsonl \\',
                `  --output benchmarks/results/benchmark-${new Date().toISOString().slice(0, 10)}.jsonl \\`,
                '  --llm-gateway http://localhost:8001',
              ].join('\n')}</pre>
            </div>
          </div>
        </Card>
      )}

      {/* Summary Table */}
      {summaries.length > 0 && (
        <>
          <Card className="overflow-hidden">
            <div className="border-b border-border-subtle px-4 py-3 flex items-center gap-2">
              <Trophy size={16} className="text-accent" />
              <p className="text-caption font-medium text-content-tertiary uppercase tracking-wider">
                Provider Comparison
              </p>
              {currentRun && (
                <span className="ml-auto text-caption text-content-tertiary">
                  {currentRun.file}
                </span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-compact">
                <thead>
                  <tr className="bg-surface-elevated">
                    <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">
                      Provider
                    </th>
                    <th className="px-4 py-3 text-right text-caption font-medium text-content-tertiary uppercase tracking-wider">
                      Precision@5
                    </th>
                    <th className="px-4 py-3 text-right text-caption font-medium text-content-tertiary uppercase tracking-wider">
                      MRR
                    </th>
                    <th className="px-4 py-3 text-right text-caption font-medium text-content-tertiary uppercase tracking-wider">
                      <span className="inline-flex items-center gap-1">
                        <Clock size={12} /> Latency
                      </span>
                    </th>
                    <th className="px-4 py-3 text-right text-caption font-medium text-content-tertiary uppercase tracking-wider">
                      <span className="inline-flex items-center gap-1">
                        <Hash size={12} /> Tokens
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {summaries.map((s) => {
                    const isWinner = s.provider === winnerProvider
                    const colors = getProviderColor(s.provider)
                    return (
                      <tr
                        key={s.provider}
                        className={clsx(
                          'transition-colors',
                          isWinner
                            ? 'bg-teal-500/5 dark:bg-teal-500/10'
                            : 'hover:bg-surface-card-hover',
                        )}
                      >
                        <td className="px-4 py-3">
                          <span className={clsx(
                            'inline-flex items-center gap-1.5 rounded-xs px-2 py-0.5 text-caption font-medium',
                            colors.bg, colors.text,
                          )}>
                            {isWinner && <Trophy size={12} />}
                            {s.provider}
                          </span>
                        </td>
                        <td className={clsx(
                          'px-4 py-3 text-right font-mono text-mono-sm',
                          isWinner ? 'text-accent font-bold' : 'text-content-primary',
                        )}>
                          {s.precision_at_5.toFixed(4)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-mono-sm text-content-primary">
                          {s.mrr.toFixed(4)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-mono-sm text-content-secondary">
                          {s.avg_latency_ms.toFixed(1)}ms
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-mono-sm text-content-secondary">
                          {s.total_tokens.toLocaleString()}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Per-Query-Type Breakdown */}
          {allQueryTypes.length > 0 && (
            <div className="space-y-4">
              <h2 className="text-h3 text-content-primary">By Query Type</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {allQueryTypes.map(qt => (
                  <Card key={qt} className="overflow-hidden">
                    <div className="border-b border-border-subtle px-4 py-3">
                      <p className="text-caption font-medium text-content-primary">
                        {QUERY_TYPE_LABELS[qt] ?? qt}
                      </p>
                      <p className="text-micro text-content-tertiary mt-0.5">
                        Precision@5 comparison
                      </p>
                    </div>
                    <div className="p-4 space-y-3">
                      {summaries.map(s => {
                        const qtData = s.by_query_type[qt]
                        if (!qtData) return null
                        const pct = Math.max((qtData.precision_at_5 / maxPrecision) * 100, 2)
                        const colors = getProviderColor(s.provider)
                        return (
                          <div key={s.provider} className="space-y-1">
                            <div className="flex items-center justify-between">
                              <span className={clsx(
                                'inline-flex items-center rounded-xs px-1.5 py-0.5 text-micro font-medium',
                                colors.bg, colors.text,
                              )}>
                                {s.provider}
                              </span>
                              <div className="flex items-center gap-3 text-micro text-content-tertiary">
                                <span>P@5: <span className="text-content-primary font-mono">{qtData.precision_at_5.toFixed(4)}</span></span>
                                <span>MRR: <span className="text-content-primary font-mono">{qtData.mrr.toFixed(4)}</span></span>
                                <span>{qtData.avg_latency_ms.toFixed(0)}ms</span>
                              </div>
                            </div>
                            <div className="h-6 w-full rounded-xs bg-surface-elevated overflow-hidden">
                              <div
                                className={clsx('h-full rounded-xs transition-all duration-500', colors.bar)}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
