import { useRef, useEffect, useCallback } from 'react'
import ForceGraph3DLib from '3d-force-graph'
import {
  Mesh,
  SphereGeometry,
  MeshBasicMaterial,
  Sprite,
  SpriteMaterial,
  CanvasTexture,
  Color,
  AdditiveBlending,
  Vector2,
} from 'three'
// @ts-expect-error — three/examples not typed
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass'

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

interface ForceGraph3DProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedId: string | null
  onSelectNode: (id: string) => void
  onBackgroundClick?: () => void
  className?: string
}

// ── Color helpers ─────────────────────────────────────────────────────────────

function getCSSColor(varName: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
  if (!raw) return '#71717a'
  const parts = raw.split(' ').map(Number)
  if (parts.length !== 3) return '#71717a'
  return '#' + parts.map(n => n.toString(16).padStart(2, '0')).join('')
}

function getAccentColor(): string {
  return getCSSColor('--accent-500')
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
const DEFAULT_COLOR = '#71717a'

// ── Glow sprite texture (cached) ─────────────────────────────────────────────

let glowTextureCache: CanvasTexture | null = null

function getGlowTexture(): CanvasTexture {
  if (glowTextureCache) return glowTextureCache
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')!
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  gradient.addColorStop(0, 'rgba(255,255,255,0.6)')
  gradient.addColorStop(0.3, 'rgba(255,255,255,0.15)')
  gradient.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, size, size)
  glowTextureCache = new CanvasTexture(canvas)
  return glowTextureCache
}

// ── Component ────────────────────────────────────────────────────────────────

export function ForceGraph3D({
  nodes,
  edges,
  selectedId,
  onSelectNode,
  onBackgroundClick,
  className,
}: ForceGraph3DProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null)
  const initializedRef = useRef(false)

  const onSelectNodeRef = useRef(onSelectNode)
  onSelectNodeRef.current = onSelectNode
  const onBackgroundClickRef = useRef(onBackgroundClick)
  onBackgroundClickRef.current = onBackgroundClick

  // Single effect: init graph + load data together
  useEffect(() => {
    const el = containerRef.current
    if (!el || !nodes.length) return

    // If already initialized, just update data
    if (graphRef.current && initializedRef.current) {
      updateGraphData(graphRef.current, nodes, edges)
      return
    }

    // Wait for container to have dimensions
    const width = el.clientWidth
    const height = el.clientHeight
    if (width === 0 || height === 0) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const graph = (ForceGraph3DLib as any)()(el)
      .width(width)
      .height(height)
      .backgroundColor(getCSSColor('--neutral-950'))
      .showNavInfo(false)

      // ── Node appearance ──────────────────────────────────────────────
      .nodeVal((node: any) => 1 + (node.importance ?? 0) * 8)
      .nodeLabel((node: any) => {
        const type = node.type === 'self_model' ? 'self model' : (node.type ?? '')
        const color = TYPE_COLORS[node.type] ?? DEFAULT_COLOR
        return `<div style="background:rgba(9,9,11,0.92);border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:8px 12px;max-width:300px;font-family:system-ui;font-size:12px;pointer-events:none;">
          <div style="color:${color};font-weight:600;margin-bottom:4px;text-transform:uppercase;font-size:10px;letter-spacing:0.5px;">${type}</div>
          <div style="color:#e4e4e7;line-height:1.4;">${node.content ?? ''}</div>
          <div style="color:#71717a;font-size:10px;margin-top:4px;">${(node.access_count ?? 0).toLocaleString()} recalls</div>
        </div>`
      })
      .nodeThreeObject((node: any) => {
        const color = TYPE_COLORS[node.type] ?? DEFAULT_COLOR
        const importance = node.importance ?? 0
        const activation = node.activation ?? 0
        const radius = 2 + importance * 4
        const alpha = 0.4 + activation * 0.6

        const geo = new SphereGeometry(radius, 16, 12)
        const mat = new MeshBasicMaterial({
          color: new Color(color),
          transparent: true,
          opacity: alpha,
        })
        const sphere = new Mesh(geo, mat)

        // Glow sprite
        const spriteMat = new SpriteMaterial({
          map: getGlowTexture(),
          color: new Color(color),
          transparent: true,
          opacity: 0.3 + activation * 0.4,
          blending: AdditiveBlending,
          depthWrite: false,
        })
        const sprite = new Sprite(spriteMat)
        sprite.scale.set(radius * 5, radius * 5, 1)
        sphere.add(sprite)

        return sphere
      })
      .nodeThreeObjectExtend(false)

      // ── Link appearance ──────────────────────────────────────────────
      .linkColor((link: any) => {
        const sourceNode = typeof link.source === 'object' ? link.source : null
        return TYPE_COLORS[sourceNode?.type] ?? '#60a5fa'
      })
      .linkOpacity(0.4)
      .linkWidth((link: any) => 0.6 + (link.weight ?? 0) * 1.8)
      .linkDirectionalParticles((link: any) => Math.ceil((link.weight ?? 0.5) * 3))
      .linkDirectionalParticleWidth(1.2)
      .linkDirectionalParticleSpeed(0.005)
      .linkDirectionalParticleColor(() => getAccentColor())

      // ── Interaction ──────────────────────────────────────────────────
      .onNodeClick((node: any) => {
        onSelectNodeRef.current(node.id)
        // Zoom to clicked node
        const distance = 80
        graph.cameraPosition(
          { x: node.x, y: node.y, z: node.z + distance },
          { x: node.x, y: node.y, z: node.z },
          800,
        )
      })
      .onBackgroundClick(() => {
        onBackgroundClickRef.current?.()
      })
      .onNodeDragEnd((node: any) => {
        node.fx = node.x
        node.fy = node.y
        node.fz = node.z
      })
      .onNodeRightClick((node: any) => {
        node.fx = undefined
        node.fy = undefined
        node.fz = undefined
      })

      // ── Forces ───────────────────────────────────────────────────────
      .d3AlphaDecay(0.02)
      .d3VelocityDecay(0.3)
      .warmupTicks(60)
      .cooldownTicks(200)

    // Configure forces
    try {
      graph.d3Force('link')?.distance((link: any) => 30 + (1 - (link.weight ?? 0.5)) * 60)
      graph.d3Force('charge')?.strength(-80)
    } catch { /* force config may fail silently */ }

    // ── Bloom post-processing ──────────────────────────────────────────
    try {
      const bloomPass = new UnrealBloomPass(
        new Vector2(width, height),
        1.5,   // strength
        0.4,   // radius
        0.1,   // threshold
      )
      graph.postProcessingComposer().addPass(bloomPass)
    } catch (e) {
      console.warn('Bloom pass failed, continuing without glow:', e)
    }

    // ── Auto-rotation (manual — TrackballControls lack autoRotate) ─────
    let rotationFrame: number
    const autoRotate = () => {
      try { graph.scene().rotation.y += 0.003 } catch { /* ok */ }
      rotationFrame = requestAnimationFrame(autoRotate)
    }
    autoRotate()

    graphRef.current = graph
    initializedRef.current = true

    // Load initial data
    updateGraphData(graph, nodes, edges)

    // Handle resize
    const ro = new ResizeObserver(([entry]) => {
      const { width: w, height: h } = entry.contentRect
      if (w > 0 && h > 0) graph.width(w).height(h)
    })
    ro.observe(el)

    return () => {
      cancelAnimationFrame(rotationFrame)
      ro.disconnect()
      initializedRef.current = false
      graphRef.current = null
      try { graph._destructor?.() } catch { /* ok */ }
      while (el.firstChild) el.removeChild(el.firstChild)
    }
  }, [nodes, edges])

  // Highlight selected node
  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.nodeColor((node: any) => {
      if (node.id === selectedId) return getCSSColor('--accent-300')
      return TYPE_COLORS[node.type] ?? DEFAULT_COLOR
    })
  }, [selectedId])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: '100%', height: '100%' }}
    />
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const CLUSTER_MIN_NODES = 3
const TYPE_LABELS: Record<string, string> = {
  fact: 'FACTS',
  entity: 'ENTITIES',
  preference: 'PREFERENCES',
  procedure: 'PROCEDURES',
  self_model: 'SELF MODEL',
  episode: 'EPISODES',
  schema: 'SCHEMAS',
  goal: 'GOALS',
}

