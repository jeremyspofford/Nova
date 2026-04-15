import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { MessageBubble } from "../MessageBubble"

it("renders user message with role badge", () => {
  render(<MessageBubble role="user" content="Hello" />)
  expect(screen.getByText("Hello")).toBeInTheDocument()
  expect(screen.getByText(/you/i)).toBeInTheDocument()
})

it("renders assistant message with role badge", () => {
  render(<MessageBubble role="assistant" content="Hi there" />)
  expect(screen.getByText("Hi there")).toBeInTheDocument()
  expect(screen.getByText(/nova/i)).toBeInTheDocument()
})

it("renders streaming bubble when content is empty string and streaming=true", () => {
  render(<MessageBubble role="assistant" content="" streaming={true} />)
  expect(document.querySelector(".message-bubble--streaming")).toBeInTheDocument()
})
