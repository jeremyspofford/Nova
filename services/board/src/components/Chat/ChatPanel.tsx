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
  const queueRef = useRef<string[]>([])

  const { data } = useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () => (conversationId ? getMessages(conversationId) : Promise.resolve({ messages: [] })),
    enabled: !!conversationId,
  })

  const messages = data?.messages ?? []

  // Snap to bottom instantly when message history loads (tab switch or initial load)
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "instant" })
  }, [messages])

  // Follow streaming output smoothly
  useEffect(() => {
    if (isStreaming) bottomRef.current?.scrollIntoView?.({ behavior: "smooth" })
  }, [streamingContent, isStreaming])

  async function sendOne(content: string) {
    startStreaming()
    try {
      for await (const event of sendMessageStream(conversationId!, content)) {
        if ("delta" in event) appendDelta(event.delta)
      }
    } catch {
      // fetch or parse error
    } finally {
      finishStreaming()
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] })
      const next = queueRef.current.shift()
      if (next) {
        // Re-add optimistic bubble — invalidateQueries replaced the cache with
        // server data which doesn't include the queued message yet.
        queryClient.setQueryData(["messages", conversationId], (old: any) => ({
          messages: [
            ...(old?.messages ?? []),
            { id: crypto.randomUUID(), role: "user", content: next },
          ],
        }))
        sendOne(next)
      }
    }
  }

  async function handleSend(content: string) {
    if (!conversationId) return

    // Always show the user message immediately
    queryClient.setQueryData(["messages", conversationId], (old: any) => ({
      messages: [
        ...(old?.messages ?? []),
        { id: crypto.randomUUID(), role: "user", content },
      ],
    }))

    if (isStreaming) {
      queueRef.current.push(content)
      return
    }

    sendOne(content)
  }

  return (
    <section className="chat-panel" aria-label="Chat">
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
        <ChatInput onSend={handleSend} disabled={!conversationId} />
      </div>
    </section>
  )
}
