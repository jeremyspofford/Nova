import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { Activity, Key, Cpu, BarChart2, Settings, X, ListTodo, Layers, MessageSquare, Plug, Menu, Network, Brain, Lock, Unlock } from 'lucide-react'
import clsx from 'clsx'

const mainLinks = [
  { to: '/',         label: 'Overview', icon: Activity         },
  { to: '/chat',     label: 'Chat',     icon: MessageSquare    },
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
  { to: '/settings',      label: 'Settings', icon: Settings    },
]

export function NavBar() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const navigate = useNavigate()

  return (
    <>
      <nav className="flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4 sm:gap-6">
          <span className="text-sm font-semibold tracking-widest text-accent-700 dark:text-accent-400 uppercase">Nova</span>

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
          {typeof window !== 'undefined' && (
            window.location.protocol === 'https:' ? (
              <span title="Secure connection (HTTPS)" className="text-emerald-500"><Lock size={14} /></span>
            ) : window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1' ? (
              <span title="Insecure connection — not using HTTPS" className="text-amber-500"><Unlock size={14} /></span>
            ) : null
          )}
          <button onClick={() => navigate('/settings')} title="Settings" className="text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 transition-colors">
            <Settings size={16} />
          </button>
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
        <div className="md:hidden border-b border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 px-4 py-2">
          <div className="grid grid-cols-3 gap-1">
            {[...mainLinks, ...systemLinks].map(({ to, label, icon: Icon }) => (
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
