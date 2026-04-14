import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { Badge } from "../Badge"

describe("Badge", () => {
  it("renders the value as text", () => {
    render(<Badge type="status" value="running" />)
    expect(screen.getByText("running")).toBeInTheDocument()
  })

  it("applies type and value classes", () => {
    render(<Badge type="status" value="failed" />)
    const el = screen.getByText("failed")
    expect(el).toHaveClass("badge")
    expect(el).toHaveClass("badge--status")
    expect(el).toHaveClass("badge--failed")
  })

  it("renders each priority value", () => {
    const { rerender } = render(<Badge type="priority" value="low" />)
    expect(screen.getByText("low")).toBeInTheDocument()
    rerender(<Badge type="priority" value="high" />)
    expect(screen.getByText("high")).toBeInTheDocument()
    rerender(<Badge type="priority" value="critical" />)
    expect(screen.getByText("critical")).toBeInTheDocument()
  })

  it("renders each risk value", () => {
    render(<Badge type="risk" value="high" />)
    expect(screen.getByText("high")).toBeInTheDocument()
  })
})
