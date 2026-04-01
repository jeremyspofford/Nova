import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { BarChart3, DollarSign, TrendingUp, TrendingDown } from 'lucide-react'
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
  aggregateByAgent,
  type UsageView,
} from '../lib/aggregations'
import clsx from 'clsx'
import { useTheme } from '../stores/theme-store'
import { PageHeader } from '../components/layout/PageHeader'
import { Card, Tabs, Metric, EmptyState } from '../components/ui'

const HELP_ENTRIES = [
  { term: 'Tokens', definition: 'The units AI models process — input tokens are your prompt, output tokens are the response. Cost is calculated per token.' },
  { term: 'Cost', definition: "Estimated spend based on each provider's per-token pricing. Local models (Ollama) are free." },
  { term: 'Key Name', definition: "The API key identifier — shows which key was used for each call (e.g. 'anthropic', 'openai')." },
  { term: 'Duration', definition: 'How long the AI model took to generate a response, in milliseconds.' },
  { term: 'Agent', definition: 'Which pipeline agent made the call — context, task, guardrail, code_review, or decision.' },
]

/** Read a CSS variable as an rgb() string for use in inline chart styles */
function cssVar(name: string): string {
  const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return val ? `rgb(${val})` : ''
}

const VIEW_TABS = [
  { id: 'alltime', label: 'All Time' },
  { id: 'weekly',  label: 'Weekly' },
  { id: 'daily',   label: 'Daily' },
  { id: 'model',   label: 'By Model' },
  { id: 'agent',   label: 'By Agent' },
]

const VIEW_DESCRIPTIONS: Record<UsageView, string> = {
  alltime: 'Monthly cost (all time)',
  weekly:  'Daily cost (last 7 days)',
  daily:   'Hourly cost (last 24 hours)',
  model:   'Total cost per model (all time)',
  agent:   'Total cost per agent (all time)',
}

const HORIZONTAL_VIEWS: UsageView[] = ['model', 'agent']

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
    case 'agent':   return aggregateByAgent(events, sortBy)
  }
}

