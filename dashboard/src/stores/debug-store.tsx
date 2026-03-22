import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

export type DebugLevel = 'off' | 'verbose'

interface DebugStore {
  level: DebugLevel
  setLevel: (level: DebugLevel) => void
  /** True when any debug features should be visible */
  isDebug: boolean
}

const STORAGE_KEY = 'nova-debug-level'

function loadLevel(): DebugLevel {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'verbose') return stored
  } catch { /* ignore */ }
  return 'off'
}

const DebugContext = createContext<DebugStore>({
  level: 'off',
  setLevel: () => {},
  isDebug: false,
})

export function DebugProvider({ children }: { children: ReactNode }) {
  const [level, setLevelState] = useState<DebugLevel>(loadLevel)

  const setLevel = (l: DebugLevel) => {
    setLevelState(l)
    try {
      localStorage.setItem(STORAGE_KEY, l)
    } catch { /* ignore */ }
  }

  return (
    <DebugContext.Provider value={{ level, setLevel, isDebug: level !== 'off' }}>
      {children}
    </DebugContext.Provider>
  )
}

export function useDebug() {
  return useContext(DebugContext)
}
