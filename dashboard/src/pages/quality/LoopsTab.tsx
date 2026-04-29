import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, GitBranch } from 'lucide-react'
import { apiFetch } from '../../api'
import { Card, EmptyState, Button, Badge } from '../../components/ui'

type LoopSummary = {
  name: string
  watches: string[]
  agency: 'auto_apply' | 'propose_for_approval' | 'alert_only'
  last_session: {
    id: string
    started_at: string | null
    completed_at: string | null
    outcome: string | null
    decision: string | null
  } | null
}

type LoopSession = {
  id: string
  started_at: string | null
  completed_at: string | null
  outcome: string | null
  decision: string | null
  proposed_changes: Record<string, { from: unknown; to: unknown }> | null
  applied: boolean
  notes: Record<string, unknown>
  decided_by: string | null
}

export function LoopsTab() {
  const { data: loops = [], isLoading } = useQuery({
    queryKey: ['quality-loops'],
    queryFn: () => apiFetch<LoopSummary[]>('/api/v1/quality/loops'),
    refetchInterval: 15_000,
  })

  return (
    <div className="space-y-6 mt-6">
      {isLoading && (
        <Card className="p-8">
          <p className="text-center text-compact text-content-tertiary">Loading loops…</p>
        </Card>
      )}
      {!isLoading && loops.length === 0 && (
        <Card>
          <EmptyState
            icon={GitBranch}
            title="No loops registered"
            description="Quality loops register on orchestrator startup. If this list is empty, check orchestrator logs."
          />
        </Card>
      )}
      {loops.map(loop => <LoopCard key={loop.name} loop={loop} />)}
    </div>
  )
}

function LoopCard({ loop }: { loop: LoopSummary }) {
  const qc = useQueryClient()

  const { data: sessions = [] } = useQuery({
    queryKey: ['quality-loop-sessions', loop.name],
    queryFn: () => apiFetch<LoopSession[]>(`/api/v1/quality/loops/${loop.name}/sessions?limit=10`),
    refetchInterval: 30_000,
  })

  const runNow = useMutation({
    mutationFn: () => apiFetch(`/api/v1/quality/loops/${loop.name}/run-now`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quality-loops'] })
      qc.invalidateQueries({ queryKey: ['quality-loop-sessions', loop.name] })
    },
  })

  return (
    <Card className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-h3 text-content-primary">{loop.name}</h3>
          <p className="text-caption text-content-tertiary mt-1">
            Watches: {loop.watches.join(', ')} · Agency: <Badge>{loop.agency}</Badge>
          </p>
        </div>
        <Button
          size="sm"
          icon={<Play size={12} />}
          loading={runNow.isPending}
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
        >
          Run Now
        </Button>
      </div>

      {sessions.length > 0 && (
        <div className="border-t border-border-subtle pt-4">
          <p className="text-caption font-medium text-content-tertiary uppercase tracking-wider mb-2">
            Recent sessions
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-compact">
              <thead>
                <tr>
                  <th className="text-left text-caption text-content-tertiary py-1 pr-4">Started</th>
                  <th className="text-left text-caption text-content-tertiary py-1 pr-4">Outcome</th>
                  <th className="text-left text-caption text-content-tertiary py-1 pr-4">Decision</th>
                  <th className="text-left text-caption text-content-tertiary py-1">Proposed</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map(s => (
                  <tr key={s.id} className="border-t border-border-subtle">
                    <td className="py-2 pr-4 text-content-secondary text-caption">
                      {s.started_at ? new Date(s.started_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '--'}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge>{s.outcome ?? '--'}</Badge>
                    </td>
                    <td className="py-2 pr-4">
                      <Badge>{s.decision ?? '--'}</Badge>
                    </td>
                    <td className="py-2 font-mono text-mono-sm text-content-tertiary truncate max-w-[300px]">
                      {s.proposed_changes ? JSON.stringify(s.proposed_changes) : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  )
}
