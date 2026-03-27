import { useRef, useEffect, useCallback, useState } from 'react'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force'
import type { SimulationNodeDatum, SimulationLinkDatum } from 'd3-force'

// ── Types ────────────────────────────────────────────────────────────────────

interface GraphNode {
  id: string
  type: string
  content: string
  activation: number
  importance: number
  access_count: number
  cluster_id?: number
  cluster_label?: string
}

interface GraphEdge {
  source: string
  target: string
  relation: string
  weight: number
}

interface ForceGraphProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedId: string | null
  onSelectNode: (id: string) => void
  className?: string
  focusClusterId?: number | null
  focusNodeId?: string | null
}

// ── Color mapping ────────────────────────────────────────────────────────────

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

const CLUSTER_COLORS = [
  '#818cf8', '#60a5fa', '#2dd4bf', '#34d399', '#fbbf24',
  '#f87171', '#c084fc', '#fb923c', '#a3e635', '#22d3ee',
  '#e879f9', '#f472b6', '#38bdf8', '#4ade80', '#facc15',
  '#a78bfa', '#67e8f9', '#fca5a5', '#86efac', '#fde68a',
]

const DEFAULT_COLOR = '#71717a'

/** Parse hex to [r,g,b] */
function hexToRgb(hex: string): [number, number, number] {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return [r, g, b]
}

function getColor(node: { type: string; cluster_id?: number }, useCluster: boolean): string {
  if (useCluster && node.cluster_id != null) {
    return CLUSTER_COLORS[node.cluster_id % CLUSTER_COLORS.length]
  }
  return TYPE_COLORS[node.type] ?? DEFAULT_COLOR
}

// ── Simulation node type ─────────────────────────────────────────────────────

interface SimNode extends SimulationNodeDatum {
  id: string
  type: string
  content: string
  activation: number
  importance: number
  access_count: number
  cluster_id?: number
  cluster_label?: string
  radius: number
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  relation: string
  weight: number
}

// ── Component ────────────────────────────────────────────────────────────────

