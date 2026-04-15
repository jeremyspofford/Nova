export interface BoardColumn {
  id: string
  name: string
  order: number
  work_in_progress_limit: number | null
  status_filter: Record<string, unknown> | null
  description: string | null
}

export interface Task {
  id: string
  title: string
  description: string | null
  goal: string | null
  status: string
  origin_event_id: string | null
  board_column_id: string | null
  owner_type: string | null
  owner_id: string | null
  created_at: string
  updated_at: string
  due_at: string | null
  priority: string
  risk_class: string
  approval_required: boolean
  last_decision: string
  next_check_at: string | null
  result_summary: string | null
  labels: string[]
  metadata: Record<string, unknown>
}

export interface TaskListResponse {
  tasks: Task[]
}

export interface BoardResponse {
  columns: BoardColumn[]
  tasks_by_column: Record<string, Task[]>
}

export interface Run {
  id: string
  tool_name: string
  status: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface ApprovalRead {
  id: string
  task_id: string
  requested_by: string
  requested_at: string
  summary: string
  consequence: string | null
  options: string[]
  status: string
  decided_by: string | null
  decided_at: string | null
  decision: string | null
  reason: string | null
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface ConversationListResponse {
  conversations: Conversation[]
}

export interface Message {
  id: string
  conversation_id: string
  role: "user" | "assistant"
  content: string
  created_at: string
}

export interface MessageListResponse {
  messages: Message[]
}

export type SSEEvent =
  | { delta: string }
  | { complete: true }
  | { error: string }

export interface ActivityEntry {
  id: string
  tool_name: string
  trigger_type: "chat" | "agent_loop"
  status: "succeeded" | "failed" | "running"
  summary: string | null
  input: Record<string, unknown> | null
  output: string | null
  error: string | null
  started_at: string
  finished_at: string | null
}

export interface ActivityResponse {
  entries: ActivityEntry[]
  total: number
}
