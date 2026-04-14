import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, act } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { ApprovalBanner } from "../ApprovalBanner"
import * as approvalsApi from "../../../api/approvals"
import type { ApprovalRead } from "../../../api/types"

vi.mock("../../../api/approvals")
const mockRespond = vi.mocked(approvalsApi.respondToApproval)

const approval: ApprovalRead = {
  id: "a1",
  task_id: "t1",
  requested_by: "nova-lite",
  requested_at: "2026-01-01T00:00:00Z",
  summary: "Run shell command",
  consequence: "Will delete files",
  options: ["approve", "deny"],
  status: "pending",
  decided_by: null,
  decided_at: null,
  decision: null,
  reason: null,
}

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      // gcTime: Infinity prevents TanStack Query's mutation GC timer from firing
      // asynchronously after test teardown, which would cause spurious unhandled
      // rejections to be attributed to subsequent tests in vitest's worker thread
      mutations: { gcTime: Infinity },
    },
  })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

// vi.clearAllMocks() (not mockReset) preserves the spy object identity while clearing
// call history. mockReset() resets the implementation to () => void 0, which leaves
// tinyspy's async result-tracking callbacks in flight across test boundaries and causes
// vitest to misattribute the next test's mutation rejection as unhandled.
beforeEach(() => vi.clearAllMocks())

it("renders summary and consequence", () => {
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  expect(screen.getByText("Run shell command")).toBeInTheDocument()
  expect(screen.getByText("Will delete files")).toBeInTheDocument()
})

it("renders approve and deny buttons", () => {
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /deny/i })).toBeInTheDocument()
})

it("calls respondToApproval with approve on Approve click", async () => {
  mockRespond.mockResolvedValue({ ...approval, status: "approved", decision: "approve" })
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  await userEvent.click(screen.getByRole("button", { name: /approve/i }))
  expect(mockRespond).toHaveBeenCalledWith("a1", "approve", "user", undefined)
  // Wait for mutation to complete so TanStack Query async callbacks don't bleed into next test
  await waitFor(() => expect(screen.getByRole("button", { name: /approve/i })).not.toBeDisabled())
})

it("disables buttons while mutation is pending", async () => {
  let resolveHang!: (v: typeof approval) => void
  const hangPromise = new Promise<typeof approval>(res => { resolveHang = res })
  mockRespond.mockImplementation(() => hangPromise)
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  await userEvent.click(screen.getByRole("button", { name: /approve/i }))
  expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled()
  expect(screen.getByRole("button", { name: /deny/i })).toBeDisabled()
  // Resolve the pending promise and wait for mutation to fully complete before test cleanup
  resolveHang({ ...approval, status: "approved", decision: "approve" })
  await hangPromise
  await waitFor(() => expect(screen.getByRole("button", { name: /approve/i })).not.toBeDisabled())
})

it("shows retry button on error", async () => {
  mockRespond.mockImplementation(() => Promise.reject(new Error("network error")))
  render(<ApprovalBanner approval={approval} taskId="t1" />, { wrapper: makeWrapper() })
  await userEvent.click(screen.getByRole("button", { name: /approve/i }))
  await waitFor(() => expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument())
})
