import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { streamChat, discoverModels, resolveModel, apiFetch, type ChatMessage, type ContentBlock, type StreamEvent } from '../../api'
import { useChatStore, type Message } from '../../stores/chat-store'
import { useAuth } from '../../stores/auth-store'
import { cleanToolArtifacts, getStableContent } from '../../utils/cleanToolArtifacts'
import { useNovaIdentity } from '../../hooks/useNovaIdentity'
import { ConversationSidebar } from '../../components/ConversationSidebar'
import { MessageBubble } from './MessageBubble'
import { ChatInput } from './ChatInput'

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

export function Chat() {
  const {
    messages, setMessages,
    sessionId, setSessionId,
    conversationId, setConversationId,
    modelId, setModelId,
    error, setError,
    resetConversation,
    loadConversation,
    newConversation,
    pendingFiles, setPendingFiles,
    outputStyle,
    customInstructions,
    webSearchEnabled,
    deepResearchEnabled,
    sidebarCollapsed, setSidebarCollapsed,
  } = useChatStore()
  const { isAuthenticated } = useAuth()
  const queryClient = useQueryClient()

  const { name: aiName, greeting } = useNovaIdentity()
  const [isStreaming, setIsStreaming] = useState(false)
  const [messageQueue, setMessageQueue] = useState<string[]>([])

  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const { data: providers } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
  })
  const models = (providers ?? [])
    .filter(p => p.available)
    .flatMap(p => p.models.filter(m => m.registered).map(m => ({ id: m.id, provider: p.name })))

  const { data: resolved } = useQuery({
    queryKey: ['resolved-model'],
    queryFn: resolveModel,
    staleTime: 30_000,
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Prevent iOS keyboard from shifting the viewport (mobile only)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv || !containerRef.current) return
    // Only apply on touch devices — on desktop, visualViewport.height includes
    // the NavBar area, which would push the chat input below the fold
    if (!('ontouchstart' in window)) return

    const onResize = () => {
      if (containerRef.current) {
        containerRef.current.style.height = `${vv.height}px`
      }
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      })
    }
    vv.addEventListener('resize', onResize)
    return () => vv.removeEventListener('resize', onResize)
  }, [])

  const handleSubmit = useCallback(async (text: string, fromQueue = false) => {
    if (isStreaming && !fromQueue) {
      // Show user message immediately, queue for sequential processing
      const queuedMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: text,
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, queuedMsg])
      setMessageQueue(q => [...q, text])
      return
    }

    setError(null)

    // Capture pending files before clearing (skip for queued messages)
    const attachments = (!fromQueue && pendingFiles.length > 0) ? [...pendingFiles] : undefined
    if (attachments) setPendingFiles([])

    const assistantMsgId = crypto.randomUUID()
    const assistantMsg: Message = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
    }

    if (fromQueue) {
      // User message already shown when queued
      setMessages(prev => [...prev, assistantMsg])
    } else {
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: text,
        timestamp: new Date(),
        attachments,
      }
      setMessages(prev => [...prev, userMsg, assistantMsg])
    }
    setIsStreaming(true)

    // Auto-create conversation for authenticated users without one
    let activeConversationId = conversationId
    if (isAuthenticated && !activeConversationId) {
      try {
        const conv = await apiFetch<{ id: string }>('/api/v1/conversations', {
          method: 'POST',
          body: JSON.stringify({}),
        })
        activeConversationId = conv.id
        setConversationId(conv.id)
        setSessionId(conv.id)
      } catch {
        // Fallback: no conversation persistence
      }
    }

    const currentSessionId = activeConversationId ?? sessionId ?? (() => {
      const newId = crypto.randomUUID()
      setSessionId(newId)
      return newId
    })()

    // Build message history
    const history: ChatMessage[] = [
      ...messages.map(m => ({ role: m.role as ChatMessage['role'], content: m.content })),
    ]

    // Build user message content — multimodal if attachments present
    let userContent: string | ContentBlock[] = text
    if (attachments && attachments.length > 0) {
      const blocks: ContentBlock[] = [{ type: 'text', text }]
      for (const att of attachments) {
        if (att.type === 'image') {
          // Convert to base64 data URL for vision models
          const data = await fileToBase64(att.file)
          blocks.push({ type: 'image_url', image_url: { url: data } })
        } else {
          // Read text file content and include inline
          const content = await att.file.text()
          blocks.push({ type: 'text', text: `Content of ${att.file.name}:\n\`\`\`\n${content}\n\`\`\`` })
        }
      }
      userContent = blocks
    }
    // For queued messages, user message is already in the messages array
    if (!fromQueue) {
      history.push({ role: 'user', content: userContent })
    }

    // Build stream options
    const streamOptions = {
      ...(outputStyle ? { output_style: outputStyle } : {}),
      ...(customInstructions.trim() ? { custom_instructions: customInstructions.trim() } : {}),
      ...(webSearchEnabled ? { web_search: true } : {}),
      ...(deepResearchEnabled ? { deep_research: true } : {}),
      ...(activeConversationId ? { conversation_id: activeConversationId } : {}),
    }

    try {
      let accumulated = ''
      let firstTextDelta = true
      for await (const event of streamChat(history, modelId || undefined, currentSessionId, streamOptions)) {
        if (typeof event === 'object' && 'status' in event) {
          const step = event.status
          setMessages(prev => prev.map(m => {
            if (m.id !== assistantMsgId) return m
            const steps = [...(m.activitySteps ?? [])]
            const idx = steps.findIndex(s => s.step === step.step)
            const enriched = { ...step, startedAt: idx >= 0 ? steps[idx].startedAt : Date.now() }
            if (idx >= 0) steps[idx] = enriched; else steps.push(enriched)
            return {
              ...m,
              activitySteps: steps,
              ...(step.model ? { modelUsed: step.model } : {}),
              ...(step.category ? { category: step.category } : {}),
            }
          }))
          continue
        }
        if (typeof event === 'object' && 'meta' in event) {
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantMsgId
                ? { ...m, modelUsed: event.meta.model, category: event.meta.category }
                : m
            )
          )
          continue
        }
        // Text delta — collapse activity feed on first token
        if (firstTextDelta) {
          firstTextDelta = false
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantMsgId ? { ...m, activityCollapsed: true } : m
            )
          )
        }
        accumulated += event
        const displayContent = getStableContent(accumulated)
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMsgId ? { ...m, content: displayContent } : m
          )
        )
      }
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: cleanToolArtifacts(accumulated), isStreaming: false }
            : m
        )
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: `Error: ${msg}`, isStreaming: false }
            : m
        )
      )
    } finally {
      setIsStreaming(false)
      if (conversationId) {
        queryClient.invalidateQueries({ queryKey: ['conversations'] })
      }
    }
  }, [messages, sessionId, conversationId, modelId, isStreaming, setMessages, setSessionId, setError, pendingFiles, setPendingFiles, outputStyle, customInstructions, webSearchEnabled, deepResearchEnabled, queryClient])

  // Process queued messages sequentially when streaming completes
  useEffect(() => {
    if (!isStreaming && messageQueue.length > 0) {
      const next = messageQueue[0]
      setMessageQueue(q => q.slice(1))
      handleSubmit(next, true)
    }
  }, [isStreaming, messageQueue, handleSubmit])

  const startNewConversation = async () => {
    setMessageQueue([])
    if (isAuthenticated) {
      await newConversation()
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    } else {
      resetConversation()
    }
  }

  // Compute streaming status text
  const streamingStatus = isStreaming ? (() => {
    const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
    if (!lastAssistant) return 'thinking\u2026'
    if (lastAssistant.content) return 'typing\u2026'
    const steps = lastAssistant.activitySteps ?? []
    const running = steps.find(s => s.state === 'running')
    if (!running) return 'thinking\u2026'
    const labels: Record<string, string> = {
      classifying: 'classifying\u2026',
      memory: 'retrieving memories\u2026',
      generating: 'generating\u2026',
    }
    return labels[running.step] ?? 'thinking\u2026'
  })() : undefined

  const chatInputProps = {
    onSubmit: handleSubmit,
    isStreaming,
    aiName,
    models,
    modelId,
    onModelChange: setModelId,
    resolvedModel: resolved?.model,
    onNewChat: startNewConversation,
    hasMessages: messages.length > 0,
  }

  const handleSelectConversation = useCallback(async (id: string) => {
    setMessageQueue([])
    await loadConversation(id)
  }, [loadConversation])

  const handleNewConversation = useCallback(async () => {
    await startNewConversation()
  }, [startNewConversation]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-full overflow-hidden bg-surface-root">
      {isAuthenticated && (
        <ConversationSidebar
          currentId={conversationId}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(c => !c)}
        />
      )}
      <div ref={containerRef} className="flex-1 flex flex-col h-full overflow-hidden">
        {messages.length === 0 ? (
          /* Empty state: greeting bubble + input */
          <div className="flex-1 flex flex-col">
            <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
              <div className="max-w-3xl mx-auto px-4 py-6">
                {greeting && (
                  <MessageBubble message={{
                    id: 'greeting',
                    role: 'assistant',
                    content: greeting,
                    timestamp: new Date(),
                  }} />
                )}
              </div>
            </div>
            <div className="shrink-0 w-full">
              <div className="max-w-3xl mx-auto">
                <ChatInput {...chatInputProps} />
              </div>
            </div>
          </div>
        ) : (
          /* Active chat: scrollable messages + bottom-pinned input */
          <>
            <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
              <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
                {greeting && (
                  <MessageBubble message={{
                    id: 'greeting',
                    role: 'assistant',
                    content: greeting,
                    timestamp: new Date(),
                  }} />
                )}
                {messages.map(msg => (
                  <MessageBubble key={msg.id} message={msg} />
                ))}

                {error && (
                  <div className="rounded-sm border border-danger/30 bg-danger-dim px-4 py-3 text-compact text-danger">
                    {error}
                  </div>
                )}

                <div ref={bottomRef} />
              </div>
            </div>

            {(streamingStatus || messageQueue.length > 0) && (
              <p className="text-caption text-content-tertiary text-center py-1">
                {streamingStatus && <>{aiName} is {streamingStatus}</>}
                {streamingStatus && messageQueue.length > 0 && ' \u00b7 '}
                {messageQueue.length > 0 && `${messageQueue.length} message${messageQueue.length > 1 ? 's' : ''} queued`}
              </p>
            )}

            <div className="shrink-0 w-full">
              <div className="max-w-3xl mx-auto">
                <ChatInput {...chatInputProps} />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
