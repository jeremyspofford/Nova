import { useState, useCallback, useEffect, lazy, Suspense } from 'react'
import { getAuthHeaders } from './api'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useIsMobile } from './hooks/useIsMobile'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppLayout } from './components/layout/AppLayout'
import { CommandPalette } from './components/CommandPalette'
import { StartupScreen } from './components/StartupScreen'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ChatProvider } from './stores/chat-store'
import { ThemeProvider } from './stores/theme-store'
import { DebugProvider } from './stores/debug-store'
import { AuthProvider, useAuth } from './stores/auth-store'
import { ToastProvider } from './components/ToastProvider'
import { Login } from './pages/Login'
import { Chat } from './pages/Chat'
import { Usage } from './pages/Usage'
import { Integrations } from './pages/Integrations'
import { Settings } from './pages/Settings'
import { Models } from './pages/Models'
import { Tasks } from './pages/Tasks'
import { Pods } from './pages/Pods'
import { Goals } from './pages/Goals'
import { Sources } from './pages/Sources'
import { Recovery } from './pages/Recovery'
import { About } from './pages/About'
import { Benchmarks } from './pages/Benchmarks'
import { Users } from './pages/Users'
import { Invite } from './pages/Invite'
import { Expired } from './pages/Expired'
import Friction from './pages/Friction'
import Brain from './pages/Brain'
import { OnboardingWizard } from './pages/onboarding/OnboardingWizard'
import ComponentGallery from './pages/dev/ComponentGallery'

const Editors = lazy(() => import('./pages/Editors'))
const Editor = lazy(() => import('./pages/Editor'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 5_000,
      gcTime: 10 * 60_000, // 10 min — prevent stale queries lingering in memory
    },
  },
})

/**
 * Check if the orchestrator is reachable. If yes, Nova is ready.
 * If not, we show the startup screen (which talks to the recovery sidecar).
 */
async function checkBackendReady(): Promise<boolean> {
  try {
    const resp = await fetch('/api/v1/pipeline/stats', { signal: AbortSignal.timeout(3000) })
    return resp.ok
  } catch {
    return false
  }
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading, authConfig } = useAuth()

  // Recovery page bypasses auth — it has its own admin auth via X-Admin-Secret,
  // and must be reachable when the orchestrator (which serves auth config) is down
  if (window.location.pathname === '/recovery') {
    return <>{children}</>
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-950">
        <div className="text-neutral-400 text-sm">Loading...</div>
      </div>
    )
  }

  // Authenticated users always get through
  if (isAuthenticated) {
    return <>{children}</>
  }

  // Trusted network (LAN, Tailscale, localhost) — skip login
  if (authConfig?.trusted_network) {
    return <>{children}</>
  }

  // If user hit an invite link while unauthenticated, redirect to login with the code
  const inviteMatch = window.location.pathname.match(/^\/invite\/(.+)$/)
  if (inviteMatch) {
    const code = inviteMatch[1]
    window.history.replaceState(null, '', `/login?invite=${code}`)
    return <Login />
  }

  // No auth config yet (fetch failed/slow) or config says auth required → show login
  // This is fail-closed: we show Login unless we know auth isn't required
  return <Login />
}

function OnboardingGate({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false)
  const [needsOnboarding, setNeedsOnboarding] = useState(false)

  useEffect(() => {
    if (window.location.pathname === '/onboarding') { setChecked(true); return }
    fetch('/api/v1/config/onboarding.completed', {
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        const completed = data?.value === true || data?.value === 'true'
        setNeedsOnboarding(!completed)
        setChecked(true)
      })
      .catch(() => { setNeedsOnboarding(true); setChecked(true) })
  }, [])

  if (!checked) return null
  if (needsOnboarding && window.location.pathname !== '/onboarding') {
    window.location.href = '/onboarding'
    return null
  }
  return <>{children}</>
}

function HomeRoute() {
  return <Navigate to="/chat" replace />
}

/** On mobile viewports, redirect all non-chat routes to /chat. */
function MobileGuard({ children }: { children: React.ReactNode }) {
  const isMobile = useIsMobile()
  if (isMobile) return <Navigate to="/chat" replace />
  return <>{children}</>
}

