import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useShallow } from "zustand/react/shallow"
import { useSettingsStore } from "./stores/settingsStore"
import { useUIStore } from "./stores/uiStore"
import { useChatStore } from "./stores/chatStore"
import { Board } from "./components/Board/Board"
import { FilterBar } from "./components/shared/FilterBar"
import { TaskDetail } from "./components/TaskDetail/TaskDetail"
import { Toast } from "./components/shared/Toast"
import { ChatPanel } from "./components/Chat/ChatPanel"
import { createConversation } from "./api/chat"

function useIsNarrow(breakpoint = 900): boolean {
  const [isNarrow, setIsNarrow] = useState(() => window.innerWidth < breakpoint)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
    const handler = (e: MediaQueryListEvent) => setIsNarrow(e.matches)
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [breakpoint])
  return isNarrow
}

export function AppShell() {
  const { layoutMode, chatSide } = useSettingsStore(
    useShallow(s => ({ layoutMode: s.layoutMode, chatSide: s.chatSide }))
  )
  const { toast, setToast, activeTab, setActiveTab } = useUIStore(
    useShallow(s => ({ toast: s.toast, setToast: s.setToast, activeTab: s.activeTab, setActiveTab: s.setActiveTab }))
  )
  const setConversation = useChatStore(s => s.setConversation)

  const isNarrow = useIsNarrow()
  const effectiveMode = isNarrow ? "tabbed" : layoutMode

  useEffect(() => {
    // Read conversationId inside the effect to avoid stale closure.
    // Zustand persist rehydrates synchronously from localStorage before first render,
    // so getState() here reflects the restored value.
    if (!useChatStore.getState().conversationId) {
      createConversation().then(conv => setConversation(conv.id))
    }
  }, [])

  const isSplit = effectiveMode === "split"

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <span className="app-shell__title">Nova Board</span>

        {isSplit ? (
          <FilterBar />
        ) : (
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
        )}

        {!isSplit && activeTab === "board" && <FilterBar />}

        <Link to="/settings" className="app-shell__settings-link" aria-label="Settings">
          ⚙
        </Link>
      </header>

      <div className="app-shell__body">
        {isSplit ? (
          <>
            <div className={`app-shell__chat-pane${chatSide === "right" ? " app-shell__chat-pane--right" : ""}`}>
              <ChatPanel />
            </div>
            <div className="app-shell__board-pane">
              <div className="board-with-detail">
                <Board />
                <TaskDetail />
              </div>
            </div>
          </>
        ) : (
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
        )}
      </div>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
