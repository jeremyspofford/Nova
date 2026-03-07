import { createContext, useContext, useState, useCallback, useEffect, useRef, type ReactNode } from 'react'
import { summarizeSession } from '../api'

export interface ActivityStep {
  step: string
  state: 'running' | 'done'
  detail?: string
  elapsed_ms?: number
  model?: string
  category?: string | null
  startedAt?: number  // Date.now(), set client-side for live timer
}

export interface AttachedFile {
  id: string
  file: File
  previewUrl: string | null  // blob URL for images, null for text files
  type: 'image' | 'text'
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  isStreaming?: boolean
  modelUsed?: string
  category?: string
  activitySteps?: ActivityStep[]
  activityCollapsed?: boolean
  attachments?: AttachedFile[]
}

interface ChatStore {
  messages: Message[]
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  sessionId: string | undefined
  setSessionId: React.Dispatch<React.SetStateAction<string | undefined>>
  modelId: string
  setModelId: React.Dispatch<React.SetStateAction<string>>
  error: string | null
  setError: React.Dispatch<React.SetStateAction<string | null>>
  resetConversation: () => void

  // Pre-fill input from external pages (e.g. "Discuss" on Tasks page)
  prefillInput: string | null
  setPrefillInput: React.Dispatch<React.SetStateAction<string | null>>

  // Drawer & input controls
  pendingFiles: AttachedFile[]
  setPendingFiles: React.Dispatch<React.SetStateAction<AttachedFile[]>>
  drawerOpen: boolean
  setDrawerOpen: React.Dispatch<React.SetStateAction<boolean>>
  outputStyle: string
  setOutputStyle: React.Dispatch<React.SetStateAction<string>>
  customInstructions: string
  setCustomInstructions: React.Dispatch<React.SetStateAction<string>>
  webSearchEnabled: boolean
  setWebSearchEnabled: React.Dispatch<React.SetStateAction<boolean>>
  deepResearchEnabled: boolean
  setDeepResearchEnabled: React.Dispatch<React.SetStateAction<boolean>>
}

const STORAGE_KEY = 'nova_chat_history'

/** Serializable subset of Message for localStorage. */
interface PersistedChat {
  sessionId: string | undefined
  messages: Array<{
    id: string
    role: 'user' | 'assistant'
    content: string
    timestamp: string
    modelUsed?: string
    category?: string
  }>
}

function loadPersistedChat(): { messages: Message[]; sessionId: string | undefined } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { messages: [], sessionId: undefined }
    const data: PersistedChat = JSON.parse(raw)
    const messages = data.messages.map(m => ({
      ...m,
      timestamp: new Date(m.timestamp),
    }))
    return { messages, sessionId: data.sessionId }
  } catch {
    return { messages: [], sessionId: undefined }
  }
}

function saveChat(messages: Message[], sessionId: string | undefined) {
  try {
    const data: PersistedChat = {
      sessionId,
      messages: messages.map(m => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: m.timestamp.toISOString(),
        ...(m.modelUsed ? { modelUsed: m.modelUsed } : {}),
        ...(m.category ? { category: m.category } : {}),
      })),
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    // localStorage full or unavailable — silently ignore
  }
}

const ChatContext = createContext<ChatStore | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const [persisted] = useState(loadPersistedChat)
  const [messages, setMessages] = useState<Message[]>(persisted.messages)
  const [sessionId, setSessionId] = useState<string | undefined>(persisted.sessionId)
  const [modelId, _setModelId] = useState(
    () => localStorage.getItem('nova_chat_model') ?? ''
  )
  const setModelId: React.Dispatch<React.SetStateAction<string>> = useCallback((val) => {
    _setModelId(prev => {
      const next = typeof val === 'function' ? val(prev) : val
      localStorage.setItem('nova_chat_model', next)
      return next
    })
  }, [])
  const [error, setError] = useState<string | null>(null)

  // Refs for current values — needed by resetConversation's stable callback
  const messagesRef = useRef(messages)
  const sessionIdRef = useRef(sessionId)
  useEffect(() => { messagesRef.current = messages }, [messages])
  useEffect(() => { sessionIdRef.current = sessionId }, [sessionId])

  const [prefillInput, setPrefillInput] = useState<string | null>(null)
  const [pendingFiles, setPendingFiles] = useState<AttachedFile[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [outputStyle, setOutputStyle] = useState(
    () => localStorage.getItem('nova_output_style') ?? ''
  )
  const [customInstructions, setCustomInstructions] = useState(
    () => localStorage.getItem('nova_custom_instructions') ?? ''
  )
  const [webSearchEnabled, setWebSearchEnabled] = useState(false)
  const [deepResearchEnabled, setDeepResearchEnabled] = useState(false)

  // Persist messages + sessionId to localStorage on change (skip streaming updates)
  const saveTimer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => {
    // Debounce saves — don't write on every streaming token
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      const hasStreaming = messages.some(m => m.isStreaming)
      if (!hasStreaming) {
        saveChat(messages, sessionId)
      }
    }, 300)
    return () => clearTimeout(saveTimer.current)
  }, [messages, sessionId])

  const resetConversation = useCallback(() => {
    // Summarize the completed conversation before clearing (fire-and-forget)
    if (sessionIdRef.current && messagesRef.current.length >= 2) {
      summarizeSession(
        sessionIdRef.current,
        messagesRef.current.map(m => ({ role: m.role, content: m.content })),
      )
    }
    setMessages([])
    setSessionId(undefined)
    setError(null)
    setPendingFiles([])
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  return (
    <ChatContext.Provider value={{
      messages, setMessages,
      sessionId, setSessionId,
      modelId, setModelId,
      error, setError,
      resetConversation,
      prefillInput, setPrefillInput,
      pendingFiles, setPendingFiles,
      drawerOpen, setDrawerOpen,
      outputStyle, setOutputStyle,
      customInstructions, setCustomInstructions,
      webSearchEnabled, setWebSearchEnabled,
      deepResearchEnabled, setDeepResearchEnabled,
    }}>
      {children}
    </ChatContext.Provider>
  )
}

export function useChatStore(): ChatStore {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChatStore must be used within ChatProvider')
  return ctx
}
