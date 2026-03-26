import { useState, useEffect, useCallback } from 'react'

/**
 * Persist the active tab in the URL hash so it survives page refresh.
 *
 * Usage:
 *   const [tab, setTab] = useTabHash('graph', ['graph', 'explorer', 'maintenance'])
 *
 * The hash is formatted as #tab=<id>. If the hash contains an unknown tab
 * ID (e.g. from a stale bookmark), falls back to the default.
 */
export function useTabHash<T extends string>(
  defaultTab: T,
  validTabs: readonly T[],
): [T, (tab: T) => void] {
  const readHash = useCallback((): T => {
    try {
      const hash = window.location.hash.slice(1) // strip #
      const params = new URLSearchParams(hash)
      const val = params.get('tab') as T | null
      if (val && (validTabs as readonly string[]).includes(val)) return val
    } catch { /* ignore */ }
    return defaultTab
  }, [defaultTab, validTabs])

  const [tab, setTabState] = useState<T>(readHash)

  const setTab = useCallback((next: T) => {
    setTabState(next)
    const hash = new URLSearchParams(window.location.hash.slice(1))
    hash.set('tab', next)
    window.history.replaceState(null, '', `#${hash.toString()}`)
  }, [])

  // Sync if user navigates back/forward
  useEffect(() => {
    const onHashChange = () => setTabState(readHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [readHash])

  return [tab, setTab]
}
