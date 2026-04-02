import { memo, useMemo } from 'react'
import { useNovaIdentity } from '../../hooks/useNovaIdentity'
import { useIsMobile } from '../../hooks/useIsMobile'
import { User, FileText } from 'lucide-react'
import { format } from 'date-fns'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'
import { ActivityFeed } from '../../components/ActivityFeed'
import { cleanToolArtifacts } from '../../utils/cleanToolArtifacts'
import type { Message } from '../../stores/chat-store'

type TextSize = 'small' | 'medium' | 'large'

const TEXT_SIZE_CLASSES: Record<TextSize, string> = {
  small: 'text-compact leading-relaxed',       // 13px
  medium: 'text-body leading-relaxed',          // 14px
  large: 'text-[16px] leading-relaxed',         // 16px — Claude-like
}

const MOBILE_TEXT_SIZE_CLASSES: Record<TextSize, string> = {
  small: 'text-body leading-relaxed',           // 14px — mobile small = desktop medium
  medium: 'text-[16px] leading-[1.65]',         // 16px — mobile default
  large: 'text-[17px] leading-[1.65]',          // 17px — mobile large
}

// Conversation mode: larger text for arm's-length reading
const VOICE_TEXT_CLASS = 'text-[20px] leading-[1.6]'

export const MessageBubble = memo(function MessageBubble({
  message,
  conversationMode = false,
}: {
  message: Message
  conversationMode?: boolean
}) {
  const { avatarUrl, isDefaultAvatar } = useNovaIdentity()
  const isMobile = useIsMobile()
  const isUser = message.role === 'user'
  const isThinking = !isUser && message.isStreaming && !message.content
  const textSize = (localStorage.getItem('nova_text_size') as TextSize) || 'medium'
  const isVoiceActive = conversationMode && message.isStreaming && !isUser
  const cleanedContent = useMemo(
    () => !isUser && message.content ? cleanToolArtifacts(message.content) : message.content,
    [isUser, message.content],
  )

  const textClass = isVoiceActive
    ? VOICE_TEXT_CLASS
    : isMobile
      ? MOBILE_TEXT_SIZE_CLASSES[textSize]
      : TEXT_SIZE_CLASSES[textSize]

  // ── Mobile layout: no avatars, user=bubble, assistant=no bubble ──
  if (isMobile) {
    return (
      <div className={clsx(isUser && 'flex justify-end')}>
        <div className={clsx(
          isUser ? 'max-w-[85%]' : 'w-full',
        )}>
          <div
            className={clsx(
              textClass,
              isUser
                ? 'bg-stone-800 text-content-primary whitespace-pre-wrap rounded-2xl px-4 py-3'
                : clsx(
                    'text-content-primary markdown-body overflow-x-auto',
                    isThinking && 'text-amber-200/80',
                  ),
            )}
          >
            {!isUser && message.activitySteps && message.activitySteps.length > 0 && (
              <ActivityFeed
                steps={message.activitySteps}
                collapsed={message.activityCollapsed ?? false}
                isStreaming={message.isStreaming ?? false}
              />
            )}

            {isUser && message.attachments && message.attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {message.attachments.map(att =>
                  att.type === 'image' && att.previewUrl ? (
                    <img key={att.id} src={att.previewUrl} alt={att.file.name} className="max-w-[200px] max-h-[150px] rounded-sm object-cover" />
                  ) : (
                    <span key={att.id} className="inline-flex items-center gap-1 rounded-xs bg-accent-500/20 px-2 py-1 text-micro">
                      <FileText size={12} />{att.file.name}
                    </span>
                  ),
                )}
              </div>
            )}

            {cleanedContent ? (
              isUser ? cleanedContent : (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleanedContent}</ReactMarkdown>
              )
            ) : message.isStreaming ? (
              <span className="inline-flex items-center gap-1.5 py-1">
                <span className={clsx('h-2 w-2 rounded-full animate-bounce [animation-delay:-0.3s]', isThinking ? 'bg-amber-400' : 'bg-accent')} />
                <span className={clsx('h-2 w-2 rounded-full animate-bounce [animation-delay:-0.15s]', isThinking ? 'bg-amber-400' : 'bg-accent')} />
                <span className={clsx('h-2 w-2 rounded-full animate-bounce', isThinking ? 'bg-amber-400' : 'bg-accent')} />
              </span>
            ) : '\u2014'}
          </div>

          {/* Footer — minimal on mobile */}
          <p className={clsx(
            'mt-1 font-mono text-[10px] text-content-tertiary/60 px-1',
            isUser && 'text-right',
          )}>
            {format(message.timestamp, 'h:mm a')}
          </p>
        </div>
      </div>
    )
  }

  // ── Desktop layout: avatars, glass-card bubbles on both sides ──
  return (
    <div className={clsx('flex gap-2', isUser ? 'justify-end' : 'items-start')}>
      {/* Assistant avatar */}
      {!isUser && (
        isDefaultAvatar ? (
          <div className={clsx(
            'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
            isThinking ? 'bg-amber-500/20 text-amber-400' : 'bg-teal-500/20 text-teal-400',
          )}>
            N
          </div>
        ) : (
          <img src={avatarUrl} alt="Nova" className={clsx(
            'mt-0.5 h-7 w-7 shrink-0 rounded-full object-cover',
            isThinking && 'ring-2 ring-amber-500/40',
          )} />
        )
      )}

      {/* Bubble column */}
      <div className={clsx(
        isUser ? 'max-w-[80%] md:max-w-prose' : 'flex-1 min-w-0 max-w-prose',
      )}>
        <div
          className={clsx(
            textClass,
            isUser
              ? 'glass-card text-content-primary whitespace-pre-wrap rounded-tl-xl rounded-tr-sm rounded-br-xl rounded-bl-xl px-4 py-3'
              : clsx(
                  'glass-card text-content-primary markdown-body overflow-x-auto rounded-tl-sm rounded-tr-xl rounded-br-xl rounded-bl-xl px-5 py-[18px]',
                  isThinking && 'border-amber-500/15',
                ),
          )}
        >
          {!isUser && message.activitySteps && message.activitySteps.length > 0 && (
            <ActivityFeed
              steps={message.activitySteps}
              collapsed={message.activityCollapsed ?? false}
              isStreaming={message.isStreaming ?? false}
            />
          )}

          {isUser && message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {message.attachments.map(att =>
                att.type === 'image' && att.previewUrl ? (
                  <img key={att.id} src={att.previewUrl} alt={att.file.name} className="max-w-[200px] max-h-[150px] rounded-sm object-cover" />
                ) : (
                  <span key={att.id} className="inline-flex items-center gap-1 rounded-xs bg-accent-500/20 px-2 py-1 text-micro">
                    <FileText size={12} />{att.file.name}
                  </span>
                ),
              )}
            </div>
          )}

          {cleanedContent ? (
            isUser ? cleanedContent : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleanedContent}</ReactMarkdown>
            )
          ) : message.isStreaming ? (
            <span className="inline-flex items-center gap-1 py-1">
              <span className={clsx('h-1.5 w-1.5 rounded-full animate-bounce [animation-delay:-0.3s]', isThinking ? 'bg-amber-400 dark:shadow-[0_0_6px_rgb(251_191_36/0.5)]' : 'bg-accent dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]')} />
              <span className={clsx('h-1.5 w-1.5 rounded-full animate-bounce [animation-delay:-0.15s]', isThinking ? 'bg-amber-400 dark:shadow-[0_0_6px_rgb(251_191_36/0.5)]' : 'bg-accent dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]')} />
              <span className={clsx('h-1.5 w-1.5 rounded-full animate-bounce', isThinking ? 'bg-amber-400 dark:shadow-[0_0_6px_rgb(251_191_36/0.5)]' : 'bg-accent dark:shadow-[0_0_6px_rgb(var(--accent-500)/0.5)]')} />
            </span>
          ) : '\u2014'}
        </div>

        {/* Footer */}
        <p className={clsx(
          'mt-1 font-mono text-mono-sm text-content-tertiary px-1',
          isUser && 'text-right',
        )}>
          {format(message.timestamp, 'h:mm a')}
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

      {/* User avatar */}
      {isUser && (
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-elevated text-content-secondary">
          <User size={13} />
        </div>
      )}
    </div>
  )
})
