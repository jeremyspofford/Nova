import { useState, useEffect, useCallback, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'
import { LogFrictionButton } from '../LogFrictionButton'
import { useNotifications } from '../../hooks/useNotifications'

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
  const qc = useQueryClient()

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed))
    } catch {
      // Ignore storage errors
    }
  }, [collapsed])

  const handleNotification = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })
    qc.invalidateQueries({ queryKey: ['attention-count'] })
  }, [qc])

  useNotifications(handleNotification)

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
      <LogFrictionButton />
    </div>
  )
}
