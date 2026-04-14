import { it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { Column } from "../Column"
import type { BoardColumn, Task } from "../../../api/types"

const col: BoardColumn = {
  id: "col-inbox",
  name: "Inbox",
  order: 1,
  work_in_progress_limit: null,
  status_filter: null,
  description: "New tasks",
}

const task: Task = {
  id: "t1", title: "Task A", description: null, goal: null, status: "pending",
  origin_event_id: null, board_column_id: "col-inbox", owner_type: null, owner_id: null,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", due_at: null,
  priority: "normal", risk_class: "low", approval_required: false, last_decision: "none",
  next_check_at: null, result_summary: null, labels: [], metadata: {},
}

it("renders column name", () => {
  render(<Column column={col} tasks={[]} />)
  expect(screen.getByText("Inbox")).toBeInTheDocument()
})

it("renders task count", () => {
  render(<Column column={col} tasks={[task]} />)
  expect(screen.getByText("1")).toBeInTheDocument()
})

it("renders WIP limit pill when set", () => {
  render(<Column column={{ ...col, work_in_progress_limit: 3 }} tasks={[]} />)
  expect(screen.getByText("0/3")).toBeInTheDocument()
})

it("renders each task card", () => {
  render(<Column column={col} tasks={[task]} />)
  expect(screen.getByText("Task A")).toBeInTheDocument()
})
