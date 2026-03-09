import { useState, useRef, useEffect } from 'react'
import { NavLink, useNavigate, useLocation } from 'react-router-dom'
import { Key, Cpu, BarChart2, Settings, X, ListTodo, Layers, MessageSquare, Plug, Menu, Network, Brain, LogOut, ChevronDown, CircleUser, Info, Users2 } from 'lucide-react'
import clsx from 'clsx'
import { useNovaIdentity } from '../hooks/useNovaIdentity'
import { useAuth } from '../stores/auth-store'
import { hasMinRole, type Role } from '../lib/roles'

const mainLinks = [
  { to: '/',         label: 'Chat',     icon: MessageSquare    },
  { to: '/tasks',    label: 'Tasks',    icon: ListTodo         },
  { to: '/pods',     label: 'Pods',     icon: Layers           },
  { to: '/usage',    label: 'Usage',    icon: BarChart2        },
  { to: '/keys',     label: 'Keys',     icon: Key              },
  { to: '/mcp',      label: 'MCP',      icon: Plug             },
  { to: '/agents',   label: 'Agents',   icon: Network          },
  { to: '/memory',   label: 'Memory',   icon: Brain            },
  { to: '/models',   label: 'Models',   icon: Cpu              },
]

const systemLinks = [
  { to: '/users',         label: 'Users',    icon: Users2      },
  { to: '/settings',      label: 'Settings', icon: Settings    },
  { to: '/about',         label: 'About',    icon: Info        },
]

export function NavBar() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const { name } = useNovaIdentity()
  const { isAuthenticated, user, logout } = useAuth()

  // Filter system links based on role
  const filteredSystemLinks = systemLinks.filter(link => {
    if (link.to === '/users') {
      return user?.role && hasMinRole(user.role as Role, 'admin')
    }
    return true
  })

  // Close user menu on click outside
  useEffect(() => {
    if (!userMenuOpen) return
    const handleClick = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node))
        setUserMenuOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [userMenuOpen])

  // Close user menu on route change
  useEffect(() => { setUserMenuOpen(false) }, [location.pathname])

  return (
    <>
      <nav className="sticky top-0 z-50 flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4 sm:gap-6">
          <span className="text-sm font-semibold tracking-widest text-accent-700 dark:text-accent-400 uppercase">{name}</span>

          {/* Desktop nav */}
          <div className="hidden md:flex gap-1">
            {mainLinks.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  clsx('flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
                    isActive
                      ? 'bg-accent-700/10 text-accent-700 dark:bg-accent-400/10 dark:text-accent-400'
                      : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-100')
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">

          {/* User dropdown */}
          <div ref={userMenuRef} className="relative">
            <button
              onClick={() => setUserMenuOpen(v => !v)}
              className={clsx(
                'flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm transition-colors',
                userMenuOpen
                  ? 'bg-neutral-100 dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100'
                  : 'text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200'
              )}
              title="User menu"
            >
              <CircleUser size={18} />
              {isAuthenticated && user && (
                <span className="hidden sm:inline text-xs max-w-[120px] truncate">
                  {user.display_name || user.email}
                </span>
              )}
              <ChevronDown size={12} className={clsx('transition-transform', userMenuOpen && 'rotate-180')} />
            </button>

            {userMenuOpen && (
              <div className="absolute right-0 top-full mt-1 w-56 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-lg py-1 z-50">
                {isAuthenticated && user && (
                  <div className="px-3 py-2 border-b border-neutral-200 dark:border-neutral-700">
                    <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate">
                      {user.display_name || 'User'}
                    </p>
                    {user.email && (
                      <p className="text-xs text-neutral-500 dark:text-neutral-400 truncate">{user.email}</p>
                    )}
                  </div>
                )}
                {user?.role && hasMinRole(user.role as Role, 'admin') && (
                  <NavLink
                    to="/users"
                    onClick={() => setUserMenuOpen(false)}
                    className={clsx(
                      'flex items-center gap-2 px-3 py-2 text-sm transition-colors',
                      location.pathname === '/users'
                        ? 'bg-accent-700/10 text-accent-700 dark:bg-accent-400/10 dark:text-accent-400'
                        : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-100'
                    )}
                  >
                    <Users2 size={14} />
                    Users
                  </NavLink>
                )}
                <NavLink
                  to="/settings"
                  onClick={() => setUserMenuOpen(false)}
                  className={clsx(
                    'flex items-center gap-2 px-3 py-2 text-sm transition-colors',
                    location.pathname.startsWith('/settings')
                      ? 'bg-accent-700/10 text-accent-700 dark:bg-accent-400/10 dark:text-accent-400'
                      : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-100'
                  )}
                >
                  <Settings size={14} />
                  Settings
                </NavLink>
                <NavLink
                  to="/about"
                  onClick={() => setUserMenuOpen(false)}
                  className={clsx(
                    'flex items-center gap-2 px-3 py-2 text-sm transition-colors',
                    location.pathname === '/about'
                      ? 'bg-accent-700/10 text-accent-700 dark:bg-accent-400/10 dark:text-accent-400'
                      : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-100'
                  )}
                >
                  <Info size={14} />
                  About
                </NavLink>
                {isAuthenticated && (
                  <button
                    onClick={() => { setUserMenuOpen(false); logout() }}
                    className="flex items-center gap-2 w-full px-3 py-2 text-sm text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-100 transition-colors"
                  >
                    <LogOut size={14} />
                    Sign out
                  </button>
                )}
              </div>
            )}
          </div>
          {/* Mobile hamburger */}
          <button
            onClick={() => setMobileMenuOpen(v => !v)}
            className="md:hidden text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 transition-colors"
          >
            {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </nav>

      {/* Mobile menu dropdown */}
      {mobileMenuOpen && (
        <div className="md:hidden sticky top-[57px] z-50 border-b border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 px-4 py-2">
          <div className="grid grid-cols-3 gap-1">
            {[...mainLinks, ...filteredSystemLinks].map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                onClick={() => setMobileMenuOpen(false)}
                className={({ isActive }) =>
                  clsx('flex flex-col items-center gap-1 rounded-md px-2 py-2.5 text-xs transition-colors',
                    isActive
                      ? 'bg-accent-700/10 text-accent-700 dark:bg-accent-400/10 dark:text-accent-400'
                      : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-100')
                }
              >
                <Icon size={16} />
                {label}
              </NavLink>
            ))}
          </div>
        </div>
      )}

    </>
  )
}
