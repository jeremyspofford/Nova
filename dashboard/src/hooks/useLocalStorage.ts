import { useState, useEffect, type Dispatch, type SetStateAction } from 'react'

const NAMESPACE = 'nova:'

/**
 * Like useState, but persists value to localStorage under the given key.
 * Falls back to `defaultValue` on first visit or if stored value is corrupted.
 * All keys are namespaced with "nova:" (e.g. "brain.showBgStars" → "nova:brain.showBgStars").
 *
 * Usage:
 *   const [showStars, setShowStars] = useLocalStorage('brain.showBgStars', true)
 */
export function useLocalStorage<T>(key: string, defaultValue: T): [T, Dispatch<SetStateAction<T>>] {
  const fullKey = NAMESPACE + key

  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(fullKey)
      return stored !== null ? JSON.parse(stored) as T : defaultValue
    } catch {
      return defaultValue
    }
  })

  // Persist to localStorage whenever value changes
  useEffect(() => {
    try {
      localStorage.setItem(fullKey, JSON.stringify(value))
    } catch { /* ignore quota/security errors */ }
  }, [fullKey, value])

  return [value, setValue]
}
