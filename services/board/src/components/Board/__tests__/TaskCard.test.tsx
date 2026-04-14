import { it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { TaskCard } from "../TaskCard"
import { useUIStore } from "../../../stores/uiStore"
import type { Task } from "../../../api/types"

const baseTask: Task = {
  id: "t1",
  title: "Deploy to staging",
  description: null,
  goal: null,
  status: "pending",
  origin_event_id: null,
  board_column_id: "col-inbox",
  owner_type: null,
  owner_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  due_at: null,
  priority: "normal",
  risk_class: "low",
  approval_required: false,
  last_decision: "none",
  next_check_at: null,
  result_summary: null,
  labels: [],
  metadata: {},
}

beforeEach(() => {
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
})

it("renders the task title", () => {
  render(<TaskCard task={baseTask} />)
  expect(screen.getByText("Deploy to staging")).toBeInTheDocument()
})

it("renders status badge", () => {
  render(<TaskCard task={baseTask} />)
  expect(screen.getByText("pending")).toBeInTheDocument()
})

it("renders priority badge", () => {
  render(<TaskCard task={{ ...baseTask, priority: "high" }} />)
  expect(screen.getByText("high")).toBeInTheDocument()
})

it("shows approval warning when task needs approval", () => {
  render(<TaskCard task={{ ...baseTask, approval_required: true, status: "needs_approval" }} />)
  expect(screen.getByText("approval needed")).toBeInTheDocument()
})

it("does not show approval warning when approval_required is false", () => {
  render(<TaskCard task={baseTask} />)
  expect(screen.queryByText(/approval needed/i)).not.toBeInTheDocument()
})

it("clicking the card sets selectedTaskId in the store", async () => {
  render(<TaskCard task={baseTask} />)
  await userEvent.click(screen.getByRole("article"))
  expect(useUIStore.getState().selectedTaskId).toBe("t1")
})

it("renders labels as badges", () => {
  render(<TaskCard task={{ ...baseTask, labels: ["ci", "infra"] }} />)
  expect(screen.getByText("ci")).toBeInTheDocument()
  expect(screen.getByText("infra")).toBeInTheDocument()
})
