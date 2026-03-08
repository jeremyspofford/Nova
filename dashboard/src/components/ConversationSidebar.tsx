import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, MessageSquare, Archive, Trash2, Pencil, Check, X, PanelLeftClose, PanelLeft, Search } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { useAuth } from '../stores/auth-store'
import { apiFetch } from '../api'

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
  if (week.length) groups.push({ label: 'Previous 7 days', items: week })
  if (month.length) groups.push({ label: 'Previous 30 days', items: month })
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
      <div className="flex flex-col items-center py-3 px-1 border-r border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 w-12 shrink-0">
        <button onClick={onToggle} className="p-1.5 rounded-md hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500">
          <PanelLeft className="w-4 h-4" />
        </button>
        <button onClick={onNew} className="mt-2 p-1.5 rounded-md hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500">
          <Plus className="w-4 h-4" />
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col w-64 shrink-0 border-r border-neutral-200 dark:border-neutral-800 bg-neutral-100 dark:bg-neutral-900 h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-neutral-200 dark:border-neutral-800">
        <button
          onClick={onNew}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-teal-600 hover:bg-teal-700 text-white text-xs font-medium transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> New chat
        </button>
        <button onClick={onToggle} className="p-1.5 rounded-md hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500">
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>

      {/* Search */}
      {conversations.length > 5 && (
        <div className="px-3 py-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-neutral-400" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search conversations..."
              className="w-full pl-7 pr-2 py-1.5 text-xs rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-neutral-800 dark:text-neutral-200 focus:outline-none focus:ring-1 focus:ring-teal-500/40"
            />
          </div>
        </div>
      )}

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {groups.map(group => (
          <div key={group.label}>
            <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">
              {group.label}
            </div>
            {group.items.map(conv => (
              <div
                key={conv.id}
                className={`group relative flex items-center px-3 py-2 cursor-pointer transition-colors ${
                  conv.id === currentId
                    ? 'bg-teal-50 dark:bg-teal-900/20 text-teal-700 dark:text-teal-300'
                    : 'hover:bg-neutral-200/50 dark:hover:bg-neutral-800/50 text-neutral-700 dark:text-neutral-300'
                }`}
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
                      className="flex-1 text-xs px-1 py-0.5 rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 focus:outline-none"
                      onClick={e => e.stopPropagation()}
                    />
                    <button onClick={e => { e.stopPropagation(); handleRename(conv.id) }} className="p-0.5 text-teal-600"><Check className="w-3 h-3" /></button>
                    <button onClick={e => { e.stopPropagation(); setEditingId(null) }} className="p-0.5 text-neutral-400"><X className="w-3 h-3" /></button>
                  </div>
                ) : (
                  <>
                    <span className="flex-1 text-xs truncate">
                      {conv.title || 'New conversation'}
                    </span>
                    {/* Action buttons on hover */}
                    <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                      <button
                        onClick={e => { e.stopPropagation(); setEditingId(conv.id); setEditTitle(conv.title ?? '') }}
                        className="p-1 rounded hover:bg-neutral-300/50 dark:hover:bg-neutral-700/50"
                        title="Rename"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); handleArchive(conv.id) }}
                        className="p-1 rounded hover:bg-neutral-300/50 dark:hover:bg-neutral-700/50"
                        title="Archive"
                      >
                        <Archive className="w-3 h-3" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(conv.id) }}
                        className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-red-500"
                        title="Delete"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-neutral-400">
            {search ? 'No matching conversations' : 'No conversations yet'}
          </div>
        )}
      </div>
    </div>
  )
}
