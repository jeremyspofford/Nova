import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { createPortal } from 'react-dom'
import {
  Search,
  MessageSquare,
  ListTodo,
  Target,
  Brain,
  Boxes,
  Monitor,
  Shield,
  Plug,
  BarChart3,
  Settings,
  HeartPulse,
  Users,
  Plus,
  ArrowRight,
} from 'lucide-react'
import clsx from 'clsx'

type PaletteItem = {
  id: string
  label: string
  icon: typeof MessageSquare
  category: 'Pages' | 'Settings' | 'Actions'
  action: () => void
}

function usePaletteItems(navigate: ReturnType<typeof useNavigate>): PaletteItem[] {
  return [
    // Pages
    { id: 'page-chat', label: 'Chat', icon: MessageSquare, category: 'Pages', action: () => navigate('/chat') },
    { id: 'page-tasks', label: 'Tasks', icon: ListTodo, category: 'Pages', action: () => navigate('/tasks') },
    { id: 'page-goals', label: 'Goals', icon: Target, category: 'Pages', action: () => navigate('/goals') },
    { id: 'page-brain', label: 'Brain', icon: Brain, category: 'Pages', action: () => navigate('/') },
    { id: 'page-pods', label: 'Pods', icon: Boxes, category: 'Pages', action: () => navigate('/pods') },
    { id: 'page-models', label: 'Models', icon: Monitor, category: 'Pages', action: () => navigate('/models') },
    { id: 'page-keys', label: 'Keys', icon: Shield, category: 'Pages', action: () => navigate('/keys') },
    { id: 'page-integrations', label: 'Integrations', icon: Plug, category: 'Pages', action: () => navigate('/mcp') },
    { id: 'page-usage', label: 'Usage', icon: BarChart3, category: 'Pages', action: () => navigate('/usage') },
    { id: 'page-settings', label: 'Settings', icon: Settings, category: 'Pages', action: () => navigate('/settings') },
    { id: 'page-recovery', label: 'Recovery', icon: HeartPulse, category: 'Pages', action: () => navigate('/recovery') },
    { id: 'page-users', label: 'Users', icon: Users, category: 'Pages', action: () => navigate('/users') },
    // Settings sections
    { id: 'settings-general', label: 'General Settings', icon: Settings, category: 'Settings', action: () => navigate('/settings?tab=general') },
    { id: 'settings-ai', label: 'AI & Models Settings', icon: Monitor, category: 'Settings', action: () => navigate('/settings?tab=ai') },
    { id: 'settings-connections', label: 'Connection Settings', icon: Plug, category: 'Settings', action: () => navigate('/settings?tab=connections') },
    { id: 'settings-appearance', label: 'Appearance Settings', icon: Settings, category: 'Settings', action: () => navigate('/settings?tab=appearance') },
    // Actions
    { id: 'action-new-task', label: 'New Task', icon: Plus, category: 'Actions', action: () => navigate('/tasks') },
    { id: 'action-new-goal', label: 'New Goal', icon: Plus, category: 'Actions', action: () => navigate('/goals') },
  ]
}

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const items = usePaletteItems(navigate)

  // Filter items
  const filtered = query
    ? items.filter(item => item.label.toLowerCase().includes(query.toLowerCase()))
    : items

  // Group by category
  const grouped = (['Pages', 'Settings', 'Actions'] as const).reduce<
    { category: string; items: PaletteItem[] }[]
  >((acc, category) => {
    const categoryItems = filtered.filter(item => item.category === category)
    if (categoryItems.length > 0) acc.push({ category, items: categoryItems })
    return acc
  }, [])

  // Flat list for keyboard navigation
  const flatItems = grouped.flatMap(g => g.items)

  // Cmd+K / Ctrl+K listener
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(prev => !prev)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Reset state when opening
  useEffect(() => {
    if (open) {
      setQuery('')
      setActiveIndex(0)
      // Focus after portal renders
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  // Reset active index when filtered results change
  useEffect(() => {
    setActiveIndex(0)
  }, [query])

  // Scroll active item into view
  useEffect(() => {
    if (!listRef.current) return
    const activeEl = listRef.current.querySelector('[data-active="true"]')
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest' })
    }
  }, [activeIndex])

  const close = useCallback(() => setOpen(false), [])

  const selectItem = useCallback(
    (item: PaletteItem) => {
      close()
      item.action()
    },
    [close],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        close()
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIndex(i => (i + 1) % Math.max(flatItems.length, 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIndex(i => (i - 1 + flatItems.length) % Math.max(flatItems.length, 1))
      } else if (e.key === 'Enter') {
        e.preventDefault()
        if (flatItems[activeIndex]) selectItem(flatItems[activeIndex])
      }
    },
    [flatItems, activeIndex, close, selectItem],
  )

  if (!open) return null

  let itemCounter = -1

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] px-4 animate-fade-in"
      onClick={e => {
        if (e.target === e.currentTarget) close()
      }}
      onKeyDown={handleKeyDown}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" />

      {/* Palette */}
      <div className="relative w-full max-w-lg bg-surface-card rounded-xl border border-border-subtle shadow-lg overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border-subtle">
          <Search className="w-4 h-4 text-content-tertiary shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search pages, settings, actions..."
            className="flex-1 bg-transparent text-compact text-content-primary placeholder:text-content-tertiary outline-none"
          />
          <kbd className="hidden sm:inline text-micro text-content-tertiary border border-border rounded-xs px-1.5 py-0.5">
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-[320px] overflow-y-auto custom-scrollbar py-2">
          {flatItems.length === 0 ? (
            <div className="px-4 py-8 text-center text-compact text-content-tertiary">
              No results found
            </div>
          ) : (
            grouped.map(group => (
              <div key={group.category}>
                <div className="px-4 pt-2 pb-1 text-micro font-semibold uppercase tracking-wider text-content-tertiary">
                  {group.category}
                </div>
                {group.items.map(item => {
                  itemCounter++
                  const idx = itemCounter
                  const Icon = item.icon
                  const isActive = idx === activeIndex
                  return (
                    <button
                      key={item.id}
                      data-active={isActive}
                      onClick={() => selectItem(item)}
                      onMouseEnter={() => setActiveIndex(idx)}
                      className={clsx(
                        'flex items-center gap-3 w-full px-4 py-2 text-left text-compact transition-colors duration-fast',
                        isActive
                          ? 'bg-accent-dim text-accent'
                          : 'text-content-secondary hover:text-content-primary',
                      )}
                    >
                      <Icon className="w-4 h-4 shrink-0" />
                      <span className="flex-1 truncate">{item.label}</span>
                      {isActive && <ArrowRight className="w-3.5 h-3.5 shrink-0 opacity-60" />}
                    </button>
                  )
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-border-subtle flex items-center gap-4 text-micro text-content-tertiary">
          <span className="flex items-center gap-1">
            <kbd className="border border-border rounded-xs px-1">&#8593;</kbd>
            <kbd className="border border-border rounded-xs px-1">&#8595;</kbd>
            navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="border border-border rounded-xs px-1">&#9166;</kbd>
            select
          </span>
          <span className="flex items-center gap-1">
            <kbd className="border border-border rounded-xs px-1">esc</kbd>
            close
          </span>
        </div>
      </div>
    </div>,
    document.body,
  )
}
