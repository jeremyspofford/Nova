import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { ChatPanel } from "../ChatPanel"
import { useChatStore } from "../../../stores/chatStore"
import * as chatApi from "../../../api/chat"

vi.mock("../../../api/chat")

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => {
  localStorage.clear()
  useChatStore.setState({ conversationId: "c1", streamingContent: "", isStreaming: false })
  vi.mocked(chatApi.getMessages).mockResolvedValue({ messages: [] })
})

it("renders the chat region", () => {
  render(<ChatPanel />, { wrapper: makeWrapper() })
  expect(screen.getByRole("region", { name: /chat/i })).toBeInTheDocument()
})

it("renders message bubbles from query data", async () => {
  vi.mocked(chatApi.getMessages).mockResolvedValue({
    messages: [{ id: "m1", role: "assistant", content: "Hello", created_at: "" }],
  })
  render(<ChatPanel />, { wrapper: makeWrapper() })
  expect(await screen.findByText("Hello")).toBeInTheDocument()
})

it("shows streaming bubble while isStreaming", () => {
  useChatStore.setState({ conversationId: "c1", streamingContent: "typing...", isStreaming: true })
  render(<ChatPanel />, { wrapper: makeWrapper() })
  expect(screen.getByText("typing...")).toBeInTheDocument()
})
