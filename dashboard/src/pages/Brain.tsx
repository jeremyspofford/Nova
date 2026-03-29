import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, X, ChevronRight, Network, Settings, Menu, Mic } from 'lucide-react'
import { apiFetch } from '../api'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { BrainChat } from '../components/BrainChat'
import { ForceGraph3D } from '../components/ForceGraph3D'
import type { ForceGraph3DHandle } from '../components/ForceGraph3D'
import type { ActivityStep } from '../stores/chat-store'

// ── Types ────────────────────────────────────────────────────────────────────

interface GraphNode {
  id: string
  type: string
  content: string
  activation: number
  importance: number
  access_count: number
  confidence: number
  source_type: string
  superseded?: boolean
  created_at?: string | null
  cluster_id?: number
  cluster_label?: string
}

interface GraphEdge {
  source: string
  target: string
  relation: string
  weight: number
}

interface ClusterInfo {
  id: number
  label: string
  count: number
}

interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  clusters?: ClusterInfo[]
  node_count: number
  edge_count: number
}

// ── Constants ────────────────────────────────────────────────────────────────

// Single clustered layout — topic clustering force handles spatial grouping

const TYPE_COLORS: Record<string, string> = {
  fact:       '#60a5fa',
  entity:     '#2dd4bf',
  preference: '#34d399',
  procedure:  '#a1a1aa',
  self_model: '#818cf8',
  episode:    '#fbbf24',
  schema:     '#f87171',
  goal:       '#c084fc',
}

const TYPE_FILTER_CLASSES: Record<string, string> = {
  fact: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  entity: 'bg-teal-500/20 text-teal-300 border-teal-500/30',
  preference: 'bg-green-500/20 text-green-300 border-green-500/30',
  procedure: 'bg-stone-500/20 text-stone-300 border-stone-500/30',
  self_model: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  episode: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  schema: 'bg-red-500/20 text-red-300 border-red-500/30',
  goal: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
}

const TYPE_DESCRIPTIONS: Record<string, string> = {
  fact:       'Objective knowledge or information Nova has learned',
  self_model: "Nova's self-knowledge and identity traits",
  procedure:  'How-to knowledge and learned workflows',
  entity:     'Named people, systems, or concepts',
  preference: 'User preferences and communication style',
  episode:    'Specific past interactions or events',
  schema:     'Patterns extracted from repeated experiences',
  goal:       'Objectives or intentions Nova is tracking',
}

const CLUSTER_COLORS = [
  '#818cf8', '#60a5fa', '#2dd4bf', '#34d399', '#fbbf24',
  '#f87171', '#c084fc', '#fb923c', '#a3e635', '#22d3ee',
  '#e879f9', '#f472b6', '#38bdf8', '#4ade80', '#facc15',
  '#a78bfa', '#67e8f9', '#fca5a5', '#86efac', '#fde68a',
]

const SCORE_TOOLTIPS: Record<string, string> = {
  Activation: 'How "hot" this memory is — rises when accessed, decays over time.',
  Importance: 'How critical for decisions — affects retrieval frequency.',
  Confidence: 'How certain Nova is this memory is accurate.',
}

// ── Score bar (glass-styled for overlay) ─────────────────────────────────────

function ScoreBar({ value, label, color }: { value: number; label: string; color: string }) {
  const pct = Math.round(Math.min(Math.max(value, 0), 1) * 100)
  return (
    <div className="flex items-center gap-2" title={SCORE_TOOLTIPS[label] ?? `${label}: ${pct}%`}>
      <span className="text-[11px] text-stone-500 w-[4.5rem] shrink-0">{label}</span>
      <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[10px] text-stone-600 w-7 text-right">{pct}%</span>
    </div>
  )
}

// ── Component ────────────────────────────────────────────────────────────────

