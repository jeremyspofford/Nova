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
  EmptyState, Skeleton, Tooltip, Sheet,
} from '../components/ui'
import { ForceGraph } from '../components/ForceGraph'
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

// Hex colors for the graph canvas — must stay in sync with ForceGraph's TYPE_COLORS
const GRAPH_TYPE_COLORS: Record<string, string> = {
  fact:       '#60a5fa',
  entity:     '#2dd4bf',
  preference: '#34d399',
  procedure:  '#a1a1aa',
  self_model: '#818cf8',
  episode:    '#fbbf24',
  schema:     '#f87171',
  goal:       '#c084fc',
}

const TYPE_DESCRIPTIONS: Record<string, string> = {
  fact:       'Objective knowledge or information Nova has learned',
  self_model: "Nova's self-knowledge and identity traits — emerges through consolidation",
  procedure:  'How-to knowledge and learned workflows',
  entity:     'Named people, systems, or concepts Nova knows about',
  preference: 'User preferences and communication style',
  episode:    'Specific past interactions or events Nova remembers',
  schema:     'Patterns extracted from repeated experiences — generalized knowledge',
  goal:       'Objectives or intentions Nova is tracking',
}

// ── Score bar helper ─────────────────────────────────────────────────────────

const SCORE_BAR_TOOLTIPS: Record<string, string> = {
  Importance: 'How critical this memory is to Nova — higher means it\'s referenced more in decisions.',
  Activation: 'How "hot" this memory is — rises when accessed recently or frequently, decays over time.',
  Confidence: 'How certain Nova is that this memory is accurate — lower confidence memories may be revised.',
}

function ScoreBar({ value, label, compact }: { value: number; label: string; compact?: boolean }) {
  const pct = Math.round(Math.min(Math.max(value, 0), 1) * 100)
  const tip = SCORE_BAR_TOOLTIPS[label]
  const labelEl = (
    <span className={`text-caption text-content-tertiary shrink-0 ${compact ? 'w-[4.5rem]' : 'w-[5.5rem]'}`}>
      {label}
    </span>
  )
  return (
    <div className="flex items-center gap-1.5" title={`${label}: ${pct}%`}>
      {tip ? <Tooltip content={tip}>{labelEl}</Tooltip> : labelEl}
      <ProgressBar value={pct} size="sm" className="flex-1" />
      <span className="text-caption text-content-tertiary w-8 text-right">{pct}%</span>
    </div>
  )
}

// ── Tab config ───────────────────────────────────────────────────────────────

