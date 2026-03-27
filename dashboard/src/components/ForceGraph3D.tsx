import { useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react'
import ForceGraph3DLib from '3d-force-graph'
import {
  Mesh,
  SphereGeometry,
  ShaderMaterial,
  Sprite,
  SpriteMaterial,
  CanvasTexture,
  Color,
  AdditiveBlending,
  Vector2,
  Vector3,
  Group,
  BufferGeometry,
  Float32BufferAttribute,
  PointsMaterial,
  Points,
  FrontSide,
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

// ── Layout presets ────────────────────────────────────────────────────────────

export interface LayoutConfig {
  sphereRadius: number
  homeForce: number
  charge: number
  linkDist: number
  linkDistSpread: number
}

export const LAYOUT_PRESETS: Record<string, LayoutConfig & { label: string; description: string }> = {
  clustered: { label: 'Clustered', sphereRadius: 0, homeForce: 0, charge: -50, linkDist: 20, linkDistSpread: 35, description: 'Topic-clustered layout with spatial grouping' },
}

export const DEFAULT_LAYOUT = 'clustered'

export interface NeuralModeConfig {
  enabled: boolean
  breathingRate?: number      // Hz, default 0.02
  breathingAmplitude?: number // 0-1, default 0.05
  bloomStrength?: number      // default 1.2 (current default is 0.8)
  particlesAlways?: boolean   // override large-graph particle disable
}

export interface ForceGraph3DHandle {
  highlightNodes: (ids: string[], durationMs: number) => void
  pulseAll: (durationMs: number) => void
  fadeInNodes: (ids: string[], durationMs: number) => void
}

interface ForceGraph3DProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  clusters?: ClusterInfo[]
  selectedId: string | null
  onSelectNode: (id: string) => void
  onBackgroundClick?: () => void
  autoSpin?: boolean
  bgColor?: string
  className?: string
  focusClusterId?: number | null
  focusClusterTs?: number
  focusNodeId?: string | null
  focusNodeTs?: number
  layoutPreset?: string
  neuralMode?: NeuralModeConfig
}

// ── Fibonacci sphere — evenly distributes cluster homes on a sphere ──────────

function fibonacciSphere(index: number, total: number, radius: number) {
  if (total <= 1) return { x: 0, y: 0, z: 0 }
  const goldenAngle = Math.PI * (3 - Math.sqrt(5))
  const y = 1 - (index / (total - 1)) * 2
  const radiusAtY = Math.sqrt(1 - y * y)
  const theta = goldenAngle * index
  return {
    x: Math.cos(theta) * radiusAtY * radius,
    y: y * radius,
    z: Math.sin(theta) * radiusAtY * radius,
  }
}

// Module-level storage for cluster home positions (survives re-renders)
const clusterHomePositions = new Map<string, { x: number; y: number; z: number }>()

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

const NEURAL_TYPE_COLORS: Record<string, string> = {
  fact:       '#3b82f6',
  entity:     '#14b8a6',
  preference: '#10b981',
  procedure:  '#a1a1aa',
  self_model: '#6366f1',
  episode:    '#f59e0b',
  schema:     '#ef4444',
  goal:       '#a855f7',
  topic:      '#06b6d4',
}

// Distinct cluster colors for full-graph mode
const CLUSTER_COLORS = [
  '#818cf8', '#60a5fa', '#2dd4bf', '#34d399', '#fbbf24',
  '#f87171', '#c084fc', '#fb923c', '#a3e635', '#22d3ee',
  '#e879f9', '#f472b6', '#38bdf8', '#4ade80', '#facc15',
  '#a78bfa', '#67e8f9', '#fca5a5', '#86efac', '#fde68a',
]

function getNodeColor(node: GraphNode, useCluster: boolean, neural?: boolean): string {
  if (useCluster && node.cluster_id != null) {
    return CLUSTER_COLORS[node.cluster_id % CLUSTER_COLORS.length]
  }
  if (neural) {
    return NEURAL_TYPE_COLORS[node.type] ?? TYPE_COLORS[node.type] ?? DEFAULT_COLOR
  }
  return TYPE_COLORS[node.type] ?? DEFAULT_COLOR
}

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

// ── Fresnel orb shader ──────────────────────────────────────────────────────

const orbVertexShader = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vViewDir;
  void main() {
    vNormal = normalize(normalMatrix * normal);
    vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
    vViewDir = normalize(-mvPos.xyz);
    gl_Position = projectionMatrix * mvPos;
  }
`

const orbFragmentShader = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform float uActivation;

  varying vec3 vNormal;
  varying vec3 vViewDir;

  void main() {
    float facing = dot(vNormal, vViewDir);

    // Fresnel rim — bright edges like a holographic shield
    float fresnel = 1.0 - facing;
    fresnel = pow(fresnel, 2.2);

    // Core illumination — bright center falloff
    float core = pow(facing, 1.6);

    // Specular highlight — virtual light from upper-right
    vec3 lightDir = normalize(vec3(0.4, 0.7, 0.6));
    vec3 halfVec = normalize(vViewDir + lightDir);
    float spec = pow(max(dot(vNormal, halfVec), 0.0), 32.0);

    // Base color: darker away from view, lit center
    vec3 baseCol = uColor * (0.25 + core * 0.55);
    // Rim highlight (boosted color + white tint)
    vec3 rimCol = uColor * 1.6 + vec3(0.2);
    // Mix — rim glow blends over base
    vec3 finalCol = mix(baseCol, rimCol, fresnel * 0.5);
    // Specular catch — white-ish highlight for glassy depth
    finalCol += vec3(1.0) * spec * 0.35;
    // Subtle ambient so back-facing areas aren't pure black
    finalCol += uColor * 0.06;

    // Alpha: slightly brighter at rim for glow
    float alpha = uOpacity * (0.85 + fresnel * 0.15);

    gl_FragColor = vec4(finalCol, alpha);
  }
`

function makeOrbMaterial(color: string, opacity: number, activation: number): ShaderMaterial {
  const mat = new ShaderMaterial({
    uniforms: {
      uColor: { value: new Color(color) },
      uOpacity: { value: opacity },
      uActivation: { value: activation },
    },
    vertexShader: orbVertexShader,
    fragmentShader: orbFragmentShader,
    transparent: true,
    side: FrontSide,
    depthWrite: true,
  })
  // Sync .opacity reads/writes with the shader uniform so animation code
  // that sets material.opacity directly still works.
  Object.defineProperty(mat, 'opacity', {
    get() { return mat.uniforms.uOpacity.value },
    set(v: number) { mat.uniforms.uOpacity.value = v },
  })
  return mat
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

  ctx.font = '600 24px system-ui'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'

  // Measure text for background pill
  const metrics = ctx.measureText(label)
  const textW = metrics.width
  const padX = 20
  const padY = 10
  const pillW = textW + padX * 2
  const pillH = 32 + padY * 2
  const pillX = (w - pillW) / 2
  const pillY = (h - pillH) / 2

  // Fully opaque dark pill — blocks glow bleed-through
  ctx.fillStyle = '#09090b'
  ctx.beginPath()
  ctx.roundRect(pillX, pillY, pillW, pillH, 8)
  ctx.fill()

  // Border in type color (stronger)
  ctx.strokeStyle = color
  ctx.globalAlpha = 0.7
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.roundRect(pillX, pillY, pillW, pillH, 8)
  ctx.stroke()

  // Thick dark outline — absorbs bloom bleed from nearby nodes
  ctx.globalAlpha = 1
  ctx.strokeStyle = '#09090b'
  ctx.lineWidth = 6
  ctx.lineJoin = 'round'
  ctx.strokeText(label, w / 2, h / 2)

  // Muted text — bright enough to read, dim enough to dodge bloom threshold
  ctx.fillStyle = '#a1a1aa'
  ctx.fillText(label, w / 2, h / 2)

  const tex = new CanvasTexture(canvas)
  labelTextureCache.set(key, tex)
  return tex
}


// ── Galaxy starfield ────────────────────────────────────────────────────────

function makeNebulaTexture(r: number, g: number, b: number): CanvasTexture {
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = size; canvas.height = size
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, size, size)

  const cx = size / 2, cy = size / 2

  // Main soft glow
  const g1 = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.45)
  g1.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.5)`)
  g1.addColorStop(0.4, `rgba(${r}, ${g}, ${b}, 0.15)`)
  g1.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`)
  ctx.fillStyle = g1
  ctx.fillRect(0, 0, size, size)

  // Asymmetric secondary highlight
  const g2 = ctx.createRadialGradient(cx + 40, cy - 30, 0, cx + 40, cy - 30, size * 0.25)
  const r2 = Math.min(255, r + 60), g2c = Math.min(255, g + 50), b2 = Math.min(255, b + 80)
  g2.addColorStop(0, `rgba(${r2}, ${g2c}, ${b2}, 0.25)`)
  g2.addColorStop(0.6, `rgba(${r}, ${g}, ${b}, 0.05)`)
  g2.addColorStop(1, `rgba(0, 0, 0, 0)`)
  ctx.fillStyle = g2
  ctx.fillRect(0, 0, size, size)

  return new CanvasTexture(canvas)
}

