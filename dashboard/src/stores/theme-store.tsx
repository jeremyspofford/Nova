import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import {
  accentPalettes, neutralPalettes, themePresets, cardSurface,
  type ColorScale,
} from '../lib/color-palettes'

type Mode = 'light' | 'dark'
type ModePreference = 'light' | 'dark' | 'system'

interface ThemeState {
  modePreference: ModePreference
  lightPreset: string
  darkPreset: string
  customLightAccent: string
  customDarkAccent: string
}

interface ThemeStore {
  mode: Mode                              // resolved (never 'system')
  modePreference: ModePreference
  setModePreference: (p: ModePreference) => void
  lightPreset: string
  setLightPreset: (name: string) => void
  darkPreset: string
  setDarkPreset: (name: string) => void
  customLightAccent: string
  setCustomLightAccent: (name: string) => void
  customDarkAccent: string
  setCustomDarkAccent: (name: string) => void
  activePreset: string                    // whichever of light/dark is active
}

const STORAGE_KEY = 'nova-appearance'
const OLD_STORAGE_KEY = 'nova-theme'

function getSystemMode(): Mode {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function resolveMode(pref: ModePreference): Mode {
  return pref === 'system' ? getSystemMode() : pref
}

function loadState(): ThemeState {
  // Migrate from very old key (just stored 'light' | 'dark')
  const old = localStorage.getItem(OLD_STORAGE_KEY)
  if (old) {
    localStorage.removeItem(OLD_STORAGE_KEY)
    const mode: Mode = old === 'dark' || old === 'light' ? old : getSystemMode()
    const state: ThemeState = {
      modePreference: mode,
      lightPreset: 'default',
      darkPreset: 'default',
      customLightAccent: 'teal',
      customDarkAccent: 'teal',
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    return state
  }

  const raw = localStorage.getItem(STORAGE_KEY)
  if (raw) {
    try {
      const parsed = JSON.parse(raw)

      // Migrate from old shape { mode, preset, accent, neutral }
      if ('preset' in parsed && !('lightPreset' in parsed)) {
        const state: ThemeState = {
          modePreference: parsed.mode === 'dark' ? 'dark' : parsed.mode === 'light' ? 'light' : 'system',
          lightPreset: parsed.preset || 'default',
          darkPreset: parsed.preset || 'default',
          customLightAccent: parsed.accent || 'teal',
          customDarkAccent: parsed.accent || 'teal',
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
        return state
      }

      // Current shape
      return {
        modePreference: ['light', 'dark', 'system'].includes(parsed.modePreference)
          ? parsed.modePreference : 'dark',
        lightPreset: parsed.lightPreset || 'default',
        darkPreset: parsed.darkPreset || 'default',
        customLightAccent: parsed.customLightAccent || 'teal',
        customDarkAccent: parsed.customDarkAccent || 'teal',
      }
    } catch { /* fall through */ }
  }

  return {
    modePreference: 'dark',
    lightPreset: 'default',
    darkPreset: 'default',
    customLightAccent: 'teal',
    customDarkAccent: 'teal',
  }
}

/**
 * Inject all CSS custom properties via a dedicated <style> element.
 * This is more robust than inline styles because it always wins
 * over the :root defaults in index.css by source order (appended last).
 */
function applyTheme(mode: Mode, state: ThemeState) {
  document.documentElement.classList.toggle('dark', mode === 'dark')

  const presetKey = mode === 'dark' ? state.darkPreset : state.lightPreset
  const preset = themePresets[presetKey]

  let accentKey: string
  let neutralKey: string

  if (presetKey === 'custom') {
    accentKey = mode === 'dark' ? state.customDarkAccent : state.customLightAccent
    neutralKey = 'stone'
  } else if (preset) {
    accentKey = preset.accent
    neutralKey = preset.neutral
  } else {
    accentKey = 'teal'
    neutralKey = 'stone'
  }

  const accent: ColorScale = accentPalettes[accentKey] ?? accentPalettes.teal
  const neutral: ColorScale = neutralPalettes[neutralKey] ?? neutralPalettes.stone
  const surfaces = cardSurface[neutralKey] ?? cardSurface.stone
  const cardValue = mode === 'dark' ? surfaces.dark : surfaces.light

  const vars = [
    ...Object.entries(accent).map(([s, v]) => `--accent-${s}:${v}`),
    ...Object.entries(neutral).map(([s, v]) => `--neutral-${s}:${v}`),
    `--card:${cardValue}`,
  ].join(';')

  let el = document.getElementById('nova-theme-vars') as HTMLStyleElement | null
  if (!el) {
    el = document.createElement('style')
    el.id = 'nova-theme-vars'
  }
  el.textContent = `:root{${vars}}`
  document.head.appendChild(el)
}

const ThemeContext = createContext<ThemeStore | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ThemeState>(loadState)
  const [resolvedMode, setResolvedMode] = useState<Mode>(() => resolveMode(state.modePreference))

  // Listen for OS color scheme changes when in system mode
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      if (state.modePreference === 'system') {
        setResolvedMode(getSystemMode())
      }
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [state.modePreference])

  // Re-resolve mode when preference changes
  useEffect(() => {
    setResolvedMode(resolveMode(state.modePreference))
  }, [state.modePreference])

  // Apply theme on mount and whenever state/resolved mode changes
  useEffect(() => {
    applyTheme(resolvedMode, state)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [state, resolvedMode])

  const setModePreference = useCallback((p: ModePreference) => {
    setState(s => ({ ...s, modePreference: p }))
  }, [])

  const setLightPreset = useCallback((name: string) => {
    if (!themePresets[name]) return
    setState(s => ({ ...s, lightPreset: name }))
  }, [])

  const setDarkPreset = useCallback((name: string) => {
    if (!themePresets[name]) return
    setState(s => ({ ...s, darkPreset: name }))
  }, [])

  const setCustomLightAccent = useCallback((name: string) => {
    if (!accentPalettes[name]) return
    setState(s => ({ ...s, customLightAccent: name, lightPreset: 'custom' }))
  }, [])

  const setCustomDarkAccent = useCallback((name: string) => {
    if (!accentPalettes[name]) return
    setState(s => ({ ...s, customDarkAccent: name, darkPreset: 'custom' }))
  }, [])

  const activePreset = resolvedMode === 'dark' ? state.darkPreset : state.lightPreset

  return (
    <ThemeContext.Provider value={{
      mode: resolvedMode,
      modePreference: state.modePreference,
      setModePreference,
      lightPreset: state.lightPreset,
      setLightPreset,
      darkPreset: state.darkPreset,
      setDarkPreset,
      customLightAccent: state.customLightAccent,
      setCustomLightAccent,
      customDarkAccent: state.customDarkAccent,
      setCustomDarkAccent,
      activePreset,
    }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeStore {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
