import { it, expect, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FilterBar } from "../FilterBar"
import { useUIStore } from "../../../stores/uiStore"

beforeEach(() => {
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {} })
})

it("renders status filter select", () => {
  render(<FilterBar />)
  expect(screen.getByLabelText(/status/i)).toBeInTheDocument()
})

it("selecting a status updates the store", async () => {
  render(<FilterBar />)
  await userEvent.selectOptions(screen.getByLabelText(/status/i), "running")
  expect(useUIStore.getState().activeFilters.status).toBe("running")
})

it("selecting empty status clears the filter", async () => {
  useUIStore.setState({ activeFilters: { status: "running" }, selectedTaskId: null, toast: null })
  render(<FilterBar />)
  await userEvent.selectOptions(screen.getByLabelText(/status/i), "")
  expect(useUIStore.getState().activeFilters.status).toBeUndefined()
})
