import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Activity, Key, Cpu, BarChart2, Settings, X, ListTodo, Layers, MessageSquare, Plug, SlidersHorizontal } from 'lucide-react'
import clsx from 'clsx'
import { getAdminSecret, setAdminSecret } from '../api'

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
  const [secret, setSecret] = useState(getAdminSecret)

  const saveSecret = () => {
    setAdminSecret(secret)
    setSettingsOpen(false)
  }

  return (
    <>
      <nav className="flex items-center justify-between border-b border-stone-200 bg-white px-6 py-3">
        <div className="flex items-center gap-6">
          <span className="text-sm font-semibold tracking-widest text-teal-700 uppercase">Nova</span>
          <div className="flex gap-1">
            {links.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  clsx('flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
                    isActive ? 'bg-teal-700/10 text-teal-700' : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900')
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </div>
        </div>
        <button onClick={() => setSettingsOpen(true)} className="text-stone-400 hover:text-stone-700 transition-colors">
          <Settings size={16} />
        </button>
      </nav>

      {settingsOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/50">
          <div className="w-96 rounded-xl border border-stone-300 bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-stone-900">Dashboard Settings</h2>
              <button onClick={() => setSettingsOpen(false)} className="text-stone-400 hover:text-stone-700"><X size={16} /></button>
            </div>
            <label className="mb-1 block text-xs text-stone-500">Admin Secret</label>
            <input
              type="password"
              value={secret}
              onChange={e => setSecret(e.target.value)}
              className="w-full rounded-md border border-stone-300 bg-stone-100 px-3 py-2 text-sm text-stone-900 outline-none focus:border-teal-600"
            />
            <div className="mt-2 rounded-md bg-stone-50 border border-stone-200 p-3 text-xs text-stone-500 space-y-1">
              <p>
                This is the <strong className="text-stone-700">server-side admin password</strong> from your{' '}
                <code className="rounded bg-stone-100 px-1 text-stone-600">.env</code> file{' '}
                (<code className="rounded bg-stone-100 px-1 text-stone-600">ADMIN_SECRET=…</code>).
              </p>
              <p>
                The dashboard sends it with every admin request (Pods, Keys, Usage).
                You only need to change it here if you changed <code className="rounded bg-stone-100 px-1 text-stone-600">ADMIN_SECRET</code>{' '}
                on the server — it doesn't change the server's password, just what this browser sends.
              </p>
              <p className="text-stone-400">Stored in your browser's localStorage only — never sent to third parties.</p>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setSettingsOpen(false)} className="rounded-md px-3 py-1.5 text-sm text-stone-500 hover:text-stone-900">Cancel</button>
              <button onClick={saveSecret} className="rounded-md bg-teal-700 px-3 py-1.5 text-sm text-white hover:bg-teal-500">Save</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