export default function Brain() {
  const queryClient = useQueryClient()
  const graphRef = useRef<ForceGraph3DHandle>(null)

  // Graph data
  const { data: graph } = useQuery<GraphData>({
    queryKey: ['brain-graph'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/graph?mode=full&max_nodes=5000'),
    staleTime: 30_000,
    retry: 1,
  })

  // UI state
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [chatOpen, setChatOpen] = useState(false)
  const layout = 'clustered'
  const [searchQuery, setSearchQuery] = useState('')
  const [searchActive, setSearchActive] = useState(false)
  const [focusCluster, setFocusCluster] = useState<{ id: number; ts: number } | null>(null)
  const [expandedClusterId, setExpandedClusterId] = useState<number | null>(null)
  const [focusNode, setFocusNode] = useState<{ id: string; ts: number } | null>(null)
  const [showBgStars, setShowBgStars] = useLocalStorage('brain.showBgStars', true)
  const [showInnerStars, setShowInnerStars] = useLocalStorage('brain.showInnerStars', false)
  const [showNebulae, setShowNebulae] = useLocalStorage('brain.showNebulae', true)
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [topicsOpen, setTopicsOpen] = useState(false)
  const [bloomStrength, setBloomStrength] = useLocalStorage('brain.bloomStrength', 1.5)

  // Search-filtered graph
  const { data: searchGraph } = useQuery<GraphData>({
    queryKey: ['brain-graph-search', searchQuery],
    queryFn: () => apiFetch(`/mem/api/v1/engrams/graph?query=${encodeURIComponent(searchQuery)}&depth=2&max_nodes=200`),
    enabled: searchActive && searchQuery.length > 2,
    staleTime: 10_000,
  })

  const activeGraph = searchActive && searchGraph ? searchGraph : graph

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === '/' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        setChatOpen(o => !o)
      }
      if (e.key === 'Escape') {
        if (settingsOpen) setSettingsOpen(false)
        else if (topicsOpen) setTopicsOpen(false)
        else if (chatOpen) setChatOpen(false)
        else if (selectedNode) setSelectedNode(null)
        else if (searchActive) { setSearchActive(false); setSearchQuery('') }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [chatOpen, searchActive, selectedNode, settingsOpen, topicsOpen])

  // Activity step handler — highlights actual retrieved engrams when IDs are available
  const handleActivityStep = useCallback((_step: ActivityStep) => {
    if (!activeGraph?.nodes) return
    if (_step.step === 'memory' && _step.state === 'done' && _step.engram_ids?.length) {
      // Real engram IDs from the memory retrieval — highlight exactly what Nova recalled
      const graphNodeIds = new Set(activeGraph.nodes.map(n => n.id))
      const matchingIds = _step.engram_ids.filter(id => graphNodeIds.has(id))
      if (matchingIds.length > 0) {
        graphRef.current?.highlightNodes(matchingIds)
      }
    } else if (_step.step === 'memory' && _step.state === 'running') {
      // Fallback: no IDs yet (running state), show a subtle pulse
      graphRef.current?.pulseAll(1000)
    }
    if (_step.step === 'generating' && _step.state === 'running') {
      graphRef.current?.pulseAll(2000)
    }
  }, [activeGraph])

  const handleStreamComplete = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['brain-graph'] })
  }, [queryClient])

  // Track previous node IDs for fade-in animation
  const prevNodeIdsRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!activeGraph?.nodes) return
    const currentIds = new Set(activeGraph.nodes.map(n => n.id))
    if (prevNodeIdsRef.current.size > 0) {
      const newIds = activeGraph.nodes
        .filter(n => !prevNodeIdsRef.current.has(n.id))
        .map(n => n.id)
      if (newIds.length > 0) {
        graphRef.current?.fadeInNodes(newIds)
      }
    }
    prevNodeIdsRef.current = currentIds
  }, [activeGraph])

  // Selected node data (graph has truncated content)
  const selectedNodeBasic = selectedNode
    ? activeGraph?.nodes.find(n => n.id === selectedNode) ?? null
    : null

  const { data: engramStats } = useQuery<{
    total_engrams: number
    total_edges: number
    total_archived: number
    by_type: Record<string, { total: number; superseded: number }>
  }>({
    queryKey: ['engram-stats'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/stats'),
    staleTime: 30_000,
  })

  const { data: routerStatus } = useQuery<{ observation_count: number }>({
    queryKey: ['engram-router-status'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/router-status'),
    staleTime: 30_000,
  })

  // Fetch full engram detail (untruncated content) when a node is selected
  const { data: selectedNodeFull } = useQuery({
    queryKey: ['engram-detail', selectedNode],
    queryFn: () => apiFetch<GraphNode>(`/mem/api/v1/engrams/engrams/${selectedNode}`),
    enabled: !!selectedNode,
    staleTime: 60_000,
  })

  // Merge: use full content from detail query, fall back to graph node data
  const selectedNodeData = selectedNodeBasic
    ? { ...selectedNodeBasic, content: selectedNodeFull?.content ?? selectedNodeBasic.content }
    : null

  // Handle search submit
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (searchQuery.trim().length > 2) {
      setSearchActive(true)
    }
  }

  const clearSearch = () => {
    setSearchActive(false)
    setSearchQuery('')
  }

  const filteredGraphData = useMemo(() => {
    if (!activeGraph || !typeFilter) return activeGraph
    const filteredNodes = activeGraph.nodes.filter(n => n.type === typeFilter)
    const nodeIds = new Set(filteredNodes.map(n => n.id))
    const filteredEdges = activeGraph.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
    return { ...activeGraph, nodes: filteredNodes, edges: filteredEdges }
  }, [activeGraph, typeFilter])

  // Navigate to node (explore from here)
  const exploreNode = (nodeId: string) => {
    setFocusNode({ id: nodeId, ts: Date.now() })
  }

  // Connections for selected node
  const selectedConnections = selectedNodeData && activeGraph
    ? activeGraph.edges.filter(e => e.source === selectedNodeData.id || e.target === selectedNodeData.id)
    : []

  const nodeColor = selectedNodeData
    ? TYPE_COLORS[selectedNodeData.type] ?? '#71717a'
    : '#71717a'

  return (
    <div className="relative w-full h-screen overflow-hidden bg-black">
      {/* Full-viewport graph */}
      <ForceGraph3D
        ref={graphRef}
        nodes={filteredGraphData?.nodes ?? []}
        edges={filteredGraphData?.edges ?? []}
        clusters={filteredGraphData?.clusters}
        selectedId={selectedNode}
        onSelectNode={setSelectedNode}
        onBackgroundClick={() => setSelectedNode(null)}
        focusClusterId={focusCluster?.id ?? null}
        focusClusterTs={focusCluster?.ts}
        focusNodeId={focusNode?.id ?? null}
        focusNodeTs={focusNode?.ts}
        autoSpin={false}
        bgColor="galaxy"
        layoutPreset={layout}
        neuralMode={{
          enabled: true,
          breathingRate: 0.02,
          breathingAmplitude: 0.05,
          bloomStrength,
          particlesAlways: true,
        }}
        showBackgroundStars={showBgStars}
        showInnerStars={showInnerStars}
        showNebulae={showNebulae}
        className="w-full h-full"
      />

      {/* ── HUD: Stats pill top-center ─────────────────────────────── */}
      <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10">
        <div className="bg-black/40 backdrop-blur-sm border border-white/[0.06] rounded-full px-3.5 py-1 flex items-center gap-2">
          {engramStats ? (
            <>
              <span className="text-[10px] text-stone-500">{engramStats.total_engrams.toLocaleString()} memories</span>
              <span className="w-px h-2.5 bg-white/[0.08]" />
              <span className="text-[10px] text-stone-500">
                {activeGraph?.clusters ? `${activeGraph.clusters.length} topics` : `${engramStats.total_edges.toLocaleString()} edges`}
              </span>
            </>
          ) : (
            <span className="text-[10px] text-stone-600">loading...</span>
          )}
        </div>
      </div>

      {/* ── HUD: Topics icon top-left ──────────────────────────────── */}
      <button
        onClick={() => setTopicsOpen(v => !v)}
        className="absolute top-3 left-3 z-10 w-8 h-8 rounded-full bg-black/40 backdrop-blur-sm border border-white/[0.06] flex items-center justify-center text-stone-600 hover:text-stone-300 transition-colors"
        title="Topics & Search"
      >
        <Menu size={14} />
      </button>

      {/* ── HUD: Settings icon top-right ───────────────────────────── */}
      <button
        onClick={() => setSettingsOpen(v => !v)}
        className="absolute top-3 right-3 z-10 w-8 h-8 rounded-full bg-black/40 backdrop-blur-sm border border-white/[0.06] flex items-center justify-center text-stone-600 hover:text-stone-300 transition-colors"
        title="Display settings"
      >
        <Settings size={14} />
      </button>

      {/* ── HUD: Search hint bottom-left ───────────────────────────── */}
      <div className="absolute bottom-5 left-3 z-10">
        <div className="bg-black/30 rounded-full px-2.5 py-1">
          <span className="text-[9px] text-stone-700">/ search</span>
        </div>
      </div>

      {/* ── Overlay: Topics & Search ───────────────────────────────── */}
      {topicsOpen && (
        <div
          className="absolute inset-0 z-20"
          onClick={(e) => { if (e.target === e.currentTarget) setTopicsOpen(false) }}
        >
          <div className="absolute top-0 left-0 w-[280px] h-full bg-black/80 backdrop-blur-md border-r border-white/[0.06] p-4 overflow-y-auto scrollbar-thin">
            {/* Close */}
            <button
              onClick={() => setTopicsOpen(false)}
              className="absolute top-3 right-3 text-stone-600 hover:text-stone-300 transition-colors"
            >
              <X size={14} />
            </button>

            {/* Search */}
            <form onSubmit={handleSearch} className="flex items-center gap-1.5 border border-white/10 rounded-lg px-3 py-1.5 mb-4">
              <Search size={13} className="text-stone-600 shrink-0" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => { setSearchQuery(e.target.value); if (!e.target.value) clearSearch() }}
                placeholder="Search memories..."
                className="bg-transparent text-sm text-stone-300 placeholder:text-stone-700 outline-none flex-1"
              />
              {searchActive && (
                <button type="button" onClick={clearSearch} className="text-stone-600 hover:text-stone-300">
                  <X size={11} />
                </button>
              )}
            </form>

            {/* Type distribution filter */}
            {engramStats?.by_type && (
              <div className="mb-3 pb-3 border-b border-white/5">
                <p className="text-[10px] uppercase tracking-wider text-stone-500 mb-2 px-1">Filter by type</p>
                <div className="flex flex-wrap gap-1">
                  <button
                    onClick={() => setTypeFilter(null)}
                    className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                      !typeFilter
                        ? 'border-white/20 text-white bg-white/10'
                        : 'border-white/5 text-stone-600 hover:text-stone-400'
                    }`}
                  >
                    All
                  </button>
                  {Object.entries(engramStats.by_type).map(([type, { total }]) => (
                    <button
                      key={type}
                      onClick={() => setTypeFilter(typeFilter === type ? null : type)}
                      className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                        typeFilter === type
                          ? TYPE_FILTER_CLASSES[type] ?? 'border-white/20 text-white'
                          : typeFilter
                            ? 'border-white/5 text-stone-700 hover:text-stone-500'
                            : 'border-white/5 text-stone-500 hover:text-stone-300'
                      }`}
                    >
                      {type === 'self_model' ? 'self model' : type} ({total})
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Topic/cluster list */}
            {activeGraph && activeGraph.clusters && activeGraph.clusters.length > 0 ? (
              <>
                <div className="text-[10px] text-stone-600 uppercase tracking-wider px-1 pb-1.5 mb-1 border-b border-white/5">
                  {activeGraph.clusters.length} topics
                </div>
                {activeGraph.clusters.slice(0, 30).map(cluster => {
                  const color = CLUSTER_COLORS[cluster.id % CLUSTER_COLORS.length]
                  const isExpanded = expandedClusterId === cluster.id
                  const isFocused = focusCluster?.id === cluster.id
                  return (
                    <div key={cluster.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setFocusCluster({ id: cluster.id, ts: Date.now() })
                          setExpandedClusterId(isExpanded ? null : cluster.id)
                        }}
                        className={`flex items-center gap-1.5 w-full text-left text-[11px] rounded px-1.5 py-1 transition-colors ${
                          isFocused ? 'bg-white/10' : 'hover:bg-white/5'
                        }`}
                      >
                        <span
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}` }}
                        />
                        <span className="text-stone-300 truncate flex-1" title={cluster.label}>
                          {cluster.label}
                        </span>
                        <span className="text-stone-600 text-[10px] shrink-0">{cluster.count}</span>
                        <ChevronRight
                          size={10}
                          className={`text-stone-600 shrink-0 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                        />
                      </button>
                      {isExpanded && (
                        <div className="pl-5 pr-1 py-0.5 space-y-px">
                          {activeGraph.nodes
                            .filter(n => n.cluster_id === cluster.id)
                            .sort((a, b) => b.importance - a.importance)
                            .slice(0, 12)
                            .map(node => (
                              <button
                                key={node.id}
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setSelectedNode(node.id)
                                  setFocusNode({ id: node.id, ts: Date.now() })
                                }}
                                className="block w-full text-left text-[10px] text-stone-500 hover:text-stone-200 truncate rounded px-1 py-0.5 hover:bg-white/5 transition-colors"
                                title={node.content}
                              >
                                {node.content}
                              </button>
                            ))}
                          {activeGraph.nodes.filter(n => n.cluster_id === cluster.id).length > 12 && (
                            <div className="text-[10px] text-stone-600 px-1 pt-0.5">
                              +{activeGraph.nodes.filter(n => n.cluster_id === cluster.id).length - 12} more
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
                {activeGraph.clusters.length > 30 && (
                  <div className="text-[10px] text-stone-600 px-1.5 pt-1 border-t border-white/5 mt-1">
                    +{activeGraph.clusters.length - 30} smaller clusters
                  </div>
                )}
              </>
            ) : activeGraph ? (
              <>
                <div className="text-[10px] text-stone-600 uppercase tracking-wider px-1 pb-1.5 mb-1 border-b border-white/5">
                  Types
                </div>
                {Array.from(new Set(activeGraph.nodes.map(n => n.type))).map(type => (
                  <div key={type} className="flex items-center gap-2 text-[11px] px-1.5 py-0.5">
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: TYPE_COLORS[type] ?? '#71717a', boxShadow: `0 0 6px ${TYPE_COLORS[type] ?? '#71717a'}` }}
                    />
                    <span className="text-stone-400" title={TYPE_DESCRIPTIONS[type]}>
                      {type === 'self_model' ? 'self model' : type}
                    </span>
                  </div>
                ))}
              </>
            ) : null}
          </div>
        </div>
      )}

      {/* ── Overlay: Display Settings ──────────────────────────────── */}
      {settingsOpen && (
        <div
          className="absolute inset-0 z-20"
          onClick={(e) => { if (e.target === e.currentTarget) setSettingsOpen(false) }}
        >
          <div className="absolute top-12 right-3 w-[220px] bg-black/80 backdrop-blur-md border border-white/[0.08] rounded-xl p-4 space-y-4">
            <button
              onClick={() => setSettingsOpen(false)}
              className="absolute top-3 right-3 text-stone-600 hover:text-stone-300 transition-colors"
            >
              <X size={12} />
            </button>

            <div className="text-[10px] text-stone-500 uppercase tracking-wider">Display</div>

            {/* Bloom strength */}
            <div className="space-y-1.5">
              <div className="text-[10px] text-stone-600">Bloom</div>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="0"
                  max="3"
                  step="0.1"
                  value={bloomStrength}
                  onChange={(e) => setBloomStrength(parseFloat(e.target.value))}
                  className="flex-1 h-1 accent-teal-500 bg-white/10 rounded-full appearance-none [&::-webkit-slider-thumb]:w-2.5 [&::-webkit-slider-thumb]:h-2.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-teal-400 [&::-webkit-slider-thumb]:appearance-none"
                />
                <span className="text-[10px] text-stone-500 w-6 text-right">{bloomStrength.toFixed(1)}</span>
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-[10px] text-stone-600 mb-1">Background</div>
              {[
                { label: 'Stars', value: showBgStars, set: setShowBgStars },
                { label: 'Inner Stars', value: showInnerStars, set: setShowInnerStars },
                { label: 'Clouds', value: showNebulae, set: setShowNebulae },
              ].map(({ label, value, set }) => (
                <button
                  key={label}
                  onClick={() => set((v: boolean) => !v)}
                  className={`block w-full text-left text-[11px] px-2 py-1 rounded transition-colors ${
                    value
                      ? 'text-teal-400 bg-teal-500/10'
                      : 'text-stone-600 hover:text-stone-400'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Memory Detail Modal ─────────────────────────────────────────── */}
      {selectedNodeData && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center"
          onClick={(e) => { if (e.target === e.currentTarget) setSelectedNode(null) }}
        >
          <div className="w-[480px] max-h-[70vh] overflow-y-auto bg-zinc-900/90 backdrop-blur-md border border-white/10 rounded-xl shadow-2xl scrollbar-thin">
            {/* Header */}
            <div className="sticky top-0 bg-zinc-900/95 backdrop-blur-md border-b border-white/5 px-5 py-3.5 flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="text-[11px] px-1.5 py-0.5 rounded font-medium shrink-0"
                  style={{
                    backgroundColor: `${nodeColor}20`,
                    color: nodeColor,
                  }}
                >
                  {selectedNodeData.type === 'self_model' ? 'self model' : selectedNodeData.type}
                </span>
                {selectedNodeData.superseded && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 shrink-0">
                    superseded
                  </span>
                )}
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="text-stone-600 hover:text-stone-300 transition-colors"
              >
                <X size={14} />
              </button>
            </div>

            <div className="p-5 space-y-4">
              {/* Content */}
              <p className="text-sm text-stone-300 leading-relaxed">{selectedNodeData.content}</p>

              {/* Scores */}
              <div className="space-y-2 pt-3 border-t border-white/5">
                <div className="text-[10px] text-stone-600 uppercase tracking-wider">Scores</div>
                <ScoreBar value={selectedNodeData.activation} label="Activation" color="#f59e0b" />
                <ScoreBar value={selectedNodeData.importance} label="Importance" color="#14b8a6" />
                <ScoreBar value={selectedNodeData.confidence} label="Confidence" color="#818cf8" />
              </div>

              {/* Metadata */}
              <div className="pt-3 border-t border-white/5">
                <div className="text-[10px] text-stone-600 uppercase tracking-wider mb-2">Metadata</div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                  <div>
                    <div className="text-[10px] text-stone-600">Source</div>
                    <div className="text-[11px] text-stone-300">{selectedNodeData.source_type || 'unknown'}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-stone-600">Recalled</div>
                    <div className="text-[11px] text-stone-300">{selectedNodeData.access_count.toLocaleString()} times</div>
                  </div>
                  {selectedNodeData.created_at && (
                    <div>
                      <div className="text-[10px] text-stone-600">Created</div>
                      <div className="text-[11px] text-stone-300">{new Date(selectedNodeData.created_at).toLocaleDateString()}</div>
                    </div>
                  )}
                </div>
                <div className="font-mono text-[9px] text-stone-700 break-all mt-2">{selectedNodeData.id}</div>
              </div>

              {/* Explore from here */}
              <button
                onClick={() => exploreNode(selectedNodeData.id)}
                className="w-full flex items-center justify-center gap-1.5 text-xs text-teal-400 bg-teal-500/10 hover:bg-teal-500/20 border border-teal-500/20 rounded-md py-1.5 transition-colors"
              >
                <Network size={12} />
                Explore from here
              </button>

              {/* Connections */}
              <div className="pt-3 border-t border-white/5">
                <div className="text-[10px] text-stone-600 uppercase tracking-wider mb-2">
                  Connections ({selectedConnections.length})
                </div>
                {selectedConnections.length > 0 ? (
                  <div className="space-y-1">
                    {selectedConnections.map((edge, i) => {
                      const otherId = edge.source === selectedNodeData.id ? edge.target : edge.source
                      const otherNode = activeGraph?.nodes.find(n => n.id === otherId)
                      const isOutgoing = edge.source === selectedNodeData.id
                      return (
                        <button
                          key={i}
                          type="button"
                          className="flex items-center gap-1.5 w-full text-left text-[11px] p-1.5 rounded hover:bg-white/5 transition-colors"
                          onClick={() => {
                            setSelectedNode(otherId)
                            setFocusNode({ id: otherId, ts: Date.now() })
                          }}
                        >
                          <span className="text-stone-600 shrink-0">{isOutgoing ? '\u2192' : '\u2190'}</span>
                          <span className="text-stone-400 font-medium shrink-0">{edge.relation.replace(/_/g, ' ')}</span>
                          <span className="flex-1 truncate text-stone-500">
                            {otherNode?.content ?? otherId.slice(0, 8)}
                          </span>
                          <span className="text-stone-700 text-[10px] shrink-0" title="Connection strength">
                            {edge.weight.toFixed(2)}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <p className="text-[11px] text-stone-600">No connections in this subgraph</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── HUD: Mic button bottom-center ──────────────────────────── */}
      {!chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          className="absolute bottom-5 left-1/2 -translate-x-1/2 z-10 w-12 h-12 rounded-full bg-teal-500/15 border-2 border-teal-500/40 flex items-center justify-center text-teal-400 hover:bg-teal-500/25 transition-colors shadow-[0_0_20px_rgba(20,184,166,0.15)]"
          title="Chat with Nova (press /)"
        >
          <Mic size={18} />
        </button>
      )}

      {/* ── Chat Panel ────────────────────────────────────────────────────── */}
      {chatOpen && (
        <BrainChat
          onClose={() => setChatOpen(false)}
          onActivityStep={handleActivityStep}
          onStreamComplete={handleStreamComplete}
        />
      )}
    </div>
  )
}
