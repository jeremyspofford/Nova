import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, Trash2 } from 'lucide-react'
import { getComments, addComment, deleteComment, type Comment } from '../api'
import { useAuth } from '../stores/auth-store'
import { Button } from './ui/Button'

interface Props {
  entityType: 'recommendation' | 'goal'
  entityId: string
}

export function DiscussionThread({ entityType, entityId }: Props) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [body, setBody] = useState('')

  const queryKey = ['comments', entityType, entityId]

  const { data: comments = [], isLoading } = useQuery({
    queryKey,
    queryFn: () => getComments(entityType, entityId),
    staleTime: 10_000,
  })

  const add = useMutation({
    mutationFn: () => addComment(entityType, entityId, body, user?.display_name ?? user?.email ?? 'User'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey })
      setBody('')
    },
  })

  const remove = useMutation({
    mutationFn: (commentId: string) => deleteComment(entityType, entityId, commentId),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (body.trim()) add.mutate()
  }

  const formatTime = (iso: string) => {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return 'just now'
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr < 24) return `${diffHr}h ago`
    const diffDays = Math.floor(diffHr / 24)
    return `${diffDays}d ago`
  }

  return (
    <div>
      <div className="text-caption font-semibold text-content-primary uppercase tracking-wide mb-3">
        Discussion ({comments.length})
      </div>

      {isLoading && <p className="text-caption text-content-tertiary">Loading...</p>}

      <div className="space-y-3 mb-4">
        {comments.map((c: Comment) => (
          <div key={c.id}>
            <div className="flex items-center gap-1.5 mb-1">
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold ${
                c.author_type === 'nova'
                  ? 'bg-gradient-to-br from-teal-400 to-sky-500 text-black'
                  : 'bg-blue-500 text-white'
              }`}>
                {c.author_type === 'nova' ? 'N' : c.author_name.charAt(0).toUpperCase()}
              </div>
              <span className={`text-caption font-semibold ${
                c.author_type === 'nova' ? 'text-teal-400' : 'text-blue-400'
              }`}>
                {c.author_name}
              </span>
              <span className="text-[10px] text-content-tertiary">{formatTime(c.created_at)}</span>
              {c.author_type === 'human' && (
                <button
                  onClick={() => remove.mutate(c.id)}
                  className="ml-auto text-content-tertiary hover:text-danger transition-colors"
                >
                  <Trash2 size={10} />
                </button>
              )}
            </div>
            <div className="text-small text-content-secondary pl-6 leading-relaxed">
              {c.body}
            </div>
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 items-start pt-3 border-t border-border">
        <input
          value={body}
          onChange={e => setBody(e.target.value)}
          placeholder="Add a comment..."
          className="flex-1 bg-surface-elevated border border-border rounded-md px-3 py-2 text-small text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <Button
          size="sm"
          type="submit"
          disabled={!body.trim() || add.isPending}
          icon={<Send size={12} />}
        >
          Send
        </Button>
      </form>

      {add.isError && (
        <p className="text-caption text-danger mt-1">Failed to post comment</p>
      )}
    </div>
  )
}
