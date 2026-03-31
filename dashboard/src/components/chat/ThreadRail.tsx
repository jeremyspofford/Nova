import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Plus } from 'lucide-react'
import { apiFetch } from '../../api'
import { useChatStore } from '../../stores/chat-store'

interface Conversation {
  id: string
  title: string | null
  preview: string | null
  updated_at: string
  message_count: number
}

export function ThreadRail() {
  const { conversationId, loadConversation, newConversation } = useChatStore()
  const [search, setSearch] = useState('')

  const { data: conversations = [] } = useQuery<Conversation[]>({
    queryKey: ['conversations'],
    queryFn: () => apiFetch<Conversation[]>('/api/v1/conversations?limit=20'),
    staleTime: 10_000,
  })

  const filtered = search
    ? conversations.filter(c =>
        (c.title ?? '').toLowerCase().includes(search.toLowerCase())
      )
    : conversations

  return (
    <div className="thread-rail group h-full shrink-0 relative z-40">
      {/* Collapsed strip */}
      <div className="w-1 h-full bg-teal-800 group-hover:hidden" />

      {/* Expanded panel */}
      <div className="absolute inset-y-0 left-0 w-0 group-hover:w-[260px] overflow-hidden
                      bg-stone-800 border-r border-stone-700
                      transition-[width] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)]">
        <div className="w-[260px] h-full flex flex-col p-3 gap-2
                        opacity-0 group-hover:opacity-100 transition-opacity duration-150 delay-50">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-stone-500" />
            <input
              type="text"
              placeholder="Search threads..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 bg-stone-700 border border-transparent
                         focus:border-teal-500 rounded-lg text-[13px] text-stone-300
                         placeholder:text-stone-500 outline-none"
            />
          </div>

          {/* New Chat */}
          <button
            onClick={() => newConversation()}
            className="w-full flex items-center justify-center gap-2 py-2 px-3
                       bg-teal-500 hover:bg-teal-600 text-white text-[13px] font-semibold
                       rounded-lg transition-colors duration-150"
          >
            <Plus className="w-4 h-4" />
            New Chat
          </button>

          {/* Thread list */}
          <div className="flex-1 overflow-y-auto space-y-0.5">
            {filtered.map(conv => (
              <button
                key={conv.id}
                onClick={() => loadConversation(conv.id)}
                className={`w-full text-left px-3 py-2.5 rounded-md border-l-2 transition-colors duration-100
                  ${conv.id === conversationId
                    ? 'border-teal-500 bg-teal-900/15'
                    : 'border-transparent hover:bg-stone-700/40'}`}
              >
                <div className="text-sm font-semibold text-stone-200 truncate">
                  {conv.title ?? `Conversation ${conv.id.slice(0, 8)}`}
                </div>
                {conv.preview && (
                  <div className="text-xs text-stone-500 truncate mt-0.5">
                    {conv.preview}
                  </div>
                )}
                <div className="text-[11px] font-mono text-stone-500 mt-0.5">
                  {formatRelativeTime(conv.updated_at)}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days === 1) return 'yesterday'
  return `${days}d ago`
}