function AppShell() {
  // Optimistic: assume backend is up. Normal refreshes render instantly.
  // Only show startup screen if the health check actually fails.
  const [ready, setReady] = useState(true)

  const handleReady = useCallback(() => setReady(true), [])

  useEffect(() => {
    checkBackendReady().then(ok => {
      if (!ok) setReady(false)
    })
  }, [])

  const handleOpenRecovery = useCallback(() => {
    // Set the URL before BrowserRouter mounts so it renders the Recovery route
    window.history.replaceState(null, '', '/recovery')
    setReady(true)
  }, [])

  if (!ready) {
    return <StartupScreen onReady={handleReady} onOpenRecovery={handleOpenRecovery} />
  }

  return (
    <AuthGate>
    <OnboardingGate>
    <ChatProvider>
    <BrowserRouter>
      <CommandPalette />
      <Routes>
        {/* Routes WITHOUT sidebar */}
        <Route path="/login" element={<Login />} />
        <Route path="/onboarding" element={<OnboardingWizard />} />
        <Route path="/invite/:code" element={<Invite />} />
        <Route path="/expired" element={<Expired />} />
        <Route path="/dev/components" element={<ComponentGallery />} />

        {/* Routes WITH sidebar */}
        <Route path="/" element={<HomeRoute />} />
        <Route path="/brain" element={<MobileGuard><AppLayout fullWidth><ErrorBoundary><Brain /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/chat" element={<AppLayout fullWidth><ErrorBoundary><Chat /></ErrorBoundary></AppLayout>} />
        <Route path="/tasks" element={<MobileGuard><AppLayout><ErrorBoundary><Tasks /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/friction" element={<MobileGuard><AppLayout><ErrorBoundary><Friction /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/pods" element={<MobileGuard><AppLayout><ErrorBoundary><Pods /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/usage" element={<MobileGuard><AppLayout><ErrorBoundary><Usage /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/goals" element={<MobileGuard><AppLayout><ErrorBoundary><Goals /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/sources" element={<MobileGuard><AppLayout><ErrorBoundary><Sources /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/integrations" element={<MobileGuard><AppLayout><ErrorBoundary><Integrations /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/models" element={<MobileGuard><AppLayout><ErrorBoundary><Models /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/editor" element={<MobileGuard><AppLayout fullWidth><ErrorBoundary><Suspense fallback={null}><Editor /></Suspense></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/ide-connections" element={<MobileGuard><AppLayout><ErrorBoundary><Suspense fallback={null}><Editors /></Suspense></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/users" element={<MobileGuard><AppLayout><ErrorBoundary><Users /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/settings" element={<MobileGuard><AppLayout><ErrorBoundary><Settings /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/recovery" element={<MobileGuard><AppLayout><ErrorBoundary><Recovery /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/benchmarks" element={<MobileGuard><AppLayout><ErrorBoundary><Benchmarks /></ErrorBoundary></AppLayout></MobileGuard>} />
        <Route path="/about" element={<MobileGuard><AppLayout><ErrorBoundary><About /></ErrorBoundary></AppLayout></MobileGuard>} />

        {/* Redirects for old routes */}
        <Route path="/intelligence" element={<Navigate to="/sources#recommendations" replace />} />
        <Route path="/mcp" element={<Navigate to="/integrations" replace />} />
        <Route path="/agents" element={<Navigate to="/integrations#agents" replace />} />
        <Route path="/keys" element={<Navigate to="/settings#keys" replace />} />
        <Route path="/skills" element={<Navigate to="/settings#behavior" replace />} />
        <Route path="/editors" element={<Navigate to="/ide-connections" replace />} />
        <Route path="/rules" element={<Navigate to="/settings#behavior" replace />} />
      </Routes>
    </BrowserRouter>
    </ChatProvider>
    </OnboardingGate>
    </AuthGate>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <DebugProvider>
          <AuthProvider>
            <ToastProvider>
              <AppShell />
            </ToastProvider>
          </AuthProvider>
        </DebugProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