export function ForceGraph({ nodes, edges, selectedId, onSelectNode, className, focusClusterId, focusNodeId }: ForceGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null)
  const nodesRef = useRef<SimNode[]>([])
  const linksRef = useRef<SimLink[]>([])
  const hoveredRef = useRef<string | null>(null)
  const dragRef = useRef<{ node: SimNode; startX: number; startY: number } | null>(null)
  const panRef = useRef<{ startX: number; startY: number; startTx: number; startTy: number } | null>(null)

  // Zoom/pan transform state
  const transformRef = useRef({ tx: 0, ty: 0, scale: 1 })
  const [, forceRender] = useState(0)

  const isLargeGraph = nodes.length > 100
  const useClusterColors = nodes.some(n => n.cluster_id != null)

  // Build simulation
  useEffect(() => {
    if (!nodes.length) return

    const canvas = canvasRef.current
    if (!canvas) return
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    canvas.width = width * window.devicePixelRatio
    canvas.height = height * window.devicePixelRatio

    // Reset transform
    transformRef.current = { tx: width / 2, ty: height / 2, scale: isLargeGraph ? 0.8 : 1 }

    const simNodes: SimNode[] = nodes.map(n => ({
      id: n.id,
      type: n.type,
      content: n.content,
      activation: n.activation,
      importance: n.importance,
      access_count: n.access_count,
      cluster_id: n.cluster_id,
      cluster_label: n.cluster_label,
      radius: isLargeGraph ? 2 + n.importance * 5 : 6 + n.importance * 12,
      x: (Math.random() - 0.5) * width * 0.8,
      y: (Math.random() - 0.5) * height * 0.8,
    }))

    const nodeMap = new Map(simNodes.map(n => [n.id, n]))
    const simLinks: SimLink[] = edges
      .filter(e => nodeMap.has(e.source) && nodeMap.has(e.target))
      .map(e => ({
        source: e.source,
        target: e.target,
        relation: e.relation,
        weight: e.weight,
      }))

    nodesRef.current = simNodes
    linksRef.current = simLinks

    simRef.current?.stop()

    const linkForce = forceLink<SimNode, SimLink>(simLinks).id(d => d.id)
    if (isLargeGraph) {
      // Weight-proportional: weak edges barely pull, strong edges pull firmly
      linkForce
        .distance(d => 30 + (1 - d.weight) * 60)
        .strength(d => 0.02 + d.weight * 0.3)
    } else {
      linkForce
        .distance(d => 60 + (1 - d.weight) * 40)
        .strength(d => 0.3 + d.weight * 0.4)
    }

    const chargeForce = forceManyBody<SimNode>()
      .strength(isLargeGraph ? -50 : -200)
    if (isLargeGraph) chargeForce.distanceMax(250)

    const sim = forceSimulation<SimNode>(simNodes)
      .force('link', linkForce)
      .force('charge', chargeForce)
      .force('center', forceCenter(0, 0).strength(isLargeGraph ? 0.008 : 0.05))
      .force('collide', forceCollide<SimNode>(d => d.radius + 2))
      .alphaDecay(0.02)
      .on('tick', () => draw(canvas, width, height))

    simRef.current = sim

    return () => {
      sim.stop()
    }
  }, [nodes, edges])

  // Redraw on selection change
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    draw(canvas, canvas.clientWidth, canvas.clientHeight)
  }, [selectedId])

  // Focus cluster
  useEffect(() => {
    if (focusClusterId == null) return
    const clusterNodes = nodesRef.current.filter(n => n.cluster_id === focusClusterId)
    if (!clusterNodes.length) return
    const canvas = canvasRef.current
    if (!canvas) return

    const cx = clusterNodes.reduce((s, n) => s + (n.x ?? 0), 0) / clusterNodes.length
    const cy = clusterNodes.reduce((s, n) => s + (n.y ?? 0), 0) / clusterNodes.length
    const w = canvas.clientWidth, h = canvas.clientHeight

    transformRef.current = { tx: w / 2 - cx * 1.5, ty: h / 2 - cy * 1.5, scale: 1.5 }
    draw(canvas, w, h)
  }, [focusClusterId])

  // Focus node
  useEffect(() => {
    if (!focusNodeId) return
    const node = nodesRef.current.find(n => n.id === focusNodeId)
    if (!node || node.x == null) return
    const canvas = canvasRef.current
    if (!canvas) return

    const w = canvas.clientWidth, h = canvas.clientHeight
    transformRef.current = { tx: w / 2 - node.x * 2, ty: h / 2 - (node.y ?? 0) * 2, scale: 2 }
    draw(canvas, w, h)
  }, [focusNodeId])

  const draw = useCallback((canvas: HTMLCanvasElement, width: number, height: number) => {
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio
    const { tx, ty, scale } = transformRef.current
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)

    // Apply zoom/pan transform
    ctx.save()
    ctx.translate(tx, ty)
    ctx.scale(scale, scale)

    const simNodes = nodesRef.current
    const simLinks = linksRef.current
    const hovered = hoveredRef.current

    // Draw edges
    for (const link of simLinks) {
      const source = link.source as SimNode
      const target = link.target as SimNode
      if (source.x == null || source.y == null || target.x == null || target.y == null) continue

      const isConnected = selectedId && (source.id === selectedId || target.id === selectedId)
      const edgeAlpha = isConnected ? 0.5 : Math.max(0.03, link.weight * 0.15)

      ctx.beginPath()
      ctx.moveTo(source.x, source.y)
      ctx.lineTo(target.x, target.y)
      ctx.strokeStyle = isConnected
        ? 'rgba(45, 212, 191, 0.5)'
        : `rgba(113, 113, 122, ${edgeAlpha})`
      ctx.lineWidth = isConnected ? 2 / scale : (0.5 + link.weight) / scale
      ctx.stroke()
    }

    // Draw nodes
    for (const node of simNodes) {
      if (node.x == null || node.y == null) continue

      const isSelected = node.id === selectedId
      const isHovered = node.id === hovered
      const color = getColor(node, useClusterColors)
      const alpha = 0.4 + node.activation * 0.6

      const [cr, cg, cb] = hexToRgb(color)

      // Glow for selected/hovered
      if (isSelected || isHovered) {
        const glowR = node.radius + 4
        const glowGrad = ctx.createRadialGradient(
          node.x, node.y, node.radius * 0.6,
          node.x, node.y, glowR,
        )
        const ga = isSelected ? 0.35 : 0.18
        glowGrad.addColorStop(0, `rgba(${cr},${cg},${cb},${ga})`)
        glowGrad.addColorStop(1, `rgba(${cr},${cg},${cb},0)`)
        ctx.beginPath()
        ctx.arc(node.x, node.y, glowR, 0, Math.PI * 2)
        ctx.fillStyle = glowGrad
        ctx.fill()
      }

      // Node orb — radial gradient with offset highlight for 3D depth
      const hlX = node.x - node.radius * 0.3  // highlight offset (upper-left)
      const hlY = node.y - node.radius * 0.3
      const orbGrad = ctx.createRadialGradient(
        hlX, hlY, node.radius * 0.05,         // bright highlight core
        node.x, node.y, node.radius,           // outer edge
      )
      // Bright highlight center
      const hi = Math.min(255, cr + 80)
      const hg = Math.min(255, cg + 80)
      const hb = Math.min(255, cb + 80)
      orbGrad.addColorStop(0, `rgba(${hi},${hg},${hb},${alpha})`)
      // Base color at mid-radius
      orbGrad.addColorStop(0.45, `rgba(${cr},${cg},${cb},${alpha})`)
      // Darker rim
      const dr = Math.floor(cr * 0.4)
      const dg = Math.floor(cg * 0.4)
      const db = Math.floor(cb * 0.4)
      orbGrad.addColorStop(1, `rgba(${dr},${dg},${db},${alpha * 0.7})`)

      ctx.beginPath()
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2)
      ctx.fillStyle = orbGrad
      ctx.fill()

      // Rim ring for definition
      ctx.strokeStyle = `rgba(${cr},${cg},${cb},${alpha * 0.5})`
      ctx.lineWidth = 0.5 / scale
      ctx.stroke()

      if (isSelected) {
        ctx.strokeStyle = color
        ctx.lineWidth = 2 / scale
        ctx.stroke()
      }

      // Label — only show when zoomed in enough or for selected/hovered
      if (scale > 1.2 || isSelected || isHovered) {
        const label = node.content.length > 30 ? node.content.slice(0, 28) + '...' : node.content
        const fontSize = Math.max(9, 11 / scale)
        ctx.font = `${isSelected || isHovered ? fontSize + 1 : fontSize}px system-ui`
        ctx.textAlign = 'center'
        ctx.fillStyle = isSelected || isHovered
          ? 'rgba(250, 250, 250, 0.95)'
          : 'rgba(212, 212, 216, 0.6)'
        ctx.fillText(label, node.x, node.y + node.radius + 12 / scale)
      }
    }

    ctx.restore()
  }, [selectedId, useClusterColors])

  // Screen → graph coordinates
  const screenToGraph = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    const { tx, ty, scale } = transformRef.current
    return {
      x: (e.clientX - rect.left - tx) / scale,
      y: (e.clientY - rect.top - ty) / scale,
    }
  }, [])

  const hitTest = useCallback((e: React.MouseEvent<HTMLCanvasElement>): SimNode | null => {
    const { x, y } = screenToGraph(e)
    for (let i = nodesRef.current.length - 1; i >= 0; i--) {
      const node = nodesRef.current[i]
      if (node.x == null || node.y == null) continue
      const dx = x - node.x
      const dy = y - node.y
      if (dx * dx + dy * dy <= (node.radius + 4) * (node.radius + 4)) {
        return node
      }
    }
    return null
  }, [screenToGraph])

  const CLICK_THRESHOLD = 5

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return

    // Pan
    if (panRef.current) {
      const dx = e.clientX - panRef.current.startX
      const dy = e.clientY - panRef.current.startY
      transformRef.current.tx = panRef.current.startTx + dx
      transformRef.current.ty = panRef.current.startTy + dy
      draw(canvas, canvas.clientWidth, canvas.clientHeight)
      return
    }

    // Drag node
    if (dragRef.current) {
      const { x, y } = screenToGraph(e)
      dragRef.current.node.fx = x
      dragRef.current.node.fy = y
      simRef.current?.alpha(0.1).restart()
      return
    }

    const node = hitTest(e)
    const newHovered = node?.id ?? null
    if (newHovered !== hoveredRef.current) {
      hoveredRef.current = newHovered
      canvas.style.cursor = newHovered ? 'pointer' : 'grab'
      draw(canvas, canvas.clientWidth, canvas.clientHeight)
    }
  }, [hitTest, draw, screenToGraph])

  const handleMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const node = hitTest(e)
    if (node) {
      dragRef.current = { node, startX: e.clientX, startY: e.clientY }
      node.fx = node.x
      node.fy = node.y
    } else {
      // Start panning
      panRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startTx: transformRef.current.tx,
        startTy: transformRef.current.ty,
      }
    }
  }, [hitTest])

  const handleMouseUp = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (dragRef.current) {
      const dx = e.clientX - dragRef.current.startX
      const dy = e.clientY - dragRef.current.startY
      const wasClick = dx * dx + dy * dy < CLICK_THRESHOLD * CLICK_THRESHOLD
      const nodeId = dragRef.current.node.id

      dragRef.current.node.fx = null
      dragRef.current.node.fy = null
      dragRef.current = null
      simRef.current?.alpha(0.1).restart()

      if (wasClick) onSelectNode(nodeId)
    }
    panRef.current = null
  }, [onSelectNode])

  // Zoom with scroll wheel
  const handleWheel = useCallback((e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return

    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top

    const { tx, ty, scale } = transformRef.current
    const factor = e.deltaY > 0 ? 0.9 : 1.1
    const newScale = Math.max(0.1, Math.min(10, scale * factor))

    // Zoom toward mouse position
    transformRef.current = {
      tx: mx - (mx - tx) * (newScale / scale),
      ty: my - (my - ty) * (newScale / scale),
      scale: newScale,
    }

    draw(canvas, canvas.clientWidth, canvas.clientHeight)
  }, [draw])

  return (
    <canvas
      ref={canvasRef}
      className={className}
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onWheel={handleWheel}
      style={{ width: '100%', height: '100%', cursor: 'grab', background: '#0a0a0a' }}
    />
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
