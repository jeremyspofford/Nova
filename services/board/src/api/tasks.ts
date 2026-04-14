import { apiFetch } from "./client"
import type { Task, TaskListResponse, Run } from "./types"

export function getTasks(filters?: Record<string, string>): Promise<TaskListResponse> {
  const qs = filters && Object.keys(filters).length
    ? `?${new URLSearchParams(filters).toString()}`
    : ""
  return apiFetch<TaskListResponse>(`/tasks${qs}`)
}

export function getTask(id: string): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}`)
}

export function getRuns(taskId: string): Promise<{ runs: Run[] }> {
  return apiFetch<{ runs: Run[] }>(`/tasks/${taskId}/runs`)
}

export function patchTask(id: string, patch: Partial<Task>): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  })
}
