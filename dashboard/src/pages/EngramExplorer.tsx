import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Network, Brain, RefreshCw, Zap, GitMerge,
  Activity, ChevronDown, ChevronRight,
} from 'lucide-react'
import { apiFetch } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import {
  Card, Badge, Metric, ProgressBar, Tabs, Table, Button, SearchInput,
  EmptyState, Skeleton,
} from '../components/ui'
import type { SemanticColor } from '../lib/design-tokens'

// ── Types ────────────────────────────────────────────────────────────────────

interface EngramNode {
  id: string
  type: string
  content: string
  activation: number
  importance: number
  access_count: number
  confidence: number
  source_type: string
  superseded: boolean
  created_at: string | null
}

interface EngramEdge {
  source: string
  target: string
  relation: string
  weight: number
  co_activations: number
}

interface GraphData {
  center_id: string
  nodes: EngramNode[]
  edges: EngramEdge[]
  node_count: number
  edge_count: number
}

interface EngramStats {
  total_engrams: number
  total_edges: number
  total_archived: number
  by_type: Record<string, { total: number; superseded: number }>
  by_relation: Record<string, { count: number; avg_weight: number }>
}

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

interface RouterStatus {
  observation_count: number
  ready: boolean
  phase: string
  message: string
}

// ── Type badge color mapping ─────────────────────────────────────────────────

const TYPE_BADGE_COLOR: Record<string, SemanticColor> = {
  fact:        'info',
  episode:     'warning',
  entity:      'accent',
  preference:  'success',
  procedure:   'neutral',
  schema:      'danger',
  goal:        'accent',
  self_model:  'info',
}

const ALL_TYPES = ['fact', 'episode', 'entity', 'preference', 'procedure', 'schema', 'goal', 'self_model']

// ── Score bar helper ─────────────────────────────────────────────────────────

function ScoreBar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(Math.min(Math.max(value, 0), 1) * 100)
  return (
    <div className="flex items-center gap-1.5" title={`${label}: ${pct}%`}>
      <span className="text-caption text-content-tertiary w-16 shrink-0">{label}</span>
      <ProgressBar value={pct} size="sm" className="flex-1" />
      <span className="text-caption text-content-tertiary w-8 text-right">{pct}%</span>
    </div>
  )
}

// ── Tab config ───────────────────────────────────────────────────────────────

const TABS = [
  { id: 'explorer', label: 'Explorer', icon: Activity },
  { id: 'graph', label: 'Graph', icon: Network },
  { id: 'self-model', label: 'Self-Model', icon: Brain },
  { id: 'consolidation', label: 'Consolidation', icon: GitMerge },
]

// ── Explorer Tab ─────────────────────────────────────────────────────────────

