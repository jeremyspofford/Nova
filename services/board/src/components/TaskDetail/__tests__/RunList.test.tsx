import { it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { RunList } from "../RunList"
import type { Run } from "../../../api/types"

const run: Run = {
  id: "r1",
  tool_name: "bash",
  status: "success",
  started_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:00:05Z",
  error: null,
}

it("renders tool_name and status", () => {
  render(<RunList runs={[run]} />)
  expect(screen.getByText("bash")).toBeInTheDocument()
  expect(screen.getByText("success")).toBeInTheDocument()
})

it("renders empty state when no runs", () => {
  render(<RunList runs={[]} />)
  expect(screen.getByText(/no runs/i)).toBeInTheDocument()
})

it("renders error text when run has error", () => {
  render(<RunList runs={[{ ...run, status: "error", error: "timeout" }]} />)
  expect(screen.getByText("timeout")).toBeInTheDocument()
})
