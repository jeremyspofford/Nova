import { useRef, useEffect, useCallback } from 'react'
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
}

// ── Color mapping ────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  fact:       '#60a5fa', // info blue
  entity:     '#2dd4bf', // accent teal
  preference: '#34d399', // success green
  procedure:  '#a1a1aa', // neutral gray
  self_model: '#818cf8', // indigo
  episode:    '#fbbf24', // warning amber
  schema:     '#f87171', // danger red
  goal:       '#c084fc', // purple
}

const DEFAULT_COLOR = '#71717a'

// ── Simulation node type ─────────────────────────────────────────────────────

interface SimNode extends SimulationNodeDatum {
  id: string
  type: string
  content: string
  activation: number
  importance: number
  access_count: number
  radius: number
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  relation: string
  weight: number
}

// ── Component ────────────────────────────────────────────────────────────────

export function ForceGraph({ nodes, edges, selectedId, onSelectNode, className }: ForceGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null)
  const nodesRef = useRef<SimNode[]>([])
  const linksRef = useRef<SimLink[]>([])
  const hoveredRef = useRef<string | null>(null)
  const dragRef = useRef<{ node: SimNode; startX: number; startY: number } | null>(null)
  const rafRef = useRef<number>(0)

  // Build simulation data
  useEffect(() => {
    if (!nodes.length) return

    const canvas = canvasRef.current
    if (!canvas) return
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    canvas.width = width * window.devicePixelRatio
    canvas.height = height * window.devicePixelRatio

    // Create simulation nodes with radius based on importance
    const simNodes: SimNode[] = nodes.map(n => ({
      id: n.id,
      type: n.type,
      content: n.content,
      activation: n.activation,
      importance: n.importance,
      access_count: n.access_count,
      radius: 8 + n.importance * 16,
      x: width / 2 + (Math.random() - 0.5) * width * 0.6,
      y: height / 2 + (Math.random() - 0.5) * height * 0.6,
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

    // Stop previous simulation
    simRef.current?.stop()

    const sim = forceSimulation<SimNode>(simNodes)
      .force('link', forceLink<SimNode, SimLink>(simLinks)
        .id(d => d.id)
        .distance(d => 80 + (1 - d.weight) * 60)
        .strength(d => 0.3 + d.weight * 0.4))
      .force('charge', forceManyBody<SimNode>().strength(-200))
      .force('center', forceCenter(width / 2, height / 2).strength(0.05))
      .force('collide', forceCollide<SimNode>(d => d.radius + 4))
      .alphaDecay(0.02)
      .on('tick', () => draw(canvas, width, height))

    simRef.current = sim

    return () => {
      sim.stop()
      cancelAnimationFrame(rafRef.current)
    }
  }, [nodes, edges])

  // Redraw when selection changes
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    draw(canvas, canvas.clientWidth, canvas.clientHeight)
  }, [selectedId])

  const draw = useCallback((canvas: HTMLCanvasElement, width: number, height: number) => {
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)

    const simNodes = nodesRef.current
    const simLinks = linksRef.current
    const hovered = hoveredRef.current

    // Draw edges
    for (const link of simLinks) {
      const source = link.source as SimNode
      const target = link.target as SimNode
      if (source.x == null || source.y == null || target.x == null || target.y == null) continue

      const isConnected = selectedId && (source.id === selectedId || target.id === selectedId)

      ctx.beginPath()
      ctx.moveTo(source.x, source.y)
      ctx.lineTo(target.x, target.y)
      ctx.strokeStyle = isConnected
        ? 'rgba(45, 212, 191, 0.5)'
        : 'rgba(113, 113, 122, 0.15)'
      ctx.lineWidth = isConnected ? 2 : 1
      ctx.stroke()

      // Draw relation label on connected edges
      if (isConnected) {
        const mx = (source.x + target.x) / 2
        const my = (source.y + target.y) / 2
        ctx.font = '10px system-ui'
        ctx.fillStyle = 'rgba(161, 161, 170, 0.8)'
        ctx.textAlign = 'center'
        ctx.fillText(link.relation.replace(/_/g, ' '), mx, my - 4)
      }
    }

    // Draw nodes
    for (const node of simNodes) {
      if (node.x == null || node.y == null) continue

      const isSelected = node.id === selectedId
      const isHovered = node.id === hovered
      const color = TYPE_COLORS[node.type] ?? DEFAULT_COLOR
      const alpha = 0.3 + node.activation * 0.7

      // Glow for selected/hovered
      if (isSelected || isHovered) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, node.radius + 4, 0, Math.PI * 2)
        ctx.fillStyle = isSelected
          ? color.replace(')', ', 0.2)').replace('rgb', 'rgba')
          : color.replace(')', ', 0.1)').replace('rgb', 'rgba')
        // For hex colors, convert
        ctx.fillStyle = isSelected
          ? hexToRgba(color, 0.25)
          : hexToRgba(color, 0.12)
        ctx.fill()
      }

      // Node circle
      ctx.beginPath()
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2)
      ctx.fillStyle = hexToRgba(color, alpha)
      ctx.fill()

      if (isSelected) {
        ctx.strokeStyle = color
        ctx.lineWidth = 2
        ctx.stroke()
      }

      // Label
      const label = node.content.length > 30 ? node.content.slice(0, 28) + '...' : node.content
      ctx.font = `${isSelected || isHovered ? '12' : '11'}px system-ui`
      ctx.textAlign = 'center'
      ctx.fillStyle = isSelected || isHovered
        ? 'rgba(250, 250, 250, 0.95)'
        : 'rgba(212, 212, 216, 0.7)'
      ctx.fillText(label, node.x, node.y + node.radius + 14)

      // Type label inside node (for larger nodes)
      if (node.radius > 14) {
        ctx.font = '9px system-ui'
        ctx.fillStyle = 'rgba(0, 0, 0, 0.6)'
        ctx.fillText(node.type === 'self_model' ? 'self' : node.type.slice(0, 4), node.x, node.y + 3)
      }
    }
  }, [selectedId])

  // Hit test helper
  const hitTest = useCallback((e: React.MouseEvent<HTMLCanvasElement>): SimNode | null => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    // Check in reverse order (top nodes first)
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
  }, [])

  const CLICK_THRESHOLD = 5 // px — movement below this counts as a click, not a drag

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return

    if (dragRef.current) {
      const rect = canvas.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      dragRef.current.node.fx = x
      dragRef.current.node.fy = y
      simRef.current?.alpha(0.1).restart()
      return
    }

    const node = hitTest(e)
    const newHovered = node?.id ?? null
    if (newHovered !== hoveredRef.current) {
      hoveredRef.current = newHovered
      canvas.style.cursor = newHovered ? 'pointer' : 'default'
      draw(canvas, canvas.clientWidth, canvas.clientHeight)
    }
  }, [hitTest, draw])

  const handleMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const node = hitTest(e)
    if (node) {
      dragRef.current = { node, startX: e.clientX, startY: e.clientY }
      node.fx = node.x
      node.fy = node.y
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
  }, [onSelectNode])

  return (
    <canvas
      ref={canvasRef}
      className={className}
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{ width: '100%', height: '100%' }}
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
