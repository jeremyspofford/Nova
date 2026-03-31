import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Plus, SlidersHorizontal, Mic, Loader2, Volume2, VolumeX, AudioLines } from 'lucide-react'
import clsx from 'clsx'
import { useChatStore } from '../../stores/chat-store'
import { useFileAttach } from '../../hooks/useFileAttach'
import { useAudioLevel } from '../../hooks/useAudioLevel'
import { useSpeechToText } from '../../hooks/useSpeechToText'
import { InputDrawer } from './InputDrawer'
import { FilePreviewBar } from './FilePreviewBar'
import { AudioLevelIndicator } from '../../components/ui/AudioLevelIndicator'
import { Tooltip } from '../../components/ui/Tooltip'
import { ModelPicker } from '../../components/ui/ModelPicker'
import type { ConversationState } from '../../hooks/useVoiceChat'

export interface VoiceControls {
  available: boolean
  isRecording: boolean
  isTranscribing: boolean
  isSpeaking: boolean
  recordingDuration: number
  toggleRecording: () => void
  muted: boolean
  setMuted: (m: boolean | ((prev: boolean) => boolean)) => void
  conversationMode: boolean
  setConversationMode: (m: boolean | ((prev: boolean) => boolean)) => void
  conversationState: ConversationState
  silenceCountdown: number
  silenceTimeoutMs: number
  mediaStream: MediaStream | null
}

interface Props {
  onSubmit: (text: string) => void
  isStreaming: boolean
  aiName: string
  models: Array<{ id: string; provider: string }>
  modelId: string
  onModelChange: (id: string) => void
  resolvedModel?: string
  hasMessages: boolean
  onManageModels: () => void
  voice?: VoiceControls
}

