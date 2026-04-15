import { useEffect } from "react"
import { Link } from "react-router-dom"
import { useShallow } from "zustand/react/shallow"
import { useUIStore } from "./stores/uiStore"
import { useChatStore } from "./stores/chatStore"
import { Board } from "./components/Board/Board"
import { FilterBar } from "./components/shared/FilterBar"
import { TaskDetail } from "./components/TaskDetail/TaskDetail"
import { Toast } from "./components/shared/Toast"
import { ChatPanel } from "./components/Chat/ChatPanel"
import { createConversation } from "./api/chat"

export function AppShell() {
  const { toast, setToast, activeTab, setActiveTab } = useUIStore(
    useShallow(s => ({ toast: s.toast, setToast: s.setToast, activeTab: s.activeTab, setActiveTab: s.setActiveTab }))
  )

  useEffect(() => {
    if (!useChatStore.getState().conversationId) {
      createConversation().then(conv => useChatStore.getState().setConversation(conv.id))
    }
  }, [])

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <span className="app-shell__title">Nova</span>

        <nav className="app-shell__tabs">
          <button
            className={`app-shell__tab${activeTab === "chat" ? " app-shell__tab--active" : ""}`}
            onClick={() => setActiveTab("chat")}
          >
            Chat
          </button>
          <button
            className={`app-shell__tab${activeTab === "board" ? " app-shell__tab--active" : ""}`}
            onClick={() => setActiveTab("board")}
          >
            Board
          </button>
        </nav>

        {activeTab === "board" && <FilterBar />}

        <Link to="/settings" className="app-shell__settings-link" aria-label="Settings">
          ⚙
        </Link>
      </header>

      <div className="app-shell__body">
        <div className="app-shell__tab-content">
          {activeTab === "chat" ? (
            <ChatPanel />
          ) : (
            <div className="board-with-detail">
              <Board />
              <TaskDetail />
            </div>
          )}
        </div>
      </div>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
