import { render, screen, fireEvent } from "@testing-library/react"
import { vi, beforeEach, it, expect } from "vitest"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { AppShell } from "../../AppShell"
import { useUIStore } from "../../stores/uiStore"
import { useChatStore } from "../../stores/chatStore"
import { useSettingsStore } from "../../stores/settingsStore"

vi.mock("../../components/Activity/ActivityFeed", () => ({ ActivityFeed: () => <div data-testid="activity-feed" /> }))
vi.mock("../../components/Chat/ChatPanel", () => ({ ChatPanel: () => <div data-testid="chat-panel" /> }))
vi.mock("../../components/shared/Toast", () => ({ Toast: () => null }))
vi.mock("../../api/chat", () => ({
  createConversation: vi.fn().mockResolvedValue({ id: "c1", title: "New Chat", created_at: "", updated_at: "", message_count: 0 }),
}))

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(MemoryRouter, {}, createElement(QueryClientProvider, { client: qc }, children))
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ theme: "system" })
  useUIStore.setState({ toast: null, activeTab: "chat" })
  useChatStore.setState({ conversationId: null, streamingContent: "", isStreaming: false })
})

it("renders Chat tab and chat panel by default", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByTestId("chat-panel")).toBeInTheDocument()
  expect(screen.queryByTestId("activity-feed")).not.toBeInTheDocument()
})

it("renders Chat and Activity tab buttons", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByRole("button", { name: /chat/i })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /activity/i })).toBeInTheDocument()
})

it("clicking Activity tab shows activity feed and hides chat panel", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /activity/i }))
  expect(screen.getByTestId("activity-feed")).toBeInTheDocument()
  expect(screen.queryByTestId("chat-panel")).not.toBeInTheDocument()
})

it("settings gear link is present", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByRole("link", { name: /settings/i })).toBeInTheDocument()
})
