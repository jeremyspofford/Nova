import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, Send, Loader2, Mic, Volume2, VolumeX, AudioLines } from 'lucide-react'
import { streamChat, resolveModel, discoverModels, type ChatMessage } from '../api'
import { cleanToolArtifacts } from '../utils/cleanToolArtifacts'
import { useVoiceChat, type ConversationState } from '../hooks/useVoiceChat'
import { useAudioLevel } from '../hooks/useAudioLevel'
import { useSpeechToText } from '../hooks/useSpeechToText'
import { AudioLevelIndicator } from './ui/AudioLevelIndicator'
import { MessageBubble } from '../pages/chat/MessageBubble'
import { useChatStore } from '../stores/chat-store'
import type { Message, ActivityStep } from '../stores/chat-store'
import { ModelPicker } from './ui/ModelPicker'
import { getHiddenModels } from './ModelManagerModal'

const CONV_STATE_LABELS: Record<ConversationState, string> = {
  idle: '',
  listening: 'Listening...',
  processing: 'Thinking...',
  speaking: 'Speaking... interrupt anytime',
}

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
  const pendingTranscriptRef = useRef<string | null>(null)

  // Use shared model from chat store (syncs with main Chat page)
  const { modelId: sharedModelId, setModelId } = useChatStore()

  // Model catalog for picker
  const { data: providers } = useQuery({
    queryKey: ['model-catalog'],
    queryFn: () => discoverModels(),
    staleTime: 60_000,
  })
  const hiddenModels = getHiddenModels()
  const models = (providers ?? [])
    .filter(p => p.available)
    .flatMap(p => p.models.filter(m => m.registered).map(m => ({ id: m.id, provider: p.name })))
    .filter(m => !hiddenModels.has(m.id))

  // Fallback to resolved model if chat store has no selection
  const { data: resolved } = useQuery({
    queryKey: ['resolve-model'],
    queryFn: resolveModel,
    staleTime: 60_000,
  })
  const modelId = sharedModelId || resolved?.model || ''

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

  // Read conversation mode settings from localStorage
  const silenceTimeoutMs = Number(localStorage.getItem('nova_voice_silence_timeout')) || 2000
  const bargeInThreshold = Number(localStorage.getItem('nova_voice_bargein_threshold')) || 0.15

  // Voice chat integration
  const handleSubmitRef = useRef<(text?: string) => void>(() => {})

  const {
    isRecording, isTranscribing, recordingDuration,
    toggleRecording, isSpeaking, muted, setMuted,
    feedText, flushBuffer, stopAllPlayback, voiceAvailable,
    mediaStream,
    conversationMode, setConversationMode, conversationState, silenceCountdown,
  } = useVoiceChat({
    onTranscript: (text) => {
      if (isStreaming) {
        pendingTranscriptRef.current = text
      } else {
        handleSubmitRef.current(text)
      }
    },
    onError: (err) => {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant' as const,
        content: `*${err}*`,
        timestamp: new Date(),
      }])
    },
    silenceTimeoutMs,
    bargeInThreshold,
  })

  // Audio level visualization from recording stream
  const audioLevel = useAudioLevel(mediaStream)

  // Parallel Web Speech API for live transcript display during recording
  const { isListening: sttListening, transcript: liveTranscript, start: sttStart, stop: sttStop, isSupported: sttSupported } = useSpeechToText()

  // Start/stop Web Speech API in sync with recording for live transcript
  useEffect(() => {
    if (!sttSupported) return
    if (isRecording && !sttListening) sttStart()
    if (!isRecording && sttListening) sttStop()
  }, [isRecording, sttListening, sttSupported, sttStart, sttStop])

  // Conversation mode: auto-listen when muted and stream finishes (TTS skipped)
  useEffect(() => {
    if (conversationMode && muted && !isStreaming && !isRecording && !isTranscribing && !isSpeaking) {
      // When muted, TTS is skipped so isSpeaking never goes true.
      // Auto-listen after a short delay for the response to fully settle.
      const timer = setTimeout(() => {
        if (conversationMode && !isRecording) {
          toggleRecording()
        }
      }, 500)
      return () => clearTimeout(timer)
    }
  }, [conversationMode, muted, isStreaming, isRecording, isTranscribing, isSpeaking, toggleRecording])

  const handleSubmit = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? input).trim()
    if (!text || isStreaming) return
    if (!overrideText) setInput('')

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
          feedText(event)  // Feed to TTS sentence buffer
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
      flushBuffer()  // Flush remaining TTS buffer
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
  }, [input, isStreaming, messages, modelId, onActivityStep, onStreamComplete, feedText, flushBuffer])

  // Keep ref in sync so voice callbacks always call latest handleSubmit
  useEffect(() => {
    handleSubmitRef.current = handleSubmit
  }, [handleSubmit])

  // Drain pending voice transcript when streaming ends
  useEffect(() => {
    if (!isStreaming && pendingTranscriptRef.current) {
      const text = pendingTranscriptRef.current
      pendingTranscriptRef.current = null
      handleSubmit(text)
    }
  }, [isStreaming, handleSubmit])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // Silence countdown for visual indicator
  const silencePct = silenceCountdown > 0 ? (silenceCountdown / silenceTimeoutMs) * 100 : 0

  return (
    <div className="fixed bottom-5 right-5 z-20 w-[420px] lg:w-[420px] md:w-[360px] h-[calc(100vh-80px)] flex flex-col overflow-hidden rounded-2xl bg-[rgba(8,45,42,0.35)] [backdrop-filter:blur(60px)_saturate(1.8)] [-webkit-backdrop-filter:blur(60px)_saturate(1.8)] border border-[rgba(255,255,255,0.12)] border-t-[rgba(255,255,255,0.20)] shadow-[0_8px_40px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.12),inset_0_-1px_0_rgba(0,0,0,0.15)]">
      {/* Header */}
      <div className="shrink-0 min-h-[48px] flex items-center px-4 border-b border-[rgba(68,64,60,0.55)]">
        <span className="text-sm font-semibold text-stone-200">Chat with Nova</span>
        <span className="ml-2 px-2.5 py-0.5 text-[11px] font-mono text-teal-400 bg-teal-500/15 rounded-full truncate max-w-[140px]">
          {modelId || 'auto'}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {voiceAvailable && (
            <button
              onClick={() => setMuted(m => !m)}
              className="text-stone-500 hover:text-stone-300 transition-colors"
              title={muted ? 'Unmute voice' : 'Mute voice'}
            >
              {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
            </button>
          )}
          <ModelPicker
            value={modelId}
            onChange={setModelId}
            models={models}
            className="w-36"
          />
          <button onClick={onClose} className="text-stone-500 hover:text-stone-300 transition-colors" title="Minimize chat">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-4 space-y-4 custom-scrollbar">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-stone-600 text-sm text-center px-6">
            <p className="mb-1">Ask Nova anything.</p>
            <p className="text-xs text-stone-700">Watch the graph respond as Nova thinks.</p>
          </div>
        )}
        {messages.map(msg => {
          const activatedCount = msg.activitySteps
            ?.filter(s => s.engram_ids && s.engram_ids.length > 0)
            .reduce((sum, s) => sum + (s.engram_ids?.length ?? 0), 0) ?? 0
          return (
            <div key={msg.id}>
              <MessageBubble message={msg} />
              {activatedCount > 0 && (
                <span className="text-[11px] italic text-stone-500 mt-1 block pl-1">
                  ({activatedCount} node{activatedCount !== 1 ? 's' : ''} activated)
                </span>
              )}
            </div>
          )
        })}
      </div>

      {/* Input */}
      <div className="shrink-0 px-3 pb-3 pt-2 border-t border-[rgba(68,64,60,0.55)]">
        {/* Conversation mode status bar */}
        {conversationMode && (
          <div className="flex items-center gap-2 px-2 py-1.5 mb-2 rounded-md border text-xs relative overflow-hidden"
            style={{
              backgroundColor: conversationState === 'listening' ? 'rgba(127, 29, 29, 0.4)' :
                               conversationState === 'speaking' ? 'rgba(20, 83, 45, 0.3)' :
                               'rgba(41, 37, 36, 0.5)',
              borderColor: conversationState === 'listening' ? 'rgba(239, 68, 68, 0.2)' :
                           conversationState === 'speaking' ? 'rgba(34, 197, 94, 0.2)' :
                           'rgba(255, 255, 255, 0.06)',
            }}
          >
            {/* Silence countdown progress bar */}
            {silencePct > 0 && (
              <div
                className="absolute inset-y-0 left-0 bg-amber-500/10 transition-all duration-100"
                style={{ width: `${100 - silencePct}%` }}
              />
            )}
            <div className="relative flex items-center gap-2 w-full">
              {conversationState === 'listening' && (
                <>
                  <Mic size={12} className="text-red-400 shrink-0 animate-pulse" />
                  <AudioLevelIndicator level={audioLevel} bars={4} className="h-3 shrink-0" />
                  <span className="text-stone-400 truncate">
                    {liveTranscript || 'Listening...'}
                  </span>
                  <span className="text-stone-600 shrink-0 ml-auto">{Math.floor(recordingDuration / 1000)}s</span>
                </>
              )}
              {conversationState === 'processing' && (
                <>
                  <Loader2 size={12} className="text-stone-400 shrink-0 animate-spin" />
                  <span className="text-stone-400">Thinking...</span>
                </>
              )}
              {conversationState === 'speaking' && (
                <>
                  <Volume2 size={12} className="text-green-400 shrink-0" />
                  <span className="text-stone-400">Speaking... interrupt anytime</span>
                </>
              )}
              {conversationState === 'idle' && (
                <span className="text-stone-500">Conversation mode — waiting...</span>
              )}
            </div>
          </div>
        )}

        {/* Non-conversation recording indicator */}
        {!conversationMode && isRecording && (
          <div className="flex items-center gap-2 px-2 py-1.5 mb-2 rounded-md bg-red-950/40 border border-red-500/20 text-xs">
            <Mic size={12} className="text-red-400 shrink-0 animate-pulse" />
            <AudioLevelIndicator level={audioLevel} bars={4} className="h-3 shrink-0" />
            <span className="text-stone-400 truncate">
              {liveTranscript || 'Listening...'}
            </span>
            <span className="text-stone-600 shrink-0 ml-auto">{Math.floor(recordingDuration / 1000)}s</span>
          </div>
        )}

        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={conversationMode ? 'Conversation mode active (Esc to exit)' : 'Ask Nova...'}
            className="flex-1 bg-white/[0.06] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-stone-200 placeholder:text-stone-600 resize-none outline-none focus:border-teal-500/30 transition-colors"
            rows={1}
            disabled={isStreaming || conversationMode}
          />
          {voiceAvailable && (
            <>
              {/* Conversation mode toggle */}
              <button
                onClick={() => setConversationMode(m => !m)}
                disabled={isTranscribing}
                className={`shrink-0 flex items-center justify-center w-8 h-8 rounded-lg transition-colors ${
                  conversationMode
                    ? 'bg-teal-600 hover:bg-teal-500 ring-1 ring-teal-400/50'
                    : 'bg-stone-700 hover:bg-stone-600'
                } text-white`}
                title={conversationMode ? 'Exit conversation mode (Esc)' : 'Start conversation mode'}
              >
                <AudioLines size={14} />
              </button>

              {/* Manual mic button (hidden in conversation mode) */}
              {!conversationMode && (
                <button
                  onClick={toggleRecording}
                  disabled={isTranscribing}
                  className={`shrink-0 flex items-center justify-center w-8 h-8 rounded-lg transition-colors ${
                    isRecording
                      ? 'bg-red-600 hover:bg-red-500'
                      : isTranscribing
                        ? 'bg-stone-700 cursor-wait'
                        : 'bg-stone-700 hover:bg-stone-600'
                  } text-white`}
                  title={isRecording ? 'Stop recording' : 'Push to talk'}
                >
                  {isTranscribing ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />}
                </button>
              )}
            </>
          )}
          <button
            onClick={() => handleSubmit()}
            disabled={isStreaming || !input.trim() || conversationMode}
            className="shrink-0 flex items-center justify-center w-8 h-8 rounded-lg bg-teal-600/80 hover:bg-teal-600 disabled:opacity-30 disabled:hover:bg-teal-600/80 text-white transition-colors"
          >
            {isStreaming ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          </button>
        </div>
      </div>
    </div>
  )
}
