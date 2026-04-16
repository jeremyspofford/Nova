import { apiFetch } from "./client"

export function getModels(): Promise<{ models: string[] }> {
  return apiFetch<{ models: string[] }>("/llm/models")
}

export function setLocalModel(model: string): Promise<{ provider_id: string; model_ref: string }> {
  return apiFetch("/llm/providers/local", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_ref: model }),
  })
}
