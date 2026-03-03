import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Activity, Key, Cpu, BarChart2, Settings, X, ListTodo, Layers, MessageSquare, Plug, SlidersHorizontal, Menu, Moon, Sun } from 'lucide-react'
import clsx from 'clsx'
import { getAdminSecret, setAdminSecret } from '../api'
import { useTheme } from '../stores/theme-store'

const links = [
  { to: '/',         label: 'Overview', icon: Activity         },
  { to: '/chat',     label: 'Chat',     icon: MessageSquare    },
  { to: '/tasks',    label: 'Tasks',    icon: ListTodo         },
  { to: '/pods',     label: 'Pods',     icon: Layers           },
  { to: '/usage',    label: 'Usage',    icon: BarChart2        },
  { to: '/keys',     label: 'Keys',     icon: Key              },
  { to: '/mcp',      label: 'MCP',      icon: Plug             },
  { to: '/models',   label: 'Models',   icon: Cpu              },
  { to: '/settings', label: 'Settings', icon: SlidersHorizontal },
]

export function NavBar() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [secret, setSecret] = useState(getAdminSecret)
  const { theme, toggle: toggleTheme } = useTheme()

  const saveSecret = () => {
    setAdminSecret(secret)
    setSettingsOpen(false)
  }

  return (
    <>
      <nav className="flex items-center justify-between border-b border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4 sm:gap-6">
          <span className="text-sm font-semibold tracking-widest text-teal-700 dark:text-teal-400 uppercase">Nova</span>

          {/* Desktop nav */}
          <div className="hidden md:flex gap-1">
            {links.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  clsx('flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
                    isActive
                      ? 'bg-teal-700/10 text-teal-700 dark:bg-teal-400/10 dark:text-teal-400'
                      : 'text-stone-500 dark:text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-800 hover:text-stone-900 dark:hover:text-stone-100')
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            className="text-stone-400 hover:text-stone-700 dark:hover:text-stone-200 transition-colors"
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button onClick={() => setSettingsOpen(true)} className="text-stone-400 hover:text-stone-700 dark:hover:text-stone-200 transition-colors">
            <Settings size={16} />
          </button>
          {/* Mobile hamburger */}
          <button
            onClick={() => setMobileMenuOpen(v => !v)}
            className="md:hidden text-stone-400 hover:text-stone-700 dark:hover:text-stone-200 transition-colors"
          >
            {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </nav>

      {/* Mobile menu dropdown */}
      {mobileMenuOpen && (
        <div className="md:hidden border-b border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 px-4 py-2">
          <div className="grid grid-cols-3 gap-1">
            {links.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                onClick={() => setMobileMenuOpen(false)}
                className={({ isActive }) =>
                  clsx('flex flex-col items-center gap-1 rounded-md px-2 py-2.5 text-xs transition-colors',
                    isActive
                      ? 'bg-teal-700/10 text-teal-700 dark:bg-teal-400/10 dark:text-teal-400'
                      : 'text-stone-500 dark:text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-800 hover:text-stone-900 dark:hover:text-stone-100')
                }
              >
                <Icon size={16} />
                {label}
              </NavLink>
            ))}
          </div>
        </div>
      )}

      {settingsOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/50 dark:bg-black/60 p-4">
          <div className="w-full max-w-sm sm:max-w-96 rounded-xl border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 p-5 sm:p-6 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-stone-900 dark:text-stone-100">Dashboard Settings</h2>
              <button onClick={() => setSettingsOpen(false)} className="text-stone-400 hover:text-stone-700 dark:hover:text-stone-200"><X size={16} /></button>
            </div>
            <label className="mb-1 block text-xs text-stone-500 dark:text-stone-400">Admin Secret</label>
            <input
              type="password"
              value={secret}
              onChange={e => setSecret(e.target.value)}
              className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-100 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
            />
            <div className="mt-2 rounded-md bg-stone-50 dark:bg-stone-800 border border-stone-200 dark:border-stone-700 p-3 text-xs text-stone-500 dark:text-stone-400 space-y-1">
              <p>
                This is the <strong className="text-stone-700 dark:text-stone-300">server-side admin password</strong> from your{' '}
                <code className="rounded bg-stone-100 dark:bg-stone-700 px-1 text-stone-600 dark:text-stone-300">.env</code> file{' '}
                (<code className="rounded bg-stone-100 dark:bg-stone-700 px-1 text-stone-600 dark:text-stone-300">ADMIN_SECRET=…</code>).
              </p>
              <p>
                The dashboard sends it with every admin request (Pods, Keys, Usage).
                You only need to change it here if you changed <code className="rounded bg-stone-100 dark:bg-stone-700 px-1 text-stone-600 dark:text-stone-300">ADMIN_SECRET</code>{' '}
                on the server — it doesn't change the server's password, just what this browser sends.
              </p>
              <p className="text-stone-400 dark:text-stone-500">Stored in your browser's localStorage only — never sent to third parties.</p>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setSettingsOpen(false)} className="rounded-md px-3 py-1.5 text-sm text-stone-500 dark:text-stone-400 hover:text-stone-900 dark:hover:text-stone-100">Cancel</button>
              <button onClick={saveSecret} className="rounded-md bg-teal-700 px-3 py-1.5 text-sm text-white hover:bg-teal-500">Save</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
