import { it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { TaskDetail } from "../TaskDetail"
import { useUIStore } from "../../../stores/uiStore"
import * as taskHooks from "../../../hooks/useTask"
import * as approvalHooks from "../../../hooks/useApproval"

vi.mock("../../../hooks/useTask")
vi.mock("../../../hooks/useApproval")

const mockUseTask = vi.mocked(taskHooks.useTask)
const mockUseApproval = vi.mocked(approvalHooks.useApproval)

function makeWrapper() {
  const qc = new QueryClient()
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

const mockTask = {
  id: "t1", title: "Deploy", description: "Deploy to prod", goal: null, status: "running",
  origin_event_id: null, board_column_id: "col-running", owner_type: null, owner_id: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", due_at: null,
  priority: "normal", risk_class: "low", approval_required: false, last_decision: "none",
  next_check_at: null, result_summary: null, labels: [], metadata: {},
}

beforeEach(() => {
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
  mockUseApproval.mockReturnValue({ data: undefined, isLoading: false } as any)
})

it("is not visible when no task selected", () => {
  mockUseTask.mockReturnValue({ task: { data: undefined, isLoading: false } as any, runs: { data: undefined } as any, pendingApprovalId: null })
  render(<TaskDetail />, { wrapper: makeWrapper() })
  const panel = document.querySelector(".detail-panel")
  expect(panel).not.toHaveClass("detail-panel--open")
})

it("becomes visible when a task is selected", () => {
  useUIStore.setState({ selectedTaskId: "t1", toast: null, activeFilters: {} })
  mockUseTask.mockReturnValue({
    task: { data: mockTask, isLoading: false } as any,
    runs: { data: { runs: [] } } as any,
    pendingApprovalId: null,
  })
  render(<TaskDetail />, { wrapper: makeWrapper() })
  expect(document.querySelector(".detail-panel--open")).toBeTruthy()
  expect(screen.getByText("Deploy")).toBeInTheDocument()
})

it("clicking close clears selectedTaskId", async () => {
  useUIStore.setState({ selectedTaskId: "t1", toast: null, activeFilters: {} })
  mockUseTask.mockReturnValue({
    task: { data: mockTask, isLoading: false } as any,
    runs: { data: { runs: [] } } as any,
    pendingApprovalId: null,
  })
  render(<TaskDetail />, { wrapper: makeWrapper() })
  await userEvent.click(screen.getByRole("button", { name: /close/i }))
  expect(useUIStore.getState().selectedTaskId).toBeNull()
})