function makeClusterLabel(text: string, color: string): Sprite {
  const canvas = document.createElement('canvas')
  const size = 512
  canvas.width = size
  canvas.height = 128
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, size, 128)
  ctx.font = '600 32px system-ui'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = color
  ctx.globalAlpha = 0.35
  ctx.fillText(text, size / 2, 64)
  const tex = new CanvasTexture(canvas)
  const mat = new SpriteMaterial({
    map: tex,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  })
  const sprite = new Sprite(mat)
  sprite.scale.set(60, 15, 1)
  sprite.renderOrder = -1
  return sprite
}

// Track cluster label sprites so we can remove them on update
const clusterSprites: Sprite[] = []

function updateGraphData(graph: any, nodes: GraphNode[], edges: GraphEdge[]) {
  const graphNodes = nodes.map(n => ({ ...n }))
  const nodeIds = new Set(nodes.map(n => n.id))
  const graphLinks = edges
    .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map(e => ({
      source: e.source,
      target: e.target,
      relation: e.relation,
      weight: e.weight,
    }))

  graph.graphData({ nodes: graphNodes, links: graphLinks })

  // Add cluster labels after simulation settles
  setTimeout(() => {
    try { graph.zoomToFit(600, 50) } catch { /* ok */ }

    // Remove old cluster labels
    const scene = graph.scene()
    for (const s of clusterSprites) scene.remove(s)
    clusterSprites.length = 0

    // Group positioned nodes by type
    const data = graph.graphData()
    const byType = new Map<string, any[]>()
    for (const node of data.nodes) {
      if (node.x == null) continue
      const list = byType.get(node.type) ?? []
      list.push(node)
      byType.set(node.type, list)
    }

    // Create labels for clusters with enough nodes
    for (const [type, group] of byType) {
      if (group.length < CLUSTER_MIN_NODES) continue
      const cx = group.reduce((s: number, n: any) => s + n.x, 0) / group.length
      const cy = group.reduce((s: number, n: any) => s + n.y, 0) / group.length
      const cz = group.reduce((s: number, n: any) => s + n.z, 0) / group.length

      const color = TYPE_COLORS[type] ?? DEFAULT_COLOR
      const label = makeClusterLabel(TYPE_LABELS[type] ?? type.toUpperCase(), color)
      label.position.set(cx, cy - 15, cz)
      scene.add(label)
      clusterSprites.push(label)
    }
  }, 1200)
}
