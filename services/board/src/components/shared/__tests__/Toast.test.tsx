import { it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Toast } from "../Toast"

it("renders message text", () => {
  render(<Toast message="something failed" onDismiss={() => {}} />)
  expect(screen.getByText("something failed")).toBeInTheDocument()
})

it("calls onDismiss when dismiss button is clicked", async () => {
  const onDismiss = vi.fn()
  render(<Toast message="err" onDismiss={onDismiss} />)
  await userEvent.click(screen.getByRole("button"))
  expect(onDismiss).toHaveBeenCalledTimes(1)
})
