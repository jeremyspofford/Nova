import { useQuery } from "@tanstack/react-query"
import { getTask, getRuns } from "../api/tasks"
import { getTaskApprovals } from "../api/approvals"

export function useTask(id: string | null) {
  const task = useQuery({
    queryKey: ["task", id],
    queryFn: () => getTask(id!),
    enabled: !!id,
  })

  const runs = useQuery({
    queryKey: ["runs", id],
    queryFn: () => getRuns(id!),
    enabled: !!id,
  })

  const taskData = task.data
  const hasPendingApproval =
    !!taskData && taskData.approval_required && taskData.status === "needs_approval"

  const pendingApprovalQuery = useQuery({
    queryKey: ["task-approvals", id],
    queryFn: async () => {
      const approvals = await getTaskApprovals(id!)
      return approvals.find(a => a.status === "pending")?.id ?? null
    },
    enabled: hasPendingApproval,
  })

  return {
    task,
    runs,
    pendingApprovalId: pendingApprovalQuery.data ?? null,
  }
}
