import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  isStreaming?: boolean
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
}

const ChatContext = createContext<ChatStore | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [modelId, setModelId] = useState('')
  const [error, setError] = useState<string | null>(null)

  const resetConversation = useCallback(() => {
    setMessages([])
    setSessionId(undefined)
    setError(null)
  }, [])

  return (
    <ChatContext.Provider value={{
      messages, setMessages,
      sessionId, setSessionId,
      modelId, setModelId,
      error, setError,
      resetConversation,
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
