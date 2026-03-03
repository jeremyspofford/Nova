import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send, Bot, User, RefreshCw, MessageSquare } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { streamChat, getModels, type ChatMessage } from '../api'
import { useChatStore, type Message } from '../stores/chat-store'

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
        isUser ? 'bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-300' : 'bg-teal-700 text-white'
      }`}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>

      {/* Bubble */}
      <div className="max-w-[85%] sm:max-w-[75%]">
        <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? 'bg-teal-700 text-white rounded-tr-sm whitespace-pre-wrap'
            : 'bg-white dark:bg-stone-900 border border-stone-300 dark:border-stone-700 text-stone-900 dark:text-stone-100 rounded-tl-sm markdown-body overflow-x-auto'
        }`}>
          {message.content ? (
            isUser ? message.content : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            )
          ) : (
            message.isStreaming ? (
              <span className="inline-flex items-center gap-1 py-1">
                <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce" />
              </span>
            ) : '—'
          )}
        </div>
        <p className={`mt-1 text-xs text-stone-500 dark:text-stone-500 px-1 ${isUser ? 'text-right' : ''}`}>
          {formatDistanceToNow(message.timestamp, { addSuffix: true })}
        </p>
      </div>
    </div>
  )
}

// ── Chat page ─────────────────────────────────────────────────────────────────

export function Chat() {
  const {
    messages, setMessages,
    sessionId, setSessionId,
    modelId, setModelId,
    error, setError,
    resetConversation,
  } = useChatStore()

  const [input, setInput]             = useState('')
  const [isStreaming, setIsStreaming]  = useState(false)

  const bottomRef   = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { data: modelsData } = useQuery({
    queryKey: ['models'],
    queryFn: getModels,
    staleTime: 60_000,
  })
  const models = modelsData?.data ?? []

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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

    const currentSessionId = sessionId ?? (() => {
      const newId = crypto.randomUUID()
      setSessionId(newId)
      return newId
    })()

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
  }, [input, messages, sessionId, modelId, isStreaming, setMessages, setSessionId, setError])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const startNewConversation = () => {
    resetConversation()
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    textareaRef.current?.focus()
  }

  return (
    <div className="flex flex-col h-[calc(100vh-57px)]">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 px-4 py-3 sm:px-6 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-sm font-semibold text-stone-900 dark:text-stone-100 shrink-0">Nova Chat</h1>
          <span className="hidden sm:inline text-xs text-stone-500 dark:text-stone-400 truncate">
            Direct conversation with the Nova agent — has memory and tools
          </span>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={modelId}
            onChange={e => setModelId(e.target.value)}
            disabled={isStreaming}
            title="Override Nova's default model for this conversation"
            className="rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-2 py-1.5 text-xs text-stone-700 dark:text-stone-300 outline-none focus:border-teal-600 disabled:opacity-40"
          >
            <option value="">Nova default model</option>
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.id}</option>
            ))}
          </select>

          <button
            onClick={startNewConversation}
            disabled={isStreaming || messages.length === 0}
            title="Start a new conversation (clears history)"
            className="flex items-center gap-1.5 rounded-md border border-stone-300 dark:border-stone-600 px-3 py-1.5 text-xs text-stone-500 dark:text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-800 hover:text-stone-900 dark:hover:text-stone-100 disabled:opacity-40 transition-colors"
          >
            <RefreshCw size={11} />
            New
          </button>
        </div>
      </div>

      {/* ── Messages ──────────────────────────────────────────────────────── */}
      <div className={`flex-1 min-h-0 px-4 py-4 sm:px-6 sm:py-6 ${messages.length > 0 ? 'overflow-y-auto space-y-5' : 'flex items-center justify-center'}`}>
        {messages.length === 0 && (
          <div className="flex flex-col items-center gap-4 text-stone-400 dark:text-stone-600 select-none">
            <MessageSquare size={44} strokeWidth={1} />
            <div className="text-center space-y-1">
              <p className="text-sm font-medium text-stone-500 dark:text-stone-400">Start a conversation with Nova</p>
              <p className="text-xs text-stone-400 dark:text-stone-500 max-w-sm">
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
          <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950 px-4 py-3 text-sm text-red-700 dark:text-red-400">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input ─────────────────────────────────────────────────────────── */}
      <div className="border-t border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 px-4 py-3 sm:px-6 sm:py-4 shrink-0">
        <div className="flex items-end gap-2 sm:gap-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => { setInput(e.target.value); resizeTextarea() }}
            onKeyDown={handleKeyDown}
            placeholder="Message Nova… (Enter to send, Shift+Enter for newline)"
            disabled={isStreaming}
            rows={1}
            className="flex-1 resize-none overflow-hidden rounded-xl border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-4 py-2.5 text-sm text-stone-900 dark:text-stone-100 placeholder:text-stone-400 dark:placeholder:text-stone-500 outline-none focus:border-teal-600 disabled:opacity-50 transition-colors"
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

        <div className="mt-2 flex items-center justify-between text-xs text-stone-500 dark:text-stone-400">
          <span>
            {isStreaming
              ? 'Nova is responding…'
              : sessionId
                ? `Session ${sessionId.slice(0, 8)}… · ${messages.filter(m => m.role === 'user').length} messages`
                : 'New session · Enter to send'}
          </span>
          {modelId && (
            <span className="font-mono text-teal-600 dark:text-teal-400">{modelId}</span>
          )}
        </div>
      </div>
    </div>
  )
}
