import { TaskCard } from "./TaskCard"
import type { BoardColumn, Task } from "../../api/types"

interface ColumnProps {
  column: BoardColumn
  tasks: Task[]
}

export function Column({ column, tasks }: ColumnProps) {
  const atLimit = column.work_in_progress_limit !== null && tasks.length >= column.work_in_progress_limit

  return (
    <div className="column">
      <div className="column__header">
        <span className="column__name">{column.name}</span>
        <span className={`column__count${atLimit ? " column__count--limit" : ""}`}>
          {tasks.length}
          {column.work_in_progress_limit !== null && `/${column.work_in_progress_limit}`}
        </span>
      </div>
      <div className="column__cards">
        {tasks.map(task => (
          <TaskCard key={task.id} task={task} />
        ))}
      </div>
    </div>
  )
}
