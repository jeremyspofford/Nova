import { useQuery, useMutation } from '@tanstack/react-query'
import { Brain, RefreshCw, Zap } from 'lucide-react'
import { apiFetch } from '../../api'
import { Card, Badge, Button, EmptyState, Skeleton, Section } from '../../components/ui'

interface GraphData {
  nodes: {
    id: string
    type: string
    content: string
    importance: number
    confidence: number
  }[]
  edges: unknown[]
  node_count: number
  edge_count: number
}

function SelfModelEngrams() {
  const { data: graph } = useQuery<GraphData>({
    queryKey: ['engram-self-model-graph'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/graph?query=self+identity+personality&depth=1&max_nodes=20'),
  })

  if (!graph || graph.nodes.length === 0) return null

  const selfNodes = graph.nodes.filter((n) => n.type === 'self_model')
  if (selfNodes.length === 0) return null

  return (
    <Card variant="default" className="p-5">
      <h3 className="text-compact font-semibold text-content-primary mb-3">Identity Engrams</h3>
      <div className="space-y-2">
        {selfNodes.map((node) => (
          <div key={node.id} className="p-3 rounded-sm bg-surface-elevated border border-border-subtle">
            <p className="text-compact text-content-secondary">{node.content}</p>
            <div className="flex gap-4 mt-1">
              <span className="text-caption text-content-tertiary">importance: {node.importance}</span>
              <span className="text-caption text-content-tertiary">confidence: {node.confidence}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

export function SelfModelSection() {
  const { data, isLoading, refetch } = useQuery<{ self_model: string }>({
    queryKey: ['engram-self-model'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/self-model'),
  })

  const bootstrap = useMutation({
    mutationFn: () => apiFetch('/mem/api/v1/engrams/self-model/bootstrap', { method: 'POST' }),
    onSuccess: () => refetch(),
  })

  return (
    <Section icon={Brain} title="Self-Model" description="Nova's emergent self-knowledge — learned traits that shape how it thinks and communicates. Unlike the Persona (which you write), the self-model evolves automatically through consolidation.">
      <div className="space-y-4">
        <Card variant="default" className="p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-compact font-semibold flex items-center gap-2 text-content-primary">
              <Brain className="w-4 h-4 text-accent" />
              Self-Model Summary
            </h3>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => refetch()} icon={<RefreshCw size={12} />}>
                Refresh
              </Button>
              {(!data?.self_model) && (
                <Button size="sm" onClick={() => bootstrap.mutate()} loading={bootstrap.isPending} icon={<Zap size={12} />}>
                  Bootstrap
                </Button>
              )}
            </div>
          </div>
          {isLoading ? (
            <Skeleton lines={4} />
          ) : data?.self_model ? (
            <p className="text-compact text-content-secondary leading-relaxed whitespace-pre-wrap">
              {data.self_model}
            </p>
          ) : (
            <EmptyState
              icon={Brain}
              title="No self-model data"
              description="Click Bootstrap to seed initial identity engrams."
              action={{ label: 'Bootstrap', onClick: () => bootstrap.mutate() }}
            />
          )}
        </Card>

        <SelfModelEngrams />
      </div>
    </Section>
  )
}
