import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { vi, beforeEach, it, expect } from "vitest"
import { ActivityFeed } from "../ActivityFeed"
import type { ActivityEntry } from "../../../api/types"

vi.mock("../../../api/activity", () => ({ getActivity: vi.fn() }))
import { getActivity } from "../../../api/activity"
const mockGet = getActivity as ReturnType<typeof vi.fn>

function entry(overrides: Partial<ActivityEntry> = {}): ActivityEntry {
  return {
    id: "r1",
    tool_name: "ha.light.turn_on",
    trigger_type: "chat",
    status: "succeeded",
    summary: "ha.light.turn_on → succeeded",
    input: { entity_id: "light.office" },
    output: '{"status": "ok"}',
    error: null,
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    ...overrides,
  }
}

beforeEach(() => {
  mockGet.mockResolvedValue({ entries: [], total: 0 })
})

it("shows empty state when no entries", async () => {
  render(<ActivityFeed />)
  await waitFor(() => expect(screen.getByText(/no activity yet/i)).toBeInTheDocument())
})

it("renders tool name, badge, status, and summary", async () => {
  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))
  expect(screen.getByText("ha.light.turn_on → succeeded")).toBeInTheDocument()
  expect(screen.getByText("chat")).toBeInTheDocument()
  expect(screen.getByText("succeeded")).toBeInTheDocument()
})

it("expands details on click", async () => {
  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))
  fireEvent.click(screen.getByRole("button", { name: /details/i }))
  expect(screen.getByText(/light\.office/)).toBeInTheDocument()
})

it("refresh button re-fetches", async () => {
  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))

  mockGet.mockResolvedValue({ entries: [], total: 0 })
  fireEvent.click(screen.getByRole("button", { name: /refresh/i }))
  await waitFor(() => screen.getByText(/no activity yet/i))
})

it("load more appends next page", async () => {
  const e1 = entry({ id: "r1", tool_name: "debug.echo" })
  const e2 = entry({ id: "r2", tool_name: "http.request" })
  mockGet.mockResolvedValueOnce({ entries: [e1], total: 2 })
  mockGet.mockResolvedValueOnce({ entries: [e2], total: 2 })

  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("debug.echo"))
  fireEvent.click(screen.getByRole("button", { name: /load more/i }))
  await waitFor(() => screen.getByText("http.request"))
  expect(screen.getByText("debug.echo")).toBeInTheDocument()
})

it("hides load more when all entries loaded", async () => {
  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))
  expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument()
})

it("renders running entry with running status", async () => {
  mockGet.mockResolvedValue({
    entries: [entry({ status: "running", finished_at: null })],
    total: 1,
  })
  render(<ActivityFeed />)
  await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument())
})

it("renders failed entry with error", async () => {
  mockGet.mockResolvedValue({
    entries: [entry({ status: "failed", error: "connection refused", output: null })],
    total: 1,
  })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))
  fireEvent.click(screen.getByRole("button", { name: /details/i }))
  expect(screen.getByText("connection refused")).toBeInTheDocument()
})

it("shows error state and retry re-fetches", async () => {
  mockGet.mockRejectedValueOnce(new Error("500"))
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText(/failed to load activity/i))

  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  fireEvent.click(screen.getByRole("button", { name: /retry/i }))
  await waitFor(() => screen.getByText("ha.light.turn_on"))
})
