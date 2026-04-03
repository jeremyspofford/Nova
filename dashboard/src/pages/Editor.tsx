import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Code, ExternalLink, Loader2, MonitorOff, Terminal } from 'lucide-react'

type EditorState = 'detecting' | 'running' | 'stopped'
type EditorFlavor = 'vscode' | 'neovim'

// code-server: localhost host port (can't do subpath proxy — absolute asset URLs)
// neovim/ttyd: nginx proxy (supports --base-path natively)
const EDITOR_URLS: Record<EditorFlavor, string> = {
  vscode: 'http://localhost:8443',
  neovim: '/editor-neovim/',
}

const FLAVOR_LABELS: Record<EditorFlavor, string> = {
  vscode: 'VS Code',
  neovim: 'Neovim',
}

const FLAVOR_ICONS: Record<EditorFlavor, typeof Code> = {
  vscode: Code,
  neovim: Terminal,
}

async function probeEditor(flavor: EditorFlavor): Promise<boolean> {
  try {
    const url = flavor === 'vscode' ? 'http://localhost:8443/healthz' : '/editor-neovim/'
    const res = await fetch(url, { signal: AbortSignal.timeout(3000) })
    return res.ok
  } catch {
    return false
  }
}

async function detectActiveEditor(): Promise<EditorFlavor | null> {
  const [vscode, neovim] = await Promise.all([probeEditor('vscode'), probeEditor('neovim')])
  if (vscode) return 'vscode'
  if (neovim) return 'neovim'
  return null
}

export default function Editor() {
  const [state, setState] = useState<EditorState>('detecting')
  const [activeFlavor, setActiveFlavor] = useState<EditorFlavor | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const detect = useCallback(async () => {
    const flavor = await detectActiveEditor()
    if (flavor) {
      setState('running')
      setActiveFlavor(flavor)
      stopPolling()
    } else {
      setState('stopped')
      stopPolling()
    }
  }, [stopPolling])

  useEffect(() => {
    detect()
    pollRef.current = setInterval(detect, 3000)
    return stopPolling
  }, [detect, stopPolling])

  if (state === 'detecting') {
    return (
      <div className="flex items-center justify-center h-full text-content-tertiary">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Detecting editor...
      </div>
    )
  }

  if (state === 'stopped') {
    return (
      <div className="flex flex-col items-center justify-center h-full text-content-tertiary gap-4">
        <MonitorOff className="w-12 h-12 text-content-disabled" />
        <p className="text-lg">No editor running</p>
        <Link
          to="/settings#connections"
          className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-500 transition-colors"
        >
          Start one in Settings
        </Link>
      </div>
    )
  }

  // Running state — render iframe
  const flavor = activeFlavor!
  const FlavorIcon = FLAVOR_ICONS[flavor]
  const editorUrl = EDITOR_URLS[flavor]

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-surface-card border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2 text-sm text-content-primary">
          <FlavorIcon className="w-4 h-4" />
          <span>{FLAVOR_LABELS[flavor]}</span>
        </div>
        <a
          href={editorUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-xs text-content-tertiary hover:text-content-primary transition-colors"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          Pop out
        </a>
      </div>

      {/* Editor iframe */}
      <iframe
        src={editorUrl}
        className="flex-1 w-full border-0"
        title={`${FLAVOR_LABELS[flavor]} Editor`}
        allow="clipboard-read; clipboard-write"
      />
    </div>
  )
}
