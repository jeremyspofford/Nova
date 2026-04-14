import { useBoard } from "../../hooks/useBoard"
import { Column } from "./Column"

export function Board() {
  const { data, isLoading, isError } = useBoard()

  if (isLoading) return <div className="board-loading">Loading board...</div>
  if (isError || !data) return <div className="board-error">Error loading board. Check API connection.</div>

  return (
    <div className="board-columns">
      {data.columns.map(col => (
        <Column
          key={col.id}
          column={col}
          tasks={data.tasks_by_column[col.id] ?? []}
        />
      ))}
    </div>
  )
}
