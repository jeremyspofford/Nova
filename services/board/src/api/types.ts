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
