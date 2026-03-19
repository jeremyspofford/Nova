import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Plus, RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import { useChatStore } from '../../stores/chat-store'
import { useFileAttach } from '../../hooks/useFileAttach'
import { InputDrawer } from './InputDrawer'
import { FilePreviewBar } from './FilePreviewBar'
import { Button } from '../../components/ui/Button'
import { Tooltip } from '../../components/ui/Tooltip'
import { ModelPicker } from '../../components/ui/ModelPicker'

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
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dropZoneRef = useRef<HTMLDivElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  const { draftInput: input, setDraftInput: setInput, drawerOpen, setDrawerOpen, prefillInput, setPrefillInput } = useChatStore()
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

  // Focus textarea on mount and after streaming; resize if draft exists
  useEffect(() => {
    if (!isStreaming) {
      textareaRef.current?.focus()
      resizeTextarea()
    }
  }, [isStreaming])

  // Build model picker items — prepend the resolved/default option
  const modelPickerItems = models.map(m => ({ id: m.id, provider: m.provider }))

  return (
    <div
      ref={dropZoneRef}
      className={clsx(
        'relative bg-surface rounded-2xl border border-border-subtle p-3 safe-area-pb shadow-sm transition-colors duration-fast',
        isDragging && 'bg-accent-dim border-accent',
      )}
    >
      {/* Model selector + New chat row */}
      <div className="flex items-center justify-between mb-2 gap-2">
        <ModelPicker
          value={modelId}
          onChange={onModelChange}
          models={modelPickerItems}
          showAuto
          className="w-56"
        />

        <Button
          variant="ghost"
          size="sm"
          icon={<RefreshCw size={12} />}
          onClick={onNewChat}
          disabled={isStreaming || !hasMessages}
        >
          New chat
        </Button>
      </div>

      <InputDrawer
        open={drawerOpen}
        onAttach={openFilePicker}
        onTranscript={handleTranscript}
      />

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
          placeholder={`Message ${aiName}...`}
          rows={1}
          className="flex-1 resize-none overflow-y-auto rounded-sm border border-border bg-surface-input px-4 py-2.5 text-compact text-content-primary placeholder:text-content-tertiary outline-none transition-colors duration-fast focus:border-border-focus focus:ring-2 focus:ring-accent-500/40 disabled:opacity-50"
          style={{ minHeight: '40px', maxHeight: '400px', fontSize: '16px' }}
        />

        <Tooltip content="Send message">
          <button
            onClick={handleSubmit}
            disabled={!input.trim()}
            className="flex items-center justify-center rounded-full bg-accent p-2.5 text-neutral-950 hover:bg-accent-hover disabled:opacity-40 transition-colors duration-fast shrink-0"
            style={{ height: '40px', width: '40px' }}
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
