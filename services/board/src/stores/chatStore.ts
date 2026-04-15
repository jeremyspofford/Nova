import { create } from "zustand"

interface ChatState {
  conversationId: string | null
  streamingContent: string
  isStreaming: boolean
  setConversation: (id: string | null) => void
  startStreaming: () => void
  appendDelta: (delta: string) => void
  finishStreaming: () => void
}

export const useChatStore = create<ChatState>(set => ({
  conversationId: null,
  streamingContent: "",
  isStreaming: false,
  setConversation: id => set({ conversationId: id }),
  startStreaming: () => set({ isStreaming: true, streamingContent: "" }),
  appendDelta: delta => set(s => ({ streamingContent: s.streamingContent + delta })),
  finishStreaming: () => set({ isStreaming: false, streamingContent: "" }),
}))
