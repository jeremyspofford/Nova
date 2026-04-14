import type { Run } from "../../api/types"

interface RunListProps {
  runs: Run[]
}

export function RunList({ runs }: RunListProps) {
  if (runs.length === 0) {
    return <p className="run-list__empty">No runs yet.</p>
  }

  return (
    <ul className="run-list">
      {runs.map(run => (
        <li key={run.id} className={`run-item run-item--${run.status}`}>
          <span className="run-item__tool">{run.tool_name}</span>
          <span className="run-item__status">{run.status}</span>
          {run.started_at && (
            <span className="run-item__time">
              {new Date(run.started_at).toLocaleTimeString()}
            </span>
          )}
          {run.error && <span className="run-item__error">{run.error}</span>}
        </li>
      ))}
    </ul>
  )
}
