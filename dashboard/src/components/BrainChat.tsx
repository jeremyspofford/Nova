import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, Send, Loader2 } from 'lucide-react'
import { streamChat, resolveModel, type ChatMessage } from '../api'
import { cleanToolArtifacts } from '../utils/cleanToolArtifacts'
import { MessageBubble } from '../pages/chat/MessageBubble'
import type { Message, ActivityStep } from '../stores/chat-store'

interface BrainChatProps {
  onClose: () => void
  onActivityStep?: (step: ActivityStep) => void
  onStreamComplete?: () => void
}

export function BrainChat({ onClose, onActivityStep, onStreamComplete }: BrainChatProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Resolve default model
  const { data: resolved } = useQuery({
    queryKey: ['resolve-model'],
    queryFn: resolveModel,
    staleTime: 60_000,
  })
  const modelId = resolved?.model ?? ''

  // Auto-scroll when near bottom
  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150
    if (isNearBottom) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  // Focus input after slide-in animation
  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 300)
    return () => clearTimeout(timer)
  }, [])

  const handleSubmit = useCallback(async () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')

    // Add user message
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])

    // Create assistant placeholder
    const assistantId = crypto.randomUUID()
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
      activitySteps: [],
    }
    setMessages(prev => [...prev, assistantMsg])

    setIsStreaming(true)
    let accumulated = ''

    try {
      // Build history for context
      const history: ChatMessage[] = [...messages, userMsg].map(m => ({
        role: m.role as ChatMessage['role'],
        content: m.content,
      }))

      for await (const event of streamChat(history, modelId || undefined)) {
        if (typeof event === 'string') {
          accumulated += event
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantId ? { ...m, content: accumulated } : m,
            ),
          )
        } else if (typeof event === 'object' && 'status' in event) {
          const step = event.status as ActivityStep
          onActivityStep?.(step)
          setMessages(prev =>
            prev.map(m => {
              if (m.id !== assistantId) return m
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
            }),
          )
        } else if (typeof event === 'object' && 'meta' in event) {
          const meta = event.meta
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantId
                ? { ...m, modelUsed: meta.model, category: meta.category }
                : m,
            ),
          )
        }
      }
    } catch {
      accumulated += '\n\n*Error: connection lost*'
    } finally {
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantId
            ? { ...m, content: cleanToolArtifacts(accumulated), isStreaming: false }
            : m,
        ),
      )
      setIsStreaming(false)
      onStreamComplete?.()
    }
  }, [input, isStreaming, messages, modelId, onActivityStep, onStreamComplete])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="absolute top-0 right-0 h-full w-[380px] z-20 flex flex-col bg-black/70 backdrop-blur-xl border-l border-white/[0.06] animate-slide-in-right">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-white/[0.06] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-stone-200">Chat</span>
          {modelId && (
            <span className="text-xs text-stone-600 truncate max-w-[180px]">{modelId}</span>
          )}
        </div>
        <button onClick={onClose} className="text-stone-500 hover:text-stone-300 transition-colors">
          <X size={16} />
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-4 space-y-4 custom-scrollbar">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-stone-600 text-sm text-center px-6">
            <p className="mb-1">Ask Nova anything.</p>
            <p className="text-xs text-stone-700">Watch the graph respond as Nova thinks.</p>
          </div>
        )}
        {messages.map(msg => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
      </div>

      {/* Input */}
      <div className="shrink-0 px-3 pb-3 pt-2 border-t border-white/[0.06]">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask Nova..."
            className="flex-1 bg-white/[0.06] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-stone-200 placeholder:text-stone-600 resize-none outline-none focus:border-teal-500/30 transition-colors"
            rows={1}
            disabled={isStreaming}
          />
          <button
            onClick={handleSubmit}
            disabled={isStreaming || !input.trim()}
            className="shrink-0 flex items-center justify-center w-8 h-8 rounded-lg bg-teal-600/80 hover:bg-teal-600 disabled:opacity-30 disabled:hover:bg-teal-600/80 text-white transition-colors"
          >
            {isStreaming ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          </button>
        </div>
      </div>
    </div>
  )
}
