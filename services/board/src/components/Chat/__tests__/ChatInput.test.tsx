import { render, screen, fireEvent } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, it, expect, vi } from "vitest"
import { ChatInput } from "../ChatInput"

it("renders textarea and send button", () => {
  render(<ChatInput onSend={vi.fn()} disabled={false} />)
  expect(screen.getByRole("textbox")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /send/i })).toBeInTheDocument()
})

it("calls onSend with content when button clicked", async () => {
  const onSend = vi.fn()
  render(<ChatInput onSend={onSend} disabled={false} />)
  await userEvent.type(screen.getByRole("textbox"), "hello")
  fireEvent.click(screen.getByRole("button", { name: /send/i }))
  expect(onSend).toHaveBeenCalledWith("hello")
})

it("clears input after send", async () => {
  const onSend = vi.fn()
  render(<ChatInput onSend={onSend} disabled={false} />)
  await userEvent.type(screen.getByRole("textbox"), "hello")
  fireEvent.click(screen.getByRole("button", { name: /send/i }))
  expect(screen.getByRole("textbox")).toHaveValue("")
})

it("does not call onSend when input is empty", () => {
  const onSend = vi.fn()
  render(<ChatInput onSend={onSend} disabled={false} />)
  fireEvent.click(screen.getByRole("button", { name: /send/i }))
  expect(onSend).not.toHaveBeenCalled()
})

it("send button is disabled when disabled=true", () => {
  render(<ChatInput onSend={vi.fn()} disabled={true} />)
  expect(screen.getByRole("button", { name: /send/i })).toBeDisabled()
})

it("Enter key sends message", async () => {
  const onSend = vi.fn()
  render(<ChatInput onSend={onSend} disabled={false} />)
  const textarea = screen.getByRole("textbox")
  await userEvent.type(textarea, "hello{Enter}")
  expect(onSend).toHaveBeenCalledWith("hello")
})

it("Shift+Enter adds newline without sending", async () => {
  const onSend = vi.fn()
  render(<ChatInput onSend={onSend} disabled={false} />)
  const textarea = screen.getByRole("textbox")
  await userEvent.type(textarea, "hello{Shift>}{Enter}{/Shift}")
  expect(onSend).not.toHaveBeenCalled()
})
