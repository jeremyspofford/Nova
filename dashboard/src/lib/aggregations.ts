import type { UsageEvent } from '../types'

export interface ChartDataPoint {
  label: string   // x-axis label (e.g. "Feb 2026", "Feb 26", "2 PM", "claude-max/...")
  cost: number    // total USD cost for this bucket
  tokens: number  // total tokens (input + output)
  calls: number   // number of API calls
}

export type UsageView = 'alltime' | 'weekly' | 'daily' | 'model'

// ─── Shared helpers ───────────────────────────────────────────────────────────

function accumulate(bucket: ChartDataPoint, e: UsageEvent) {
  bucket.cost   += e.cost_usd ?? 0
  bucket.tokens += e.input_tokens + e.output_tokens
  bucket.calls  += 1
}

function emptyBucket(label: string): ChartDataPoint {
  return { label, cost: 0, tokens: 0, calls: 0 }
}

// ─── All time — grouped by calendar month ────────────────────────────────────
// Shows every month that has at least one event, sorted chronologically.
// Useful for spotting long-term cost trends.

export function aggregateAllTime(events: UsageEvent[]): ChartDataPoint[] {
  // Use YYYY-MM as the sort key but display "Mon YYYY" as the label
  const buckets = new Map<string, ChartDataPoint>()

  for (const e of events) {
    const d = new Date(e.created_at)
    const sortKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    const label   = d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    if (!buckets.has(sortKey)) buckets.set(sortKey, emptyBucket(label))
    accumulate(buckets.get(sortKey)!, e)
  }

  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, v]) => v)
}

// ─── Weekly — last 7 calendar days, one bar per day ──────────────────────────
// Pre-fills all 7 days so days with zero usage still appear as empty bars.

export function aggregateWeekly(events: UsageEvent[]): ChartDataPoint[] {
  const buckets = new Map<string, ChartDataPoint>()

  for (let i = 6; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    buckets.set(label, emptyBucket(label))
  }

  for (const e of events) {
    const label = new Date(e.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    const bucket = buckets.get(label)
    if (bucket) accumulate(bucket, e)
  }

  return [...buckets.values()]
}

// ─── Daily — last 24 hours, one bar per hour ─────────────────────────────────
// Pre-fills all 24 hours. Empty hours show as zero bars.

export function aggregateDaily(events: UsageEvent[]): ChartDataPoint[] {
  const now     = new Date()
  const cutoff  = new Date(now.getTime() - 24 * 60 * 60 * 1000)
  const buckets = new Map<string, ChartDataPoint>()

  for (let i = 23; i >= 0; i--) {
    const d = new Date(now)
    d.setHours(d.getHours() - i, 0, 0, 0)
    const label = d.toLocaleTimeString('en-US', { hour: 'numeric', hour12: true })
    buckets.set(label, emptyBucket(label))
  }

  for (const e of events) {
    const d = new Date(e.created_at)
    if (d < cutoff) continue
    const floored = new Date(d)
    floored.setMinutes(0, 0, 0)
    const label = floored.toLocaleTimeString('en-US', { hour: 'numeric', hour12: true })
    const bucket = buckets.get(label)
    if (bucket) accumulate(bucket, e)
  }

  return [...buckets.values()]
}

// ─── By Model — your implementation ──────────────────────────────────────────
//
// One bar per model across ALL events. This is the most flexible view:
// you can see exactly which providers are costing the most.
//
// Design choices to make:
//   1. Sorting — by cost descending (most expensive first) is usually most
//      useful, but alphabetical or by call count are also valid.
//
//   2. Label formatting — full model IDs like "claude-max/claude-sonnet-4-6"
//      are verbose. You could strip the provider prefix, truncate at N chars,
//      or keep them full and let the chart rotate them.
//
//   3. Zero-cost filtering — streaming calls have cost_usd = null (counted
//      as 0). Should a model used only for streaming still appear in the chart?
//
// @param events  All raw events, newest first
// @param sortBy  'cost' (default — highest cost first) or 'alpha' (a→z)
// @returns       One ChartDataPoint per model; zero-cost models included

export function aggregateByModel(
  events: UsageEvent[],
  sortBy: 'cost' | 'alpha' = 'cost',
): ChartDataPoint[] {
  const buckets = new Map<string, ChartDataPoint>()

  for (const e of events) {
    // Full model ID kept for precision — chart rotates labels automatically
    const label = e.model
    if (!buckets.has(label)) buckets.set(label, emptyBucket(label))
    accumulate(buckets.get(label)!, e)
  }

  const points = [...buckets.values()]

  if (sortBy === 'alpha') {
    return points.sort((a, b) => a.label.localeCompare(b.label))
  }
  // Default: highest cost first; ties broken alphabetically for stability
  return points.sort((a, b) => b.cost - a.cost || a.label.localeCompare(b.label))
}
