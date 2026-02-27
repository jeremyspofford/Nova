import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NavBar } from './components/NavBar'
import { Overview } from './pages/Overview'
import { Chat } from './pages/Chat'
import { Usage } from './pages/Usage'
import { Keys } from './pages/Keys'
import { MCP } from './pages/MCP'
import { Settings } from './pages/Settings'
import { Models } from './pages/Models'
import { Tasks } from './pages/Tasks'
import { Pods } from './pages/Pods'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 5_000,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen bg-stone-50">
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
              <Route path="/models"   element={<Models />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
