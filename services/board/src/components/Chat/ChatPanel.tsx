import { useEffect, useRef } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useUIStore } from "../../stores/uiStore"
import { useChatStore } from "../../stores/chatStore"
import { getMessages, sendMessageStream } from "../../api/chat"
import { ChatInput } from "./ChatInput"
import { MessageBubble } from "./MessageBubble"

export function ChatPanel() {
  const { chatOpen, toggleChat } = useUIStore(s => ({
    chatOpen: s.chatOpen,
    toggleChat: s.toggleChat,
  }))
  const { conversationId, streamingContent, isStreaming, startStreaming, appendDelta, finishStreaming } =
    useChatStore()
  const queryClient = useQueryClient()
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () => (conversationId ? getMessages(conversationId) : Promise.resolve({ messages: [] })),
    enabled: !!conversationId,
  })

  const messages = data?.messages ?? []

  useEffect(() => {
    if (bottomRef.current && typeof bottomRef.current.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [messages, streamingContent])

  async function handleSend(content: string) {
    if (!conversationId || isStreaming) return
    startStreaming()
    try {
      for await (const event of sendMessageStream(conversationId, content)) {
        if ("delta" in event) appendDelta(event.delta)
        if ("complete" in event) {
          finishStreaming()
          queryClient.invalidateQueries({ queryKey: ["messages", conversationId] })
        }
        if ("error" in event) {
          finishStreaming()
        }
      }
    } catch {
      finishStreaming()
    }
  }

  if (!chatOpen) return null

  return (
    <section className="chat-panel" aria-label="Chat">
      <div className="chat-panel__header">
        <span className="chat-panel__title">Nova</span>
        <button
          className="chat-panel__close"
          onClick={toggleChat}
          aria-label="Close chat"
        >
          &#x2715;
        </button>
      </div>

      <div className="chat-panel__messages">
        {messages.map(m => (
          <MessageBubble key={m.id} role={m.role} content={m.content} />
        ))}
        {isStreaming && (
          <MessageBubble role="assistant" content={streamingContent} streaming={true} />
        )}
        <div ref={bottomRef} />
      </div>

      <ChatInput onSend={handleSend} disabled={isStreaming} />
    </section>
  )
}
