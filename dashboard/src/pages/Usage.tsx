import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { getUsage } from '../api'
import {
  aggregateAllTime,
  aggregateWeekly,
  aggregateDaily,
  aggregateByModel,
  type UsageView,
} from '../lib/aggregations'
import clsx from 'clsx'
import { useTheme } from '../stores/theme-store'
import Card from '../components/Card'

/** Read a CSS variable as an rgb() string for use in inline chart styles */
function cssVar(name: string): string {
  const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return val ? `rgb(${val})` : ''
}

const VIEWS: { id: UsageView; label: string; description: string }[] = [
  { id: 'alltime', label: 'All Time',  description: 'Monthly cost (all time)'          },
  { id: 'weekly',  label: 'Weekly',    description: 'Daily cost (last 7 days)'          },
  { id: 'daily',   label: 'Daily',     description: 'Hourly cost (last 24 hours)'       },
  { id: 'model',   label: 'By Model',  description: 'Total cost per model (all time)'   },
]

function getChartData(
  view: UsageView,
  events: ReturnType<typeof getUsage> extends Promise<infer T> ? T : never,
  sortBy: 'cost' | 'alpha' = 'cost',
) {
  switch (view) {
    case 'alltime': return aggregateAllTime(events)
    case 'weekly':  return aggregateWeekly(events)
    case 'daily':   return aggregateDaily(events)
    case 'model':   return aggregateByModel(events, sortBy)
  }
}

