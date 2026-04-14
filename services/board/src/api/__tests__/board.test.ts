import { describe, it, expect, vi, beforeEach } from "vitest"
import * as client from "../client"
import { getBoard, moveTask } from "../board"

vi.mock("../client")
const mockFetch = vi.mocked(client.apiFetch)

beforeEach(() => mockFetch.mockReset())

describe("getBoard", () => {
  it("calls GET /board with no filters", async () => {
    mockFetch.mockResolvedValue({ columns: [], tasks_by_column: {} })
    await getBoard()
    expect(mockFetch).toHaveBeenCalledWith("/board")
  })

  it("appends filter query params", async () => {
    mockFetch.mockResolvedValue({ columns: [], tasks_by_column: {} })
    await getBoard({ status: "running", labels: ["infra", "ci"] })
    const url = mockFetch.mock.calls[0][0] as string
    expect(url).toContain("status=running")
    expect(url).toContain("labels=infra")
    expect(url).toContain("labels=ci")
  })
})

describe("moveTask", () => {
  it("calls PATCH /board/tasks/{id} with correct body", async () => {
    mockFetch.mockResolvedValue({ id: "t1", board_column_id: "col-done" })
    await moveTask("t1", "col-done")
    expect(mockFetch).toHaveBeenCalledWith("/board/tasks/t1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board_column_id: "col-done" }),
    })
  })
})
