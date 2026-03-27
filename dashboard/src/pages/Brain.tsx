import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, MessageSquare, X } from 'lucide-react'
import { apiFetch } from '../api'
import { BrainChat } from '../components/BrainChat'
import { ForceGraph3D } from '../components/ForceGraph3D'
import type { ForceGraph3DHandle } from '../components/ForceGraph3D'
import type { ActivityStep } from '../stores/chat-store'

// Reuse graph data types matching the memory-service API response
interface GraphNode {
  id: string
  type: string
  content: string
  activation: number
  importance: number
  access_count: number
  confidence: number
  source_type: string
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

const LAYOUT_PRESETS = ['compact', 'spread', 'galaxy', 'constellation'] as const

export default function Brain() {
  const queryClient = useQueryClient()
  const graphRef = useRef<ForceGraph3DHandle>(null)

  // Graph data
  const { data: graph } = useQuery<GraphData>({
    queryKey: ['brain-graph'],
    queryFn: () => apiFetch('/mem/api/v1/engrams/graph?mode=full&max_nodes=2000'),
    staleTime: 30_000,
    retry: 1,
  })

  // UI state
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [chatOpen, setChatOpen] = useState(false)
  const [layout, setLayout] = useState<string>('spread')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchActive, setSearchActive] = useState(false)

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
      // Don't capture when typing in input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === '/' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        setChatOpen(o => !o)
      }
      if (e.key === 'Escape') {
        if (chatOpen) setChatOpen(false)
        else if (searchActive) { setSearchActive(false); setSearchQuery('') }
        else setSelectedNode(null)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [chatOpen, searchActive])

  // Activity step handler for Phase 3
  const handleActivityStep = useCallback((_step: ActivityStep) => {
    if (!activeGraph?.nodes) return
    if (_step.step === 'memory' && _step.state === 'running') {
      const nodes = activeGraph.nodes
      const count = Math.max(3, Math.floor(nodes.length * 0.15))
      const shuffled = [...nodes].sort(() => Math.random() - 0.5)
      const ids = shuffled.slice(0, count).map(n => n.id)
      graphRef.current?.highlightNodes(ids, 1500)
    }
    if (_step.step === 'generating' && _step.state === 'running') {
      graphRef.current?.pulseAll(2000)
    }
  }, [activeGraph])

  const handleStreamComplete = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['brain-graph'] })
  }, [queryClient])

  // Track previous node IDs for fade-in animation on new engrams
  const prevNodeIdsRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!activeGraph?.nodes) return
    const currentIds = new Set(activeGraph.nodes.map(n => n.id))
    if (prevNodeIdsRef.current.size > 0) {
      const newIds = activeGraph.nodes
        .filter(n => !prevNodeIdsRef.current.has(n.id))
        .map(n => n.id)
      if (newIds.length > 0) {
        graphRef.current?.fadeInNodes(newIds, 1000)
      }
    }
    prevNodeIdsRef.current = currentIds
  }, [activeGraph])

  // Selected node data
  const selectedNodeData = selectedNode
    ? activeGraph?.nodes.find(n => n.id === selectedNode)
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

  return (
    <div className="relative w-full h-screen overflow-hidden bg-black">
      {/* Full-viewport graph */}
      <ForceGraph3D
        ref={graphRef}
        nodes={activeGraph?.nodes ?? []}
        edges={activeGraph?.edges ?? []}
        clusters={activeGraph?.clusters}
        selectedId={selectedNode}
        onSelectNode={setSelectedNode}
        onBackgroundClick={() => setSelectedNode(null)}
        autoSpin
        bgColor="galaxy"
        layoutPreset={layout}
        neuralMode={{
          enabled: true,
          breathingRate: 0.02,
          breathingAmplitude: 0.05,
          bloomStrength: 1.2,
          particlesAlways: true,
        }}
        className="w-full h-full"
      />

      {/* -- Floating Controls: Top Left ---------------------------------------- */}
      <div className="absolute top-4 left-4 z-10 flex flex-col gap-2">
        {/* Search bar */}
        <form onSubmit={handleSearch} className="flex items-center gap-1 bg-black/60 backdrop-blur-sm border border-white/10 rounded-lg px-3 py-1.5">
          <Search size={14} className="text-stone-500 shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => { setSearchQuery(e.target.value); if (!e.target.value) clearSearch() }}
            placeholder="Search memories..."
            className="bg-transparent text-sm text-stone-200 placeholder:text-stone-600 outline-none w-48"
          />
          {searchActive && (
            <button type="button" onClick={clearSearch} className="text-stone-500 hover:text-stone-300">
              <X size={12} />
            </button>
          )}
        </form>

        {/* Layout presets */}
        <div className="flex gap-1 bg-black/60 backdrop-blur-sm border border-white/10 rounded-lg px-2 py-1">
          {LAYOUT_PRESETS.map(preset => (
            <button
              key={preset}
              onClick={() => setLayout(preset)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                layout === preset
                  ? 'bg-teal-500/20 text-teal-400'
                  : 'text-stone-500 hover:text-stone-300'
              }`}
            >
              {preset}
            </button>
          ))}
        </div>

        {/* Stats badge */}
        {activeGraph && (
          <div className="text-xs text-stone-600 px-1">
            {activeGraph.nodes.length} memories · {activeGraph.edges.length} connections
            {activeGraph.clusters && ` · ${activeGraph.clusters.length} domains`}
          </div>
        )}
      </div>

      {/* -- Selected Node Detail: Bottom Left --------------------------------- */}
      {selectedNodeData && (
        <div className="absolute bottom-6 left-4 z-10 max-w-md bg-black/70 backdrop-blur-sm border border-white/10 rounded-lg p-4">
          <div className="flex items-start gap-2 mb-2">
            <span className="text-xs px-1.5 py-0.5 rounded bg-teal-500/20 text-teal-400 shrink-0">
              {selectedNodeData.type}
            </span>
            {selectedNodeData.source_type && (
              <span className="text-xs text-stone-600">
                from: {selectedNodeData.source_type}
              </span>
            )}
          </div>
          <p className="text-sm text-stone-300 leading-relaxed line-clamp-4">
            {selectedNodeData.content}
          </p>
          <div className="flex gap-4 mt-3 text-xs text-stone-500">
            <div className="flex items-center gap-1.5">
              <span>Importance</span>
              <div className="w-16 h-1 bg-stone-800 rounded-full overflow-hidden">
                <div className="h-full bg-teal-500 rounded-full" style={{ width: `${selectedNodeData.importance * 100}%` }} />
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <span>Activation</span>
              <div className="w-16 h-1 bg-stone-800 rounded-full overflow-hidden">
                <div className="h-full bg-amber-500 rounded-full" style={{ width: `${selectedNodeData.activation * 100}%` }} />
              </div>
            </div>
            <span>{selectedNodeData.access_count} recalls</span>
          </div>
        </div>
      )}

      {/* -- Chat Toggle FAB: Bottom Right ------------------------------------- */}
      {!chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          className="absolute bottom-6 right-6 z-10 flex items-center gap-2 bg-teal-600/80 hover:bg-teal-600 backdrop-blur-sm text-white rounded-full px-4 py-2.5 transition-colors shadow-lg shadow-teal-900/30"
          title="Chat with Nova (press /)"
        >
          <MessageSquare size={16} />
          <span className="text-sm font-medium">Chat</span>
        </button>
      )}

      {/* -- Chat Panel --------------------------------------------------------- */}
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
