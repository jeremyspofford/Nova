import { create } from "zustand"
import { persist } from "zustand/middleware"

interface ChatState {
  conversationId: string | null
  streamingContent: string
  isStreaming: boolean
  setConversation: (id: string | null) => void
  startStreaming: () => void
  appendDelta: (delta: string) => void
  finishStreaming: () => void
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      conversationId: null,
      streamingContent: "",
      isStreaming: false,
      setConversation: id => set({ conversationId: id }),
      startStreaming: () => set({ isStreaming: true, streamingContent: "" }),
      appendDelta: delta => set(s => ({ streamingContent: s.streamingContent + delta })),
      finishStreaming: () => set({ isStreaming: false, streamingContent: "" }),
    }),
    {
      name: "nova-chat",
      partialize: (state) => ({ conversationId: state.conversationId }),
    }
  )
)
