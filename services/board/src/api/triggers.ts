import { apiFetch } from "./client"

export interface Trigger {
  id: string
  name: string
  description: string | null
  cron_expression: string
  active_hours_start: string | null
  active_hours_end: string | null
  enabled: boolean
  payload_template: Record<string, unknown>
  last_fired_at: string | null
}

export function getTriggers(): Promise<{ triggers: Trigger[] }> {
  return apiFetch<{ triggers: Trigger[] }>("/system/triggers")
}
