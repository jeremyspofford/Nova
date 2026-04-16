import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { MessageBubble } from "../MessageBubble"

it("renders user message content", () => {
  render(<MessageBubble role="user" content="Hello" />)
  expect(screen.getByText("Hello")).toBeInTheDocument()
})

it("renders assistant message with avatar and content", () => {
  render(<MessageBubble role="assistant" content="Hi there" />)
  expect(screen.getByText("Hi there")).toBeInTheDocument()
  expect(screen.getByText("N")).toBeInTheDocument()
})

it("renders typing dots when streaming with no content yet", () => {
  render(<MessageBubble role="assistant" content="" streaming={true} />)
  expect(document.querySelector(".message-bubble--streaming")).toBeInTheDocument()
  expect(document.querySelector(".message-bubble__typing")).toBeInTheDocument()
})
