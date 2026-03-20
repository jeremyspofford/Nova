import { useState, useCallback, useEffect } from 'react'
import { getAuthHeaders } from './api'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppLayout } from './components/layout/AppLayout'
import { CommandPalette } from './components/CommandPalette'
import { StartupScreen } from './components/StartupScreen'
import { ChatProvider } from './stores/chat-store'
import { ThemeProvider } from './stores/theme-store'
import { AuthProvider, useAuth } from './stores/auth-store'
import { ToastProvider } from './components/ToastProvider'
import { Login } from './pages/Login'
import { Chat } from './pages/Chat'
import { Usage } from './pages/Usage'
import { Keys } from './pages/Keys'
import { MCP } from './pages/MCP'
import { Settings } from './pages/Settings'
import { Models } from './pages/Models'
import { Tasks } from './pages/Tasks'
import { Pods } from './pages/Pods'
import { AgentEndpoints } from './pages/AgentEndpoints'
import { EngramExplorer } from './pages/EngramExplorer'
import { Goals } from './pages/Goals'
import { Recovery } from './pages/Recovery'
import { About } from './pages/About'
import { Users } from './pages/Users'
import { Invite } from './pages/Invite'
import { Expired } from './pages/Expired'
import Friction from './pages/Friction'
import Overview from './pages/Overview'
import { OnboardingWizard } from './pages/onboarding/OnboardingWizard'
import ComponentGallery from './pages/dev/ComponentGallery'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 5_000,
    },
  },
})

/**
 * Check if the orchestrator is reachable. If yes, Nova is ready.
 * If not, we show the startup screen (which talks to the recovery sidecar).
 */
async function checkBackendReady(): Promise<boolean> {
  try {
    const resp = await fetch('/api/health/live', { signal: AbortSignal.timeout(3000) })
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
        <Route path="/" element={<AppLayout><Overview /></AppLayout>} />
        <Route path="/chat" element={<AppLayout fullWidth><Chat /></AppLayout>} />
        <Route path="/tasks" element={<AppLayout><Tasks /></AppLayout>} />
        <Route path="/friction" element={<AppLayout><Friction /></AppLayout>} />
        <Route path="/pods" element={<AppLayout><Pods /></AppLayout>} />
        <Route path="/usage" element={<AppLayout><Usage /></AppLayout>} />
        <Route path="/keys" element={<AppLayout><Keys /></AppLayout>} />
        <Route path="/mcp" element={<AppLayout><MCP /></AppLayout>} />
        <Route path="/agents" element={<AppLayout><AgentEndpoints /></AppLayout>} />
        <Route path="/engrams" element={<AppLayout><EngramExplorer /></AppLayout>} />
        <Route path="/goals" element={<AppLayout><Goals /></AppLayout>} />
        <Route path="/models" element={<AppLayout><Models /></AppLayout>} />
        <Route path="/users" element={<AppLayout><Users /></AppLayout>} />
        <Route path="/settings" element={<AppLayout><Settings /></AppLayout>} />
        <Route path="/recovery" element={<AppLayout><Recovery /></AppLayout>} />
        <Route path="/about" element={<AppLayout><About /></AppLayout>} />
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
        <AuthProvider>
          <ToastProvider>
            <AppShell />
          </ToastProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
