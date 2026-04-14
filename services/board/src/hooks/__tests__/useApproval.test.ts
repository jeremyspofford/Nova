import { it, expect, vi, beforeEach } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { useApproval } from "../useApproval"
import * as approvalsApi from "../../api/approvals"

vi.mock("../../api/approvals")
const mockGetApproval = vi.mocked(approvalsApi.getApproval)

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => mockGetApproval.mockReset())

it("does not fetch when approvalId is null", () => {
  const { result } = renderHook(() => useApproval(null), { wrapper: makeWrapper() })
  expect(result.current.fetchStatus).toBe("idle")
  expect(mockGetApproval).not.toHaveBeenCalled()
})

it("fetches approval when approvalId is provided", async () => {
  mockGetApproval.mockResolvedValue({ id: "a1", status: "pending" } as any)
  const { result } = renderHook(() => useApproval("a1"), { wrapper: makeWrapper() })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(mockGetApproval).toHaveBeenCalledWith("a1")
})
