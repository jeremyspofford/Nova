interface MessageBubbleProps {
  role: "user" | "assistant"
  content: string
  streaming?: boolean
}

export function MessageBubble({ role, content, streaming }: MessageBubbleProps) {
  const isThinking = streaming && !content

  if (role === "user") {
    return (
      <div className={`message-bubble message-bubble--user${streaming ? " message-bubble--streaming" : ""}`}>
        <p className="message-bubble__content">{content}</p>
      </div>
    )
  }

  return (
    <div className={`message-bubble message-bubble--assistant${streaming ? " message-bubble--streaming" : ""}`}>
      <div className="message-bubble__avatar">N</div>
      {isThinking ? (
        <div className="message-bubble__typing" aria-label="Nova is thinking">
          <span />
          <span />
          <span />
        </div>
      ) : (
        <p className="message-bubble__content">{content}</p>
      )}
    </div>
  )
}