function makeGalaxyTexture(): CanvasTexture {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size; canvas.height = size
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, size, size)

  // Elliptical galaxy — scale Y to flatten
  ctx.save()
  ctx.translate(size / 2, size / 2)
  ctx.scale(1, 0.35)

  const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, size / 3)
  grad.addColorStop(0, 'rgba(255, 245, 230, 0.7)')
  grad.addColorStop(0.3, 'rgba(180, 160, 220, 0.25)')
  grad.addColorStop(0.7, 'rgba(80, 100, 180, 0.08)')
  grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = grad
  ctx.beginPath()
  ctx.arc(0, 0, size / 2, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()

  return new CanvasTexture(canvas)
}

function createStarfield(): Group {
  const group = new Group()
  group.name = 'starfield'

  // ── Dim stars — the background dust ──
  const dimCount = 2000
  const dimPos = new Float32Array(dimCount * 3)
  const dimCol = new Float32Array(dimCount * 3)

  for (let i = 0; i < dimCount; i++) {
    const r = 600 + Math.random() * 900
    const theta = Math.random() * Math.PI * 2
    const phi = Math.acos(2 * Math.random() - 1)
    dimPos[i * 3]     = r * Math.sin(phi) * Math.cos(theta)
    dimPos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
    dimPos[i * 3 + 2] = r * Math.cos(phi)

    const t = Math.random()
    if (t < 0.5) {        // cool white/blue-white
      dimCol[i * 3] = 0.8 + Math.random() * 0.2
      dimCol[i * 3 + 1] = 0.85 + Math.random() * 0.15
      dimCol[i * 3 + 2] = 1.0
    } else if (t < 0.75) { // warm yellow
      dimCol[i * 3] = 1.0
      dimCol[i * 3 + 1] = 0.8 + Math.random() * 0.2
      dimCol[i * 3 + 2] = 0.5 + Math.random() * 0.2
    } else {                // blue
      dimCol[i * 3] = 0.5 + Math.random() * 0.2
      dimCol[i * 3 + 1] = 0.6 + Math.random() * 0.2
      dimCol[i * 3 + 2] = 1.0
    }
  }

  const dimGeo = new BufferGeometry()
  dimGeo.setAttribute('position', new Float32BufferAttribute(dimPos, 3))
  dimGeo.setAttribute('color', new Float32BufferAttribute(dimCol, 3))
  group.add(new Points(dimGeo, new PointsMaterial({
    size: 0.8, vertexColors: true, transparent: true, opacity: 0.6, sizeAttenuation: true,
  })))

  // ── Bright stars — the visible ones ──
  const brightCount = 300
  const brightPos = new Float32Array(brightCount * 3)
  const brightCol = new Float32Array(brightCount * 3)

  for (let i = 0; i < brightCount; i++) {
    const r = 500 + Math.random() * 1000
    const theta = Math.random() * Math.PI * 2
    const phi = Math.acos(2 * Math.random() - 1)
    brightPos[i * 3]     = r * Math.sin(phi) * Math.cos(theta)
    brightPos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
    brightPos[i * 3 + 2] = r * Math.cos(phi)

    brightCol[i * 3] = 0.9 + Math.random() * 0.1
    brightCol[i * 3 + 1] = 0.9 + Math.random() * 0.1
    brightCol[i * 3 + 2] = 1.0
  }

  const brightGeo = new BufferGeometry()
  brightGeo.setAttribute('position', new Float32BufferAttribute(brightPos, 3))
  brightGeo.setAttribute('color', new Float32BufferAttribute(brightCol, 3))
  group.add(new Points(brightGeo, new PointsMaterial({
    size: 2.0, vertexColors: true, transparent: true, opacity: 0.9, sizeAttenuation: true,
  })))

  // ── Nebulae — distant color clouds ──
  const nebulae = [
    { x: 700,  y: 300,  z: -500, s: 500, r: 100, g: 60,  b: 180, op: 0.15 },
    { x: -500, y: -400, z: 600,  s: 400, r: 40,  g: 80,  b: 160, op: 0.12 },
    { x: 300,  y: 700,  z: 400,  s: 350, r: 160, g: 40,  b: 80,  op: 0.08 },
    { x: -700, y: 200,  z: -300, s: 550, r: 30,  g: 100, b: 120, op: 0.10 },
    { x: 100,  y: -600, z: -700, s: 280, r: 140, g: 100, b: 40,  op: 0.06 },
  ]

  for (const n of nebulae) {
    const tex = makeNebulaTexture(n.r, n.g, n.b)
    const mat = new SpriteMaterial({
      map: tex, transparent: true, opacity: n.op,
      blending: AdditiveBlending, depthWrite: false,
    })
    const sprite = new Sprite(mat)
    sprite.position.set(n.x, n.y, n.z)
    sprite.scale.set(n.s, n.s, 1)
    group.add(sprite)
  }

  // ── Distant galaxies — tiny elliptical blobs ──
  const galaxies = [
    { x: 900,  y: 500,  z: -400, w: 70, h: 25, rot: 0.3 },
    { x: -800, y: -300, z: 800,  w: 50, h: 18, rot: -0.5 },
    { x: 400,  y: -700, z: -600, w: 60, h: 22, rot: 0.8 },
    { x: -300, y: 800,  z: -500, w: 45, h: 16, rot: -0.2 },
  ]

  for (const g of galaxies) {
    const tex = makeGalaxyTexture()
    const mat = new SpriteMaterial({
      map: tex, transparent: true, opacity: 0.5,
      blending: AdditiveBlending, depthWrite: false,
    })
    mat.rotation = g.rot
    const sprite = new Sprite(mat)
    sprite.position.set(g.x, g.y, g.z)
    sprite.scale.set(g.w, g.h, 1)
    group.add(sprite)
  }

  return group
}