export function Usage() {
  const [view, setView]     = useState<UsageView>('weekly')
  const [sortBy, setSortBy] = useState<'cost' | 'alpha'>('cost')
  const { activePreset, mode } = useTheme()

  const chartColors = useMemo(() => ({
    bar:      cssVar('--accent-500') || '#19A89E',
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

  const now = new Date()
  const dayAgo   = new Date(now.getTime() - 24 * 60 * 60 * 1000)
  const weekAgo  = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
  const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
  const yearAgo  = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000)

  const costInPeriod = (since: Date) =>
    events.filter(e => new Date(e.created_at) >= since).reduce((s, e) => s + (e.cost_usd ?? 0), 0)

  // Compare period cost vs previous period for trend arrows
  const costInRange = (from: Date, to: Date) =>
    events.filter(e => { const d = new Date(e.created_at); return d >= from && d < to }).reduce((s, e) => s + (e.cost_usd ?? 0), 0)

  const twoDaysAgo  = new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000)
  const twoWeeksAgo = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000)
  const twoMonthsAgo = new Date(now.getTime() - 60 * 24 * 60 * 60 * 1000)

  const todayCost = costInPeriod(dayAgo)
  const yesterdayCost = costInRange(twoDaysAgo, dayAgo)
  const weekCost = costInPeriod(weekAgo)
  const lastWeekCost = costInRange(twoWeeksAgo, weekAgo)
  const monthCost = costInPeriod(monthAgo)
  const lastMonthCost = costInRange(twoMonthsAgo, monthAgo)

  const totalCost   = events.reduce((s, e) => s + (e.cost_usd ?? 0), 0)
  const totalTokens = events.reduce((s, e) => s + e.input_tokens + e.output_tokens, 0)
  const totalCalls  = events.length
  const shownCount  = Math.min(totalCalls, 50)

  const chartData   = getChartData(view, events, sortBy)
  const isHorizontal = HORIZONTAL_VIEWS.includes(view)

  const trendDelta = (current: number, previous: number) => {
    if (previous === 0) return null
    const diff = current - previous
    return { diff, direction: diff >= 0 ? 'up' as const : 'down' as const }
  }

  const todayTrend = trendDelta(todayCost, yesterdayCost)
  const weekTrend = trendDelta(weekCost, lastWeekCost)
  const monthTrend = trendDelta(monthCost, lastMonthCost)

  return (
    <div className="space-y-6">
      <PageHeader title="Usage" description="Track LLM costs and usage across all providers and models." helpEntries={HELP_ENTRIES} />

      {/* Period cost cards with trend indicators */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* Hero: Today's spend */}
        <Card className={clsx(
          'col-span-2 sm:col-span-1 p-5 relative overflow-hidden',
          todayCost > 0 && 'border-accent/30 shadow-[0_0_20px_rgba(25,168,158,0.15)]',
        )}>
          <div className="flex items-center gap-3">
            <div className={clsx(
              'flex items-center justify-center w-10 h-10 rounded-lg',
              todayCost > 0 ? 'bg-accent/15 text-accent' : 'bg-surface-elevated text-content-tertiary',
            )}>
              <DollarSign size={20} />
            </div>
            <div>
              <p className="text-caption text-content-tertiary">Today</p>
              <p className={clsx(
                'text-2xl font-bold tracking-tight font-mono',
                todayCost > 0 ? 'text-accent' : 'text-content-primary',
              )}>
                ${todayCost.toFixed(2)}
              </p>
            </div>
          </div>
          {todayTrend && (
            <div className={clsx(
              'mt-2 flex items-center gap-1 text-caption',
              todayTrend.direction === 'up' ? 'text-warning' : 'text-success',
            )}>
              {todayTrend.direction === 'up'
                ? <TrendingUp size={12} />
                : <TrendingDown size={12} />}
              <span>${Math.abs(todayTrend.diff).toFixed(2)} vs yesterday</span>
            </div>
          )}
        </Card>

        {/* Secondary period cards with deltas */}
        <Card className="p-4">
          <Metric label="This Week" value={`$${weekCost.toFixed(2)}`} />
          {weekTrend && (
            <div className={clsx(
              'mt-1 flex items-center gap-1 text-caption',
              weekTrend.direction === 'up' ? 'text-warning' : 'text-success',
            )}>
              {weekTrend.direction === 'up' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              <span>${Math.abs(weekTrend.diff).toFixed(2)}</span>
            </div>
          )}
        </Card>
        <Card className="p-4">
          <Metric label="This Month" value={`$${monthCost.toFixed(2)}`} />
          {monthTrend && (
            <div className={clsx(
              'mt-1 flex items-center gap-1 text-caption',
              monthTrend.direction === 'up' ? 'text-warning' : 'text-success',
            )}>
              {monthTrend.direction === 'up' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              <span>${Math.abs(monthTrend.diff).toFixed(2)}</span>
            </div>
          )}
        </Card>
        <Card className="p-4">
          <Metric label="All Time" value={`$${totalCost.toFixed(2)}`} />
          <div className="mt-1 flex items-center gap-3 text-caption text-content-tertiary">
            <span>{totalTokens.toLocaleString()} tokens</span>
            <span>{totalCalls.toLocaleString()} calls</span>
          </div>
        </Card>
      </div>

      {/* Chart section */}
      <Card className="overflow-hidden">
        <div className="px-4 pt-3">
          <div className="flex items-center justify-between gap-4">
            <Tabs
              tabs={VIEW_TABS}
              activeTab={view}
              onChange={(id) => setView(id as UsageView)}
            />
            {(view === 'model' || view === 'agent') && (
              <div className="flex items-center gap-0.5 rounded-sm border border-border p-0.5 shrink-0">
                {(['cost', 'alpha'] as const).map(s => (
                  <button
                    key={s}
                    onClick={() => setSortBy(s)}
                    className={clsx(
                      'rounded-xs px-2 py-1 text-caption font-medium transition-colors',
                      sortBy === s
                        ? 'bg-surface-elevated text-content-primary'
                        : 'text-content-tertiary hover:text-content-secondary',
                    )}
                  >
                    {s === 'cost' ? 'By Cost' : 'A-Z'}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="p-4">
          <p className="mb-4 text-caption text-content-tertiary">{VIEW_DESCRIPTIONS[view]}</p>

          {chartData.length === 0 ? (
            isLoading ? (
              <p className="py-8 text-center text-compact text-content-tertiary">Loading...</p>
            ) : (
              <EmptyState
                icon={BarChart3}
                title="No usage data yet"
                description="Usage tracking starts when Nova processes its first task. Costs, tokens, and model usage will appear here."
              />
            )
          ) : isHorizontal ? (
            <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 36)}>
              <BarChart
                layout="vertical"
                data={chartData}
                margin={{ top: 0, right: 30, left: 10, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} horizontal={false} />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={Math.min(220, Math.max(110, chartData.reduce((m, d) => Math.max(m, d.label.length), 0) * 7))}
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
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-border-subtle pt-3">
              {[
                { label: 'Cost',   value: `$${chartData.reduce((s, d) => s + d.cost, 0).toFixed(4)}` },
                { label: 'Tokens', value: chartData.reduce((s, d) => s + d.tokens, 0).toLocaleString() },
                { label: 'Calls',  value: chartData.reduce((s, d) => s + d.calls, 0).toLocaleString()  },
              ].map(({ label, value }) => (
                <div key={label}>
                  <span className="text-caption text-content-tertiary">{label}: </span>
                  <span className="text-caption font-medium text-content-secondary">{value}</span>
                </div>
              ))}
              <span className="ml-auto hidden sm:inline text-caption text-content-tertiary">{VIEW_DESCRIPTIONS[view]}</span>
            </div>
          )}
        </div>
      </Card>

      {/* Recent events table */}
      <Card className="overflow-hidden">
        <div className="border-b border-border-subtle px-4 py-3 flex items-center justify-between">
          <p className="text-caption font-medium text-content-tertiary uppercase tracking-wider">Recent Events</p>
          <p className="text-caption text-content-tertiary">last {shownCount} of {totalCalls}</p>
        </div>
        {isLoading && <p className="p-4 text-compact text-content-tertiary">Loading...</p>}
        {error     && <p className="p-4 text-compact text-danger">Failed to load usage: {String(error)}</p>}
        <div className="overflow-x-auto">
          <table className="w-full text-compact">
            <thead>
              <tr className="bg-surface-elevated">
                <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Time</th>
                <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Agent</th>
                <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Model</th>
                <th className="hidden sm:table-cell px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Key</th>
                <th className="hidden lg:table-cell px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">In</th>
                <th className="hidden lg:table-cell px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Out</th>
                <th className="px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Cost</th>
                <th className="hidden md:table-cell px-4 py-3 text-left text-caption font-medium text-content-tertiary uppercase tracking-wider">Duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {events.slice(0, 50).map(e => (
                <tr key={e.id} className="hover:bg-surface-card-hover transition-colors">
                  <td className="px-4 py-3 text-content-secondary whitespace-nowrap text-caption">
                    {formatDistanceToNow(new Date(e.created_at), { addSuffix: true })}
                  </td>
                  <td className="px-4 py-3 text-caption text-content-primary whitespace-nowrap">
                    <span>{e.agent_name || '\u2014'}</span>
                    {e.pod_name && (
                      <span className="ml-1.5 text-content-tertiary text-[10px]">{e.pod_name}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-mono-sm text-content-primary max-w-32 sm:max-w-48 truncate">{e.model || 'unknown'}</td>
                  <td className="hidden sm:table-cell px-4 py-3 text-content-tertiary text-caption">{e.key_name ?? 'dev'}</td>
                  <td className="hidden lg:table-cell px-4 py-3 text-content-tertiary text-caption">{e.input_tokens.toLocaleString()}</td>
                  <td className="hidden lg:table-cell px-4 py-3 text-content-tertiary text-caption">{e.output_tokens.toLocaleString()}</td>
                  <td className="px-4 py-3 text-success text-caption">
                    {e.cost_usd != null ? `$${e.cost_usd.toFixed(4)}` : '\u2014'}
                  </td>
                  <td className="hidden md:table-cell px-4 py-3 text-content-tertiary text-caption">
                    {e.duration_ms != null ? `${e.duration_ms}ms` : '\u2014'}
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
