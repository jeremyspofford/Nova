import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, MessageSquare, Archive, Trash2, Pencil, Check, X, PanelLeftClose, PanelLeft } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'
import { useAuth } from '../stores/auth-store'
import { apiFetch } from '../api'
import { Button } from './ui/Button'
import { SearchInput } from './ui/SearchInput'
import { Tooltip } from './ui/Tooltip'

export interface Conversation {
  id: string
  user_id: string
  title: string | null
  created_at: string
  updated_at: string
  last_message_at: string | null
  is_archived: boolean
}

interface ConversationSidebarProps {
  currentId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  collapsed: boolean
  onToggle: () => void
}

export function ConversationSidebar({ currentId, onSelect, onNew, collapsed, onToggle }: ConversationSidebarProps) {
  const { isAuthenticated } = useAuth()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const editRef = useRef<HTMLInputElement>(null)

  const { data: conversations = [] } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => apiFetch<Conversation[]>('/api/v1/conversations'),
    enabled: isAuthenticated,
    staleTime: 5_000,
  })

  useEffect(() => {
    if (editingId && editRef.current) editRef.current.focus()
  }, [editingId])

  const filtered = search
    ? conversations.filter(c => (c.title ?? '').toLowerCase().includes(search.toLowerCase()))
    : conversations

  // Group by time
  const now = Date.now()
  const DAY = 86400000
  const groups: { label: string; items: Conversation[] }[] = []
  const today: Conversation[] = []
  const yesterday: Conversation[] = []
  const week: Conversation[] = []
  const month: Conversation[] = []
  const older: Conversation[] = []

  for (const c of filtered) {
    const t = new Date(c.last_message_at ?? c.created_at).getTime()
    const age = now - t
    if (age < DAY) today.push(c)
    else if (age < 2 * DAY) yesterday.push(c)
    else if (age < 7 * DAY) week.push(c)
    else if (age < 30 * DAY) month.push(c)
    else older.push(c)
  }
  if (today.length) groups.push({ label: 'Today', items: today })
  if (yesterday.length) groups.push({ label: 'Yesterday', items: yesterday })
  if (week.length) groups.push({ label: 'This Week', items: week })
  if (month.length) groups.push({ label: 'This Month', items: month })
  if (older.length) groups.push({ label: 'Older', items: older })

  const handleRename = async (id: string) => {
    if (!editTitle.trim()) { setEditingId(null); return }
    try {
      await apiFetch(`/api/v1/conversations/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: editTitle.trim() }),
      })
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    } catch { /* ignore */ }
    setEditingId(null)
  }

  const handleArchive = async (id: string) => {
    try {
      await apiFetch(`/api/v1/conversations/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_archived: true }),
      })
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    } catch { /* ignore */ }
  }

  const handleDelete = async (id: string) => {
    try {
      await apiFetch(`/api/v1/conversations/${id}`, { method: 'DELETE' })
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    } catch { /* ignore */ }
  }

  if (collapsed) {
    return (
      <div className="flex flex-col items-center py-3 px-1 border-r border-border-subtle bg-surface w-12 shrink-0">
        <Tooltip content="Expand sidebar" side="right">
          <button onClick={onToggle} className="p-1.5 rounded-sm hover:bg-surface-elevated text-content-tertiary hover:text-content-primary transition-colors duration-fast">
            <PanelLeft className="w-4 h-4" />
          </button>
        </Tooltip>
        <Tooltip content="New chat" side="right">
          <button onClick={onNew} className="mt-2 p-1.5 rounded-sm hover:bg-surface-elevated text-content-tertiary hover:text-content-primary transition-colors duration-fast">
            <Plus className="w-4 h-4" />
          </button>
        </Tooltip>
      </div>
    )
  }

  return (
    <div className="flex flex-col w-[280px] shrink-0 border-r border-border-subtle bg-surface h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-border-subtle">
        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={12} />}
          onClick={onNew}
        >
          New Chat
        </Button>
        <Tooltip content="Collapse sidebar">
          <button onClick={onToggle} className="p-1.5 rounded-sm hover:bg-surface-elevated text-content-tertiary hover:text-content-primary transition-colors duration-fast">
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </Tooltip>
      </div>

      {/* Search */}
      {conversations.length > 5 && (
        <div className="px-3 py-2">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search conversations..."
            debounceMs={150}
          />
        </div>
      )}

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {groups.map(group => (
          <div key={group.label}>
            <div className="px-3 py-1.5 text-micro font-semibold uppercase tracking-wider text-content-tertiary">
              {group.label}
            </div>
            {group.items.map(conv => (
              <div
                key={conv.id}
                className={clsx(
                  'group relative flex items-center px-3 py-2 cursor-pointer transition-colors duration-fast',
                  conv.id === currentId
                    ? 'bg-accent-dim text-accent'
                    : 'hover:bg-surface-elevated text-content-primary',
                )}
                onClick={() => { if (editingId !== conv.id) onSelect(conv.id) }}
              >
                <MessageSquare className="w-3.5 h-3.5 shrink-0 mr-2 opacity-50" />
                {editingId === conv.id ? (
                  <div className="flex items-center gap-1 flex-1 min-w-0">
                    <input
                      ref={editRef}
                      value={editTitle}
                      onChange={e => setEditTitle(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') handleRename(conv.id)
                        if (e.key === 'Escape') setEditingId(null)
                      }}
                      className="flex-1 text-caption px-1.5 py-0.5 rounded-xs border border-border bg-surface-input text-content-primary focus:outline-none focus:border-border-focus"
                      onClick={e => e.stopPropagation()}
                    />
                    <button onClick={e => { e.stopPropagation(); handleRename(conv.id) }} className="p-0.5 text-accent"><Check className="w-3 h-3" /></button>
                    <button onClick={e => { e.stopPropagation(); setEditingId(null) }} className="p-0.5 text-content-tertiary"><X className="w-3 h-3" /></button>
                  </div>
                ) : (
                  <>
                    <div className="flex-1 min-w-0">
                      <span className="block text-caption truncate">
                        {conv.title || 'New conversation'}
                      </span>
                      <span className="block font-mono text-mono-sm text-content-tertiary">
                        {formatDistanceToNow(new Date(conv.last_message_at ?? conv.created_at), { addSuffix: true })}
                      </span>
                    </div>
                    {/* Action buttons on hover */}
                    <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                      <Tooltip content="Rename">
                        <button
                          onClick={e => { e.stopPropagation(); setEditingId(conv.id); setEditTitle(conv.title ?? '') }}
                          className="p-1 rounded-xs hover:bg-surface-card-hover transition-colors duration-fast"
                        >
                          <Pencil className="w-3 h-3" />
                        </button>
                      </Tooltip>
                      <Tooltip content="Archive">
                        <button
                          onClick={e => { e.stopPropagation(); handleArchive(conv.id) }}
                          className="p-1 rounded-xs hover:bg-surface-card-hover transition-colors duration-fast"
                        >
                          <Archive className="w-3 h-3" />
                        </button>
                      </Tooltip>
                      <Tooltip content="Delete">
                        <button
                          onClick={e => { e.stopPropagation(); handleDelete(conv.id) }}
                          className="p-1 rounded-xs hover:bg-danger-dim text-danger transition-colors duration-fast"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </Tooltip>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="px-3 py-8 text-center text-caption text-content-tertiary">
            {search ? 'No matching conversations' : 'No conversations yet'}
          </div>
        )}
      </div>
    </div>
  )
}
