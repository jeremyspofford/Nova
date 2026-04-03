import { useState, useCallback, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Code, Terminal, Loader2, Play, Square, RefreshCw } from 'lucide-react'
import { patchEnv, manageComposeProfile, getAllServiceStatus, getEnvVars } from '../../api-recovery'
import type { AllServicesResponse } from '../../api-recovery'
import { Section } from '../../components/ui'
import { ServiceStatusBadge } from './shared'

type EditorFlavor = 'vscode' | 'neovim'

const FLAVOR_CONFIG: Record<EditorFlavor, { label: string; icon: typeof Code; profile: string; container: string; configEnvKey: string; configLabel: string }> = {
  vscode: { label: 'VS Code', icon: Code, profile: 'editor-vscode', container: 'nova-editor-vscode', configEnvKey: 'VSCODE_CONFIG_PATH', configLabel: 'VS Code Config Path' },
  neovim: { label: 'Neovim', icon: Terminal, profile: 'editor-neovim', container: 'nova-editor-neovim', configEnvKey: 'NEOVIM_CONFIG_PATH', configLabel: 'Neovim Config Path' },
}

interface EditorState {
  flavor: EditorFlavor
  loading: boolean
  error: string
  workspacePath: string
  configPath: string
  dotfilesRepo: string
}

function deriveRunning(data: AllServicesResponse | undefined) {
  const optional = data?.optional ?? []
  const vsRunning = optional.some(s => s.service === 'editor-vscode' && s.status === 'running')
  const nvimRunning = optional.some(s => s.service === 'editor-neovim' && s.status === 'running')
  return { vsRunning, nvimRunning }
}

