import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send, Bot, User, RefreshCw, MessageSquare } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { streamChat, getModels, type ChatMessage } from '../api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  isStreaming?: boolean
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
        isUser ? 'bg-stone-200 text-stone-600' : 'bg-teal-700 text-white'
      }`}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>

      {/* Bubble */}
      <div className="max-w-[75%]">
        <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-teal-700 text-white rounded-tr-sm'
            : 'bg-white border border-stone-200 text-stone-900 rounded-tl-sm'
        }`}>
          {message.content || (
            message.isStreaming ? (
              /* Typing indicator while waiting for first token */
              <span className="inline-flex items-center gap-1 py-1">
                <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce" />
              </span>
            ) : '—'
          )}
        </div>
        <p className={`mt-1 text-xs text-stone-400 px-1 ${isUser ? 'text-right' : ''}`}>
          {formatDistanceToNow(message.timestamp, { addSuffix: true })}
        </p>
      </div>
    </div>
  )
}

// ── Chat page ─────────────────────────────────────────────────────────────────

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput]           = useState('')
  const [sessionId, setSessionId]   = useState<string | undefined>(undefined)
  const [modelId, setModelId]       = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError]           = useState<string | null>(null)

  const bottomRef   = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { data: modelsData } = useQuery({
    queryKey: ['models'],
    queryFn: getModels,
    staleTime: 60_000,
  })
  const models = modelsData?.data ?? []

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-resize textarea
  const resizeTextarea = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }

  const handleSubmit = useCallback(async () => {
    const text = input.trim()
    if (!text || isStreaming) return

    setError(null)
    setInput('')
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = 'auto'

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date(),
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

    // Establish or reuse the session ID.
    // Generate once per conversation and hold it in state so all turns share
    // the same memory thread in the orchestrator.
    const currentSessionId = sessionId ?? (() => {
      const newId = crypto.randomUUID()
      setSessionId(newId)
      return newId
    })()

    // Build conversation history for the API (all prior messages + new user turn)
    const history: ChatMessage[] = [
      ...messages.map(m => ({ role: m.role as ChatMessage['role'], content: m.content })),
      { role: 'user', content: text },
    ]

    try {
      let accumulated = ''
      for await (const delta of streamChat(history, modelId || undefined, currentSessionId)) {
        accumulated += delta
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMsgId ? { ...m, content: accumulated } : m
          )
        )
      }
      // Mark streaming complete
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
      textareaRef.current?.focus()
    }
  }, [input, messages, sessionId, modelId, isStreaming])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const startNewConversation = () => {
    setMessages([])
    setSessionId(undefined)
    setError(null)
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    textareaRef.current?.focus()
  }

  return (
    <div className="flex flex-col h-[calc(100vh-57px)]">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-stone-200 bg-white px-6 py-3 shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-semibold text-stone-900">Nova Chat</h1>
          <span className="text-xs text-stone-400">
            Direct conversation with the Nova agent — has memory and tools
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Model selector */}
          <select
            value={modelId}
            onChange={e => setModelId(e.target.value)}
            disabled={isStreaming}
            title="Override Nova's default model for this conversation"
            className="rounded-md border border-stone-300 bg-stone-50 px-2 py-1.5 text-xs text-stone-700 outline-none focus:border-teal-600 disabled:opacity-40"
          >
            <option value="">Nova default model</option>
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.id}</option>
            ))}
          </select>

          {/* New conversation */}
          <button
            onClick={startNewConversation}
            disabled={isStreaming || messages.length === 0}
            title="Start a new conversation (clears history)"
            className="flex items-center gap-1.5 rounded-md border border-stone-300 px-3 py-1.5 text-xs text-stone-500 hover:bg-stone-100 hover:text-stone-900 disabled:opacity-40 transition-colors"
          >
            <RefreshCw size={11} />
            New
          </button>
        </div>
      </div>

      {/* ── Messages ──────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-stone-300 select-none">
            <MessageSquare size={44} strokeWidth={1} />
            <div className="text-center space-y-1">
              <p className="text-sm font-medium text-stone-400">Start a conversation with Nova</p>
              <p className="text-xs text-stone-300 max-w-sm">
                Nova has persistent memory, can use tools (filesystem, shell, git),
                and remembers previous sessions.
              </p>
            </div>
          </div>
        )}

        {messages.map(msg => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input ─────────────────────────────────────────────────────────── */}
      <div className="border-t border-stone-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-end gap-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => { setInput(e.target.value); resizeTextarea() }}
            onKeyDown={handleKeyDown}
            placeholder="Message Nova… (Enter to send, Shift+Enter for newline)"
            disabled={isStreaming}
            rows={1}
            className="flex-1 resize-none overflow-hidden rounded-xl border border-stone-300 bg-stone-50 px-4 py-2.5 text-sm text-stone-900 placeholder:text-stone-400 outline-none focus:border-teal-600 disabled:opacity-50 transition-colors"
            style={{ minHeight: '42px', maxHeight: '160px' }}
          />
          <button
            onClick={handleSubmit}
            disabled={!input.trim() || isStreaming}
            className="flex items-center justify-center rounded-xl bg-teal-700 p-2.5 text-white hover:bg-teal-500 disabled:opacity-40 transition-colors shrink-0"
            style={{ height: '42px', width: '42px' }}
          >
            <Send size={15} />
          </button>
        </div>

        {/* Status bar */}
        <div className="mt-2 flex items-center justify-between text-xs text-stone-400">
          <span>
            {isStreaming
              ? 'Nova is responding…'
              : sessionId
                ? `Session ${sessionId.slice(0, 8)}… · ${messages.filter(m => m.role === 'user').length} messages`
                : 'New session · Enter to send'}
          </span>
          {modelId && (
            <span className="font-mono text-teal-600">{modelId}</span>
          )}
        </div>
      </div>
    </div>
  )
}
