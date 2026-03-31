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
      <div className={isUser ? 'ml-auto max-w-[85%]' : 'flex-1 min-w-0 max-w-[85%]'}>
        <div
          className={clsx(
            'text-compact leading-relaxed',
            isUser
              ? 'bg-stone-800 text-content-primary whitespace-pre-wrap rounded-xl px-4 py-3'
              : 'bg-stone-800/60 border-l-2 border-teal-800 text-content-primary markdown-body overflow-x-auto rounded-r-xl px-5 py-[18px]',
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
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-bounce [animation-delay:-0.3s] dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]" />
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-bounce [animation-delay:-0.15s] dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]" />
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-bounce dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]" />
            </span>
          ) : '\u2014'}
        </div>

        {/* Footer: time, model, category, channel */}
        <p
          className={clsx(
            'mt-1 font-mono text-mono-sm text-content-tertiary px-1',
            isUser && 'text-right',
          )}
        >
          {formatDistanceToNow(message.timestamp, { addSuffix: true })}
          {message.metadata?.channel === 'telegram' && (
            <span className="ml-1.5 text-content-tertiary/50">via Telegram</span>
          )}
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
