import { useUIStore } from "../../stores/uiStore"

const STATUS_OPTIONS = ["", "pending", "ready", "running", "needs_approval", "done", "failed", "cancelled"]
const PRIORITY_OPTIONS = ["", "low", "normal", "high", "critical"]
const RISK_OPTIONS = ["", "low", "medium", "high"]

export function FilterBar() {
  const { activeFilters, setFilters } = useUIStore(s => ({
    activeFilters: s.activeFilters,
    setFilters: s.setFilters,
  }))

  function update(key: string, value: string) {
    const next = { ...activeFilters }
    if (value) {
      (next as Record<string, string>)[key] = value
    } else {
      delete (next as Record<string, string>)[key]
    }
    setFilters(next)
  }

  return (
    <div className="filter-bar" role="search">
      <label>
        Status
        <select
          aria-label="Status"
          value={activeFilters.status ?? ""}
          onChange={e => update("status", e.target.value)}
        >
          {STATUS_OPTIONS.map(o => (
            <option key={o} value={o}>{o || "All"}</option>
          ))}
        </select>
      </label>

      <label>
        Priority
        <select
          aria-label="Priority"
          value={activeFilters.priority ?? ""}
          onChange={e => update("priority", e.target.value)}
        >
          {PRIORITY_OPTIONS.map(o => (
            <option key={o} value={o}>{o || "All"}</option>
          ))}
        </select>
      </label>

      <label>
        Risk
        <select
          aria-label="Risk"
          value={activeFilters.risk_class ?? ""}
          onChange={e => update("risk_class", e.target.value)}
        >
          {RISK_OPTIONS.map(o => (
            <option key={o} value={o}>{o || "All"}</option>
          ))}
        </select>
      </label>
    </div>
  )
}
