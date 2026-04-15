import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { ChatPanel } from "../ChatPanel"
import { useUIStore } from "../../../stores/uiStore"
import { useChatStore } from "../../../stores/chatStore"
import * as chatApi from "../../../api/chat"

vi.mock("../../../api/chat")

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => {
  useUIStore.setState({ chatOpen: true, selectedTaskId: null, toast: null, activeFilters: {} })
  useChatStore.setState({ conversationId: "c1", streamingContent: "", isStreaming: false })
  vi.mocked(chatApi.getMessages).mockResolvedValue({ messages: [] })
  vi.mocked(chatApi.createConversation).mockResolvedValue({
    id: "c1", title: "New Chat", created_at: "", updated_at: "", message_count: 0,
  })
})

it("renders chat panel when chatOpen=true", () => {
  render(<ChatPanel />, { wrapper: makeWrapper() })
  expect(screen.getByRole("region", { name: /chat/i })).toBeInTheDocument()
})

it("does not render content when chatOpen=false", () => {
  useUIStore.setState({ chatOpen: false, selectedTaskId: null, toast: null, activeFilters: {} })
  render(<ChatPanel />, { wrapper: makeWrapper() })
  expect(screen.queryByRole("region", { name: /chat/i })).not.toBeInTheDocument()
})

it("close button toggles chatOpen off", () => {
  render(<ChatPanel />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /close/i }))
  expect(useUIStore.getState().chatOpen).toBe(false)
})
