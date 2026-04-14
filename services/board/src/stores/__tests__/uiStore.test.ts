import { describe, it, expect, beforeEach } from "vitest"
import { useUIStore } from "../uiStore"

beforeEach(() => {
  useUIStore.setState({
    selectedTaskId: null,
    toast: null,
    activeFilters: {},
  })
})

it("setSelectedTask updates selectedTaskId", () => {
  useUIStore.getState().setSelectedTask("t1")
  expect(useUIStore.getState().selectedTaskId).toBe("t1")
})

it("setSelectedTask(null) clears selection", () => {
  useUIStore.getState().setSelectedTask("t1")
  useUIStore.getState().setSelectedTask(null)
  expect(useUIStore.getState().selectedTaskId).toBeNull()
})

it("setToast updates toast message", () => {
  useUIStore.getState().setToast("something went wrong")
  expect(useUIStore.getState().toast).toBe("something went wrong")
})

it("setFilters updates activeFilters", () => {
  useUIStore.getState().setFilters({ status: "running", labels: ["ci"] })
  expect(useUIStore.getState().activeFilters).toEqual({ status: "running", labels: ["ci"] })
})
