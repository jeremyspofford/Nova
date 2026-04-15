import { create } from "zustand"
import type { BoardFilters } from "../api/board"

type ActiveTab = "chat" | "activity"

interface UIState {
  selectedTaskId: string | null
  toast: string | null
  activeFilters: BoardFilters
  activeTab: ActiveTab
  setSelectedTask: (id: string | null) => void
  setToast: (msg: string | null) => void
  setFilters: (filters: BoardFilters) => void
  setActiveTab: (tab: ActiveTab) => void
}

export const useUIStore = create<UIState>(set => ({
  selectedTaskId: null,
  toast: null,
  activeFilters: {},
  activeTab: "chat",
  setSelectedTask: id => set({ selectedTaskId: id }),
  setToast: msg => set({ toast: msg }),
  setFilters: filters => set({ activeFilters: filters }),
  setActiveTab: tab => set({ activeTab: tab }),
}))
