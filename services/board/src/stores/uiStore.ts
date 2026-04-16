import { create } from "zustand"

type ActiveTab = "chat" | "activity"

interface UIState {
  toast: string | null
  activeTab: ActiveTab
  setToast: (msg: string | null) => void
  setActiveTab: (tab: ActiveTab) => void
}

export const useUIStore = create<UIState>(set => ({
  toast: null,
  activeTab: "chat",
  setToast: msg => set({ toast: msg }),
  setActiveTab: tab => set({ activeTab: tab }),
}))
