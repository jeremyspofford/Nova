import { useUIStore } from "./stores/uiStore"
import { Board } from "./components/Board/Board"
import { FilterBar } from "./components/shared/FilterBar"
import { TaskDetail } from "./components/TaskDetail/TaskDetail"
import { Toast } from "./components/shared/Toast"

export function App() {
  const { toast, setToast } = useUIStore(s => ({
    toast: s.toast,
    setToast: s.setToast,
  }))

  return (
    <div className="board-layout">
      <header className="board-header">
        <span style={{ fontWeight: 700, fontSize: 15 }}>Nova Board</span>
        <FilterBar />
      </header>

      <div className="board-with-detail">
        <Board />
        <TaskDetail />
      </div>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
