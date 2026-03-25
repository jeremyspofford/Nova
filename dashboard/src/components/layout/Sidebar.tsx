import { useLocation, NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  MessageSquare,
  ListTodo,
  AlertTriangle,
  Target,
  Lightbulb,
  Brain,
  Boxes,
  Monitor,
  Shield,
  Plug,
  BarChart3,
  Settings,
  ChevronsLeft,
  ChevronsRight,
  ChevronDown,
} from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '../../stores/auth-store'
import { useDebug } from '../../stores/debug-store'
import { hasMinRole, type Role } from '../../lib/roles'
import { useAttentionCount } from '../../hooks/useAttentionCount'

type NavItem = {
  to: string
  debugOnly?: boolean
  label: string
  icon: typeof MessageSquare
  minRole: Role
  badge?: number
}

type NavSection = {
  label?: string
  items: NavItem[]
}

const navSections: NavSection[] = [
  {
    // Core — no label, always visible
    items: [
      { to: '/', label: 'Overview', icon: LayoutDashboard, minRole: 'guest' },
      { to: '/chat', label: 'Chat', icon: MessageSquare, minRole: 'guest' },
      { to: '/tasks', label: 'Tasks', icon: ListTodo, minRole: 'member' },
      { to: '/friction', label: 'Friction', icon: AlertTriangle, minRole: 'member', debugOnly: true },
      { to: '/goals', label: 'Goals', icon: Target, minRole: 'member' },
      { to: '/intelligence', label: 'Intelligence', icon: Lightbulb, minRole: 'member' },
      { to: '/engrams', label: 'Memory', icon: Brain, minRole: 'member' },
    ],
  },
  {
    label: 'Configure',
    items: [
      { to: '/pods', label: 'Pods', icon: Boxes, minRole: 'admin' },
      { to: '/models', label: 'Models', icon: Monitor, minRole: 'member' },
      { to: '/keys', label: 'Keys', icon: Shield, minRole: 'admin' },
      { to: '/mcp', label: 'Integrations', icon: Plug, minRole: 'admin' },
    ],
  },
  {
    label: 'Monitor',
    items: [
      { to: '/usage', label: 'Usage', icon: BarChart3, minRole: 'member' },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/settings', label: 'Settings', icon: Settings, minRole: 'admin' },
    ],
  },
]

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const location = useLocation()
  const { user, authConfig } = useAuth()
  const userRole: Role = (user?.role as Role) || (authConfig?.trusted_network ? 'owner' : 'guest')
  const { data: attentionCount = 0 } = useAttentionCount()
  const { isDebug } = useDebug()

  const isActive = (to: string) => {
    return location.pathname === to
  }

  return (
    <aside
      className={clsx(
        'hidden md:flex flex-col h-full bg-surface border-r border-border-subtle transition-[width] duration-200 ease-in-out shrink-0 dark:bg-surface-root/80 dark:backdrop-blur-xl dark:border-white/[0.04]',
        collapsed ? 'w-[60px]' : 'w-[240px]',
      )}
    >
      {/* Logo */}
      <div className={clsx('flex items-center gap-2.5 px-3 h-14 shrink-0', collapsed && 'justify-center')}>
        <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center shrink-0 dark:shadow-[0_0_16px_rgb(var(--accent-500)/0.3)]">
          <span className="text-white text-compact font-bold leading-none">N</span>
        </div>
        {!collapsed && (
          <span className="text-h3 text-content-primary tracking-tight">Nova</span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-2 space-y-4">
        {navSections.map((section, sIdx) => {
          const visibleItems = section.items.filter(item =>
            hasMinRole(userRole, item.minRole) && (!item.debugOnly || isDebug)
          )
          if (visibleItems.length === 0) return null
          return (
            <div key={sIdx}>
              {section.label && !collapsed && (
                <div className="text-micro font-semibold uppercase tracking-wider text-content-tertiary px-2.5 mb-1">
                  {section.label}
                </div>
              )}
              {collapsed && section.label && (
                <div className="h-px bg-border-subtle mx-2 mb-2" />
              )}
              <div className="space-y-0.5">
                {visibleItems.map(item => {
                  const Icon = item.icon
                  const active = isActive(item.to)
                  const badge = item.to === '/tasks' ? attentionCount : (item.badge ?? 0)
                  return (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      title={collapsed ? item.label : undefined}
                      className={clsx(
                        'relative flex items-center gap-2.5 rounded-md text-compact font-medium transition-colors duration-fast',
                        collapsed ? 'justify-center px-2 py-2' : 'px-2.5 py-2',
                        active
                          ? 'bg-accent-dim text-accent dark:shadow-[inset_0_0_20px_rgb(var(--accent-500)/0.06)]'
                          : 'text-content-secondary hover:text-content-primary hover:bg-surface-card',
                      )}
                    >
                      {active && (
                        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-4 rounded-r-full bg-accent" />
                      )}
                      <Icon className="w-[18px] h-[18px] shrink-0" />
                      {!collapsed && (
                        <>
                          <span className="truncate">{item.label}</span>
                          {badge > 0 && (
                            <span className="ml-auto text-micro bg-accent-dim text-accent rounded-full px-1.5 py-0.5 leading-none">
                              {badge}
                            </span>
                          )}
                        </>
                      )}
                    </NavLink>
                  )
                })}
              </div>
            </div>
          )
        })}
      </nav>

      {/* User card */}
      {!collapsed && user && (
        <div className="px-2 pb-2">
          <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-md hover:bg-surface-card transition-colors duration-fast cursor-pointer">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white text-caption font-medium shrink-0">
              {getInitials(user.display_name || user.email || 'N')}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-compact font-medium text-content-primary truncate">
                {user.display_name || user.email || 'User'}
              </div>
              <div className="text-micro text-content-tertiary capitalize">{user.role}</div>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-content-tertiary shrink-0" />
          </div>
        </div>
      )}

      {/* Collapse toggle */}
      <div className="px-2 pb-3 shrink-0">
        <button
          onClick={onToggle}
          className={clsx(
            'flex items-center gap-2 rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-card transition-colors duration-fast w-full',
            collapsed ? 'justify-center px-2 py-2' : 'px-2.5 py-2',
          )}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <ChevronsRight className="w-[18px] h-[18px]" />
          ) : (
            <>
              <ChevronsLeft className="w-[18px] h-[18px]" />
              <span className="text-compact">Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
