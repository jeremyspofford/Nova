import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, waitFor, act } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { useBoard } from "../useBoard"
import * as boardApi from "../../api/board"
import { useUIStore } from "../../stores/uiStore"

vi.mock("../../api/board")
const mockGetBoard = vi.mocked(boardApi.getBoard)

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => {
  mockGetBoard.mockReset()
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
})

it("calls getBoard on mount", async () => {
  mockGetBoard.mockResolvedValue({ columns: [], tasks_by_column: {} })
  const { result } = renderHook(() => useBoard(), { wrapper: makeWrapper() })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(mockGetBoard).toHaveBeenCalledTimes(1)
})

it("query key includes activeFilters so filter changes trigger refetch", async () => {
  mockGetBoard.mockResolvedValue({ columns: [], tasks_by_column: {} })
  const { result } = renderHook(() => useBoard(), { wrapper: makeWrapper() })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))

  mockGetBoard.mockResolvedValue({ columns: [], tasks_by_column: {} })
  act(() => {
    useUIStore.getState().setFilters({ status: "running" })
  })
  await waitFor(() => expect(mockGetBoard).toHaveBeenCalledTimes(2))
})
