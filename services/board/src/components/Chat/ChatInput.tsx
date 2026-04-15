import { useState, type KeyboardEvent } from "react"

interface ChatInputProps {
  onSend: (content: string) => void
  disabled: boolean
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("")

  function handleSend() {
    const trimmed = value.trim()
    if (!trimmed) return
    onSend(trimmed)
    setValue("")
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-input">
      <textarea
        className="chat-input__textarea"
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Message Nova…"
        rows={2}
        disabled={disabled}
      />
      <button
        className="chat-input__send"
        onClick={handleSend}
        disabled={disabled}
        aria-label="Send"
      >
        Send
      </button>
    </div>
  )
}