function disposeStarfield(group: Group) {
  group.traverse((obj) => {
    if (obj instanceof Points || obj instanceof Mesh) {
      obj.geometry?.dispose()
      const mat = obj.material
      if (Array.isArray(mat)) mat.forEach(m => m.dispose())
      else mat?.dispose()
    }
    if (obj instanceof Sprite) {
      obj.material?.map?.dispose()
      obj.material?.dispose()
    }
  })
}

// ── Progressive label visibility threshold ───────────────────────────────────
// Camera must be within this distance for node labels to appear.
// Mimics Obsidian's "zoom in to read" behavior.
const LABEL_SHOW_DISTANCE = 350
const LABEL_MIN_IMPORTANCE = 0.3

// ── Component ────────────────────────────────────────────────────────────────

export const ForceGraph3D = forwardRef<ForceGraph3DHandle, ForceGraph3DProps>(function ForceGraph3D({
  nodes,
  edges,
  clusters,
  selectedId,
  onSelectNode,
  onBackgroundClick,
  autoSpin = true,
  bgColor = '#000000',
  className,
  focusClusterId,
  focusClusterTs,
  focusNodeId,
  focusNodeTs,
  layoutPreset = DEFAULT_LAYOUT,
  neuralMode,
}: ForceGraph3DProps, ref) {
  const useClusterColors = (clusters?.length ?? 0) > 0
  const isLargeGraph = nodes.length > 200
  const layoutRef = useRef(LAYOUT_PRESETS[layoutPreset] ?? LAYOUT_PRESETS[DEFAULT_LAYOUT])
  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null)
  const initializedRef = useRef(false)
  const spinningRef = useRef(true)
  const starfieldRef = useRef<Group | null>(null)
  const bgColorRef = useRef(bgColor)
  bgColorRef.current = bgColor
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const bloomPassRef = useRef<any>(null)
  const neuralModeRef = useRef(neuralMode)
  neuralModeRef.current = neuralMode

  // Activity visualization refs (imperative handle)
  const highlightedNodesRef = useRef<Set<string>>(new Set())
  const globalPulseRef = useRef<{ active: boolean; startTime: number; duration: number }>({ active: false, startTime: 0, duration: 0 })
  const fadeInNodesRef = useRef<Map<string, number>>(new Map()) // id -> birthTime

  useImperativeHandle(ref, () => ({
    highlightNodes(ids: string[], durationMs: number) {
      ids.forEach(id => highlightedNodesRef.current.add(id))
      setTimeout(() => {
        ids.forEach(id => highlightedNodesRef.current.delete(id))
      }, durationMs)
    },
    pulseAll(durationMs: number) {
      globalPulseRef.current = { active: true, startTime: Date.now(), duration: durationMs }
    },
    fadeInNodes(ids: string[], durationMs: number) {
      const now = Date.now()
      ids.forEach(id => fadeInNodesRef.current.set(id, now))
      setTimeout(() => {
        ids.forEach(id => fadeInNodesRef.current.delete(id))
      }, durationMs)
    },
  }))

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
      updateGraphData(graphRef.current, nodes, edges, useClusterColors, layoutRef.current)
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
      .backgroundColor(bgColorRef.current === 'galaxy' ? '#000000' : bgColorRef.current)
      .showNavInfo(false)

      // ── Node appearance ──────────────────────────────────────────────
      .nodeVal((node: any) => 1 + (node.importance ?? 0) * 8)
      .nodeLabel((node: any) => {
        const type = node.type === 'self_model' ? 'self model' : (node.type ?? '')
        const color = getNodeColor(node, useClusterColors, neuralModeRef.current?.enabled)
        const clusterLine = node.cluster_label
          ? `<div style="color:${color};font-weight:600;margin-bottom:2px;font-size:10px;letter-spacing:0.5px;">${node.cluster_label}</div>`
          : ''
        return `<div style="background:rgba(9,9,11,0.92);border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:8px 12px;max-width:300px;font-family:system-ui;font-size:12px;pointer-events:none;">
          ${clusterLine}
          <div style="color:#71717a;text-transform:uppercase;font-size:9px;letter-spacing:0.5px;margin-bottom:3px;">${type}</div>
          <div style="color:#e4e4e7;line-height:1.4;">${node.content ?? ''}</div>
          <div style="color:#71717a;font-size:10px;margin-top:4px;">${(node.access_count ?? 0).toLocaleString()} recalls</div>
        </div>`
      })
      .nodeThreeObject((node: any) => {
        const color = getNodeColor(node, useClusterColors, neuralModeRef.current?.enabled)
        const importance = node.importance ?? 0
        const activation = node.activation ?? 0
        // Smaller base radius for large graphs so clusters don't overlap
        const baseRadius = isLargeGraph ? 1.2 : 2
        const radiusScale = isLargeGraph ? 2.5 : 4
        const radius = baseRadius + importance * radiusScale
        const alpha = 0.7 + activation * 0.3
        // Sphere detail — higher for smooth close-up, lower for large graphs
        const segments = isLargeGraph ? 16 : 32

        const group = new Group()

        // Sphere — Fresnel orb shader for lit, glassy depth
        const geo = new SphereGeometry(radius, segments, segments)
        const mat = makeOrbMaterial(color, alpha, activation)
        const sphere = new Mesh(geo, mat)
        group.add(sphere)

        // Glow sprite — skip for unimportant nodes in large graphs
        if (!isLargeGraph || importance >= 0.3) {
          const spriteMat = new SpriteMaterial({
            map: getGlowTexture(),
            color: new Color(color),
            transparent: true,
            opacity: 0.35 + activation * 0.25,
            blending: AdditiveBlending,
            depthWrite: false,
          })
          const sprite = new Sprite(spriteMat)
          sprite.scale.set(radius * 3, radius * 3, 1)
          group.add(sprite)
        }

        // Text label — only for notable nodes, shown by proximity in render loop
        const labelThreshold = isLargeGraph ? 0.5 : LABEL_MIN_IMPORTANCE
        if (importance >= labelThreshold) {
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
        if (!sourceNode) return '#60a5fa'
        return getNodeColor(sourceNode, useClusterColors, neuralModeRef.current?.enabled)
      })
      .linkOpacity(isLargeGraph ? 0.15 : 0.4)
      .linkWidth((link: any) => isLargeGraph ? 0.3 + (link.weight ?? 0) * 0.8 : 0.6 + (link.weight ?? 0) * 1.8)
      .linkDirectionalParticles((link: any) => {
        if (neuralModeRef.current?.particlesAlways) {
          return Math.max(1, Math.ceil((link.weight ?? 0.5) * 2))
        }
        return isLargeGraph ? 0 : Math.ceil((link.weight ?? 0.5) * 3)
      })
      .linkDirectionalParticleWidth(1.2)
      .linkDirectionalParticleSpeed(0.005)
      .linkDirectionalParticleColor(() => getAccentColor())

      // ── Interaction ──────────────────────────────────────────────────
      .onNodeClick((node: any) => {
        onSelectNodeRef.current(node.id)
        // Freeze node position so it doesn't drift during camera animation
        node.fx = node.x
        node.fy = node.y
        node.fz = node.z
        // Zoom to clicked node using current coordinates
        const distance = 80
        graph.cameraPosition(
          { x: node.x, y: node.y, z: node.z + distance },
          { x: node.x, y: node.y, z: node.z },
          800,
        )
        // Unfreeze after camera arrives
        setTimeout(() => {
          node.fx = undefined
          node.fy = undefined
          node.fz = undefined
        }, 900)
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
      // Organic force-directed layout — let topology create clusters
      // naturally. No artificial sphere positioning.
      .d3AlphaDecay(0.02)
      .d3VelocityDecay(0.3)
      .warmupTicks(isLargeGraph ? 150 : 60)
      .cooldownTicks(isLargeGraph ? 400 : 200)

    try {
      if (isLargeGraph) {
        const cfg = layoutRef.current
        graph.d3Force('charge')?.strength(cfg.charge).distanceMax(250)
        // Weight-proportional: strong edges pull firmly (short distance),
        // weak edges barely pull (long distance + low strength).
        // This is the key to preventing clumping without losing edges.
        graph.d3Force('link')
          ?.distance((link: any) => {
            const w = link.weight ?? 0.3
            return cfg.linkDist + (1 - w) * cfg.linkDistSpread
          })
          .strength((link: any) => {
            const w = link.weight ?? 0.3
            return 0.02 + w * 0.3  // weak=0.02, strong=0.32
          })
        graph.d3Force('center')?.strength(0.008)
      } else {
        graph.d3Force('link')?.distance((link: any) => 30 + (1 - (link.weight ?? 0.5)) * 60)
        graph.d3Force('charge')?.strength(-80)
      }
    } catch { /* force config may fail silently */ }

    // ── Topic clustering force ─────────────────────────────────────────
    // Nudge nodes toward their topic cluster centroid each tick.
    // This creates visible spatial groupings by topic while still
    // letting the force simulation handle fine positioning.
    graph.onEngineTick(() => {
      const data = graph.graphData()
      if (!data?.nodes?.length) return

      // Compute centroid per cluster (skip uncategorized — let those float freely)
      const centroids = new Map<number, { x: number; y: number; z: number; count: number }>()
      for (const node of data.nodes) {
        if (node.x == null || node.cluster_id == null) continue
        if (node.cluster_label === 'Uncategorized') continue
        const c = centroids.get(node.cluster_id) ?? { x: 0, y: 0, z: 0, count: 0 }
        c.x += node.x; c.y += node.y; c.z += node.z; c.count++
        centroids.set(node.cluster_id, c)
      }

      // Apply clustering force only to nodes in real topics
      const strength = 0.008
      for (const node of data.nodes) {
        if (node.x == null || node.cluster_id == null) continue
        if (node.cluster_label === 'Uncategorized') continue
        const c = centroids.get(node.cluster_id)
        if (!c || c.count < 2) continue
        const cx = c.x / c.count, cy = c.y / c.count, cz = c.z / c.count
        node.vx = (node.vx ?? 0) + (cx - node.x) * strength
        node.vy = (node.vy ?? 0) + (cy - node.y) * strength
        node.vz = (node.vz ?? 0) + (cz - node.z) * strength
      }
    })

    // ── Bloom post-processing ──────────────────────────────────────────
    try {
      const bloomStrength = neuralModeRef.current?.enabled
        ? (neuralModeRef.current.bloomStrength ?? 1.2)
        : 0.8
      const bloomPass = new UnrealBloomPass(
        new Vector2(width, height),
        bloomStrength,   // strength — full node glow
        0.3,   // radius
        0.5,   // threshold — glow sprites (additive) exceed this, labels (normal blend) don't
      )
      bloomPassRef.current = bloomPass
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

      // ── Neural mode pulsation + bloom breathing ─────────────────────
      try {
        const neuralCfg = neuralModeRef.current
        if (neuralCfg?.enabled) {
          const time = Date.now() * 0.001
          const rate = neuralCfg.breathingRate ?? 0.02
          const amp = neuralCfg.breathingAmplitude ?? 0.05

          // Per-node pulsation
          const graphData = graph.graphData()
          graphData.nodes.forEach((node: any, i: number) => {
            const obj = node.__threeObj
            if (!obj) return
            const phase = i * 0.7
            const scale = 1 + Math.sin(time * rate * Math.PI * 2 + phase) * amp
            obj.children.forEach((child: any) => {
              if (child.geometry) { // sphere
                child.scale.setScalar(scale)
              }
            })
          })

          // Global bloom breathing
          if (bloomPassRef.current) {
            const baseStrength = neuralCfg.bloomStrength ?? 1.2
            const breathe = 1 + Math.sin(time * 0.02 * Math.PI * 2) * 0.05
            bloomPassRef.current.strength = baseStrength * breathe
          }
        }
      } catch { /* ok during init */ }

      // ── Activity visualization: highlighted nodes ───────────────────
      try {
        if (highlightedNodesRef.current.size > 0) {
          const graphData = graph.graphData()
          graphData.nodes.forEach((node: any) => {
            if (!highlightedNodesRef.current.has(node.id)) return
            const obj = node.__threeObj
            if (!obj) return
            obj.children.forEach((child: any) => {
              if (child.material?.opacity !== undefined) {
                child.material.opacity = Math.min(1, child.material.opacity + 0.3)
              }
              if (child.isSprite) {
                child.scale.multiplyScalar(1.5)
              }
            })
          })
        }
      } catch { /* ok */ }

      // ── Activity visualization: global pulse ────────────────────────
      try {
        if (globalPulseRef.current.active && bloomPassRef.current) {
          const elapsed = Date.now() - globalPulseRef.current.startTime
          if (elapsed > globalPulseRef.current.duration) {
            globalPulseRef.current.active = false
          } else {
            const t = elapsed / globalPulseRef.current.duration
            bloomPassRef.current.strength += Math.sin(t * Math.PI) * 0.3
          }
        }
      } catch { /* ok */ }

      // ── Activity visualization: fade-in nodes ──────────────────────
      try {
        if (fadeInNodesRef.current.size > 0) {
          const now = Date.now()
          const graphData = graph.graphData()
          graphData.nodes.forEach((node: any) => {
            const birthTime = fadeInNodesRef.current.get(node.id)
            if (birthTime === undefined) return
            const obj = node.__threeObj
            if (!obj) return
            const elapsed = now - birthTime
            const alpha = Math.min(1, elapsed / 1000)
            obj.children.forEach((child: any) => {
              if (child.material?.opacity !== undefined) {
                child.material.opacity *= alpha
              }
            })
          })
        }
      } catch { /* ok */ }

      rotationFrame = requestAnimationFrame(tick)
    }
    tick()

    // Stop spinning on any user interaction with the graph
    const stopSpin = () => { spinningRef.current = false }
    el.addEventListener('pointerdown', stopSpin)

    graphRef.current = graph
    initializedRef.current = true

    // Attach starfield if galaxy mode at init
    if (bgColorRef.current === 'galaxy') {
      const sf = createStarfield()
      graph.scene().add(sf)
      starfieldRef.current = sf
    }

    // Load initial data
    updateGraphData(graph, nodes, edges, useClusterColors, layoutRef.current)

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
      if (starfieldRef.current) {
        disposeStarfield(starfieldRef.current)
        starfieldRef.current = null
      }
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

  // Live-update background + starfield without reinitializing graph
  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return

    const scene = graph.scene()

    // Remove existing starfield
    if (starfieldRef.current) {
      scene.remove(starfieldRef.current)
      disposeStarfield(starfieldRef.current)
      starfieldRef.current = null
    }

    if (bgColor === 'galaxy') {
      graph.backgroundColor('#000000')
      const sf = createStarfield()
      scene.add(sf)
      starfieldRef.current = sf
    } else {
      graph.backgroundColor(bgColor)
    }
  }, [bgColor])

  // Layout preset is now fixed (single "clustered" layout) — no dynamic switching needed

  // Highlight selected node
  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.nodeColor((node: any) => {
      if (node.id === selectedId) return getCSSColor('--accent-300')
      return getNodeColor(node, useClusterColors, neuralModeRef.current?.enabled)
    })
  }, [selectedId, useClusterColors])

  // Navigate camera to a cluster's centroid
  useEffect(() => {
    const graph = graphRef.current
    if (!graph || focusClusterId == null) return
    const data = graph.graphData()
    const clusterNodes = data.nodes.filter((n: any) => n.cluster_id === focusClusterId)
    if (!clusterNodes.length) return

    const cx = clusterNodes.reduce((s: number, n: any) => s + (n.x ?? 0), 0) / clusterNodes.length
    const cy = clusterNodes.reduce((s: number, n: any) => s + (n.y ?? 0), 0) / clusterNodes.length
    const cz = clusterNodes.reduce((s: number, n: any) => s + (n.z ?? 0), 0) / clusterNodes.length

    const maxDist = Math.max(...clusterNodes.map((n: any) =>
      Math.sqrt(((n.x ?? 0) - cx) ** 2 + ((n.y ?? 0) - cy) ** 2 + ((n.z ?? 0) - cz) ** 2)
    ))
    const distance = Math.max(maxDist * 2.5, 60)

    spinningRef.current = false
    graph.cameraPosition(
      { x: cx, y: cy, z: cz + distance },
      { x: cx, y: cy, z: cz },
      1000,
    )
  }, [focusClusterId, focusClusterTs])

  // Navigate camera to a specific node
  useEffect(() => {
    const graph = graphRef.current
    if (!graph || !focusNodeId) return
    const data = graph.graphData()
    const node = data.nodes.find((n: any) => n.id === focusNodeId)
    if (!node || node.x == null) return

    spinningRef.current = false
    graph.cameraPosition(
      { x: node.x, y: node.y, z: node.z + 60 },
      { x: node.x, y: node.y, z: node.z },
      800,
    )
  }, [focusNodeId, focusNodeTs])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: '100%', height: '100%' }}
    />
  )
})

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

