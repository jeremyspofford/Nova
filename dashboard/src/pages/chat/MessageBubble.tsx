import { memo, useMemo } from 'react'
import { Bot, User, FileText } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'
import { ActivityFeed } from '../../components/ActivityFeed'
import { cleanToolArtifacts } from '../../utils/cleanToolArtifacts'
import type { Message } from '../../stores/chat-store'

export const MessageBubble = memo(function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const cleanedContent = useMemo(
    () => !isUser && message.content ? cleanToolArtifacts(message.content) : message.content,
    [isUser, message.content],
  )

  return (
    <div className={clsx('flex gap-3', isUser && 'flex-row-reverse')}>
      {/* Avatar */}
      <div
        className={clsx(
          'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
          isUser
            ? 'bg-surface-elevated text-content-secondary'
            : 'bg-accent text-neutral-950',
        )}
      >
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>

      {/* Bubble */}
      <div className={isUser ? 'max-w-[80%]' : 'flex-1 min-w-0 max-w-[85%]'}>
        <div
          className={clsx(
            'text-compact leading-relaxed rounded-lg px-4 py-3',
            isUser
              ? 'bg-accent-dim text-content-primary whitespace-pre-wrap'
              : 'bg-surface-card border border-border-subtle text-content-primary markdown-body overflow-x-auto',
          )}
        >
          {!isUser && message.activitySteps && message.activitySteps.length > 0 && (
            <ActivityFeed
              steps={message.activitySteps}
              collapsed={message.activityCollapsed ?? false}
              isStreaming={message.isStreaming ?? false}
            />
          )}

          {/* User message attachments */}
          {isUser && message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {message.attachments.map(att =>
                att.type === 'image' && att.previewUrl ? (
                  <img
                    key={att.id}
                    src={att.previewUrl}
                    alt={att.file.name}
                    className="max-w-[200px] max-h-[150px] rounded-sm object-cover"
                  />
                ) : (
                  <span
                    key={att.id}
                    className="inline-flex items-center gap-1 rounded-xs bg-accent-500/20 px-2 py-1 text-micro"
                  >
                    <FileText size={12} />
                    {att.file.name}
                  </span>
                ),
              )}
            </div>
          )}

          {cleanedContent ? (
            isUser ? cleanedContent : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {cleanedContent}
              </ReactMarkdown>
            )
          ) : message.isStreaming ? (
            <span className="inline-flex items-center gap-1 py-1">
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-bounce [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-bounce [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-bounce" />
            </span>
          ) : '\u2014'}
        </div>

        {/* Footer: time, model, category */}
        <p
          className={clsx(
            'mt-1 font-mono text-mono-sm text-content-tertiary px-1',
            isUser && 'text-right',
          )}
        >
          {formatDistanceToNow(message.timestamp, { addSuffix: true })}
          {!isUser && message.modelUsed && (
            <span className="ml-1.5">
              &middot; {message.modelUsed}
              {message.category && (
                <span className="text-content-tertiary/60"> ({message.category})</span>
              )}
            </span>
          )}
        </p>
      </div>
    </div>
  )
})
