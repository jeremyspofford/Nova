import { useEffect, useRef } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useShallow } from "zustand/react/shallow"
import { useUIStore } from "../../stores/uiStore"
import { useChatStore } from "../../stores/chatStore"
import { getMessages, sendMessageStream } from "../../api/chat"
import { ChatInput } from "./ChatInput"
import { MessageBubble } from "./MessageBubble"

export function ChatPanel() {
  const { chatOpen, toggleChat } = useUIStore(
    useShallow(s => ({ chatOpen: s.chatOpen, toggleChat: s.toggleChat }))
  )
  const { conversationId, streamingContent, isStreaming, startStreaming, appendDelta, finishStreaming } =
    useChatStore(
      useShallow(s => ({
        conversationId: s.conversationId,
        streamingContent: s.streamingContent,
        isStreaming: s.isStreaming,
        startStreaming: s.startStreaming,
        appendDelta: s.appendDelta,
        finishStreaming: s.finishStreaming,
      }))
    )
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
        if ("error" in event) {
          // error already sent by server in SSE stream — stream will end
        }
      }
    } catch {
      // fetch error or parse error
    } finally {
      finishStreaming()
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] })
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
