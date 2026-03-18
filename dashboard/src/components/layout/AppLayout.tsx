import { useState, useEffect, type ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'

const STORAGE_KEY = 'nova-sidebar-collapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function AppLayout({
  children,
  fullWidth = false,
}: {
  children: ReactNode
  fullWidth?: boolean
}) {
  const [collapsed, setCollapsed] = useState(readCollapsed)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed))
    } catch {
      // Ignore storage errors
    }
  }, [collapsed])

  return (
    <div className="flex h-screen bg-surface-root">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
      <main className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
        {fullWidth ? (
          children
        ) : (
          <div className="mx-auto max-w-[1200px] w-full px-6 py-8">
            {children}
          </div>
        )}
      </main>
      <MobileNav />
    </div>
  )
}