export function Usage() {
  const [view, setView]     = useState<UsageView>('weekly')
  const [sortBy, setSortBy] = useState<'cost' | 'alpha'>('cost')
  const { activePreset, mode } = useTheme()

  // Re-read CSS vars whenever the active preset or mode changes so charts update
  const chartColors = useMemo(() => ({
    bar:      cssVar('--accent-700') || '#0f766e',
    grid:     cssVar('--neutral-200') || '#e7e5e0',
    tick:     cssVar('--neutral-400') || '#a8a29e',
    tooltipBg: cssVar('--card') || '#ffffff',
    tooltipBorder: cssVar('--neutral-200') || '#e7e5e0',
    label:    cssVar('--neutral-900') || '#1c1917',
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [activePreset, mode])

  const { data: events = [], isLoading, error } = useQuery({
    queryKey: ['usage'],
    queryFn: () => getUsage(1000),
    refetchInterval: 30_000,
  })

  const totalCost   = events.reduce((s, e) => s + (e.cost_usd ?? 0), 0)
  const totalTokens = events.reduce((s, e) => s + e.input_tokens + e.output_tokens, 0)
  const totalCalls  = events.length

  const chartData   = getChartData(view, events, sortBy)
  const activeView  = VIEWS.find(v => v.id === view)!

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Usage & Cost</h1>

      {/* ── Summary cards (always visible, all-time totals) ─────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
        {[
          { label: 'Total cost (all time)',   value: `$${totalCost.toFixed(4)}`          },
          { label: 'Total tokens (all time)', value: totalTokens.toLocaleString()         },
          { label: 'Total calls (all time)',  value: totalCalls.toLocaleString()          },
        ].map(({ label, value }) => (
          <Card key={label} className="p-4">
            <p className="text-xs text-neutral-500 dark:text-neutral-400">{label}</p>
            <p className="mt-1 text-xl font-semibold text-neutral-900 dark:text-neutral-100">{value}</p>
          </Card>
        ))}
      </div>

      {/* ── Drill-down chart ─────────────────────────────────────────────── */}
      <Card className="overflow-hidden">

        {/* Tab bar */}
        <div className="flex items-center gap-1 border-b border-neutral-200 dark:border-neutral-800 px-4 pt-3 pb-0">
          {VIEWS.map(v => (
            <button
              key={v.id}
              onClick={() => setView(v.id)}
              className={clsx(
                'px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors',
                view === v.id
                  ? 'border-accent-600 text-accent-700 dark:text-accent-400'
                  : 'border-transparent text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300',
              )}
            >
              {v.label}
            </button>
          ))}

          {/* Sort toggle — only visible in By Model view */}
          {view === 'model' && (
            <div className="ml-auto mb-1 flex items-center gap-0.5 rounded-lg border border-neutral-300 dark:border-neutral-600 p-0.5">
              {(['cost', 'alpha'] as const).map(s => (
                <button
                  key={s}
                  onClick={() => setSortBy(s)}
                  className={clsx(
                    'rounded px-2 py-1 text-xs font-medium transition-colors',
                    sortBy === s
                      ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100'
                      : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300',
                  )}
                >
                  {s === 'cost' ? 'By Cost' : 'A → Z'}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="p-4">
          <p className="mb-4 text-xs text-neutral-500 dark:text-neutral-400">{activeView.description}</p>

          {chartData.length === 0 ? (
            <p className="py-8 text-center text-sm text-neutral-500 dark:text-neutral-400">
              {isLoading ? 'Loading…' : 'No data for this period'}
            </p>
          ) : view === 'model' ? (
            /* ── Horizontal bar chart for long model names ─────────────── */
            <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 36)}>
              <BarChart
                layout="vertical"
                data={chartData}
                margin={{ top: 0, right: 30, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} horizontal={false} />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={110}
                  tick={{ fontSize: 10, fill: chartColors.tick }}
                  axisLine={false}
                  tickLine={false}
                />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: chartColors.tick }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={v => `$${Number(v).toFixed(3)}`}
                />
                <Tooltip
                  cursor={false}
                  contentStyle={{ background: chartColors.tooltipBg, border: `1px solid ${chartColors.tooltipBorder}`, borderRadius: 8, boxShadow: '0 4px 12px rgb(0 0 0 / 0.08)' }}
                  labelStyle={{ color: chartColors.label, fontSize: 12 }}
                  formatter={(v: unknown, name: string) => {
                    if (name === 'cost')   return [`$${Number(v).toFixed(4)}`, 'Cost']
                    if (name === 'tokens') return [Number(v).toLocaleString(), 'Tokens']
                    if (name === 'calls')  return [String(v), 'Calls']
                    return [String(v), name]
                  }}
                />
                <Bar dataKey="cost" fill={chartColors.bar} radius={[0, 4, 4, 0]} activeBar={{ fill: chartColors.bar }} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            /* ── Vertical bar chart for time-based views ───────────────── */
            <ResponsiveContainer width="100%" height={200}>
              <BarChart
                data={chartData}
                margin={{ top: 0, right: 0, left: -20, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: chartColors.tick }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: chartColors.tick }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={v => `$${Number(v).toFixed(3)}`}
                />
                <Tooltip
                  cursor={false}
                  contentStyle={{ background: chartColors.tooltipBg, border: `1px solid ${chartColors.tooltipBorder}`, borderRadius: 8, boxShadow: '0 4px 12px rgb(0 0 0 / 0.08)' }}
                  labelStyle={{ color: chartColors.label, fontSize: 12 }}
                  formatter={(v: unknown, name: string) => {
                    if (name === 'cost')   return [`$${Number(v).toFixed(4)}`, 'Cost']
                    if (name === 'tokens') return [Number(v).toLocaleString(), 'Tokens']
                    if (name === 'calls')  return [String(v), 'Calls']
                    return [String(v), name]
                  }}
                />
                <Bar dataKey="cost" fill={chartColors.bar} radius={[4, 4, 0, 0]} activeBar={{ fill: chartColors.bar }} />
              </BarChart>
            </ResponsiveContainer>
          )}

          {/* Per-view summary row */}
          {chartData.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-neutral-200 dark:border-neutral-800 pt-3">
              {[
                { label: 'Cost',   value: `$${chartData.reduce((s, d) => s + d.cost, 0).toFixed(4)}` },
                { label: 'Tokens', value: chartData.reduce((s, d) => s + d.tokens, 0).toLocaleString() },
                { label: 'Calls',  value: chartData.reduce((s, d) => s + d.calls, 0).toLocaleString()  },
              ].map(({ label, value }) => (
                <div key={label}>
                  <span className="text-xs text-neutral-500 dark:text-neutral-400">{label}: </span>
                  <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">{value}</span>
                </div>
              ))}
              <span className="ml-auto hidden sm:inline text-xs text-neutral-500 dark:text-neutral-400">{activeView.description}</span>
            </div>
          )}
        </div>
      </Card>

      {/* ── Recent events table ──────────────────────────────────────────── */}
      <Card className="overflow-hidden">
        <div className="border-b border-neutral-200 dark:border-neutral-800 px-4 py-3 flex items-center justify-between">
          <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">Recent Events</p>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">showing last 50 of {totalCalls}</p>
        </div>
        {isLoading && <p className="p-4 text-sm text-neutral-500 dark:text-neutral-400">Loading…</p>}
        {error     && <p className="p-4 text-sm text-red-600 dark:text-red-400">Failed to load usage: {String(error)}</p>}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-200 dark:border-neutral-800 text-xs text-neutral-500 dark:text-neutral-400">
                <th className="px-3 sm:px-4 py-2 text-left font-medium">Time</th>
                <th className="px-3 sm:px-4 py-2 text-left font-medium">Model</th>
                <th className="hidden sm:table-cell px-4 py-2 text-left font-medium">Key</th>
                <th className="hidden lg:table-cell px-4 py-2 text-left font-medium">In</th>
                <th className="hidden lg:table-cell px-4 py-2 text-left font-medium">Out</th>
                <th className="px-3 sm:px-4 py-2 text-left font-medium">Cost</th>
                <th className="hidden md:table-cell px-4 py-2 text-left font-medium">Duration</th>
              </tr>
            </thead>
            <tbody>
              {events.slice(0, 50).map(e => (
                <tr key={e.id} className="border-b border-neutral-200/50 dark:border-neutral-800/50 hover:bg-neutral-100/30 dark:hover:bg-neutral-800/30 transition-colors">
                  <td className="px-3 sm:px-4 py-2 text-neutral-500 dark:text-neutral-400 whitespace-nowrap text-xs">
                    {formatDistanceToNow(new Date(e.created_at), { addSuffix: true })}
                  </td>
                  <td className="px-3 sm:px-4 py-2 font-mono text-xs text-neutral-700 dark:text-neutral-300 max-w-32 sm:max-w-48 truncate">{e.model}</td>
                  <td className="hidden sm:table-cell px-4 py-2 text-neutral-500 dark:text-neutral-400 text-xs">{e.key_name ?? 'dev'}</td>
                  <td className="hidden lg:table-cell px-4 py-2 text-neutral-500 dark:text-neutral-400 text-xs">{e.input_tokens.toLocaleString()}</td>
                  <td className="hidden lg:table-cell px-4 py-2 text-neutral-500 dark:text-neutral-400 text-xs">{e.output_tokens.toLocaleString()}</td>
                  <td className="px-3 sm:px-4 py-2 text-emerald-700 dark:text-emerald-400 text-xs">
                    {e.cost_usd != null ? `$${e.cost_usd.toFixed(4)}` : '—'}
                  </td>
                  <td className="hidden md:table-cell px-4 py-2 text-neutral-500 dark:text-neutral-400 text-xs">
                    {e.duration_ms != null ? `${e.duration_ms}ms` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
