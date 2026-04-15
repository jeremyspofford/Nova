import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { useSettingsStore } from "../settingsStore"

function resetStore() {
  localStorage.clear()
  useSettingsStore.setState({
    theme: "system",
    layoutMode: "split",
    chatSide: "left",
  })
  document.documentElement.removeAttribute("data-theme")
}

beforeEach(resetStore)
afterEach(resetStore)

it("has correct defaults", () => {
  const s = useSettingsStore.getState()
  expect(s.theme).toBe("system")
  expect(s.layoutMode).toBe("split")
  expect(s.chatSide).toBe("left")
})

it("setTheme('dark') applies data-theme=dark to <html>", () => {
  useSettingsStore.getState().setTheme("dark")
  expect(document.documentElement.dataset.theme).toBe("dark")
})

it("setTheme('light') applies data-theme=light to <html>", () => {
  useSettingsStore.getState().setTheme("light")
  expect(document.documentElement.dataset.theme).toBe("light")
})

it("setTheme('system') removes data-theme attribute", () => {
  document.documentElement.dataset.theme = "dark"
  useSettingsStore.getState().setTheme("system")
  expect(document.documentElement.dataset.theme).toBeUndefined()
})

it("setLayoutMode updates layoutMode", () => {
  useSettingsStore.getState().setLayoutMode("tabbed")
  expect(useSettingsStore.getState().layoutMode).toBe("tabbed")
})

it("setChatSide updates chatSide", () => {
  useSettingsStore.getState().setChatSide("right")
  expect(useSettingsStore.getState().chatSide).toBe("right")
})
