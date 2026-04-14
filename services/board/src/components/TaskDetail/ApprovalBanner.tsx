import { useMutation, useQueryClient } from "@tanstack/react-query"
import { respondToApproval } from "../../api/approvals"
import type { ApprovalRead } from "../../api/types"

interface ApprovalBannerProps {
  approval: ApprovalRead
  taskId: string
}

export function ApprovalBanner({ approval, taskId }: ApprovalBannerProps) {
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: ({ decision }: { decision: string }) =>
      respondToApproval(approval.id, decision, "user", undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["board"] })
      queryClient.invalidateQueries({ queryKey: ["task", taskId] })
      queryClient.invalidateQueries({ queryKey: ["task-approvals", taskId] })
      queryClient.invalidateQueries({ queryKey: ["approval", approval.id] })
    },
    onError: () => {
      // Error is surfaced via mutation.isError — no rethrow needed
    },
  })

  const options = approval.options.length > 0 ? approval.options : ["approve", "deny"]

  return (
    <div className="approval-banner">
      <div className="approval-banner__summary">{approval.summary}</div>
      {approval.consequence && (
        <div className="approval-banner__consequence">{approval.consequence}</div>
      )}

      {mutation.isError && (
        <div className="approval-banner__error">
          Failed: {(mutation.error as Error).message}
          <button onClick={() => mutation.reset()} aria-label="Retry">Retry</button>
        </div>
      )}

      <div className="approval-banner__actions">
        {options.map(opt => (
          <button
            key={opt}
            className={`approval-btn approval-btn--${opt}`}
            disabled={mutation.isPending}
            onClick={() => mutation.mutate({ decision: opt })}
            aria-label={opt.charAt(0).toUpperCase() + opt.slice(1)}
          >
            {opt.charAt(0).toUpperCase() + opt.slice(1)}
          </button>
        ))}
      </div>
    </div>
  )
}