function makeDomainLabel(text: string, count: number, color: string): Sprite {
  const canvas = document.createElement('canvas')
  const w = 512
  const h = 128
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, w, h)

  // Domain label
  const label = text.length > 30 ? text.slice(0, 28) + '...' : text
  ctx.font = '600 28px system-ui'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = color
  ctx.globalAlpha = 0.5
  ctx.fillText(label, w / 2, h / 2 - 12)

  // Count badge
  ctx.font = '400 20px system-ui'
  ctx.globalAlpha = 0.3
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

function updateGraphData(graph: any, nodes: GraphNode[], edges: GraphEdge[], useClusterMode: boolean, config?: LayoutConfig) {
  const cfg = config ?? LAYOUT_PRESETS[DEFAULT_LAYOUT]
  const graphNodes = nodes.map(n => ({ ...n })) as any[]
  const nodeIds = new Set(nodes.map(n => n.id))
  const graphLinks = edges
    .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map(e => ({
      source: e.source,
      target: e.target,
      relation: e.relation,
      weight: e.weight,
    }))

  // Let d3-force handle layout organically — no forced positioning.
  // The topology (edges) naturally creates clusters, charge pushes
  // unconnected nodes apart, and domain coloring makes groups visible.
  graph.graphData({ nodes: graphNodes, links: graphLinks })

  // Longer settle time for large graphs
  const settleMs = nodes.length > 500 ? 3000 : 1200

  // Add cluster/domain labels after simulation settles
  setTimeout(() => {
    try { graph.zoomToFit(600, 60) } catch { /* ok */ }

    // Remove old cluster visuals
    const scene = graph.scene()
    for (const s of clusterVisuals) scene.remove(s)
    clusterVisuals.length = 0

    const data = graph.graphData()

    if (useClusterMode) {
      // ── Cluster mode: group by cluster_id, label by domain ──
      const byCluster = new Map<number, any[]>()
      for (const node of data.nodes) {
        if (node.x == null) continue
        const cid = node.cluster_id ?? -1
        const list = byCluster.get(cid) ?? []
        list.push(node)
        byCluster.set(cid, list)
      }

      for (const [clusterId, group] of byCluster) {
        if (group.length < CLUSTER_MIN_NODES) continue

        const cx = group.reduce((s: number, n: any) => s + n.x, 0) / group.length
        const cy = group.reduce((s: number, n: any) => s + n.y, 0) / group.length
        const cz = group.reduce((s: number, n: any) => s + n.z, 0) / group.length

        const maxDist = Math.max(
          ...group.map((n: any) => Math.sqrt(
            (n.x - cx) ** 2 + (n.y - cy) ** 2 + (n.z - cz) ** 2
          ))
        )
        const haloRadius = Math.max(maxDist + 15, 25)

        const color = clusterId >= 0
          ? CLUSTER_COLORS[clusterId % CLUSTER_COLORS.length]
          : DEFAULT_COLOR

        // Use the cluster_label from the first node in this group
        const domainLabel = group[0]?.cluster_label ?? `Cluster ${clusterId}`

        const label = makeDomainLabel(domainLabel, group.length, color)
        label.position.set(cx, cy - haloRadius - 5, cz)
        scene.add(label)
        clusterVisuals.push(label)
      }
    } else {
      // ── Type mode: group by engram type (original behavior) ──
      const byType = new Map<string, any[]>()
      for (const node of data.nodes) {
        if (node.x == null) continue
        const list = byType.get(node.type) ?? []
        list.push(node)
        byType.set(node.type, list)
      }

      for (const [type, group] of byType) {
        if (group.length < CLUSTER_MIN_NODES) continue

        const cx = group.reduce((s: number, n: any) => s + n.x, 0) / group.length
        const cy = group.reduce((s: number, n: any) => s + n.y, 0) / group.length
        const cz = group.reduce((s: number, n: any) => s + n.z, 0) / group.length

        const maxDist = Math.max(
          ...group.map((n: any) => Math.sqrt(
            (n.x - cx) ** 2 + (n.y - cy) ** 2 + (n.z - cz) ** 2
          ))
        )
        const haloRadius = Math.max(maxDist + 15, 25)

        const color = TYPE_COLORS[type] ?? DEFAULT_COLOR

        const label = makeDomainLabel(
          TYPE_LABELS[type] ?? type.toUpperCase(),
          group.length,
          color,
        )
        label.position.set(cx, cy - haloRadius - 5, cz)
        scene.add(label)
        clusterVisuals.push(label)
      }
    }
  }, settleMs)
}