function ExplorerTab() {
  const [searchQuery, setSearchQuery] = useState('')
  const [activeSearch, setActiveSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | null>(null)

  const { data: stats, isLoading: statsLoading } = useQuery<EngramStats>({
    queryKey: ['engram-stats'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/stats'),
  })

  const { data: routerStatus } = useQuery<RouterStatus>({
    queryKey: ['engram-router-status'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/router-status'),
  })

  const { data: graph, isLoading: graphLoading } = useQuery<GraphData>({
    queryKey: ['engram-explorer', activeSearch],
    queryFn: () => {
      const params = new URLSearchParams()
      if (activeSearch) params.set('query', activeSearch)
      params.set('depth', '1')
      params.set('max_nodes', '50')
      return apiFetch(`/mem/api/v1/engrams/graph?${params}`)
    },
    enabled: true,
  })

  const handleSearch = (val: string) => {
    setSearchQuery(val)
    // Debounced via SearchInput, trigger search
    setActiveSearch(val)
  }

  if (statsLoading) return <Skeleton lines={6} />
  if (!stats) return <p className="text-content-tertiary p-4">No data</p>

  const filteredNodes = graph?.nodes?.filter(n => !typeFilter || n.type === typeFilter) ?? []

  return (
    <div className="space-y-6">
      {/* Stats bar */}
      <div className="flex flex-wrap gap-6">
        <Metric label="Total Engrams" value={stats.total_engrams} />
        <Metric label="Edges" value={stats.total_edges} />
        <Metric label="Archived" value={stats.total_archived} />
        <Metric label="Router Observations" value={routerStatus?.observation_count ?? 0} />
      </div>

      {/* Type distribution */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setTypeFilter(null)}
          className={!typeFilter ? undefined : 'opacity-50'}
        >
          <Badge color="neutral" size="sm">All</Badge>
        </button>
        {Object.entries(stats.by_type).map(([type, { total }]) => (
          <button
            key={type}
            onClick={() => setTypeFilter(typeFilter === type ? null : type)}
            className={typeFilter && typeFilter !== type ? 'opacity-40' : undefined}
          >
            <Badge color={TYPE_BADGE_COLOR[type] ?? 'neutral'} size="sm">
              {type} ({total})
            </Badge>
          </button>
        ))}
      </div>

      {/* Search */}
      <SearchInput
        value={searchQuery}
        onChange={handleSearch}
        placeholder="Semantic search engrams..."
        debounceMs={500}
      />

      {/* Engram list */}
      {graphLoading ? (
        <Skeleton lines={5} />
      ) : filteredNodes.length === 0 ? (
        <EmptyState
          icon={Network}
          title="No engrams found"
          description={activeSearch ? `No results for "${activeSearch}"` : "Memory is empty. Engrams are created through conversations."}
        />
      ) : (
        <div className="space-y-2">
          <p className="text-caption text-content-tertiary">{filteredNodes.length} engrams</p>
          {filteredNodes.map(node => (
            <Card key={node.id} variant="hoverable" className="p-4">
              <div className="flex items-start gap-3">
                <Badge color={TYPE_BADGE_COLOR[node.type] ?? 'neutral'} size="sm">
                  {node.type}
                </Badge>
                <div className="flex-1 min-w-0">
                  <p className="text-compact text-content-primary line-clamp-2">{node.content}</p>
                  <div className="flex gap-4 mt-2">
                    <ScoreBar value={node.importance} label="Imp" />
                    <ScoreBar value={node.activation} label="Act" />
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className="text-caption text-content-tertiary">{node.access_count}x</span>
                  {node.created_at && (
                    <span className="text-micro text-content-tertiary">
                      {new Date(node.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Neural Router Status */}
      {routerStatus && (
        <Card variant="default" className="p-5">
          <h3 className="text-compact font-semibold text-content-primary mb-3">Neural Router</h3>
          <div className="flex items-center gap-3 mb-2">
            <Zap className={`w-4 h-4 ${routerStatus.ready ? 'text-success' : 'text-warning'}`} />
            <span className="text-compact text-content-secondary">{routerStatus.message}</span>
          </div>
          <ProgressBar
            value={Math.min(100, (routerStatus.observation_count / 200) * 100)}
            size="md"
          />
          <p className="text-caption text-content-tertiary mt-1">
            {routerStatus.observation_count} / 200 observations
          </p>
        </Card>
      )}

      {/* Edges by Relation */}
      <Card variant="default" className="p-5">
        <h3 className="text-compact font-semibold text-content-primary mb-3">Edges by Relation</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Object.entries(stats.by_relation).map(([relation, { count, avg_weight }]) => (
            <div key={relation} className="p-3 rounded-sm bg-surface-elevated">
              <div className="text-compact font-medium text-content-primary">{relation.replace(/_/g, ' ')}</div>
              <div className="text-display font-mono text-accent">{count}</div>
              <div className="text-micro text-content-tertiary">avg weight: {avg_weight}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

// ── Graph Tab ────────────────────────────────────────────────────────────────

function GraphTab() {
  const [query, setQuery] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedNode, setSelectedNode] = useState<EngramNode | null>(null)

  const { data: graph, isLoading } = useQuery<GraphData>({
    queryKey: ['engram-graph', searchQuery],
    queryFn: () => {
      const params = new URLSearchParams()
      if (searchQuery) params.set('query', searchQuery)
      params.set('depth', '2')
      params.set('max_nodes', '50')
      return apiFetch(`/mem/api/v1/engrams/graph?${params}`)
    },
    enabled: true,
  })

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setSearchQuery(query)
    setSelectedNode(null)
  }

  const exploreNode = (nodeId: string) => {
    setSelectedNode(null)
    apiFetch<GraphData>(`/mem/api/v1/engrams/graph?center_id=${nodeId}&depth=2&max_nodes=50`)
      .then(() => {
        setSearchQuery(`__node:${nodeId}`)
      })
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSearch} className="flex gap-2">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Search engram graph..."
          debounceMs={0}
          className="flex-1"
        />
        <Button type="submit" icon={<Network size={14} />}>
          Explore
        </Button>
      </form>

      {isLoading && <Skeleton lines={5} />}

      {graph && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Node List */}
          <div className="lg:col-span-2 space-y-2">
            <p className="text-caption text-content-tertiary">
              {graph.node_count} nodes, {graph.edge_count} edges
            </p>
            {graph.nodes.map((node) => (
              <Card
                key={node.id}
                variant="hoverable"
                className={`p-3 ${selectedNode?.id === node.id ? 'border-accent' : ''}`}
                onClick={() => setSelectedNode(node)}
              >
                <div className="flex items-start gap-2">
                  <Badge color={TYPE_BADGE_COLOR[node.type] ?? 'neutral'} size="sm">
                    {node.type}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <p className="text-compact text-content-primary line-clamp-2">
                      {node.content}
                    </p>
                    <div className="flex gap-3 mt-1">
                      <ScoreBar value={node.activation} label="Act" />
                      <ScoreBar value={node.importance} label="Imp" />
                    </div>
                  </div>
                  <span className="text-caption text-content-tertiary shrink-0">
                    {node.access_count}x
                  </span>
                </div>
              </Card>
            ))}
          </div>

          {/* Detail Panel */}
          <div className="space-y-4">
            {selectedNode ? (
              <>
                <Card variant="default" className="p-4">
                  <h3 className="text-compact font-semibold text-content-primary mb-2">Engram Detail</h3>
                  <div className="space-y-2 text-compact">
                    <div className="flex gap-2 items-center">
                      <Badge color={TYPE_BADGE_COLOR[selectedNode.type] ?? 'neutral'} size="sm">
                        {selectedNode.type}
                      </Badge>
                      {selectedNode.superseded && (
                        <Badge color="danger" size="sm">superseded</Badge>
                      )}
                    </div>
                    <p className="text-content-secondary">{selectedNode.content}</p>
                    <div className="space-y-1 pt-2 border-t border-border-subtle">
                      <ScoreBar value={selectedNode.activation} label="Activation" />
                      <ScoreBar value={selectedNode.importance} label="Importance" />
                      <ScoreBar value={selectedNode.confidence} label="Confidence" />
                    </div>
                    <div className="text-caption text-content-tertiary space-y-0.5 pt-2">
                      <div>Source: {selectedNode.source_type}</div>
                      <div>Accessed: {selectedNode.access_count} times</div>
                      {selectedNode.created_at && (
                        <div>Created: {new Date(selectedNode.created_at).toLocaleDateString()}</div>
                      )}
                      <div className="font-mono text-micro break-all mt-1 opacity-50">{selectedNode.id}</div>
                    </div>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-3 w-full"
                    onClick={() => exploreNode(selectedNode.id)}
                    icon={<Network size={12} />}
                  >
                    Explore from here
                  </Button>
                </Card>

                {/* Connected Edges */}
                <Card variant="default" className="p-4">
                  <h3 className="text-compact font-semibold text-content-primary mb-2">Connections</h3>
                  <div className="space-y-1.5">
                    {graph.edges
                      .filter((e) => e.source === selectedNode.id || e.target === selectedNode.id)
                      .map((edge, i) => {
                        const otherId = edge.source === selectedNode.id ? edge.target : edge.source
                        const otherNode = graph.nodes.find((n) => n.id === otherId)
                        const isOutgoing = edge.source === selectedNode.id
                        return (
                          <div
                            key={i}
                            className="flex items-center gap-1.5 text-caption p-1.5 rounded-sm hover:bg-surface-card-hover cursor-pointer transition-colors"
                            onClick={() => {
                              const n = graph.nodes.find((n) => n.id === otherId)
                              if (n) setSelectedNode(n)
                            }}
                          >
                            <span className="text-content-tertiary">{isOutgoing ? '\u2192' : '\u2190'}</span>
                            <span className="font-medium text-content-secondary">{edge.relation.replace(/_/g, ' ')}</span>
                            <span className="flex-1 truncate text-content-tertiary">
                              {otherNode?.content.slice(0, 60) ?? otherId.slice(0, 8)}
                            </span>
                            <span className="text-content-tertiary">{edge.weight.toFixed(2)}</span>
                          </div>
                        )
                      })}
                    {graph.edges.filter(
                      (e) => e.source === selectedNode.id || e.target === selectedNode.id
                    ).length === 0 && (
                      <p className="text-caption text-content-tertiary">No connections in this subgraph</p>
                    )}
                  </div>
                </Card>
              </>
            ) : (
              <Card variant="default" className="p-4">
                <p className="text-compact text-content-tertiary">Click a node to see details</p>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Self-Model Tab ───────────────────────────────────────────────────────────

function SelfModelTab() {
  const { data, isLoading, refetch } = useQuery<{ self_model: string }>({
    queryKey: ['engram-self-model'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/self-model'),
  })

  const bootstrap = useMutation({
    mutationFn: () => apiFetch('/mem/api/v1/engrams/self-model/bootstrap', { method: 'POST' }),
    onSuccess: () => refetch(),
  })

  return (
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

      {/* Self-model engrams from graph */}
      <SelfModelEngrams />
    </div>
  )
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

// ── Consolidation Tab ────────────────────────────────────────────────────────

function ConsolidationTab() {
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

      {isLoading && <Skeleton lines={5} />}

      {data?.entries.length === 0 && (
        <EmptyState
          icon={GitMerge}
          title="No consolidation runs yet"
          description="Consolidation triggers automatically on idle (30min), nightly (3 AM), or after 50+ new engrams."
        />
      )}

      {data?.entries.map((entry) => (
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
                <Badge color="neutral" size="sm">{entry.trigger}</Badge>
                <span className="text-caption text-content-tertiary">
                  {entry.created_at ? new Date(entry.created_at).toLocaleString() : 'unknown'}
                </span>
                <span className="text-caption text-content-tertiary ml-auto">{entry.duration_ms}ms</span>
              </div>
            </div>
          </div>

          {expandedId === entry.id && (
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
              <StatCell label="Reviewed" value={entry.engrams_reviewed} />
              <StatCell label="Schemas Created" value={entry.schemas_created} />
              <StatCell label="Edges Strengthened" value={entry.edges_strengthened} />
              <StatCell label="Edges Pruned" value={entry.edges_pruned} />
              <StatCell label="Engrams Pruned" value={entry.engrams_pruned} />
              <StatCell label="Merged" value={entry.engrams_merged} />
              <StatCell label="Contradictions" value={entry.contradictions_resolved} />
              <div className="p-2 rounded-sm bg-surface-elevated">
                <div className="text-caption text-content-tertiary">Maturity</div>
                <div className="text-compact font-medium text-content-primary">
                  {(entry.self_model_updates as Record<string, string>)?.maturity_stage ?? '-'}
                </div>
              </div>
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}

function StatCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="p-2 rounded-sm bg-surface-elevated">
      <div className="text-caption text-content-tertiary">{label}</div>
      <div className="text-display font-mono text-accent">{value}</div>
    </div>
  )
}

// ── Main Component ───────────────────────────────────────────────────────────

export function EngramExplorer() {
  const [activeTab, setActiveTab] = useState('explorer')

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      <PageHeader title="Memory" />

      <Tabs
        tabs={TABS}
        activeTab={activeTab}
        onChange={setActiveTab}
      />

      {activeTab === 'explorer' && <ExplorerTab />}
      {activeTab === 'graph' && <GraphTab />}
      {activeTab === 'self-model' && <SelfModelTab />}
      {activeTab === 'consolidation' && <ConsolidationTab />}
    </div>
  )
}
