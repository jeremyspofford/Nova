import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, beforeEach } from "vitest"
import { MemoryRouter } from "react-router-dom"
import { createElement } from "react"
import { Settings } from "../Settings"
import { useSettingsStore } from "../../../stores/settingsStore"

function makeWrapper() {
  return ({ children }: { children: React.ReactNode }) =>
    createElement(MemoryRouter, {}, children)
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ theme: "system", layoutMode: "split", chatSide: "left" })
})

it("renders all three setting rows", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  expect(screen.getByText("Theme")).toBeInTheDocument()
  expect(screen.getByText("Mode")).toBeInTheDocument()
  expect(screen.getByText("Chat side")).toBeInTheDocument()
})

it("clicking Dark theme button updates settingsStore", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /^dark$/i }))
  expect(useSettingsStore.getState().theme).toBe("dark")
})

it("clicking Tabbed mode button updates settingsStore", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /^tabbed$/i }))
  expect(useSettingsStore.getState().layoutMode).toBe("tabbed")
})

it("clicking Right chat side button updates settingsStore", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /^right$/i }))
  expect(useSettingsStore.getState().chatSide).toBe("right")
})

it("chat side row is dimmed when mode is tabbed", () => {
  useSettingsStore.setState({ theme: "system", layoutMode: "tabbed", chatSide: "left" })
  render(<Settings />, { wrapper: makeWrapper() })
  const chatSideRow = screen.getByText("Chat side").closest(".settings-row")
  expect(chatSideRow).toHaveClass("settings-row--dimmed")
})

it("back link points to /", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/")
})
