import { apiFetch } from "./client"
import type { ActivityResponse } from "./types"

export function getActivity(limit = 50, offset = 0): Promise<ActivityResponse> {
  return apiFetch<ActivityResponse>(`/activity?limit=${limit}&offset=${offset}`)
}
