import { useState, useCallback, useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NavBar } from './components/NavBar'
import { StartupScreen } from './components/StartupScreen'
import { ChatProvider } from './stores/chat-store'
import { ThemeProvider } from './stores/theme-store'
import { AuthProvider, useAuth } from './stores/auth-store'
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
import { MemoryInspector } from './pages/MemoryInspector'
import { Recovery } from './pages/Recovery'
import { RemoteAccess } from './pages/RemoteAccess'

function PageShell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-6xl w-full">{children}</main>
}

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

  // No auth config yet (fetch failed/slow) or config says auth required → show login
  // This is fail-closed: we show Login unless we know auth isn't required
  return <Login />
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
    <ChatProvider>
    <BrowserRouter>
      <div className="h-screen overflow-hidden flex flex-col bg-neutral-50 dark:bg-neutral-950">
        <NavBar />
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          <Routes>
            {/* Chat gets full width for sidebar layout */}
            <Route path="/"        element={<Chat />} />
            <Route path="/chat"    element={<Chat />} />
            {/* Other pages get constrained width with scroll */}
            <Route path="/tasks"   element={<PageShell><Tasks /></PageShell>} />
            <Route path="/pods"    element={<PageShell><Pods /></PageShell>} />
            <Route path="/usage"   element={<PageShell><Usage /></PageShell>} />
            <Route path="/keys"    element={<PageShell><Keys /></PageShell>} />
            <Route path="/mcp"     element={<PageShell><MCP /></PageShell>} />
            <Route path="/agents"  element={<PageShell><AgentEndpoints /></PageShell>} />
            <Route path="/memory"  element={<PageShell><MemoryInspector /></PageShell>} />
            <Route path="/models"   element={<PageShell><Models /></PageShell>} />
            <Route path="/settings" element={<PageShell><Settings /></PageShell>} />
            <Route path="/recovery" element={<PageShell><Recovery /></PageShell>} />
            <Route path="/remote-access" element={<PageShell><RemoteAccess /></PageShell>} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
    </ChatProvider>
    </AuthGate>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <AppShell />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