export default function EditorSection() {
  const queryClient = useQueryClient()

  const { data: allServices } = useQuery<AllServicesResponse>({
    queryKey: ['all-service-status'],
    queryFn: getAllServiceStatus,
    refetchInterval: 5_000,
  })

  const { vsRunning, nvimRunning } = deriveRunning(allServices)
  const activeRunning = vsRunning || nvimRunning
  const runningFlavor: EditorFlavor | null = vsRunning ? 'vscode' : nvimRunning ? 'neovim' : null

  const [s, setS] = useState<EditorState>({
    flavor: 'vscode',
    loading: false,
    error: '',
    workspacePath: '',
    configPath: '',
    dotfilesRepo: '',
  })
  const set = (patch: Partial<EditorState>) => setS(prev => ({ ...prev, ...patch }))

  // Load current env values on mount
  useEffect(() => {
    getEnvVars().then(env => {
      setS(prev => ({
        ...prev,
        flavor: (env.EDITOR_FLAVOR as EditorFlavor) || prev.flavor,
        workspacePath: env.EDITOR_WORKSPACE || '',
        configPath: env[FLAVOR_CONFIG[(env.EDITOR_FLAVOR as EditorFlavor) || 'vscode'].configEnvKey] || '',
        dotfilesRepo: env.EDITOR_DOTFILES_REPO || '',
      }))
    }).catch(() => { /* recovery service may not be up yet */ })
  }, [])

  // Sync flavor selector to whichever is running
  useEffect(() => {
    if (runningFlavor) setS(prev => ({ ...prev, flavor: runningFlavor }))
  }, [runningFlavor])

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['service-status'] })
  }, [queryClient])

  const handleStart = useCallback(async () => {
    set({ loading: true, error: '' })
    try {
      // Save env vars if changed
      const envUpdates: Record<string, string> = {}
      if (s.workspacePath.trim()) envUpdates.EDITOR_WORKSPACE = s.workspacePath.trim()
      const cfg = FLAVOR_CONFIG[s.flavor]
      if (s.configPath.trim()) envUpdates[cfg.configEnvKey] = s.configPath.trim()
      if (s.dotfilesRepo.trim()) envUpdates.EDITOR_DOTFILES_REPO = s.dotfilesRepo.trim()
      if (Object.keys(envUpdates).length > 0) await patchEnv(envUpdates)

      await manageComposeProfile(cfg.profile, 'start')
      set({ loading: false })
      refresh()
    } catch (e: any) {
      set({ error: e.message || 'Failed to start editor', loading: false })
    }
  }, [s.flavor, s.workspacePath, s.configPath, s.dotfilesRepo, refresh])

  const handleStop = useCallback(async () => {
    const flavor = runningFlavor ?? s.flavor
    set({ loading: true, error: '' })
    try {
      await manageComposeProfile(FLAVOR_CONFIG[flavor].profile, 'stop')
      set({ loading: false })
      refresh()
    } catch (e: any) {
      set({ error: e.message || 'Failed to stop editor', loading: false })
    }
  }, [runningFlavor, s.flavor, refresh])

  const handleSwitch = useCallback(async () => {
    if (!runningFlavor) return
    const target: EditorFlavor = runningFlavor === 'vscode' ? 'neovim' : 'vscode'
    set({ loading: true, error: '', flavor: target })
    try {
      await manageComposeProfile(FLAVOR_CONFIG[runningFlavor].profile, 'stop')
      await manageComposeProfile(FLAVOR_CONFIG[target].profile, 'start')
      set({ loading: false })
      refresh()
    } catch (e: any) {
      set({ error: e.message || 'Failed to switch editor', loading: false })
    }
  }, [runningFlavor, refresh])

  const handleEnvBlur = useCallback(async (key: string, value: string) => {
    if (!value.trim()) return
    try {
      await patchEnv({ [key]: value.trim() })
    } catch {
      // Silent — will save on next start
    }
  }, [])

  const cfg = FLAVOR_CONFIG[s.flavor]

  return (
    <Section
      icon={Code}
      title="Editor"
      description="Embedded code editor (VS Code Server or Neovim). Accessible from the Editor page in the sidebar."
    >
      {/* Flavor selector */}
      <div className="space-y-4">
        <div>
          <label className="text-compact font-medium text-content-primary block mb-2">Editor</label>
          <div className="flex gap-2">
            {(['vscode', 'neovim'] as EditorFlavor[]).map(f => {
              const fc = FLAVOR_CONFIG[f]
              const Icon = fc.icon
              const selected = s.flavor === f
              return (
                <button
                  key={f}
                  onClick={() => set({ flavor: f })}
                  disabled={s.loading}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
                    selected
                      ? 'bg-teal-600 text-white border-teal-600'
                      : 'bg-surface-card text-content-secondary border-border-subtle hover:bg-surface-card-hover'
                  } disabled:opacity-50`}
                >
                  <Icon className="w-4 h-4" />
                  {fc.label}
                </button>
              )
            })}
          </div>
        </div>

        {/* Status + actions */}
        <div className="flex items-center gap-3">
          <span className="text-compact text-content-tertiary">Status:</span>
          <ServiceStatusBadge
            configured={true}
            running={s.flavor === 'vscode' ? vsRunning : nvimRunning}
          />
        </div>

        <div className="flex items-center gap-2">
          {!activeRunning && (
            <button
              onClick={handleStart}
              disabled={s.loading}
              className="flex items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50 transition-colors"
            >
              {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Start {cfg.label}
            </button>
          )}

          {activeRunning && (
            <>
              <button
                onClick={handleStop}
                disabled={s.loading}
                className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-card px-4 py-2 text-sm font-medium text-content-primary hover:bg-surface-card-hover disabled:opacity-50 transition-colors"
              >
                {s.loading ? <Loader2 size={14} className="animate-spin" /> : <Square size={14} />}
                Stop
              </button>
              <button
                onClick={handleSwitch}
                disabled={s.loading}
                className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-card px-4 py-2 text-sm font-medium text-content-primary hover:bg-surface-card-hover disabled:opacity-50 transition-colors"
              >
                {s.loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Switch to {runningFlavor === 'vscode' ? 'Neovim' : 'VS Code'}
              </button>
            </>
          )}
        </div>

        {/* Configuration fields */}
        <div className="border-t border-border-subtle pt-4 space-y-3">
          <div>
            <label className="text-caption font-medium text-content-secondary block mb-1">Workspace Path</label>
            <input
              type="text"
              value={s.workspacePath}
              onChange={e => set({ workspacePath: e.target.value })}
              onBlur={() => handleEnvBlur('EDITOR_WORKSPACE', s.workspacePath)}
              placeholder="/home/user/projects"
              className="w-full rounded-md border border-border-subtle bg-surface-card px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary"
            />
            <p className="mt-1 text-micro text-content-tertiary">Host directory mounted into the editor container.</p>
          </div>

          <div>
            <label className="text-caption font-medium text-content-secondary block mb-1">{cfg.configLabel}</label>
            <input
              type="text"
              value={s.configPath}
              onChange={e => set({ configPath: e.target.value })}
              onBlur={() => handleEnvBlur(cfg.configEnvKey, s.configPath)}
              placeholder={s.flavor === 'vscode' ? '~/.vscode-server' : '~/.config/nvim'}
              className="w-full rounded-md border border-border-subtle bg-surface-card px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary"
            />
            <p className="mt-1 text-micro text-content-tertiary">
              {s.flavor === 'vscode' ? 'Persisted VS Code settings and extensions.' : 'Persisted Neovim configuration directory.'}
            </p>
          </div>

          <div>
            <label className="text-caption font-medium text-content-secondary block mb-1">Dotfiles Repository</label>
            <input
              type="text"
              value={s.dotfilesRepo}
              onChange={e => set({ dotfilesRepo: e.target.value })}
              onBlur={() => handleEnvBlur('EDITOR_DOTFILES_REPO', s.dotfilesRepo)}
              placeholder="https://github.com/user/dotfiles"
              className="w-full rounded-md border border-border-subtle bg-surface-card px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary"
            />
            <p className="mt-1 text-micro text-content-tertiary">Optional. Cloned into the editor container on startup for shell config, aliases, etc.</p>
          </div>
        </div>

        {s.error && (
          <p className="text-sm text-red-600 dark:text-red-400">{s.error}</p>
        )}
      </div>
    </Section>
  )
}
