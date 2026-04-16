import { describe, it, expect, beforeEach } from "vitest"
import { useUIStore } from "../uiStore"

beforeEach(() => {
  useUIStore.setState({ toast: null, activeTab: "chat" })
})

it("setToast updates toast message", () => {
  useUIStore.getState().setToast("something went wrong")
  expect(useUIStore.getState().toast).toBe("something went wrong")
})

it("setToast(null) clears toast", () => {
  useUIStore.getState().setToast("msg")
  useUIStore.getState().setToast(null)
  expect(useUIStore.getState().toast).toBeNull()
})

it("setActiveTab updates activeTab", () => {
  useUIStore.getState().setActiveTab("activity")
  expect(useUIStore.getState().activeTab).toBe("activity")
})

it("activeTab defaults to chat", () => {
  expect(useUIStore.getState().activeTab).toBe("chat")
})
