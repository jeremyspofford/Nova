interface MessageBubbleProps {
  role: "user" | "assistant"
  content: string
  streaming?: boolean
}

export function MessageBubble({ role, content, streaming }: MessageBubbleProps) {
  return (
    <div className={`message-bubble message-bubble--${role}${streaming ? " message-bubble--streaming" : ""}`}>
      <span className="message-bubble__role">
        {role === "user" ? "You" : "Nova"}
      </span>
      <p className="message-bubble__content">{content}</p>
    </div>
  )
}
