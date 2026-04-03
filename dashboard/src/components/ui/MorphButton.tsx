import { useState, useRef, useCallback } from 'react'
import { Send, Mic, Square, Loader2 } from 'lucide-react'
import clsx from 'clsx'

interface MorphButtonProps {
  hasText: boolean
  isRecording: boolean
  isTranscribing: boolean
  conversationMode: boolean
  voiceAvailable: boolean
  onSend: () => void
  onToggleRecording: () => void
  onStartConversation: () => void
  onStopConversation: () => void
}

type MorphState = 'mic' | 'send' | 'stop-recording' | 'stop-conversation' | 'transcribing'

function getMorphState(props: MorphButtonProps): MorphState {
  // Priority order per spec
  if (props.isRecording) return 'stop-recording'
  if (props.conversationMode) return 'stop-conversation'
  if (props.isTranscribing) return 'transcribing'
  if (props.hasText) return 'send'
  if (props.voiceAvailable) return 'mic'
  return 'send' // No voice: always show send (disabled when empty via hasText)
}

const LONG_PRESS_MS = 500

export function MorphButton(props: MorphButtonProps) {
  const { voiceAvailable, onSend, onToggleRecording, onStartConversation, onStopConversation } = props
  const state = getMorphState(props)
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [longPressTriggered, setLongPressTriggered] = useState(false)
  const [showHint, setShowHint] = useState(() => {
    try { return !localStorage.getItem('nova_morph_hint_dismissed') } catch { return true }
  })

  const handlePointerDown = useCallback(() => {
    if (state !== 'mic' || !voiceAvailable) return
    setLongPressTriggered(false)
    longPressTimer.current = setTimeout(() => {
      setLongPressTriggered(true)
      onStartConversation()
      // Dismiss hint permanently
      if (showHint) {
        setShowHint(false)
        try { localStorage.setItem('nova_morph_hint_dismissed', '1') } catch {}
      }
    }, LONG_PRESS_MS)
  }, [state, voiceAvailable, onStartConversation, showHint])

  const handlePointerUp = useCallback(() => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
    // If long press already triggered conversation mode, don't also do a tap action
    if (longPressTriggered) {
      setLongPressTriggered(false)
      return
    }
  }, [longPressTriggered])

  const handleClick = useCallback(() => {
    if (longPressTriggered) return // handled by pointerUp
    switch (state) {
      case 'send': onSend(); break
      case 'mic': onStartConversation(); break  // Tap mic = start conversation mode
      case 'stop-recording': onToggleRecording(); break
      case 'stop-conversation': onStopConversation(); break
      case 'transcribing': break // disabled
    }
  }, [state, longPressTriggered, onSend, onToggleRecording, onStartConversation, onStopConversation])

  const disabled = state === 'transcribing'
  const isStop = state === 'stop-recording'
  const isConvStop = state === 'stop-conversation'

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={handleClick}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        disabled={disabled}
        className={clsx(
          'w-11 h-11 rounded-full flex items-center justify-center transition-all duration-150 shrink-0',
          isStop
            ? 'bg-danger text-white hover:bg-red-500'
            : isConvStop
              ? 'bg-amber-500 text-neutral-950 hover:bg-amber-400'
              : 'bg-teal-500 hover:bg-teal-600 text-white shadow-[0_0_12px_rgba(25,168,158,0.3)] hover:shadow-[0_0_20px_rgba(25,168,158,0.4)]',
          disabled && 'opacity-40 cursor-wait',
        )}
      >
        {state === 'transcribing' && <Loader2 size={16} className="animate-spin" />}
        {state === 'send' && <Send size={16} />}
        {state === 'mic' && <Mic size={16} />}
        {state === 'stop-recording' && <Square size={14} fill="currentColor" />}
        {state === 'stop-conversation' && <Square size={14} fill="currentColor" />}
      </button>
      {/* One-time hint for long-press — desktop only, too cluttered on mobile */}
      {showHint && state === 'mic' && voiceAvailable && (
        <div className="hidden md:block absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap bg-surface-elevated text-content-secondary text-micro px-2 py-1 rounded-md shadow-sm border border-border-subtle pointer-events-none animate-fade-in">
          Hold for conversation
        </div>
      )}
    </div>
  )
}
