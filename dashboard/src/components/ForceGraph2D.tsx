import { useEffect, useRef, useCallback } from 'react'
import ForceGraph from 'force-graph'

// ── Types ────────────────────────────────────────────────────────────────────

interface GraphNode {
  id: string
  type: string
  importance: number
  cluster_id?: number
  cluster_label?: string
  content?: string
  source_type?: string
  x?: number
  y?: number
  _edgeCount?: number
}

interface GraphEdge {
  source: string
  target: string
  weight: number
  relation?: string
}

interface ForceGraph2DProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedId: string | null
  onSelectNode: (id: string) => void
  onBackgroundClick: () => void
  className?: string
}

// ── Colors — cluster-aware, Obsidian-style muted palette ────────────────────

const CLUSTER_COLORS = [
  '#7c9dd6', '#6dbfb8', '#8bc48a', '#c4a86d', '#c48a8a',
  '#b09dd6', '#6dafc4', '#c4b86d', '#d69d9d', '#9dc46d',
  '#8aaac4', '#c49d6d', '#a3c48a', '#c46d8a', '#6dc4a3',
]

const TYPE_COLORS: Record<string, string> = {
  fact:       '#7c9dd6',
  entity:     '#6dbfb8',
  preference: '#8bc48a',
  procedure:  '#a1a1aa',
  self_model: '#b09dd6',
  episode:    '#c4a86d',
  schema:     '#c48a8a',
  goal:       '#b09dd6',
}

const DEFAULT_COLOR = '#71717a'
const BG_COLOR = '#0c0a09'
const GRID_COLOR = 'rgba(255, 255, 255, 0.02)'
const LINK_COLOR = 'rgba(120, 113, 108, 0.15)'
const LINK_HIGHLIGHT = 'rgba(200, 200, 200, 0.35)'
const LABEL_COLOR = '#d6d3d1'
const LABEL_DIM = '#78716c'

function getColor(node: GraphNode, useCluster: boolean): string {
  if (useCluster && node.cluster_id != null && node.cluster_id >= 0) {
    return CLUSTER_COLORS[node.cluster_id % CLUSTER_COLORS.length]
  }
  return TYPE_COLORS[node.type] ?? DEFAULT_COLOR
}

// ── Component ────────────────────────────────────────────────────────────────

