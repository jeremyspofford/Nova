import { useUIStore } from "../../stores/uiStore"
import { Badge } from "../shared/Badge"
import type { Task } from "../../api/types"

interface TaskCardProps {
  task: Task
}

export function TaskCard({ task }: TaskCardProps) {
  const setSelectedTask = useUIStore(s => s.setSelectedTask)
  const needsApproval = task.approval_required && task.status === "needs_approval"

  return (
    <article
      className={`task-card${needsApproval ? " task-card--approval" : ""}`}
      onClick={() => setSelectedTask(task.id)}
      role="article"
      tabIndex={0}
      onKeyDown={e => e.key === "Enter" && setSelectedTask(task.id)}
    >
      <div className="task-card__title">{task.title}</div>

      <div className="task-card__badges">
        <Badge type="status" value={task.status} />
        <Badge type="priority" value={task.priority} />
        {task.risk_class !== "low" && <Badge type="risk" value={task.risk_class} />}
        {task.labels.map(l => (
          <Badge key={l} type="label" value={l} />
        ))}
      </div>

      {needsApproval && (
        <div className="task-card__approval-warning">approval needed</div>
      )}
    </article>
  )
}
