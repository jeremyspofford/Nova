import { apiFetch } from "./client"
import type { ApprovalRead } from "./types"

export function getApproval(id: string): Promise<ApprovalRead> {
  return apiFetch<ApprovalRead>(`/approvals/${id}`)
}

export function getTaskApprovals(taskId: string): Promise<ApprovalRead[]> {
  return apiFetch<ApprovalRead[]>(`/tasks/${taskId}/approvals`)
}

export function respondToApproval(
  id: string,
  decision: string,
  decidedBy: string,
  reason?: string,
): Promise<ApprovalRead> {
  return apiFetch<ApprovalRead>(`/approvals/${id}/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, decided_by: decidedBy, reason }),
  })
}
