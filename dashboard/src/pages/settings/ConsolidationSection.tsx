import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { GitMerge, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { apiFetch } from '../../api'
import { Section, Card, Badge, Button, EmptyState, Skeleton } from '../../components/ui'
import type { SemanticColor } from '../../lib/design-tokens'

interface ConsolidationEntry {
  id: string
  trigger: string
  engrams_reviewed: number
  schemas_created: number
  edges_strengthened: number
  edges_pruned: number
  engrams_pruned: number
  engrams_merged: number
  contradictions_resolved: number
  self_model_updates: Record<string, unknown>
  model_used: string | null
  duration_ms: number
  created_at: string | null
}

function summarizeConsolidation(entry: ConsolidationEntry): string[] {
  const parts: string[] = []
  if (entry.engrams_reviewed > 0)
    parts.push(`Reviewed ${entry.engrams_reviewed} memories`)
  if (entry.schemas_created > 0)
    parts.push(`extracted ${entry.schemas_created} pattern${entry.schemas_created > 1 ? 's' : ''}`)
  if (entry.edges_strengthened > 0)
    parts.push(`strengthened ${entry.edges_strengthened} connection${entry.edges_strengthened > 1 ? 's' : ''}`)
  if (entry.edges_pruned > 0)
    parts.push(`pruned ${entry.edges_pruned} weak edge${entry.edges_pruned > 1 ? 's' : ''}`)
  if (entry.engrams_merged > 0)
    parts.push(`merged ${entry.engrams_merged} duplicate${entry.engrams_merged > 1 ? 's' : ''}`)
  if (entry.engrams_pruned > 0)
    parts.push(`archived ${entry.engrams_pruned} dead memor${entry.engrams_pruned > 1 ? 'ies' : 'y'}`)
  if (entry.contradictions_resolved > 0)
    parts.push(`resolved ${entry.contradictions_resolved} contradiction${entry.contradictions_resolved > 1 ? 's' : ''}`)
  return parts
}

const TRIGGER_COLOR: Record<string, SemanticColor> = {
  manual: 'info',
  idle: 'neutral',
  scheduled: 'accent',
  threshold: 'warning',
}

function StatPill({ label, value }: { label: string; value: number | string }) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-sm bg-surface-elevated text-caption">
      <span className="text-content-tertiary">{label}</span>
      <span className="font-mono font-medium text-content-secondary">{value}</span>
    </span>
  )
}