export function ForceGraph2D({
  nodes,
  edges,
  selectedId,
  onSelectNode,
  onBackgroundClick,
  className,
}: ForceGraph2DProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<InstanceType<typeof ForceGraph> | null>(null)
  const selectedIdRef = useRef(selectedId)
  selectedIdRef.current = selectedId
  const hoveredIdRef = useRef<string | null>(null)
  const onSelectNodeRef = useRef(onSelectNode)
  onSelectNodeRef.current = onSelectNode
  const onBackgroundClickRef = useRef(onBackgroundClick)
  onBackgroundClickRef.current = onBackgroundClick

  // Build adjacency map for hover highlighting
  const adjacencyRef = useRef(new Map<string, Set<string>>())
  const useCluster = nodes.some(n => n.cluster_id != null && n.cluster_id >= 0)

  const prepareData = useCallback((rawNodes: GraphNode[], rawEdges: GraphEdge[]) => {
    const edgeCounts = new Map<string, number>()
    const adj = new Map<string, Set<string>>()
    for (const e of rawEdges) {
      edgeCounts.set(e.source, (edgeCounts.get(e.source) ?? 0) + 1)
      edgeCounts.set(e.target, (edgeCounts.get(e.target) ?? 0) + 1)
      if (!adj.has(e.source)) adj.set(e.source, new Set())
      if (!adj.has(e.target)) adj.set(e.target, new Set())
      adj.get(e.source)!.add(e.target)
      adj.get(e.target)!.add(e.source)
    }
    adjacencyRef.current = adj

    return {
      nodes: rawNodes.map(n => ({ ...n, _edgeCount: edgeCounts.get(n.id) ?? 0 })),
      links: rawEdges.map(e => ({ source: e.source, target: e.target, weight: e.weight })),
    }
  }, [])

  useEffect(() => {
    const el = containerRef.current
    if (!el || !nodes.length) return

    if (graphRef.current) {
      graphRef.current.graphData(prepareData(nodes, edges))
      return
    }

    const width = el.clientWidth
    const height = el.clientHeight

    const graph = new ForceGraph(el)
      .width(width)
      .height(height)
      .backgroundColor('transparent')

      // ── Node rendering — Obsidian-style dots with labels ──
      .nodeCanvasObjectMode(() => 'replace')
      .nodeCanvasObject((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const edgeCount = node._edgeCount ?? 0
        const importance = node.importance ?? 0
        const radius = Math.min(1.8 + Math.sqrt(edgeCount) * 0.7 + importance * 2, 10)
        const color = getColor(node, useCluster)
        const isSelected = node.id === selectedIdRef.current
        const isHovered = node.id === hoveredIdRef.current
        const hovered = hoveredIdRef.current
        const isNeighbor = hovered ? adjacencyRef.current.get(hovered)?.has(node.id) : false
        const isDimmed = hovered && !isHovered && !isNeighbor && node.id !== hovered

        // Node dot
        ctx.beginPath()
        ctx.arc(node.x!, node.y!, radius, 0, 2 * Math.PI)
        ctx.fillStyle = color
        ctx.globalAlpha = isDimmed ? 0.15 : (isSelected || isHovered ? 1.0 : 0.8)
        ctx.fill()

        // Hover/selected glow ring
        if (isSelected || isHovered) {
          ctx.beginPath()
          ctx.arc(node.x!, node.y!, radius + 3, 0, 2 * Math.PI)
          ctx.strokeStyle = isSelected ? '#ffffff' : color
          ctx.globalAlpha = isSelected ? 0.8 : 0.4
          ctx.lineWidth = (isSelected ? 1.5 : 1.0) / globalScale
          ctx.stroke()
        }

        // Labels — always show for important/connected nodes at sufficient zoom
        const showLabel = (isSelected || isHovered || isNeighbor)
          || (globalScale > 0.6 && (importance > 0.3 || edgeCount > 5))
          || (globalScale > 1.2 && edgeCount > 2)
          || (globalScale > 2.0)

        if (showLabel && !isDimmed) {
          const text = node.cluster_label
            ?? (node.content && node.content.length > 40
              ? node.content.slice(0, 37) + '...'
              : node.content)
            ?? node.id.slice(0, 8)

          const fontSize = Math.max(11 / globalScale, 2.5)
          ctx.font = `500 ${fontSize}px system-ui, sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'
          ctx.globalAlpha = isSelected || isHovered ? 0.95 : (isNeighbor ? 0.7 : 0.5)
          ctx.fillStyle = isSelected || isHovered ? LABEL_COLOR : LABEL_DIM
          ctx.fillText(text, node.x!, node.y! + radius + 2.5)
        }

        ctx.globalAlpha = 1.0
      })
      .nodePointerAreaPaint((node: any, color: string, ctx: CanvasRenderingContext2D) => {
        const edgeCount = node._edgeCount ?? 0
        const radius = Math.min(1.8 + Math.sqrt(edgeCount) * 0.7, 10) + 4
        ctx.beginPath()
        ctx.arc(node.x!, node.y!, radius, 0, 2 * Math.PI)
        ctx.fillStyle = color
        ctx.fill()
      })

      // ── Link rendering — weight-based opacity ──
      .linkCanvasObjectMode(() => 'replace')
      .linkCanvasObject((link: any, ctx: CanvasRenderingContext2D) => {
        const src = link.source
        const tgt = link.target
        if (!src?.x || !tgt?.x) return

        const hovered = hoveredIdRef.current
        const isHighlighted = hovered && (src.id === hovered || tgt.id === hovered)
        const isDimmed = hovered && !isHighlighted

        const weight = link.weight ?? 0.3
        ctx.beginPath()
        ctx.moveTo(src.x, src.y)
        ctx.lineTo(tgt.x, tgt.y)
        ctx.strokeStyle = isHighlighted ? LINK_HIGHLIGHT : LINK_COLOR
        ctx.globalAlpha = isDimmed ? 0.03 : (isHighlighted ? 0.5 : 0.08 + weight * 0.12)
        ctx.lineWidth = isHighlighted ? 0.8 : 0.3 + weight * 0.4
        ctx.stroke()
        ctx.globalAlpha = 1.0
      })

      // Interaction
      .onNodeClick((node: any) => onSelectNodeRef.current(node.id))
      .onNodeHover((node: any) => {
        hoveredIdRef.current = node?.id ?? null
        el.style.cursor = node ? 'pointer' : 'default'
      })
      .onBackgroundClick(() => {
        hoveredIdRef.current = null
        onBackgroundClickRef.current()
      })
      .enableNodeDrag(true)

      // Force layout — Obsidian-like spread
      .d3AlphaDecay(0.025)
      .d3VelocityDecay(0.35)
      .warmupTicks(300)
      .cooldownTicks(0)

    // Tune forces
    try {
      graph.d3Force('charge')?.strength(-25).distanceMax(350)
      graph.d3Force('center')?.strength(0.02)
      graph.d3Force('link')
        ?.distance((link: any) => 25 + (1 - (link.weight ?? 0.3)) * 50)
        .strength((link: any) => 0.04 + (link.weight ?? 0.3) * 0.12)
    } catch { /* force config may fail */ }

    graph.graphData(prepareData(nodes, edges))

    graph.onEngineStop(() => {
      graph.zoomToFit(400, 80)
    })

    graphRef.current = graph

    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width: w, height: h } = entry.contentRect
        graph.width(w).height(h)
      }
    })
    ro.observe(el)

    return () => {
      ro.disconnect()
      graph._destructor()
      graphRef.current = null
    }
  }, [nodes, edges, prepareData, useCluster])

  useEffect(() => {
    graphRef.current?.nodeCanvasObject(graphRef.current.nodeCanvasObject())
  }, [selectedId])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        background: `
          radial-gradient(circle at 1px 1px, ${GRID_COLOR} 1px, transparent 0) 0 0 / 24px 24px,
          ${BG_COLOR}
        `,
      }}
    />
  )
}
