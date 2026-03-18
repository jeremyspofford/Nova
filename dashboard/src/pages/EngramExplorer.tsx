import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Search, Network, Brain, RefreshCw, Zap, GitMerge,
  ChevronDown, ChevronRight, Activity, Clock, AlertTriangle,
} from 'lucide-react'
import { apiFetch } from '../api'
import Card from '../components/Card'
import { Input, Button, Badge } from '../components/ui'

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Helpers ───────────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  fact:        'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300',
  episode:     'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300',
  entity:      'bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300',
  preference:  'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300',
  procedure:   'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300',
  schema:      'bg-pink-100 dark:bg-pink-900/40 text-pink-700 dark:text-pink-300',
  goal:        'bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300',
  self_model:  'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300',
}

function TypeBadge({ type }: { type: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TYPE_COLORS[type] ?? 'bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400'}`}>
      {type}
    </span>
  )
}

function ScoreBar({ value, label, color = 'bg-teal-500' }: { value: number; label: string; color?: string }) {
  const pct = Math.round(Math.min(Math.max(value, 0), 1) * 100)
  return (
    <div className="flex items-center gap-1.5" title={`${label}: ${pct}%`}>
      <span className="text-xs text-neutral-500 dark:text-neutral-400 w-16 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-neutral-200 dark:bg-neutral-700">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-neutral-500 dark:text-neutral-400 w-8 text-right">{pct}%</span>
    </div>
  )
}

// ── Tab Navigation ────────────────────────────────────────────────────────────

type TabId = 'overview' | 'graph' | 'self-model' | 'consolidation'

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'overview',       label: 'Overview',       icon: <Activity className="w-4 h-4" /> },
  { id: 'graph',          label: 'Graph Explorer',  icon: <Network className="w-4 h-4" /> },
  { id: 'self-model',     label: 'Self-Model',      icon: <Brain className="w-4 h-4" /> },
  { id: 'consolidation',  label: 'Consolidation',   icon: <GitMerge className="w-4 h-4" /> },
]

// ── Overview Tab ──────────────────────────────────────────────────────────────

function OverviewTab() {
  const { data: stats, isLoading } = useQuery<EngramStats>({
    queryKey: ['engram-stats'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/stats'),
  })

  const { data: routerStatus } = useQuery<RouterStatus>({
    queryKey: ['engram-router-status'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/router-status'),
  })

  if (isLoading) return <p className="text-neutral-500 p-4">Loading...</p>
  if (!stats) return <p className="text-neutral-500 p-4">No data</p>

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Card className="p-4 text-center">
          <div className="text-2xl font-semibold text-teal-600 dark:text-teal-400">{stats.total_engrams}</div>
          <div className="text-xs text-neutral-500 mt-1">Total Engrams</div>
        </Card>
        <Card className="p-4 text-center">
          <div className="text-2xl font-semibold text-teal-600 dark:text-teal-400">{stats.total_edges}</div>
          <div className="text-xs text-neutral-500 mt-1">Edges</div>
        </Card>
        <Card className="p-4 text-center">
          <div className="text-2xl font-semibold text-amber-600 dark:text-amber-400">{stats.total_archived}</div>
          <div className="text-xs text-neutral-500 mt-1">Archived</div>
        </Card>
        <Card className="p-4 text-center">
          <div className="text-2xl font-semibold text-indigo-600 dark:text-indigo-400">
            {routerStatus?.observation_count ?? 0}
          </div>
          <div className="text-xs text-neutral-500 mt-1">Router Observations</div>
        </Card>
      </div>

      {/* Engrams by Type */}
      <Card className="p-5">
        <h3 className="text-sm font-semibold mb-3">Engrams by Type</h3>
        <div className="space-y-2">
          {Object.entries(stats.by_type).map(([type, { total, superseded }]) => (
            <div key={type} className="flex items-center gap-3">
              <TypeBadge type={type} />
              <div className="flex-1 h-2 rounded-full bg-neutral-200 dark:bg-neutral-700">
                <div
                  className="h-full rounded-full bg-teal-500"
                  style={{ width: `${Math.min(100, (total / Math.max(stats.total_engrams, 1)) * 100)}%` }}
                />
              </div>
              <span className="text-sm text-neutral-600 dark:text-neutral-400 w-16 text-right">
                {total}
              </span>
              {superseded > 0 && (
                <span className="text-xs text-neutral-400">({superseded} superseded)</span>
              )}
            </div>
          ))}
        </div>
      </Card>

      {/* Edges by Relation */}
      <Card className="p-5">
        <h3 className="text-sm font-semibold mb-3">Edges by Relation</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Object.entries(stats.by_relation).map(([relation, { count, avg_weight }]) => (
            <div key={relation} className="p-3 rounded-lg bg-neutral-50 dark:bg-neutral-800">
              <div className="text-sm font-medium">{relation.replace(/_/g, ' ')}</div>
              <div className="text-lg font-semibold text-teal-600 dark:text-teal-400">{count}</div>
              <div className="text-xs text-neutral-400">avg weight: {avg_weight}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* Neural Router Status */}
      {routerStatus && (
        <Card className="p-5">
          <h3 className="text-sm font-semibold mb-3">Neural Router</h3>
          <div className="flex items-center gap-3 mb-2">
            <Zap className={`w-4 h-4 ${routerStatus.ready ? 'text-emerald-500' : 'text-amber-500'}`} />
            <span className="text-sm">{routerStatus.message}</span>
          </div>
          <div className="h-2 rounded-full bg-neutral-200 dark:bg-neutral-700">
            <div
              className={`h-full rounded-full transition-all ${routerStatus.ready ? 'bg-emerald-500' : 'bg-amber-500'}`}
              style={{ width: `${Math.min(100, (routerStatus.observation_count / 200) * 100)}%` }}
            />
          </div>
          <div className="text-xs text-neutral-400 mt-1">
            {routerStatus.observation_count} / 200 observations
          </div>
        </Card>
      )}
    </div>
  )
}

// ── Graph Explorer Tab ────────────────────────────────────────────────────────

function GraphTab() {
  const [query, setQuery] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedNode, setSelectedNode] = useState<EngramNode | null>(null)

  const { data: graph, isLoading, refetch } = useQuery<GraphData>({
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

  // Explore from a specific node
  const exploreNode = (nodeId: string) => {
    setSelectedNode(null)
    // Re-fetch with center_id
    apiFetch<GraphData>(`/mem/api/v1/engrams/graph?center_id=${nodeId}&depth=2&max_nodes=50`)
      .then((data) => {
        // Trigger a re-render by updating the query
        setSearchQuery(`__node:${nodeId}`)
      })
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSearch} className="flex gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search engram graph..."
          className="flex-1"
        />
        <Button type="submit">
          <Search className="w-4 h-4 mr-1" /> Explore
        </Button>
      </form>

      {isLoading && <p className="text-neutral-500 p-4">Loading graph...</p>}

      {graph && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Node List */}
          <div className="lg:col-span-2 space-y-2">
            <div className="text-xs text-neutral-400 mb-2">
              {graph.node_count} nodes, {graph.edge_count} edges
            </div>
            {graph.nodes.map((node) => (
              <Card
                key={node.id}
                className={`p-3 cursor-pointer transition-colors hover:border-teal-400 ${
                  selectedNode?.id === node.id ? 'border-teal-500 dark:border-teal-500' : ''
                }`}
                onClick={() => setSelectedNode(node)}
              >
                <div className="flex items-start gap-2">
                  <TypeBadge type={node.type} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-neutral-700 dark:text-neutral-300 line-clamp-2">
                      {node.content}
                    </p>
                    <div className="flex gap-3 mt-1">
                      <ScoreBar value={node.activation} label="Act" color="bg-teal-500" />
                      <ScoreBar value={node.importance} label="Imp" color="bg-amber-500" />
                    </div>
                  </div>
                  <span className="text-xs text-neutral-400 shrink-0">
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
                <Card className="p-4">
                  <h3 className="text-sm font-semibold mb-2">Engram Detail</h3>
                  <div className="space-y-2 text-sm">
                    <div className="flex gap-2 items-center">
                      <TypeBadge type={selectedNode.type} />
                      {selectedNode.superseded && (
                        <Badge color="danger" size="sm">
                          superseded
                        </Badge>
                      )}
                    </div>
                    <p className="text-neutral-700 dark:text-neutral-300">{selectedNode.content}</p>
                    <div className="space-y-1 pt-2 border-t border-neutral-200 dark:border-neutral-700">
                      <ScoreBar value={selectedNode.activation} label="Activation" color="bg-teal-500" />
                      <ScoreBar value={selectedNode.importance} label="Importance" color="bg-amber-500" />
                      <ScoreBar value={selectedNode.confidence} label="Confidence" color="bg-emerald-500" />
                    </div>
                    <div className="text-xs text-neutral-400 space-y-0.5 pt-2">
                      <div>Source: {selectedNode.source_type}</div>
                      <div>Accessed: {selectedNode.access_count} times</div>
                      {selectedNode.created_at && (
                        <div>Created: {new Date(selectedNode.created_at).toLocaleDateString()}</div>
                      )}
                      <div className="font-mono text-[10px] break-all mt-1 opacity-50">{selectedNode.id}</div>
                    </div>
                  </div>
                  <Button
                    className="mt-3 w-full text-xs"
                    onClick={() => exploreNode(selectedNode.id)}
                  >
                    <Network className="w-3 h-3 mr-1" /> Explore from here
                  </Button>
                </Card>

                {/* Connected Edges */}
                <Card className="p-4">
                  <h3 className="text-sm font-semibold mb-2">Connections</h3>
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
                            className="flex items-center gap-1.5 text-xs p-1.5 rounded hover:bg-neutral-50 dark:hover:bg-neutral-800 cursor-pointer"
                            onClick={() => {
                              const n = graph.nodes.find((n) => n.id === otherId)
                              if (n) setSelectedNode(n)
                            }}
                          >
                            <span className="text-neutral-400">{isOutgoing ? '\u2192' : '\u2190'}</span>
                            <span className="font-medium text-neutral-500">{edge.relation.replace(/_/g, ' ')}</span>
                            <span className="flex-1 truncate text-neutral-600 dark:text-neutral-400">
                              {otherNode?.content.slice(0, 60) ?? otherId.slice(0, 8)}
                            </span>
                            <span className="text-neutral-400">{edge.weight.toFixed(2)}</span>
                          </div>
                        )
                      })}
                    {graph.edges.filter(
                      (e) => e.source === selectedNode.id || e.target === selectedNode.id
                    ).length === 0 && (
                      <p className="text-xs text-neutral-400">No connections in this subgraph</p>
                    )}
                  </div>
                </Card>
              </>
            ) : (
              <Card className="p-4">
                <p className="text-sm text-neutral-400">Click a node to see details</p>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Self-Model Tab ────────────────────────────────────────────────────────────

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
      <Card className="p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Brain className="w-4 h-4 text-indigo-500" />
            Self-Model Summary
          </h3>
          <div className="flex gap-2">
            <Button onClick={() => refetch()} className="text-xs">
              <RefreshCw className="w-3 h-3 mr-1" /> Refresh
            </Button>
            <Button onClick={() => bootstrap.mutate()} className="text-xs">
              <Zap className="w-3 h-3 mr-1" /> Bootstrap
            </Button>
          </div>
        </div>
        {isLoading ? (
          <p className="text-neutral-400">Loading...</p>
        ) : (
          <p className="text-sm text-neutral-700 dark:text-neutral-300 leading-relaxed whitespace-pre-wrap">
            {data?.self_model || 'No self-model data. Click Bootstrap to seed initial identity engrams.'}
          </p>
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
    <Card className="p-5">
      <h3 className="text-sm font-semibold mb-3">Identity Engrams</h3>
      <div className="space-y-2">
        {selfNodes.map((node) => (
          <div key={node.id} className="p-3 rounded-lg bg-indigo-50/50 dark:bg-indigo-900/10 border border-indigo-100 dark:border-indigo-800/30">
            <p className="text-sm text-neutral-700 dark:text-neutral-300">{node.content}</p>
            <div className="flex gap-4 mt-1">
              <span className="text-xs text-neutral-400">importance: {node.importance}</span>
              <span className="text-xs text-neutral-400">confidence: {node.confidence}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

// ── Consolidation Tab ─────────────────────────────────────────────────────────

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
        <h3 className="text-sm font-semibold">Consolidation History</h3>
        <Button onClick={() => consolidate.mutate()} disabled={consolidate.isPending} className="text-xs">
          <RefreshCw className={`w-3 h-3 mr-1 ${consolidate.isPending ? 'animate-spin' : ''}`} />
          {consolidate.isPending ? 'Running...' : 'Run Now'}
        </Button>
      </div>

      {isLoading && <p className="text-neutral-500 p-4">Loading...</p>}

      {data?.entries.length === 0 && (
        <Card className="p-5 text-center">
          <p className="text-sm text-neutral-400">No consolidation runs yet.</p>
          <p className="text-xs text-neutral-400 mt-1">
            Consolidation triggers automatically on idle (30min), nightly (3 AM), or after 50+ new engrams.
          </p>
        </Card>
      )}

      {data?.entries.map((entry) => (
        <Card key={entry.id} className="p-4">
          <div
            className="flex items-center gap-3 cursor-pointer"
            onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
          >
            {expandedId === entry.id ? (
              <ChevronDown className="w-4 h-4 text-neutral-400 shrink-0" />
            ) : (
              <ChevronRight className="w-4 h-4 text-neutral-400 shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <Badge color="neutral" size="sm">
                  {entry.trigger}
                </Badge>
                <span className="text-xs text-neutral-400">
                  {entry.created_at ? new Date(entry.created_at).toLocaleString() : 'unknown'}
                </span>
                <span className="text-xs text-neutral-400 ml-auto">{entry.duration_ms}ms</span>
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
              <div className="p-2 rounded bg-neutral-50 dark:bg-neutral-800">
                <div className="text-xs text-neutral-400">Maturity</div>
                <div className="text-sm font-medium">
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
    <div className="p-2 rounded bg-neutral-50 dark:bg-neutral-800">
      <div className="text-xs text-neutral-400">{label}</div>
      <div className="text-lg font-semibold text-teal-600 dark:text-teal-400">{value}</div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function EngramExplorer() {
  const [activeTab, setActiveTab] = useState<TabId>('overview')

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <Network className="w-5 h-5 text-teal-600" />
          Engram Network
        </h1>
      </div>

      {/* Tab Bar */}
      <div className="flex gap-1 p-1 rounded-lg bg-neutral-100 dark:bg-neutral-800 w-fit">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
              activeTab === tab.id
                ? 'bg-white dark:bg-neutral-700 shadow-sm font-medium'
                : 'text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && <OverviewTab />}
      {activeTab === 'graph' && <GraphTab />}
      {activeTab === 'self-model' && <SelfModelTab />}
      {activeTab === 'consolidation' && <ConsolidationTab />}
    </div>
  )
}