export function ConsolidationSection() {
  const { data, isLoading, refetch } = useQuery<{ count: number; entries: ConsolidationEntry[] }>({
    queryKey: ['engram-consolidation-log'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/consolidation-log?limit=20'),
  })

  const consolidate = useMutation({
    mutationFn: () => apiFetch('/mem/api/v1/engrams/consolidate', { method: 'POST' }),
    onSuccess: () => refetch(),
  })

  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <Section icon={GitMerge} title="Consolidation" description="Memory maintenance cycles — replays recent memories, extracts patterns, resolves contradictions, and prunes weak connections.">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-compact font-semibold text-content-primary">Consolidation History</h3>
          <Button
            size="sm"
            onClick={() => consolidate.mutate()}
            loading={consolidate.isPending}
            icon={<RefreshCw size={12} />}
          >
            {consolidate.isPending ? 'Running...' : 'Run Now'}
          </Button>
        </div>

        <p className="text-caption text-content-tertiary -mt-2">
          Memory maintenance cycles — replays recent memories, extracts patterns, resolves contradictions, and prunes weak connections. Runs automatically on idle, nightly, or after 50+ new engrams.
        </p>

        {isLoading && <Skeleton lines={5} />}

        {data?.entries.length === 0 && (
          <EmptyState
            icon={GitMerge}
            title="No consolidation runs yet"
            description="Consolidation triggers automatically on idle (30min), nightly (3 AM), or after 50+ new engrams."
          />
        )}

        {data?.entries.map((entry) => {
          const summary = summarizeConsolidation(entry)
          const selfModel = entry.self_model_updates as Record<string, unknown> | null
          const hadActivity = summary.length > 0

          return (
            <Card key={entry.id} variant="default" className="p-4">
              <div
                className="flex items-center gap-3 cursor-pointer"
                onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
              >
                {expandedId === entry.id ? (
                  <ChevronDown className="w-4 h-4 text-content-tertiary shrink-0" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-content-tertiary shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge color={TRIGGER_COLOR[entry.trigger] ?? 'neutral'} size="sm">{entry.trigger}</Badge>
                    <span className="text-caption text-content-secondary">
                      {hadActivity ? summary.join(', ') : 'No changes — memory is stable'}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5 text-micro text-content-tertiary">
                    <span>{entry.created_at ? formatDistanceToNow(new Date(entry.created_at), { addSuffix: true }) : 'unknown'}</span>
                    <span>{entry.duration_ms}ms</span>
                    {selfModel?.maturity_stage != null && (
                      <span>maturity: {String(selfModel.maturity_stage)}</span>
                    )}
                  </div>
                </div>
              </div>

              {expandedId === entry.id && (
                <div className="mt-3 pt-3 border-t border-border-subtle space-y-3">
                  {/* Non-zero stats */}
                  {hadActivity ? (
                    <div className="flex flex-wrap gap-2">
                      {entry.engrams_reviewed > 0 && <StatPill label="Reviewed" value={entry.engrams_reviewed} />}
                      {entry.schemas_created > 0 && <StatPill label="Patterns" value={entry.schemas_created} />}
                      {entry.edges_strengthened > 0 && <StatPill label="Strengthened" value={entry.edges_strengthened} />}
                      {entry.edges_pruned > 0 && <StatPill label="Edges pruned" value={entry.edges_pruned} />}
                      {entry.engrams_merged > 0 && <StatPill label="Merged" value={entry.engrams_merged} />}
                      {entry.engrams_pruned > 0 && <StatPill label="Archived" value={entry.engrams_pruned} />}
                      {entry.contradictions_resolved > 0 && <StatPill label="Contradictions" value={entry.contradictions_resolved} />}
                    </div>
                  ) : (
                    <p className="text-caption text-content-tertiary">
                      All phases ran but found nothing to change. This is normal for a stable memory graph.
                    </p>
                  )}

                  {/* Self-model snapshot */}
                  {selfModel && Object.keys(selfModel).length > 0 && (
                    <div>
                      <p className="text-micro font-medium uppercase tracking-wider text-content-tertiary mb-1.5">Self-Model Snapshot</p>
                      <div className="flex flex-wrap gap-2">
                        {selfModel.maturity_stage != null && (
                          <StatPill label="Maturity" value={String(selfModel.maturity_stage)} />
                        )}
                        {typeof selfModel.total_engrams === 'number' && (
                          <StatPill label="Total engrams" value={selfModel.total_engrams} />
                        )}
                        {typeof selfModel.schema_count === 'number' && selfModel.schema_count > 0 && (
                          <StatPill label="Schemas" value={selfModel.schema_count} />
                        )}
                        {typeof selfModel.reflection_count === 'number' && selfModel.reflection_count > 0 && (
                          <StatPill label="Reflections" value={selfModel.reflection_count} />
                        )}
                      </div>
                    </div>
                  )}

                  {/* Meta */}
                  <div className="flex items-center gap-4 text-micro text-content-tertiary">
                    <span>{entry.created_at ? new Date(entry.created_at).toLocaleString() : 'unknown'}</span>
                    <span>Duration: {entry.duration_ms}ms</span>
                    {entry.model_used && <span>Model: {entry.model_used}</span>}
                  </div>
                </div>
              )}
            </Card>
          )
        })}
      </div>
    </Section>
  )
}
