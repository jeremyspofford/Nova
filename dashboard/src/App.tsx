import { useState, useCallback, useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NavBar } from './components/NavBar'
import { StartupScreen } from './components/StartupScreen'
import { ChatProvider } from './stores/chat-store'
import { ThemeProvider } from './stores/theme-store'
import { Overview } from './pages/Overview'
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

function AppShell() {
  const [ready, setReady] = useState<boolean | null>(null) // null = checking

  const handleReady = useCallback(() => setReady(true), [])

  useEffect(() => {
    checkBackendReady().then(ok => setReady(ok))
  }, [])

  // Still checking initial status
  if (ready === null) return null

  // Backend is down — show startup screen (talks to recovery service)
  if (!ready) {
    return <StartupScreen onReady={handleReady} />
  }

  // Normal operation
  return (
    <ChatProvider>
    <BrowserRouter>
      <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950">
        <NavBar />
        <main className="mx-auto max-w-6xl">
          <Routes>
            <Route path="/"        element={<Overview />} />
            <Route path="/chat"    element={<Chat />} />
            <Route path="/tasks"   element={<Tasks />} />
            <Route path="/pods"    element={<Pods />} />
            <Route path="/usage"   element={<Usage />} />
            <Route path="/keys"    element={<Keys />} />
            <Route path="/mcp"     element={<MCP />} />
            <Route path="/agents"  element={<AgentEndpoints />} />
            <Route path="/memory"  element={<MemoryInspector />} />
            <Route path="/models"   element={<Models />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/recovery" element={<Recovery />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
    </ChatProvider>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>
    </QueryClientProvider>
  )
}