export function ChatInput({ onSubmit, isStreaming, aiName, models, modelId, onModelChange, resolvedModel, hasMessages, onManageModels, voice }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dropZoneRef = useRef<HTMLDivElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  const { draftInput: input, setDraftInput: setInput, drawerOpen, setDrawerOpen, prefillInput, setPrefillInput } = useChatStore()
  const { pendingFiles, addFiles, removeFile, openFilePicker } = useFileAttach()

  // Audio level from voice recording stream (for visualizer bars)
  const audioLevel = useAudioLevel(voice?.mediaStream ?? null)

  // Browser Web Speech API for live transcript display while server-side STT processes
  const { isListening: sttListening, transcript: liveTranscript, start: sttStart, stop: sttStop, isSupported: sttSupported } = useSpeechToText()

  // Sync browser STT start/stop with server-side recording state
  useEffect(() => {
    if (!sttSupported || !voice) return
    if (voice.isRecording && !sttListening) sttStart()
    if (!voice.isRecording && sttListening) sttStop()
  }, [voice?.isRecording, sttListening, sttSupported, sttStart, sttStop])

  // Consume prefilled input (e.g. from "Discuss" on Tasks page)
  useEffect(() => {
    if (prefillInput) {
      setInput(prefillInput)
      setPrefillInput(null)
      setTimeout(() => {
        resizeTextarea()
        textareaRef.current?.focus()
      }, 0)
    }
  }, [prefillInput, setPrefillInput])

  const resizeTextarea = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxH = el.value.split('\n').length > 5 ? 400 : 200
    el.style.height = `${Math.min(el.scrollHeight, maxH)}px`
  }

  const handleSubmit = useCallback(() => {
    const text = input.trim()
    if (!text) return
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    onSubmit(text)
  }, [input, onSubmit])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // Clipboard paste for images
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    const onPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items
      if (!items) return
      const files: File[] = []
      for (let i = 0; i < items.length; i++) {
        if (items[i].kind === 'file') {
          const f = items[i].getAsFile()
          if (f) files.push(f)
        }
      }
      if (files.length > 0) {
        e.preventDefault()
        addFiles(files)
      }
    }
    el.addEventListener('paste', onPaste)
    return () => el.removeEventListener('paste', onPaste)
  }, [addFiles])

  // Drag-and-drop
  useEffect(() => {
    const zone = dropZoneRef.current
    if (!zone) return

    const onDragOver = (e: DragEvent) => { e.preventDefault(); setIsDragging(true) }
    const onDragLeave = (e: DragEvent) => {
      if (!zone.contains(e.relatedTarget as Node)) setIsDragging(false)
    }
    const onDrop = (e: DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      if (e.dataTransfer?.files.length) addFiles(e.dataTransfer.files)
    }

    zone.addEventListener('dragover', onDragOver)
    zone.addEventListener('dragleave', onDragLeave)
    zone.addEventListener('drop', onDrop)
    return () => {
      zone.removeEventListener('dragover', onDragOver)
      zone.removeEventListener('dragleave', onDragLeave)
      zone.removeEventListener('drop', onDrop)
    }
  }, [addFiles])

  // Focus textarea on mount and after streaming; skip during conversation mode
  useEffect(() => {
    if (!isStreaming && !voice?.conversationMode) {
      textareaRef.current?.focus()
      resizeTextarea()
    }
  }, [isStreaming, voice?.conversationMode])

  const modelPickerItems = models.map(m => ({ id: m.id, provider: m.provider }))

  // Silence countdown percentage for conversation mode progress bar
  const silencePct = voice && voice.silenceCountdown > 0
    ? (voice.silenceCountdown / voice.silenceTimeoutMs) * 100
    : 0

  return (
    <div
      ref={dropZoneRef}
      className={clsx(
        'relative bg-surface rounded-2xl border border-border-subtle p-3 safe-area-pb shadow-sm transition-colors duration-fast',
        isDragging && 'bg-accent-dim border-accent',
      )}
    >
      {/* Model selector + controls row */}
      <div className="flex items-center justify-between mb-2 gap-2">
        <div className="flex items-center gap-1.5">
          <ModelPicker
            value={modelId}
            onChange={onModelChange}
            models={modelPickerItems}
            className="w-72"
            buttonClassName="flex items-center justify-between gap-2 w-full px-3 py-1.5 bg-stone-700 rounded-full text-[13px] font-mono text-stone-300 border-none cursor-pointer"
          />
          <Tooltip content="Manage models">
            <button
              type="button"
              onClick={onManageModels}
              className="flex items-center justify-center rounded-sm p-1.5 text-content-tertiary hover:text-content-primary hover:bg-surface-elevated transition-colors duration-fast"
            >
              <SlidersHorizontal size={14} />
            </button>
          </Tooltip>
          {voice?.available && (
            <Tooltip content={voice.muted ? 'Unmute voice responses' : 'Mute voice responses'}>
              <button
                type="button"
                onClick={() => voice.setMuted(m => !m)}
                className={clsx(
                  'flex items-center justify-center rounded-sm p-1.5 transition-colors duration-fast',
                  voice.muted
                    ? 'text-content-tertiary hover:text-content-primary hover:bg-surface-elevated'
                    : 'text-accent hover:text-accent-hover hover:bg-surface-elevated',
                )}
              >
                {voice.muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              </button>
            </Tooltip>
          )}
        </div>
      </div>

      <InputDrawer
        open={drawerOpen}
        onAttach={openFilePicker}
      />

      {/* Conversation mode status bar */}
      {voice?.conversationMode && (
        <div
          className="flex items-center gap-2 px-3 py-2 mb-2 rounded-lg border text-sm relative overflow-hidden"
          style={{
            backgroundColor: voice.conversationState === 'listening' ? 'rgba(127, 29, 29, 0.4)'
              : voice.conversationState === 'speaking' ? 'rgba(20, 83, 45, 0.3)'
              : 'rgba(41, 37, 36, 0.5)',
            borderColor: voice.conversationState === 'listening' ? 'rgba(239, 68, 68, 0.2)'
              : voice.conversationState === 'speaking' ? 'rgba(34, 197, 94, 0.2)'
              : 'rgba(255, 255, 255, 0.06)',
          }}
        >
          {silencePct > 0 && (
            <div
              className="absolute inset-y-0 left-0 bg-amber-500/10 transition-all duration-100"
              style={{ width: `${100 - silencePct}%` }}
            />
          )}
          <div className="relative flex items-center gap-2 w-full">
            {voice.conversationState === 'listening' && (
              <>
                <Mic size={14} className="text-red-400 shrink-0 animate-pulse" />
                <AudioLevelIndicator level={audioLevel} bars={4} className="h-3.5 shrink-0" />
                <span className="text-content-secondary truncate">
                  {liveTranscript || 'Listening...'}
                </span>
                <span className="text-content-tertiary shrink-0 ml-auto text-xs">
                  {Math.floor(voice.recordingDuration / 1000)}s
                </span>
              </>
            )}
            {voice.conversationState === 'processing' && (
              <>
                <Loader2 size={14} className="text-content-tertiary shrink-0 animate-spin" />
                <span className="text-content-secondary">Thinking...</span>
              </>
            )}
            {voice.conversationState === 'speaking' && (
              <>
                <Volume2 size={14} className="text-green-400 shrink-0" />
                <span className="text-content-secondary">Speaking... interrupt anytime</span>
              </>
            )}
            {voice.conversationState === 'idle' && (
              <span className="text-content-tertiary">Conversation mode — waiting...</span>
            )}
          </div>
        </div>
      )}

      {/* Non-conversation recording indicator */}
      {voice && !voice.conversationMode && voice.isRecording && (
        <div className="flex items-center gap-2 px-3 py-2 mb-2 rounded-lg bg-danger-dim/50 border border-danger/20 text-sm">
          <Mic size={14} className="text-danger shrink-0 animate-pulse" />
          <AudioLevelIndicator level={audioLevel} bars={4} className="h-3.5 shrink-0" />
          <span className="text-content-secondary truncate">
            {liveTranscript || 'Listening...'}
          </span>
          <span className="text-content-tertiary shrink-0 ml-auto text-xs">
            {Math.floor(voice.recordingDuration / 1000)}s
          </span>
        </div>
      )}

      <FilePreviewBar files={pendingFiles} onRemove={removeFile} />

      <div className="flex items-end gap-2">
        {/* Drawer toggle */}
        <Tooltip content={drawerOpen ? 'Close controls' : 'Open controls'}>
          <button
            type="button"
            onClick={() => setDrawerOpen(o => !o)}
            className={clsx(
              'relative flex items-center justify-center rounded-full border p-2 transition-all duration-fast shrink-0',
              drawerOpen
                ? 'border-accent text-accent bg-accent-dim'
                : 'border-border text-content-tertiary hover:bg-surface-elevated hover:text-content-primary',
            )}
            style={{ height: '40px', width: '40px' }}
          >
            <Plus
              size={18}
              className="transition-transform duration-normal"
              style={{ transform: drawerOpen ? 'rotate(45deg)' : 'rotate(0deg)' }}
            />
            {!drawerOpen && pendingFiles.length > 0 && (
              <span className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-micro font-medium text-neutral-950">
                {pendingFiles.length}
              </span>
            )}
          </button>
        </Tooltip>

        <textarea
          ref={textareaRef}
          value={input}
          onChange={e => { setInput(e.target.value); resizeTextarea() }}
          onKeyDown={handleKeyDown}
          placeholder={voice?.conversationMode ? 'Conversation mode active (Esc to exit)' : `Message ${aiName}...`}
          rows={1}
          disabled={voice?.conversationMode}
          className="flex-1 resize-none overflow-y-auto rounded-sm border border-border bg-surface-input px-4 py-2.5 text-compact text-content-primary placeholder:text-content-tertiary outline-none transition-colors duration-fast focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 disabled:opacity-50"
          style={{ minHeight: '40px', maxHeight: '400px', fontSize: '16px' }}
        />

        {/* Voice controls */}
        {voice?.available && (
          <>
            {/* Conversation mode toggle */}
            <Tooltip content={voice.conversationMode ? 'Exit conversation mode (Esc)' : 'Start conversation mode'}>
              <button
                type="button"
                onClick={() => voice.setConversationMode(m => !m)}
                disabled={voice.isTranscribing}
                className={clsx(
                  'flex items-center justify-center rounded-full p-2 transition-colors duration-fast shrink-0',
                  voice.conversationMode
                    ? 'bg-accent text-neutral-950 hover:bg-accent-hover'
                    : 'border border-border text-content-tertiary hover:bg-surface-elevated hover:text-content-primary',
                )}
                style={{ height: '40px', width: '40px' }}
              >
                <AudioLines size={16} />
              </button>
            </Tooltip>

            {/* Manual mic button (hidden in conversation mode) */}
            {!voice.conversationMode && (
              <Tooltip content={voice.isRecording ? 'Stop recording' : voice.isTranscribing ? 'Transcribing...' : 'Push to talk'}>
                <button
                  type="button"
                  onClick={voice.toggleRecording}
                  disabled={voice.isTranscribing}
                  className={clsx(
                    'flex items-center justify-center rounded-full p-2 transition-colors duration-fast shrink-0',
                    voice.isRecording
                      ? 'bg-danger text-white hover:bg-red-500'
                      : voice.isTranscribing
                        ? 'border border-border text-content-tertiary cursor-wait'
                        : 'border border-border text-content-tertiary hover:bg-surface-elevated hover:text-content-primary',
                  )}
                  style={{ height: '40px', width: '40px' }}
                >
                  {voice.isTranscribing ? <Loader2 size={16} className="animate-spin" /> : <Mic size={16} />}
                </button>
              </Tooltip>
            )}
          </>
        )}

        <Tooltip content="Send message">
          <button
            onClick={handleSubmit}
            disabled={!input.trim() || voice?.conversationMode}
            className="w-11 h-11 rounded-full bg-teal-500 hover:bg-teal-600 text-white flex items-center justify-center shadow-[0_0_12px_rgba(25,168,158,0.3)] hover:shadow-[0_0_20px_rgba(25,168,158,0.4)] disabled:opacity-40 transition-all duration-150 shrink-0"
          >
            <Send size={16} />
          </button>
        </Tooltip>
      </div>

      {isDragging && (
        <div className="absolute inset-0 flex items-center justify-center bg-accent-dim pointer-events-none">
          <p className="text-compact font-medium text-accent">Drop files here</p>
        </div>
      )}
    </div>
  )
}
