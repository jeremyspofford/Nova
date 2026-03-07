import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Plus, RefreshCw } from 'lucide-react'
import { useChatStore } from '../../stores/chat-store'
import { useFileAttach } from '../../hooks/useFileAttach'
import { InputDrawer } from './InputDrawer'
import { FilePreviewBar } from './FilePreviewBar'

interface Props {
  onSubmit: (text: string) => void
  isStreaming: boolean
  aiName: string
  models: Array<{ id: string; provider: string }>
  modelId: string
  onModelChange: (id: string) => void
  resolvedModel?: string
  onNewChat: () => void
  hasMessages: boolean
}

export function ChatInput({ onSubmit, isStreaming, aiName, models, modelId, onModelChange, resolvedModel, onNewChat, hasMessages }: Props) {
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dropZoneRef = useRef<HTMLDivElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  const { drawerOpen, setDrawerOpen, prefillInput, setPrefillInput } = useChatStore()
  const { pendingFiles, addFiles, removeFile, openFilePicker } = useFileAttach()

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
    // Allow taller expansion when there's a lot of content (e.g. prefilled task context)
    const maxH = el.value.split('\n').length > 5 ? 400 : 200
    el.style.height = `${Math.min(el.scrollHeight, maxH)}px`
  }

  const handleSubmit = useCallback(() => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    onSubmit(text)
  }, [input, isStreaming, onSubmit])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleTranscript = useCallback((text: string) => {
    setInput(prev => prev + (prev ? ' ' : '') + text)
    setTimeout(resizeTextarea, 0)
  }, [])

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

  // Focus textarea on mount and after streaming
  useEffect(() => {
    if (!isStreaming) textareaRef.current?.focus()
  }, [isStreaming])

  return (
    <div
      ref={dropZoneRef}
      className={`relative rounded-2xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-lg dark:shadow-neutral-950/50 p-3 safe-area-pb transition-colors ${
        isDragging ? 'bg-accent-50 dark:bg-accent-950/20 border-accent-400 dark:border-accent-700' : ''
      }`}
    >
      {/* Model selector + New chat row */}
      <div className="flex items-center justify-between mb-2 px-1">
        <select
          value={modelId}
          onChange={e => onModelChange(e.target.value)}
          disabled={isStreaming}
          title={`Override ${aiName}'s default model for this conversation`}
          className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-2 py-1 text-[16px] sm:text-xs text-neutral-700 dark:text-neutral-300 outline-none focus:border-accent-600 disabled:opacity-40"
        >
          <option value="">Auto{resolvedModel ? ` (${resolvedModel})` : ''}</option>
          {models.map(m => (
            <option key={m.id} value={m.id}>{m.id} ({m.provider})</option>
          ))}
        </select>

        <button
          onClick={onNewChat}
          disabled={isStreaming || !hasMessages}
          title="Start a new conversation"
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 disabled:opacity-40 transition-colors"
        >
          <RefreshCw size={14} />
          <span className="text-xs">New chat</span>
        </button>
      </div>

      <InputDrawer
        open={drawerOpen}
        onAttach={openFilePicker}
        onTranscript={handleTranscript}
      />

      <FilePreviewBar files={pendingFiles} onRemove={removeFile} />

      <div className="flex items-end gap-2">
        {/* Drawer toggle */}
        <button
          type="button"
          onClick={() => setDrawerOpen(o => !o)}
          title={drawerOpen ? 'Close controls' : 'Open controls'}
          className="relative flex items-center justify-center rounded-full border border-neutral-300 dark:border-neutral-600 p-2 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-all shrink-0"
          style={{ height: '42px', width: '42px' }}
        >
          <Plus
            size={18}
            className="transition-transform duration-200"
            style={{ transform: drawerOpen ? 'rotate(45deg)' : 'rotate(0deg)' }}
          />
          {!drawerOpen && pendingFiles.length > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-700 px-1 text-[10px] font-medium text-white">
              {pendingFiles.length}
            </span>
          )}
        </button>

        <textarea
          ref={textareaRef}
          value={input}
          onChange={e => { setInput(e.target.value); resizeTextarea() }}
          onKeyDown={handleKeyDown}
          placeholder={`Message ${aiName}...`}
          rows={1}
          className="flex-1 resize-none overflow-y-auto rounded-xl border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-4 py-2.5 text-base text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 dark:placeholder:text-neutral-500 outline-none focus:border-accent-600 disabled:opacity-50 transition-colors"
          style={{ minHeight: '42px', maxHeight: '400px', fontSize: '16px' }}
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

      {isDragging && (
        <div className="absolute inset-0 flex items-center justify-center bg-accent-700/10 dark:bg-accent-700/5 rounded-2xl pointer-events-none">
          <p className="text-sm font-medium text-accent-700 dark:text-accent-400">Drop files here</p>
        </div>
      )}
    </div>
  )
}
