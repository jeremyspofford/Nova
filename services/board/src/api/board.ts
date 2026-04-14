import { apiFetch } from "./client"
import type { BoardResponse, Task } from "./types"

export interface BoardFilters {
  status?: string
  risk_class?: string
  priority?: string
  labels?: string[]
}

export function getBoard(filters?: BoardFilters): Promise<BoardResponse> {
  if (!filters || Object.keys(filters).every(k => !filters[k as keyof BoardFilters])) {
    return apiFetch<BoardResponse>("/board")
  }
  const params = new URLSearchParams()
  if (filters.status) params.set("status", filters.status)
  if (filters.risk_class) params.set("risk_class", filters.risk_class)
  if (filters.priority) params.set("priority", filters.priority)
  filters.labels?.forEach(l => params.append("labels", l))
  return apiFetch<BoardResponse>(`/board?${params.toString()}`)
}

export function moveTask(taskId: string, columnId: string): Promise<Task> {
  return apiFetch<Task>(`/board/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ board_column_id: columnId }),
  })
}
