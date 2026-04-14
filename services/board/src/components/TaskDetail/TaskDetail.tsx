import { useUIStore } from "../../stores/uiStore"
import { useTask } from "../../hooks/useTask"
import { useApproval } from "../../hooks/useApproval"
import { Badge } from "../shared/Badge"
import { RunList } from "./RunList"
import { ApprovalBanner } from "./ApprovalBanner"

export function TaskDetail() {
  const { selectedTaskId, setSelectedTask } = useUIStore(s => ({
    selectedTaskId: s.selectedTaskId,
    setSelectedTask: s.setSelectedTask,
  }))

  const { task, runs, pendingApprovalId } = useTask(selectedTaskId)
  const approval = useApproval(pendingApprovalId)

  const isOpen = !!selectedTaskId
  const taskData = task.data
  const runsData = runs.data?.runs ?? []

  return (
    <div className={`detail-panel${isOpen ? " detail-panel--open" : ""}`}>
      <div className="detail-panel__header">
        <span>{taskData?.title ?? "Loading…"}</span>
        <button
          className="detail-panel__close"
          onClick={() => setSelectedTask(null)}
          aria-label="Close"
        >
          &times;
        </button>
      </div>

      {taskData && (
        <div className="detail-panel__body">
          <div className="detail-panel__badges">
            <Badge type="status" value={taskData.status} />
            <Badge type="priority" value={taskData.priority} />
            <Badge type="risk" value={taskData.risk_class} />
          </div>

          {taskData.description && (
            <p className="detail-panel__description">{taskData.description}</p>
          )}

          {approval.data && (
            <ApprovalBanner approval={approval.data} taskId={taskData.id} />
          )}

          <section className="detail-panel__section">
            <h3>Run History</h3>
            <RunList runs={runsData} />
          </section>
        </div>
      )}
    </div>
  )
}
