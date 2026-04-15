import { create } from "zustand"
import type { BoardFilters } from "../api/board"

interface UIState {
  selectedTaskId: string | null
  toast: string | null
  activeFilters: BoardFilters
  chatOpen: boolean
  setSelectedTask: (id: string | null) => void
  setToast: (msg: string | null) => void
  setFilters: (filters: BoardFilters) => void
  toggleChat: () => void
}

export const useUIStore = create<UIState>(set => ({
  selectedTaskId: null,
  toast: null,
  activeFilters: {},
  chatOpen: false,
  setSelectedTask: id => set({ selectedTaskId: id }),
  setToast: msg => set({ toast: msg }),
  setFilters: filters => set({ activeFilters: filters }),
  toggleChat: () => set(s => ({ chatOpen: !s.chatOpen })),
}))
