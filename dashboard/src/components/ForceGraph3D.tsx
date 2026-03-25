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
  Vector3,
  Group,
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
  autoSpin?: boolean
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

// ── Node label texture ───────────────────────────────────────────────────────

const labelTextureCache = new Map<string, CanvasTexture>()

function makeNodeLabelTexture(text: string, color: string): CanvasTexture {
  const key = `${text}|${color}`
  const cached = labelTextureCache.get(key)
  if (cached) return cached

  const canvas = document.createElement('canvas')
  const w = 512
  const h = 64
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, w, h)

  // Truncate long text
  const label = text.length > 40 ? text.slice(0, 38) + '...' : text

  ctx.font = '500 24px system-ui'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'

  // Measure text for background pill
  const metrics = ctx.measureText(label)
  const textW = metrics.width
  const padX = 16
  const padY = 8
  const pillW = textW + padX * 2
  const pillH = 32 + padY * 2
  const pillX = (w - pillW) / 2
  const pillY = (h - pillH) / 2

  // Fully opaque dark pill — no glow bleed-through
  ctx.fillStyle = '#09090b'
  ctx.beginPath()
  ctx.roundRect(pillX, pillY, pillW, pillH, 8)
  ctx.fill()

  // Border in type color
  ctx.strokeStyle = color
  ctx.globalAlpha = 0.5
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.roundRect(pillX, pillY, pillW, pillH, 8)
  ctx.stroke()

  // Pure white text
  ctx.fillStyle = '#ffffff'
  ctx.globalAlpha = 1
  ctx.fillText(label, w / 2, h / 2)

  const tex = new CanvasTexture(canvas)
  labelTextureCache.set(key, tex)
  return tex
}


// ── Progressive label visibility threshold ───────────────────────────────────
// Camera must be within this distance for node labels to appear.
// Mimics Obsidian's "zoom in to read" behavior.
const LABEL_SHOW_DISTANCE = 350
const LABEL_MIN_IMPORTANCE = 0.3

// ── Component ────────────────────────────────────────────────────────────────

export function ForceGraph3D({
  nodes,
  edges,
  selectedId,
  onSelectNode,
  onBackgroundClick,
  autoSpin = true,
  className,
}: ForceGraph3DProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null)
  const initializedRef = useRef(false)
  const spinningRef = useRef(true)

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
        const alpha = (0.4 + activation * 0.6) * 0.7

        const group = new Group()

        // Sphere
        const geo = new SphereGeometry(radius, 16, 12)
        const mat = new MeshBasicMaterial({
          color: new Color(color),
          transparent: true,
          opacity: alpha,
        })
        const sphere = new Mesh(geo, mat)
        group.add(sphere)

        // Glow sprite
        const spriteMat = new SpriteMaterial({
          map: getGlowTexture(),
          color: new Color(color),
          transparent: true,
          opacity: (0.3 + activation * 0.4) * 0.7,
          blending: AdditiveBlending,
          depthWrite: false,
        })
        const sprite = new Sprite(spriteMat)
        sprite.scale.set(radius * 3.5, radius * 3.5, 1)
        group.add(sprite)

        // Text label — only for notable nodes, shown by proximity in render loop
        if (importance >= LABEL_MIN_IMPORTANCE) {
          const content = node.content ?? ''
          const labelTex = makeNodeLabelTexture(content, color)
          const labelMat = new SpriteMaterial({
            map: labelTex,
            transparent: true,
            depthWrite: false,
            depthTest: false,
          })
          const labelSprite = new Sprite(labelMat)
          labelSprite.scale.set(28, 3.5, 1)
          labelSprite.position.set(0, -(radius + 4), 0)
          labelSprite.visible = false
          labelSprite.name = 'nodeLabel'
          group.add(labelSprite)
        }

        return group
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

    // ── Type clustering force ──────────────────────────────────────────
    // Gentle attraction between same-type nodes so they organically group.
    // Unlike hard grouping, this preserves the graph topology — connected
    // nodes of different types still stay close, but same-type nodes drift
    // toward their siblings.
    graph.onEngineTick(() => {
      const data = graph.graphData()
      if (!data?.nodes?.length) return

      // Compute centroids per type
      const centroids = new Map<string, { x: number; y: number; z: number; count: number }>()
      for (const node of data.nodes) {
        if (node.x == null) continue
        const c = centroids.get(node.type) ?? { x: 0, y: 0, z: 0, count: 0 }
        c.x += node.x
        c.y += node.y
        c.z += node.z
        c.count++
        centroids.set(node.type, c)
      }

      // Nudge each node gently toward its type centroid
      const strength = 0.003
      for (const node of data.nodes) {
        if (node.x == null) continue
        const c = centroids.get(node.type)
        if (!c || c.count < 2) continue
        const cx = c.x / c.count
        const cy = c.y / c.count
        const cz = c.z / c.count
        node.vx = (node.vx ?? 0) + (cx - node.x) * strength
        node.vy = (node.vy ?? 0) + (cy - node.y) * strength
        node.vz = (node.vz ?? 0) + (cz - node.z) * strength
      }
    })

    // ── Bloom post-processing ──────────────────────────────────────────
    try {
      const bloomPass = new UnrealBloomPass(
        new Vector2(width, height),
        0.8,   // strength (was 1.5 — less glow wash-out on labels)
        0.3,   // radius
        0.25,  // threshold (higher = only bright things bloom, labels stay crisp)
      )
      graph.postProcessingComposer().addPass(bloomPass)
    } catch (e) {
      console.warn('Bloom pass failed, continuing without glow:', e)
    }

    // ── Auto-rotation — spins until user interacts, resets on remount ────
    spinningRef.current = autoSpin
    let rotationFrame: number

    const camPos = new Vector3()
    const nodePos = new Vector3()

    const tick = () => {
      // Slow auto-rotate
      if (spinningRef.current) {
        try { graph.scene().rotation.y += 0.001 } catch { /* ok */ }
      }

      // Progressive label visibility — Obsidian-style zoom-to-read
      try {
        const camera = graph.camera()
        camPos.copy(camera.position)

        const data = graph.graphData()
        for (const node of data.nodes) {
          const obj = node.__threeObj
          if (!obj) continue
          const label = obj.getObjectByName('nodeLabel')
          if (!label) continue

          nodePos.set(node.x ?? 0, node.y ?? 0, node.z ?? 0)
          // Account for scene rotation
          nodePos.applyMatrix4(graph.scene().matrixWorld)
          const dist = camPos.distanceTo(nodePos)

          if (dist < LABEL_SHOW_DISTANCE) {
            label.visible = true
            // Fade in/out smoothly based on distance
            const t = 1 - (dist / LABEL_SHOW_DISTANCE)
            label.material.opacity = t * t  // ease-in curve
          } else {
            label.visible = false
          }
        }
      } catch { /* ok during init */ }

      rotationFrame = requestAnimationFrame(tick)
    }
    tick()

    // Stop spinning on any user interaction with the graph
    const stopSpin = () => { spinningRef.current = false }
    el.addEventListener('pointerdown', stopSpin)

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
      el.removeEventListener('pointerdown', stopSpin)
      ro.disconnect()
      initializedRef.current = false
      graphRef.current = null
      try { graph._destructor?.() } catch { /* ok */ }
      while (el.firstChild) el.removeChild(el.firstChild)
    }
  }, [nodes, edges])

  // Sync autoSpin prop to ref
  useEffect(() => {
    spinningRef.current = autoSpin
  }, [autoSpin])

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

