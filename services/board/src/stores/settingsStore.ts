import { create } from "zustand"
import { persist } from "zustand/middleware"

type Theme = "light" | "dark" | "system"
type LayoutMode = "split" | "tabbed"
type ChatSide = "left" | "right"

interface SettingsState {
  theme: Theme
  layoutMode: LayoutMode
  chatSide: ChatSide
  setTheme: (theme: Theme) => void
  setLayoutMode: (mode: LayoutMode) => void
  setChatSide: (side: ChatSide) => void
}

function applyTheme(theme: Theme) {
  if (theme === "system") {
    delete document.documentElement.dataset.theme
  } else {
    document.documentElement.dataset.theme = theme
  }
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: "system",
      layoutMode: "split",
      chatSide: "left",
      setTheme: (theme) => {
        applyTheme(theme)
        set({ theme })
      },
      setLayoutMode: (layoutMode) => set({ layoutMode }),
      setChatSide: (chatSide) => set({ chatSide }),
    }),
    { name: "nova-settings" }
  )
)

// Apply theme on store initialization (page load)
applyTheme(useSettingsStore.getState().theme)
