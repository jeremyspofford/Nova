import { apiFetch } from "./client"
import type {
  Conversation,
  ConversationListResponse,
  Message,
  MessageListResponse,
  SSEEvent,
} from "./types"

export function getConversations(limit = 10): Promise<ConversationListResponse> {
  return apiFetch<ConversationListResponse>(`/conversations?limit=${limit}`)
}

export function createConversation(): Promise<Conversation> {
  return apiFetch<Conversation>("/conversations", { method: "POST" })
}

export function getMessages(conversationId: string): Promise<MessageListResponse> {
  return apiFetch<MessageListResponse>(`/conversations/${conversationId}/messages`)
}

export async function* sendMessageStream(
  conversationId: string,
  content: string,
): AsyncGenerator<SSEEvent> {
  const base: string = import.meta.env.VITE_API_URL ?? ""
  const res = await fetch(`${base}/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, stream: true }),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${detail}`)
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split("\n")
    buffer = lines.pop() ?? ""
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        yield JSON.parse(line.slice(6)) as SSEEvent
      }
    }
  }
}
