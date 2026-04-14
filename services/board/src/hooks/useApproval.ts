import { useQuery } from "@tanstack/react-query"
import { getApproval } from "../api/approvals"

export function useApproval(approvalId: string | null) {
  return useQuery({
    queryKey: ["approval", approvalId],
    queryFn: () => getApproval(approvalId!),
    enabled: !!approvalId,
  })
}
