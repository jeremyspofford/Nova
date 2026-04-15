import { useState, useRef, type KeyboardEvent } from "react"

interface ChatInputProps {
  onSend: (content: string) => void
  disabled: boolean
}

function SendIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 14V2M2 8l6-6 6 6"/>
    </svg>
  )
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  function resize() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  function handleSend() {
    const trimmed = value.trim()
    if (!trimmed) return
    onSend(trimmed)
    setValue("")
    if (textareaRef.current) textareaRef.current.style.height = "auto"
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const canSend = !disabled && !!value.trim()

  return (
    <div className="chat-input">
      <div className="chat-input__pill">
        <textarea
          ref={textareaRef}
          className="chat-input__textarea"
          value={value}
          onChange={e => { setValue(e.target.value); resize() }}
          onKeyDown={handleKeyDown}
          placeholder="Message Nova…"
          rows={1}
          disabled={disabled}
        />
        <div className="chat-input__actions">
          <button
            className={`chat-input__send${canSend ? " chat-input__send--active" : ""}`}
            onClick={handleSend}
            disabled={!canSend}
            aria-label="Send"
          >
            <SendIcon />
          </button>
        </div>
      </div>
    </div>
  )
}
