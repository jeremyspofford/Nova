import { describe, it, expect, vi, beforeEach } from "vitest"
import * as client from "../client"
import { getTask, getRuns, patchTask } from "../tasks"

vi.mock("../client")
const mockFetch = vi.mocked(client.apiFetch)

beforeEach(() => mockFetch.mockReset())

it("getTask calls GET /tasks/{id}", async () => {
  mockFetch.mockResolvedValue({ id: "t1", title: "test" })
  await getTask("t1")
  expect(mockFetch).toHaveBeenCalledWith("/tasks/t1")
})

it("getRuns calls GET /tasks/{id}/runs", async () => {
  mockFetch.mockResolvedValue({ runs: [] })
  await getRuns("t1")
  expect(mockFetch).toHaveBeenCalledWith("/tasks/t1/runs")
})

it("patchTask calls PATCH /tasks/{id} with body", async () => {
  mockFetch.mockResolvedValue({ id: "t1", status: "done" })
  await patchTask("t1", { status: "done" })
  expect(mockFetch).toHaveBeenCalledWith("/tasks/t1", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "done" }),
  })
})
