import { describe, it, expect, vi, beforeEach } from "vitest"
import * as client from "../client"
import { getApproval, getTaskApprovals, respondToApproval } from "../approvals"

vi.mock("../client")
const mockFetch = vi.mocked(client.apiFetch)

beforeEach(() => mockFetch.mockReset())

it("getApproval calls GET /approvals/{id}", async () => {
  mockFetch.mockResolvedValue({ id: "a1", status: "pending" })
  await getApproval("a1")
  expect(mockFetch).toHaveBeenCalledWith("/approvals/a1")
})

it("getTaskApprovals calls GET /tasks/{id}/approvals", async () => {
  mockFetch.mockResolvedValue([])
  await getTaskApprovals("t1")
  expect(mockFetch).toHaveBeenCalledWith("/tasks/t1/approvals")
})

it("respondToApproval calls POST /approvals/{id}/respond with body", async () => {
  mockFetch.mockResolvedValue({ id: "a1", status: "approved" })
  await respondToApproval("a1", "approve", "user", "all good")
  expect(mockFetch).toHaveBeenCalledWith("/approvals/a1/respond", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: "approve", decided_by: "user", reason: "all good" }),
  })
})
