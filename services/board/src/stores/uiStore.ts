import { create } from "zustand"
import type { BoardFilters } from "../api/board"

interface UIState {
  selectedTaskId: string | null
  toast: string | null
  activeFilters: BoardFilters
  setSelectedTask: (id: string | null) => void
  setToast: (msg: string | null) => void
  setFilters: (filters: BoardFilters) => void
}

export const useUIStore = create<UIState>(set => ({
  selectedTaskId: null,
  toast: null,
  activeFilters: {},
  setSelectedTask: id => set({ selectedTaskId: id }),
  setToast: msg => set({ toast: msg }),
  setFilters: filters => set({ activeFilters: filters }),
}))
