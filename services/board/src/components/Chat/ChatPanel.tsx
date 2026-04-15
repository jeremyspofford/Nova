import { useEffect, useRef } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useShallow } from "zustand/react/shallow"
import { useChatStore } from "../../stores/chatStore"
import { getMessages, sendMessageStream } from "../../api/chat"
import { ChatInput } from "./ChatInput"
import { MessageBubble } from "./MessageBubble"

export function ChatPanel() {
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
      }
    } catch {
      // fetch or parse error
    } finally {
      finishStreaming()
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] })
    }
  }

  return (
    <section className="chat-panel" aria-label="Chat">
      <div className="chat-panel__header">
        <span className="chat-panel__title">Nova</span>
      </div>

      <div className="chat-panel__messages">
        <div className="chat-panel__messages-inner">
          {messages.map(m => (
            <MessageBubble key={m.id} role={m.role} content={m.content} />
          ))}
          {isStreaming && (
            <MessageBubble role="assistant" content={streamingContent} streaming={true} />
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="chat-panel__footer">
        <ChatInput onSend={handleSend} disabled={isStreaming} />
      </div>
    </section>
  )
}