const CLUSTER_MIN_NODES = 2
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

function makeClusterLabel(text: string, count: number, color: string): Sprite {
  const canvas = document.createElement('canvas')
  const w = 512
  const h = 128
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, w, h)

  // Type name
  ctx.font = '600 28px system-ui'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = color
  ctx.globalAlpha = 0.4
  ctx.fillText(text, w / 2, h / 2 - 12)

  // Count badge
  ctx.font = '400 20px system-ui'
  ctx.globalAlpha = 0.25
  ctx.fillText(`${count} memories`, w / 2, h / 2 + 16)

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

// Track cluster visuals so we can remove them on update
const clusterVisuals: (Sprite | Mesh)[] = []

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

  // Add cluster labels + halos after simulation settles
  setTimeout(() => {
    try { graph.zoomToFit(600, 50) } catch { /* ok */ }

    // Remove old cluster visuals
    const scene = graph.scene()
    for (const s of clusterVisuals) scene.remove(s)
    clusterVisuals.length = 0

    // Group positioned nodes by type
    const data = graph.graphData()
    const byType = new Map<string, any[]>()
    for (const node of data.nodes) {
      if (node.x == null) continue
      const list = byType.get(node.type) ?? []
      list.push(node)
      byType.set(node.type, list)
    }

    // Create labels + halos for clusters
    for (const [type, group] of byType) {
      if (group.length < CLUSTER_MIN_NODES) continue

      const cx = group.reduce((s: number, n: any) => s + n.x, 0) / group.length
      const cy = group.reduce((s: number, n: any) => s + n.y, 0) / group.length
      const cz = group.reduce((s: number, n: any) => s + n.z, 0) / group.length

      // Compute cluster spread for halo sizing
      const maxDist = Math.max(
        ...group.map((n: any) => Math.sqrt(
          (n.x - cx) ** 2 + (n.y - cy) ** 2 + (n.z - cz) ** 2
        ))
      )
      const haloRadius = Math.max(maxDist + 15, 25)

      const color = TYPE_COLORS[type] ?? DEFAULT_COLOR

      // Cluster label with count
      const label = makeClusterLabel(
        TYPE_LABELS[type] ?? type.toUpperCase(),
        group.length,
        color,
      )
      label.position.set(cx, cy - haloRadius - 5, cz)
      scene.add(label)
      clusterVisuals.push(label)

    }
  }, 1200)
}
