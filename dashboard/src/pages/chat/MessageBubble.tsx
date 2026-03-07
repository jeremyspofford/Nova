import { useMemo } from 'react'
import { Bot, User, FileText } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ActivityFeed } from '../../components/ActivityFeed'
import { cleanToolArtifacts } from '../../utils/cleanToolArtifacts'
import type { Message } from '../../stores/chat-store'

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const cleanedContent = useMemo(
    () => !isUser && message.content ? cleanToolArtifacts(message.content) : message.content,
    [isUser, message.content],
  )

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
        isUser ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300' : 'bg-accent-700 text-white'
      }`}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>

      {/* Bubble */}
      <div className={isUser ? 'max-w-[85%] sm:max-w-[75%]' : 'flex-1 min-w-0'}>
        <div className={`text-sm leading-relaxed ${
          isUser
            ? 'rounded-2xl rounded-tr-sm px-4 py-2.5 bg-accent-700 text-white whitespace-pre-wrap'
            : 'rounded-2xl rounded-tl-sm px-4 py-2.5 bg-neutral-100 dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100 markdown-body overflow-x-auto'
        }`}>
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
                    className="max-w-[200px] max-h-[150px] rounded-lg object-cover"
                  />
                ) : (
                  <span
                    key={att.id}
                    className="inline-flex items-center gap-1 rounded-md bg-white/20 px-2 py-1 text-xs"
                  >
                    <FileText size={12} />
                    {att.file.name}
                  </span>
                )
              )}
            </div>
          )}

          {cleanedContent ? (
            isUser ? cleanedContent : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {cleanedContent}
              </ReactMarkdown>
            )
          ) : (
            !isUser && message.activitySteps && message.activitySteps.length > 0
              ? null  // ActivityFeed handles the "waiting" visual
              : message.isStreaming ? (
                <span className="inline-flex items-center gap-1 py-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-neutral-400 animate-bounce [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-neutral-400 animate-bounce [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-neutral-400 animate-bounce" />
                </span>
              ) : '—'
          )}
        </div>
        <p className={`mt-1 text-xs text-neutral-500 dark:text-neutral-500 px-1 ${isUser ? 'text-right' : ''}`}>
          {formatDistanceToNow(message.timestamp, { addSuffix: true })}
          {!isUser && message.modelUsed && (
            <span className="ml-1.5">
              &middot; {message.modelUsed}
              {message.category && <span className="text-neutral-400 dark:text-neutral-600"> ({message.category})</span>}
            </span>
          )}
        </p>
      </div>
    </div>
  )
}
