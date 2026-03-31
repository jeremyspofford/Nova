// ── HUD Widgets for Living Observatory ──────────────────────────────────────
// Fixed-position glass panels overlaying the 3D brain graph.
// SystemStatusWidget: bottom-left — health indicator + consolidation progress ring
// ActiveTopicsWidget: top-left — cluster topic pills

// ── Types ────────────────────────────────────────────────────────────────────
// These mirror the shapes already used in Brain.tsx for engram stats and clusters.

interface EngramStats {
  total_engrams: number
  total_edges: number
  total_archived: number
  by_type: Record<string, { total: number; superseded: number }>
}

interface ClusterInfo {
  id: number
  label: string
  count: number
}

// ── Glass panel base classes ────────────────────────────────────────────────
// Matches the design tokens from the Living Observatory finalized spec:
// --glass-bg: rgba(12,10,9,0.88), --glass-border: rgba(68,64,60,0.55), --glass-blur: 20px

const glassPanel = [
  'z-10 rounded-xl',
  'bg-[rgba(12,10,9,0.88)] backdrop-blur-[20px]',
  'border border-[rgba(68,64,60,0.55)]',
  'shadow-[0_4px_24px_rgba(0,0,0,0.25),inset_0_1px_0_rgba(250,250,249,0.03)]',
].join(' ')

// ── SystemStatusWidget ──────────────────────────────────────────────────────

export function SystemStatusWidget({ stats }: { stats?: EngramStats }) {
  // Derive consolidation percentage from archived vs total
  const total = stats?.total_engrams ?? 0
  const archived = stats?.total_archived ?? 0
  const typeCount = Object.keys(stats?.by_type ?? {}).length
  const consolidationPct = total > 0 ? Math.round(((total - archived) / total) * 100) : 0

  // SVG ring: circumference = 2 * pi * 45 ~= 283
  const circumference = 283
  const dashOffset = circumference - (circumference * consolidationPct) / 100

  return (
    <div
      className={`fixed bottom-5 left-5 w-[220px] p-3.5 px-4 ${glassPanel}`}
      role="region"
      aria-label="System status and consolidation"
    >
      {/* Health row */}
      <div className="flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        <span className="text-xs font-medium text-stone-300">Healthy</span>
        <span className="text-[11px] font-mono text-stone-500 ml-auto">
          {stats?.total_engrams?.toLocaleString() ?? '\u2014'} nodes
        </span>
      </div>

      {/* Divider */}
      <div className="h-px bg-[rgba(68,64,60,0.55)] my-2.5" />

      {/* Consolidation row */}
      <div className="flex items-center gap-3">
        {/* Progress ring */}
        <div className="relative w-12 h-12 shrink-0">
          <svg viewBox="0 0 100 100" className="w-12 h-12 -rotate-90">
            <circle
              cx="50" cy="50" r="45" fill="none"
              stroke="rgb(68,64,60)" strokeWidth="4"
            />
            <circle
              cx="50" cy="50" r="45" fill="none"
              stroke="rgb(25,168,158)" strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              className="transition-[stroke-dashoffset] duration-1000"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center
                          text-sm font-semibold font-mono text-stone-200">
            {consolidationPct}%
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-stone-400 mb-1">
            Consolidation
          </div>
          <div className="text-[11px] font-mono text-stone-400 space-y-0.5">
            <div>{stats?.total_engrams?.toLocaleString() ?? '\u2014'} processed</div>
            <div>{typeCount} types</div>
          </div>
          <div className="text-[10px] text-stone-500 mt-1">
            {stats?.total_edges?.toLocaleString() ?? '\u2014'} edges
          </div>
        </div>
      </div>
    </div>
  )
}

// ── ActiveTopicsWidget ──────────────────────────────────────────────────────

export function ActiveTopicsWidget({ clusters }: { clusters: ClusterInfo[] }) {
  const top = clusters.slice(0, 6)
  if (top.length === 0) return null

  return (
    <div
      className={`fixed top-16 left-5 max-w-[220px] p-3 ${glassPanel}`}
      role="region"
      aria-label="Active topics"
    >
      <div className="text-[10px] font-semibold uppercase tracking-widest text-stone-400 mb-2">
        Active Topics
      </div>
      <div className="flex flex-wrap gap-[5px]">
        {top.map((c, i) => (
          <span
            key={c.id}
            className={`text-[11px] font-medium px-2.5 py-1 rounded-xl
              ${i < 3
                ? 'bg-teal-500/15 text-teal-400'
                : 'bg-stone-700 text-stone-400'}`}
          >
            {c.label} {c.count}
          </span>
        ))}
      </div>
    </div>
  )
}