const TABS = [
  { id: 'explorer', label: 'Explorer', icon: Activity },
  { id: 'graph', label: 'Graph Explorer', icon: Network },
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
        <Metric label="Total Engrams" value={stats.total_engrams} tooltip="Individual memory units — facts, procedures, entities, and preferences Nova has learned." />
        <Metric label="Edges" value={stats.total_edges} tooltip="Connections between engrams forming the memory graph." />
        <Metric label="Archived" value={stats.total_archived} tooltip="Engrams pruned during consolidation but preserved for reference." />
        <Metric label="Router Observations" value={routerStatus?.observation_count ?? 0} tooltip="Retrieval feedback samples used to train the neural re-ranker." />
      </div>

      {/* Type distribution */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setTypeFilter(null)}
          className={!typeFilter ? undefined : 'opacity-50'}
        >
          <Badge color="neutral" size="sm">All</Badge>
        </button>
        {Object.entries(stats.by_type).map(([type, { total }]) => {
          const desc = TYPE_DESCRIPTIONS[type]
          const btn = (
            <button
              key={type}
              onClick={() => setTypeFilter(typeFilter === type ? null : type)}
              className={typeFilter && typeFilter !== type ? 'opacity-40' : undefined}
            >
              <Badge color={TYPE_BADGE_COLOR[type] ?? 'neutral'} size="sm">
                {type} ({total})
              </Badge>
            </button>
          )
          return desc ? <Tooltip key={type} content={desc}>{btn}</Tooltip> : btn
        })}
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
          {filteredNodes.map(node => {
            const typeDesc = TYPE_DESCRIPTIONS[node.type]
            const badge = (
              <Badge color={TYPE_BADGE_COLOR[node.type] ?? 'neutral'} size="sm">
                {node.type === 'self_model' ? 'self model' : node.type}
              </Badge>
            )
            return (
            <Card key={node.id} variant="hoverable" className="p-4">
              <div className="flex items-start gap-3">
                {typeDesc ? <Tooltip content={typeDesc}>{badge}</Tooltip> : badge}
                <div className="flex-1 min-w-0">
                  <p className="text-compact text-content-primary line-clamp-2">{node.content}</p>
                  <div className="flex gap-4 mt-2">
                    <ScoreBar value={node.importance} label="Importance" compact />
                    <ScoreBar value={node.activation} label="Activation" compact />
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <Tooltip content="Times this memory was retrieved during conversations">
                    <span className="text-caption text-content-tertiary">{node.access_count.toLocaleString()} recalls</span>
                  </Tooltip>
                  {node.created_at && (
                    <span className="text-micro text-content-tertiary">
                      {new Date(node.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>
            </Card>
            )
          })}
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
    setSearchQuery(`__node:${nodeId}`)
  }

  const handleSelectNode = (nodeId: string) => {
    const node = graph?.nodes.find(n => n.id === nodeId)
    if (node) setSelectedNode(node)
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSearch} className="flex gap-2">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Search memories..."
          debounceMs={0}
          className="flex-1"
        />
        <Button type="submit" icon={<Network size={14} />}>
          Explore
        </Button>
      </form>

      {isLoading && <Skeleton lines={5} />}

      {graph && graph.nodes.length > 0 && (
        <>
          <Card variant="default" className="overflow-hidden">
            <div className="h-[600px] relative">
              <ForceGraph
                nodes={graph.nodes}
                edges={graph.edges}
                selectedId={selectedNode?.id ?? null}
                onSelectNode={handleSelectNode}
                className="w-full h-full"
              />
              <div className="absolute bottom-3 left-3 text-micro text-content-tertiary bg-surface-card/80 px-2 py-1 rounded-sm">
                {graph.node_count} memories, {graph.edge_count} connections — click to select, drag to rearrange
              </div>
              {/* Type legend */}
              <div className="absolute top-3 right-3 bg-surface-card/90 border border-border-subtle rounded-sm px-3 py-2 space-y-1">
                {Array.from(new Set(graph.nodes.map(n => n.type))).map(type => (
                  <div key={type} className="flex items-center gap-2 text-micro">
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: GRAPH_TYPE_COLORS[type] ?? '#71717a' }}
                    />
                    <Tooltip content={TYPE_DESCRIPTIONS[type] ?? type}>
                      <span className="text-content-tertiary cursor-help">
                        {type === 'self_model' ? 'self model' : type}
                      </span>
                    </Tooltip>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* Detail Sheet */}
          <Sheet
            open={!!selectedNode}
            onClose={() => setSelectedNode(null)}
            title="Memory Detail"
            width="wide"
          >
            {selectedNode && (
              <div className="p-5 space-y-5">
                {/* Type & status */}
                <div className="flex gap-2 items-center flex-wrap">
                  {(() => {
                    const desc = TYPE_DESCRIPTIONS[selectedNode.type]
                    const badge = (
                      <Badge color={TYPE_BADGE_COLOR[selectedNode.type] ?? 'neutral'} size="sm">
                        {selectedNode.type === 'self_model' ? 'self model' : selectedNode.type}
                      </Badge>
                    )
                    return desc ? <Tooltip content={desc}>{badge}</Tooltip> : badge
                  })()}
                  {selectedNode.superseded && (
                    <Badge color="danger" size="sm">superseded</Badge>
                  )}
                </div>

                {/* Full content */}
                <p className="text-body text-content-primary leading-relaxed">{selectedNode.content}</p>

                {/* Scores */}
                <div className="space-y-2 pt-2 border-t border-border-subtle">
                  <h4 className="text-caption font-semibold text-content-secondary uppercase tracking-wider">Scores</h4>
                  <ScoreBar value={selectedNode.activation} label="Activation" />
                  <ScoreBar value={selectedNode.importance} label="Importance" />
                  <ScoreBar value={selectedNode.confidence} label="Confidence" />
                </div>

                {/* Metadata */}
                <div className="space-y-1.5 pt-2 border-t border-border-subtle">
                  <h4 className="text-caption font-semibold text-content-secondary uppercase tracking-wider">Metadata</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <div className="text-micro text-content-tertiary">Source</div>
                      <div className="text-compact text-content-primary">{selectedNode.source_type}</div>
                    </div>
                    <div>
                      <div className="text-micro text-content-tertiary">Recalled</div>
                      <div className="text-compact text-content-primary">{selectedNode.access_count.toLocaleString()} times</div>
                    </div>
                    {selectedNode.created_at && (
                      <div>
                        <div className="text-micro text-content-tertiary">Created</div>
                        <div className="text-compact text-content-primary">{new Date(selectedNode.created_at).toLocaleDateString()}</div>
                      </div>
                    )}
                  </div>
                  <div className="font-mono text-micro text-content-tertiary break-all mt-2 opacity-50">{selectedNode.id}</div>
                </div>

                {/* Actions */}
                <Button
                  variant="secondary"
                  size="sm"
                  className="w-full"
                  onClick={() => exploreNode(selectedNode.id)}
                  icon={<Network size={12} />}
                >
                  Explore from here
                </Button>

                {/* Connections */}
                <div className="pt-2 border-t border-border-subtle">
                  <h4 className="text-caption font-semibold text-content-secondary uppercase tracking-wider mb-2">Connections</h4>
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
                            className="flex items-center gap-1.5 text-caption p-2 rounded-sm hover:bg-surface-card-hover cursor-pointer transition-colors"
                            onClick={() => {
                              const n = graph.nodes.find((n) => n.id === otherId)
                              if (n) setSelectedNode(n)
                            }}
                          >
                            <span className="text-content-tertiary">{isOutgoing ? '\u2192' : '\u2190'}</span>
                            <span className="font-medium text-content-secondary">{edge.relation.replace(/_/g, ' ')}</span>
                            <span className="flex-1 truncate text-content-tertiary">
                              {otherNode?.content ?? otherId.slice(0, 8)}
                            </span>
                            <Tooltip content="Connection strength (0.0 = weak, 1.0 = strong)">
                              <span className="text-content-tertiary">{edge.weight.toFixed(2)}</span>
                            </Tooltip>
                          </div>
                        )
                      })}
                    {graph.edges.filter(
                      (e) => e.source === selectedNode.id || e.target === selectedNode.id
                    ).length === 0 && (
                      <p className="text-caption text-content-tertiary">No connections in this subgraph</p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </Sheet>
        </>
      )}

      {graph && graph.nodes.length === 0 && (
        <EmptyState
          icon={Network}
          title="No memories found"
          description={searchQuery ? `No results for "${searchQuery}"` : "Memory is empty. Memories are created through conversations."}
        />
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
          <p className="text-caption text-content-tertiary mt-1 mb-2">
            Nova's emergent self-knowledge — learned traits that shape how it thinks and communicates. Unlike the Persona in Settings (which you write), the self-model evolves automatically through consolidation.
          </p>
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

// ── Help entries per tab ─────────────────────────────────────────────────────

const HELP_ENTRIES: Record<string, { term: string; definition: string }[]> = {
  explorer: [
    { term: 'Engram', definition: 'An individual unit of memory — a fact, preference, procedure, or entity that Nova learned from conversations.' },
    { term: 'Activation', definition: 'How "hot" a memory is — rises when accessed recently or frequently, decays over time like a neuron.' },
    { term: 'Importance', definition: 'How critical this memory is for Nova\'s operation — high-importance memories are retrieved more often.' },
    { term: 'Recalls', definition: 'The total number of times Nova retrieved this memory while generating responses.' },
    { term: 'Neural Router', definition: 'A learned ML re-ranker that improves which memories are retrieved. Trains automatically after 200+ retrieval observations.' },
    { term: 'Edges', definition: 'Connections between memories forming a knowledge graph — e.g. "Jeremy" is connected to "Aria Labs" via a "founded by" relation.' },
  ],
  graph: [
    { term: 'Node size', definition: 'Larger circles = higher importance. Node brightness = higher activation (recently/frequently used).' },
    { term: 'Node color', definition: 'Each memory type has a color — see the legend in the top-right of the graph.' },
    { term: 'Edge lines', definition: 'Lines between nodes are connections. Highlighted teal when you select a node to show its neighbors.' },
    { term: 'Connection weight', definition: 'A 0.00–1.00 score showing how strongly two memories are linked. Higher = more closely related.' },
    { term: 'Explore from here', definition: 'Re-centers the graph on the selected memory, loading its neighborhood of connections.' },
  ],
  'self-model': [
    { term: 'Self-Model', definition: 'Nova\'s emergent self-knowledge — personality traits and behavioral patterns it has learned about itself through conversations.' },
    { term: 'Bootstrap', definition: 'Seeds initial identity engrams so Nova has a starting self-concept before learning from conversations.' },
    { term: 'Identity Engrams', definition: 'Specific self-model memories — individual traits like "I tend to be thorough" or "I prefer concise responses."' },
  ],
  consolidation: [
    { term: 'Consolidation', definition: 'A "sleep cycle" for memory — reviews recent memories, extracts patterns, resolves contradictions, and prunes weak connections.' },
    { term: 'Schemas Created', definition: 'Generalized patterns extracted from repeated experiences (e.g. "user prefers short answers" from multiple similar episodes).' },
    { term: 'Edges Strengthened', definition: 'Connections between memories that were reinforced because they frequently co-occur or support each other.' },
    { term: 'Edges Pruned', definition: 'Weak connections removed because they were rarely used or contradicted by newer information.' },
    { term: 'Contradictions', definition: 'Conflicting memories that were identified and resolved — e.g. two facts that can\'t both be true.' },
    { term: 'Maturity', definition: 'The current growth stage of Nova\'s memory system — progresses from nascent through developing to mature.' },
  ],
}

// ── Main Component ───────────────────────────────────────────────────────────

export function EngramExplorer() {
  const [activeTab, setActiveTab] = useState('explorer')

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      <PageHeader title="Memory" description="Nova's persistent memory — everything it learns from conversations is stored as individual memories (engrams) connected in a knowledge graph." helpEntries={HELP_ENTRIES[activeTab] ?? []} />

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
