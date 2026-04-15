import { describe, it, expect, vi, beforeEach } from "vitest"
import * as client from "../client"
import {
  getConversations,
  createConversation,
  getMessages,
} from "../chat"

vi.mock("../client")
const mockFetch = vi.mocked(client.apiFetch)

beforeEach(() => mockFetch.mockReset())

it("getConversations calls GET /conversations", async () => {
  mockFetch.mockResolvedValue({ conversations: [] })
  await getConversations()
  expect(mockFetch).toHaveBeenCalledWith("/conversations?limit=10")
})

it("getConversations passes custom limit", async () => {
  mockFetch.mockResolvedValue({ conversations: [] })
  await getConversations(5)
  expect(mockFetch).toHaveBeenCalledWith("/conversations?limit=5")
})

it("createConversation calls POST /conversations", async () => {
  mockFetch.mockResolvedValue({ id: "c1", title: "New Chat" })
  const result = await createConversation()
  expect(mockFetch).toHaveBeenCalledWith("/conversations", { method: "POST" })
  expect(result.id).toBe("c1")
})

it("getMessages calls GET /conversations/{id}/messages", async () => {
  mockFetch.mockResolvedValue({ messages: [] })
  await getMessages("c1")
  expect(mockFetch).toHaveBeenCalledWith("/conversations/c1/messages")
})
