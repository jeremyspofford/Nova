import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle } from 'lucide-react'
import { apiFetch } from '../api'
import { Card, Skeleton } from './ui'

interface HealthData {
  outcome_feedback: {
    engrams_with_outcomes: number
    avg_outcome_score: number | null
    max_observations: number
    recalibration: { boost_eligible: number; demote_eligible: number; recalibrated_total: number }
  }
  activation: { full: number; mid: number; low: number; floor: number }
  co_activations: { edges_strengthened: number; max_co_activations: number }
  consolidation: {
    living_topics: number; superseded_topics: number; supersession_rate: number
    last_run: string | null
    last_run_stats: { topics_created: number; engrams_merged: number; edges_pruned: number } | null
  }
  neural_router: { models_trained: number; retrieval_observations: number; latest_model_date: string | null }
  self_improving: boolean
  issues: string[]
}

function StatusDot({ ok }: { ok: boolean }) {
  return <div className={`w-2 h-2 rounded-full ${ok ? 'bg-success' : 'bg-warning'}`} />
}

function StatCard({ label, value, sub, ok }: { label: string; value: string | number; sub?: string; ok?: boolean }) {
  return (
    <Card className="p-3">
      <div className="flex items-center justify-between">
        <span className="text-micro text-content-tertiary uppercase font-semibold tracking-wider">{label}</span>
        {ok !== undefined && <StatusDot ok={ok} />}
      </div>
      <p className="text-display text-content-primary mt-1">{value}</p>
      {sub && <p className="text-micro text-content-tertiary mt-0.5">{sub}</p>}
    </Card>
  )
}

export function MemoryHealth() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['memory-health'],
    queryFn: () => apiFetch<HealthData>('/mem/api/v1/engrams/health'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Card className="p-4"><Skeleton lines={2} /></Card>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="p-3"><Skeleton lines={2} /></Card>
          ))}
        </div>
        <Card className="p-4"><Skeleton lines={3} /></Card>
      </div>
    )
  }

  if (error || !data) {
    return (
      <Card className="p-4">
        <p className="text-compact text-danger">Failed to load memory health data</p>
      </Card>
    )
  }

  const h = data

  return (
    <div className="space-y-4">
      {/* Overall status */}
      <div className={`flex items-center gap-3 p-3 rounded-lg border ${
        h.self_improving
          ? 'bg-success-dim border-success/30'
          : 'bg-warning-dim border-warning/30'
      }`}>
        {h.self_improving
          ? <CheckCircle size={18} className="text-success" />
          : <AlertTriangle size={18} className="text-warning" />}
        <span className="text-compact text-content-primary font-medium">
          {h.self_improving ? 'Memory system is learning' : 'Memory learning has issues'}
        </span>
      </div>

      {/* Issues */}
      {h.issues.length > 0 && (
        <div className="space-y-1">
          {h.issues.map((issue, i) => (
            <div key={i} className="flex items-start gap-2 text-compact text-warning">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{issue}</span>
            </div>
          ))}
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Outcome Feedback"
          value={h.outcome_feedback.engrams_with_outcomes}
          sub={h.outcome_feedback.avg_outcome_score ? `avg ${h.outcome_feedback.avg_outcome_score.toFixed(2)}` : 'no data'}
          ok={h.outcome_feedback.engrams_with_outcomes > 0}
        />
        <StatCard
          label="Recalibration"
          value={h.outcome_feedback.recalibration.recalibrated_total}
          sub={`${h.outcome_feedback.recalibration.boost_eligible} boost, ${h.outcome_feedback.recalibration.demote_eligible} demote eligible`}
          ok={h.outcome_feedback.recalibration.boost_eligible > 0 || h.outcome_feedback.recalibration.recalibrated_total > 0}
        />
        <StatCard
          label="Living Topics"
          value={h.consolidation.living_topics}
          sub={`${Math.round(h.consolidation.supersession_rate * 100)}% superseded`}
          ok={h.consolidation.supersession_rate < 0.80}
        />
        <StatCard
          label="Neural Router"
          value={`${h.neural_router.models_trained} models`}
          sub={`${h.neural_router.retrieval_observations.toLocaleString()} observations`}
          ok={h.neural_router.models_trained > 0}
        />
      </div>

      {/* Activation distribution */}
      <Card className="p-3">
        <h4 className="text-micro text-content-tertiary uppercase font-semibold tracking-wider mb-2">Activation Distribution</h4>
        <div className="flex gap-1 h-4 rounded-full overflow-hidden bg-surface-elevated">
          {h.activation.full > 0 && (
            <div className="bg-success" style={{ flex: h.activation.full }} title={`Full: ${h.activation.full}`} />
          )}
          {h.activation.mid > 0 && (
            <div className="bg-info" style={{ flex: h.activation.mid }} title={`Mid: ${h.activation.mid}`} />
          )}
          {h.activation.low > 0 && (
            <div className="bg-warning" style={{ flex: h.activation.low }} title={`Low: ${h.activation.low}`} />
          )}
          {h.activation.floor > 0 && (
            <div className="bg-danger" style={{ flex: h.activation.floor }} title={`Floor: ${h.activation.floor}`} />
          )}
        </div>
        <div className="flex gap-4 mt-1.5 text-micro text-content-tertiary">
          <span><span className="inline-block w-2 h-2 rounded-full bg-success mr-1" />Full ({h.activation.full})</span>
          <span><span className="inline-block w-2 h-2 rounded-full bg-info mr-1" />Mid ({h.activation.mid})</span>
          <span><span className="inline-block w-2 h-2 rounded-full bg-warning mr-1" />Low ({h.activation.low})</span>
          <span><span className="inline-block w-2 h-2 rounded-full bg-danger mr-1" />Floor ({h.activation.floor})</span>
        </div>
      </Card>

      {/* Last consolidation */}
      {h.consolidation.last_run && h.consolidation.last_run_stats && (
        <Card className="p-3">
          <h4 className="text-micro text-content-tertiary uppercase font-semibold tracking-wider mb-1">Last Consolidation</h4>
          <p className="text-micro text-content-tertiary">{new Date(h.consolidation.last_run).toLocaleString()}</p>
          <div className="flex gap-4 mt-1 text-compact text-content-secondary">
            <span>{h.consolidation.last_run_stats.topics_created} topics</span>
            <span>{h.consolidation.last_run_stats.engrams_merged} merged</span>
            <span>{h.consolidation.last_run_stats.edges_pruned.toLocaleString()} edges pruned</span>
          </div>
        </Card>
      )}

      {/* Hebbian learning */}
      <Card className="p-3">
        <div className="flex items-center gap-2">
          <h4 className="text-micro text-content-tertiary uppercase font-semibold tracking-wider">Hebbian Learning</h4>
          <StatusDot ok={h.co_activations.edges_strengthened > 0} />
        </div>
        <p className="text-compact text-content-secondary mt-1">
          {h.co_activations.edges_strengthened} edges strengthened (max co-activation: {h.co_activations.max_co_activations})
        </p>
      </Card>
    </div>
  )
}
