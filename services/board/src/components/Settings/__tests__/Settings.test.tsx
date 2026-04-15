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
  useSettingsStore.setState({ theme: "system" })
})

it("renders the theme setting row", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  expect(screen.getByText("Theme")).toBeInTheDocument()
})

it("clicking Dark updates settingsStore", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /^dark$/i }))
  expect(useSettingsStore.getState().theme).toBe("dark")
})

it("clicking Light updates settingsStore", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /^light$/i }))
  expect(useSettingsStore.getState().theme).toBe("light")
})

it("back link points to /", () => {
  render(<Settings />, { wrapper: makeWrapper() })
  expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/")
})
