import { useUIStore } from "./stores/uiStore"
import { useChatStore } from "./stores/chatStore"
import { Board } from "./components/Board/Board"
import { FilterBar } from "./components/shared/FilterBar"
import { TaskDetail } from "./components/TaskDetail/TaskDetail"
import { Toast } from "./components/shared/Toast"
import { ChatPanel } from "./components/Chat/ChatPanel"
import { createConversation } from "./api/chat"
import { useShallow } from "zustand/react/shallow"

export function AppShell() {
  const { toast, setToast, chatOpen, toggleChat } = useUIStore(
    useShallow(s => ({
      toast: s.toast,
      setToast: s.setToast,
      chatOpen: s.chatOpen,
      toggleChat: s.toggleChat,
    }))
  )
  const { conversationId, setConversation } = useChatStore(
    useShallow(s => ({
      conversationId: s.conversationId,
      setConversation: s.setConversation,
    }))
  )

  async function handleToggleChat() {
    if (!chatOpen && !conversationId) {
      const conv = await createConversation()
      setConversation(conv.id)
    }
    toggleChat()
  }

  return (
    <div className="board-layout">
      <header className="board-header">
        <span style={{ fontWeight: 700, fontSize: 15 }}>Nova Board</span>
        <FilterBar />
        <button
          className="chat-toggle-btn"
          onClick={handleToggleChat}
          aria-label="Toggle chat"
          aria-pressed={chatOpen}
        >
          Chat
        </button>
      </header>

      <div className="board-with-detail">
        <Board />
        <TaskDetail />
      </div>

      <ChatPanel />

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
