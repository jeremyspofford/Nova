import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { streamChat, uploadFile, discoverModels, resolveModel, type ChatMessage, type ContentBlock, type StreamEvent } from '../../api'
import { useChatStore, type Message } from '../../stores/chat-store'
import { useNovaIdentity } from '../../hooks/useNovaIdentity'
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
    modelId, setModelId,
    error, setError,
    resetConversation,
    pendingFiles, setPendingFiles,
    outputStyle,
    customInstructions,
    webSearchEnabled,
    deepResearchEnabled,
  } = useChatStore()

  const { name: aiName, greeting } = useNovaIdentity()
  const [isStreaming, setIsStreaming] = useState(false)

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

  // Prevent iOS keyboard from shifting the viewport
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv || !containerRef.current) return

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

  const handleSubmit = useCallback(async (text: string) => {
    if (isStreaming) return

    setError(null)

    // Capture pending files before clearing
    const attachments = pendingFiles.length > 0 ? [...pendingFiles] : undefined
    if (attachments) setPendingFiles([])

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date(),
      attachments,
    }

    const assistantMsgId = crypto.randomUUID()
    const assistantMsg: Message = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
    }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setIsStreaming(true)

    const currentSessionId = sessionId ?? (() => {
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
    history.push({ role: 'user', content: userContent })

    // Upload files to memory service (fire-and-forget for storage)
    if (attachments) {
      for (const att of attachments) {
        uploadFile(att.file, currentSessionId).catch(() => {})
      }
    }

    // Build stream options
    const streamOptions = {
      ...(outputStyle ? { output_style: outputStyle } : {}),
      ...(customInstructions.trim() ? { custom_instructions: customInstructions.trim() } : {}),
      ...(webSearchEnabled ? { web_search: true } : {}),
      ...(deepResearchEnabled ? { deep_research: true } : {}),
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
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMsgId ? { ...m, content: accumulated } : m
          )
        )
      }
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantMsgId ? { ...m, isStreaming: false } : m
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
    }
  }, [messages, sessionId, modelId, isStreaming, setMessages, setSessionId, setError, pendingFiles, setPendingFiles, outputStyle, customInstructions, webSearchEnabled, deepResearchEnabled])

  const startNewConversation = () => {
    resetConversation()
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

  return (
    <div ref={containerRef} className="flex flex-col h-full overflow-hidden bg-neutral-50 dark:bg-neutral-950">
      {messages.length === 0 ? (
        /* Empty state: greeting bubble + input */
        <div className="flex-1 flex flex-col">
          <div className="flex-1 min-h-0 overflow-y-auto">
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
          <div className="shrink-0 w-full pb-4 pt-2 px-4">
            <div className="max-w-3xl mx-auto">
              <ChatInput {...chatInputProps} />
            </div>
          </div>
        </div>
      ) : (
        /* Active chat: scrollable messages + bottom-pinned input */
        <>
          <div className="flex-1 min-h-0 overflow-y-auto">
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
                <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950 px-4 py-3 text-sm text-red-700 dark:text-red-400">
                  {error}
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          </div>

          {streamingStatus && (
            <p className="text-xs text-neutral-400 text-center py-1">{aiName} is {streamingStatus}</p>
          )}

          <div className="shrink-0 w-full pb-4 pt-2 px-4">
            <div className="max-w-3xl mx-auto">
              <ChatInput {...chatInputProps} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
