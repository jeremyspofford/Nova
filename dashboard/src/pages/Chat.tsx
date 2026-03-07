import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send, Bot, User, RefreshCw, MessageSquare } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { streamChat, discoverModels, resolveModel, type ChatMessage, type StreamEvent } from '../api'
import { useChatStore, type Message } from '../stores/chat-store'
import Card from '../components/Card'
import { useNovaIdentity } from '../hooks/useNovaIdentity'

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
        isUser ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300' : 'bg-accent-700 text-white'
      }`}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>

      {/* Bubble */}
      <div className="max-w-[85%] sm:max-w-[75%]">
        <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? 'bg-accent-700 text-white rounded-tr-sm whitespace-pre-wrap'
            : 'bg-card dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-700 text-neutral-900 dark:text-neutral-100 rounded-tl-sm markdown-body overflow-x-auto'
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
                <span className="h-1.5 w-1.5 rounded-full bg-neutral-400 animate-bounce [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 rounded-full bg-neutral-400 animate-bounce [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 rounded-full bg-neutral-400 animate-bounce" />
              </span>
            ) : '—'
          )}
        </div>
        <p className={`mt-1 text-xs text-neutral-500 dark:text-neutral-500 px-1 ${isUser ? 'text-right' : ''}`}>
          {formatDistanceToNow(message.timestamp, { addSuffix: true })}
          {!isUser && message.modelUsed && (
            <span className="ml-1.5">
              &middot; {message.modelUsed}
              {message.category && <span className="text-neutral-400 dark:text-neutral-600"> ({message.category})</span>}
            </span>
          )}
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

  const { name: aiName, greeting } = useNovaIdentity()
  const [input, setInput]             = useState('')
  const [isStreaming, setIsStreaming]  = useState(false)

  const bottomRef   = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

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

  const containerRef = useRef<HTMLDivElement>(null)

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
      // Scroll to keep input visible
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      })
    }
    vv.addEventListener('resize', onResize)
    return () => vv.removeEventListener('resize', onResize)
  }, [])

  const resizeTextarea = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
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
      for await (const event of streamChat(history, modelId || undefined, currentSessionId)) {
        if (typeof event === 'object' && 'meta' in event) {
          // Routing metadata — store on assistant message
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantMsgId
                ? { ...m, modelUsed: event.meta.model, category: event.meta.category }
                : m
            )
          )
          continue
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
    <div ref={containerRef} className="flex flex-col h-[calc(100dvh-57px)] overflow-hidden">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-3 py-2.5 sm:px-6 sm:py-3 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-700 text-white">
            <Bot size={15} />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100 leading-tight">{aiName}</h1>
            <p className="text-[11px] text-neutral-500 dark:text-neutral-400 leading-tight truncate">
              {isStreaming ? 'typing…' : 'online'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <select
            value={modelId}
            onChange={e => setModelId(e.target.value)}
            disabled={isStreaming}
            title={`Override ${aiName}'s default model for this conversation`}
            className="w-24 sm:w-auto rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-2 py-1.5 text-[16px] sm:text-xs text-neutral-700 dark:text-neutral-300 outline-none focus:border-accent-600 disabled:opacity-40"
          >
            <option value="">Auto{resolved ? ` (${resolved.model})` : ''}</option>
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.id} ({m.provider})</option>
            ))}
          </select>

          <button
            onClick={startNewConversation}
            disabled={isStreaming || messages.length === 0}
            title="Start a new conversation"
            className="flex items-center justify-center rounded-md border border-neutral-300 dark:border-neutral-600 p-1.5 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 disabled:opacity-40 transition-colors"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* ── Messages ──────────────────────────────────────────────────────── */}
      <div className={`flex-1 min-h-0 px-3 py-3 sm:px-6 sm:py-6 bg-neutral-50 dark:bg-neutral-950 ${messages.length > 0 ? 'overflow-y-auto space-y-4' : 'flex items-center justify-center'}`}>
        {messages.length === 0 && (
          <div className="flex flex-col items-center gap-4 text-neutral-400 dark:text-neutral-600 select-none">
            <MessageSquare size={44} strokeWidth={1} />
            <div className="text-center space-y-1">
              <p className="text-sm font-medium text-neutral-500 dark:text-neutral-400">{`Start a conversation with ${aiName}`}</p>
              <p className="text-xs text-neutral-500 dark:text-neutral-400 max-w-sm">
                {`${aiName} has persistent memory, can use tools, and remembers previous sessions.`}
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
      <div className="border-t border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-3 py-2 sm:px-6 sm:py-3 shrink-0 safe-area-pb">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => { setInput(e.target.value); resizeTextarea() }}
            onKeyDown={handleKeyDown}
            placeholder={`Message ${aiName}...`}
            rows={1}
            className="flex-1 resize-none overflow-hidden rounded-2xl border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-4 py-2.5 text-base text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 dark:placeholder:text-neutral-500 outline-none focus:border-accent-600 disabled:opacity-50 transition-colors"
            style={{ minHeight: '42px', maxHeight: '120px', fontSize: '16px' }}
          />
          <button
            onClick={handleSubmit}
            disabled={!input.trim() || isStreaming}
            className="flex items-center justify-center rounded-full bg-accent-700 p-2.5 text-white hover:bg-accent-500 disabled:opacity-40 transition-colors shrink-0"
            style={{ height: '42px', width: '42px' }}
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
