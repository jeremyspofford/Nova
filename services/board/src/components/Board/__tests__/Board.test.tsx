import { it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { Board } from "../Board"
import * as hooks from "../../../hooks/useBoard"
import { useUIStore } from "../../../stores/uiStore"

vi.mock("../../../hooks/useBoard")
const mockUseBoard = vi.mocked(hooks.useBoard)

function makeWrapper() {
  const qc = new QueryClient()
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => {
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
})

it("renders 8 columns from board data", () => {
  const columns = [
    { id: "col-inbox", name: "Inbox", order: 1, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-ready", name: "Ready", order: 2, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-running", name: "Running", order: 3, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-waiting", name: "Waiting", order: 4, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-approval", name: "Needs Approval", order: 5, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-done", name: "Done", order: 6, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-failed", name: "Failed", order: 7, work_in_progress_limit: null, status_filter: null, description: null },
    { id: "col-cancelled", name: "Cancelled", order: 8, work_in_progress_limit: null, status_filter: null, description: null },
  ]
  mockUseBoard.mockReturnValue({
    data: { columns, tasks_by_column: Object.fromEntries(columns.map(c => [c.id, []])) },
    isLoading: false,
    isError: false,
    error: null,
  } as any)

  render(<Board />, { wrapper: makeWrapper() })
  expect(screen.getByText("Inbox")).toBeInTheDocument()
  expect(screen.getByText("Needs Approval")).toBeInTheDocument()
  expect(screen.getByText("Cancelled")).toBeInTheDocument()
})

it("shows loading state", () => {
  mockUseBoard.mockReturnValue({ isLoading: true, isError: false, data: undefined, error: null } as any)
  render(<Board />, { wrapper: makeWrapper() })
  expect(screen.getByText(/loading/i)).toBeInTheDocument()
})

it("shows error state", () => {
  mockUseBoard.mockReturnValue({ isLoading: false, isError: true, data: undefined, error: new Error("fail") } as any)
  render(<Board />, { wrapper: makeWrapper() })
  expect(screen.getByText(/error/i)).toBeInTheDocument()
})
