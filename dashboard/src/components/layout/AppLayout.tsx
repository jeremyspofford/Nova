import { useState, useEffect, useCallback, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'
import { LogFrictionButton } from '../LogFrictionButton'
import { useNotifications, toastVariantFor, type PipelineNotification } from '../../hooks/useNotifications'
import { useToast } from '../ToastProvider'
import { useDebug } from '../../stores/debug-store'
import { MobileNavProvider } from '../../hooks/useMobileNav'
import { useIsMobile } from '../../hooks/useIsMobile'

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
  const { isDebug } = useDebug()
  const qc = useQueryClient()
  const isMobile = useIsMobile()

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed))
    } catch {
      // Ignore storage errors
    }
  }, [collapsed])

  const { addToast } = useToast()

  const handleNotification = useCallback((n: PipelineNotification) => {
    qc.invalidateQueries({ queryKey: ['pipeline-tasks'] })
    qc.invalidateQueries({ queryKey: ['attention-count'] })
    addToast({ variant: toastVariantFor(n.type), message: n.body || n.title })
  }, [qc, addToast])

  useNotifications(handleNotification)

  return (
    <MobileNavProvider>
      <div className="flex h-dvh bg-surface-root dark:bg-transparent">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
        <main className={`flex-1 min-h-0 ${fullWidth ? 'overflow-hidden' : 'overflow-y-auto custom-scrollbar'}`}>
          {fullWidth ? (
            children
          ) : (
            <div className="mx-auto max-w-[1200px] w-full px-6 py-8 animate-fade-in">
              {children}
            </div>
          )}
        </main>
        {!isMobile && <MobileNav />}
        {isDebug && <LogFrictionButton />}
      </div>
    </MobileNavProvider>
  )
}
