// dashboard/src/pages/Editors.tsx
import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Code, Copy, Check, RefreshCw, Zap, AlertCircle } from 'lucide-react'
import clsx from 'clsx'
import { apiFetch, getKeys, createKey, revokeKey, getModels } from '../api'
import { useAuth } from '../stores/auth-store'
import { hasMinRole } from '../lib/roles'
import { useTabHash } from '../hooks/useTabHash'
import { Button } from '../components/ui'
import {
  EDITORS,
  EDITOR_SLUGS,
  generateConfig,
  getPasteInstructions,
  type EditorSlug,
} from './editors/editorConfigs'

// ── Types ────────────────────────────────────────────────────────────────────

interface EditorConnection {
  editor: string
  last_seen: number | null
  request_count: number
  status: 'connected' | 'idle' | 'disconnected' | 'never'
}

interface ConnectionsResponse {
  connections: Record<string, EditorConnection>
  endpoint: string
  auth_required: boolean
}

// ── Connection Monitor (Zone 1) ──────────────────────────────────────────────

function ConnectionMonitor({ data }: { data: ConnectionsResponse | undefined }) {
  const [copied, setCopied] = useState(false)
  const endpoint = data?.endpoint ?? 'http://localhost:8001/v1'

  const copyEndpoint = () => {
    navigator.clipboard.writeText(endpoint)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const statusDot = (status: string) => {
    if (status === 'connected') return 'bg-success'
    if (status === 'idle') return 'bg-warning'
    return 'bg-neutral-500'
  }

  const formatLastSeen = (ts: number | null) => {
    if (!ts) return null
    const ago = Math.round((Date.now() / 1000) - ts)
    if (ago < 60) return `${ago}s ago`
    if (ago < 3600) return `${Math.round(ago / 60)}m ago`
    return `${Math.round(ago / 3600)}h ago`
  }

  return (
    <div className="flex items-center justify-between gap-4 p-4 border-b border-border-subtle">
      <div className="flex-1">
        <div className="text-micro font-semibold uppercase tracking-wider text-content-tertiary mb-2">
          Connected Editors
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {data && Object.values(data.connections).map(conn => (
            <div key={conn.editor} className="flex items-center gap-1.5 text-compact">
              <div className={clsx('w-1.5 h-1.5 rounded-full', statusDot(conn.status))} />
              <span className={clsx(
                conn.status === 'connected' ? 'text-content-primary' : 'text-content-tertiary',
              )}>
                {EDITORS.find(e => e.slug === conn.editor)?.name ?? conn.editor}
              </span>
              {conn.status === 'connected' && conn.last_seen && (
                <span className="text-content-tertiary text-micro">{formatLastSeen(conn.last_seen)}</span>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-2 text-compact text-content-secondary shrink-0">
        <span className="font-mono text-micro">{endpoint}</span>
        <button
          onClick={copyEndpoint}
          className="p-1 rounded hover:bg-surface-elevated transition-colors"
          title="Copy endpoint URL"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  )
}

// ── Config Panel (Zone 3) ────────────────────────────────────────────────────

function ConfigPanel({
  slug,
  endpoint,
  authRequired,
}: {
  slug: EditorSlug
  endpoint: string
  authRequired: boolean
}) {
  const { user, authConfig } = useAuth()
  const userRole = (user?.role ?? (authConfig?.trusted_network ? 'owner' : 'guest')) as string
  const isAdmin = hasMinRole(userRole as any, 'admin')

  const [copied, setCopied] = useState(false)
  const [selectedModel, setSelectedModel] = useState('')
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle')
  const [testError, setTestError] = useState('')
  const [editorKey, setEditorKey] = useState<string | null>(null)
  const [editorKeyId, setEditorKeyId] = useState<string | null>(null)

  // Fetch available models
  const { data: modelsData } = useQuery({
    queryKey: ['oai-models'],
    queryFn: getModels,
    staleTime: 30_000,
  })
  const models = modelsData?.data ?? []

  // Set default model on load
  useEffect(() => {
    if (models.length > 0 && !selectedModel) {
      setSelectedModel(models[0].id)
    }
  }, [models, selectedModel])

  // Fetch/create editor API key
  const { data: keys, refetch: refetchKeys } = useQuery({
    queryKey: ['api-keys'],
    queryFn: getKeys,
    enabled: authRequired && isAdmin,
    staleTime: 10_000,
  })

  // Find existing key for this editor
  const existingKey = keys?.find(k => k.name === `editor-${slug}`)

  // Determine the API key value to show in config
  const apiKeyDisplay = authRequired
    ? (editorKey ?? existingKey?.key_prefix ?? 'sk-nova-...')
    : 'unused'

  // Create key for this editor
  const createEditorKey = useMutation({
    mutationFn: async () => {
      if (existingKey) return null // Already exists
      const result = await createKey(`editor-${slug}`, 120)
      setEditorKey(result.raw_key)
      setEditorKeyId(result.id)
      return result
    },
    onSuccess: () => refetchKeys(),
  })

  // Regenerate key (revoke + recreate)
  const regenerateKey = useMutation({
    mutationFn: async () => {
      const keyToRevoke = editorKeyId ?? existingKey?.id
      if (keyToRevoke) {
        await revokeKey(keyToRevoke)
      }
      const result = await createKey(`editor-${slug}`, 120)
      setEditorKey(result.raw_key)
      setEditorKeyId(result.id)
      return result
    },
    onSuccess: () => refetchKeys(),
  })

  // Auto-create key on tab visit (if auth required, admin, and no key exists)
  const [keyCreationAttempted, setKeyCreationAttempted] = useState(false)
  useEffect(() => {
    if (authRequired && isAdmin && !existingKey && !editorKey && !keyCreationAttempted) {
      setKeyCreationAttempted(true)
      createEditorKey.mutate()
    }
  }, [authRequired, isAdmin, existingKey, editorKey, keyCreationAttempted])

  const config = generateConfig(slug, endpoint, selectedModel || 'your-model-id', apiKeyDisplay)
  const instructions = getPasteInstructions(slug)

  const copyConfig = () => {
    navigator.clipboard.writeText(config)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const testConnection = async () => {
    setTestStatus('testing')
    setTestError('')
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Nova-Editor': slug, // Tells the gateway which editor this is
      }
      if (authRequired && apiKeyDisplay !== 'sk-nova-...') {
        headers['Authorization'] = `Bearer ${apiKeyDisplay}`
      }
      const resp = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          model: selectedModel,
          messages: [{ role: 'user', content: 'ping' }],
          max_tokens: 1,
        }),
      })
      if (resp.ok) {
        setTestStatus('success')
      } else if (resp.status === 401 || resp.status === 403) {
        setTestStatus('error')
        setTestError('API key is invalid or revoked. Click Regenerate Key.')
      } else {
        const text = await resp.text().catch(() => '')
        setTestStatus('error')
        setTestError(text || `Gateway returned ${resp.status}`)
      }
    } catch {
      setTestStatus('error')
      setTestError('LLM Gateway is not responding. Check service status.')
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Non-admin warning */}
      {authRequired && !isAdmin && (
        <div className="flex items-start gap-2 p-3 rounded-md bg-warning/10 border border-warning/20 text-compact text-warning">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>Ask an admin to create an API key for you, or create one from Settings &gt; Keys.</span>
        </div>
      )}

      {/* Model selector */}
      <div>
        <label className="text-micro font-semibold uppercase tracking-wider text-content-tertiary mb-1.5 block">
          Step 1: Pick a model
        </label>
        <select
          value={selectedModel}
          onChange={e => setSelectedModel(e.target.value)}
          className="w-full max-w-sm rounded-md border border-border-subtle bg-surface-root px-3 py-2 text-compact text-content-primary focus:outline-none focus:ring-1 focus:ring-accent"
        >
          {models.map(m => (
            <option key={m.id} value={m.id}>{m.id}</option>
          ))}
        </select>
      </div>

      {/* Config block */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-micro font-semibold uppercase tracking-wider text-content-tertiary">
            Step 2: Copy this config
          </label>
          <button
            onClick={copyConfig}
            className="flex items-center gap-1 text-micro text-accent hover:text-accent-hover transition-colors"
          >
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
        <pre className="p-4 rounded-md bg-surface-root border border-border-subtle text-compact font-mono overflow-x-auto text-content-secondary">
          {config}
        </pre>
        {authRequired && isAdmin && (editorKey || existingKey) && (
          <div className="mt-2 flex items-center gap-2">
            <button
              onClick={() => regenerateKey.mutate()}
              disabled={regenerateKey.isPending}
              className="flex items-center gap-1 text-micro text-content-tertiary hover:text-content-primary transition-colors"
            >
              <RefreshCw className={clsx('w-3 h-3', regenerateKey.isPending && 'animate-spin')} />
              Regenerate Key
            </button>
            {regenerateKey.isSuccess && (
              <span className="text-micro text-warning">Key regenerated — update your editor config.</span>
            )}
          </div>
        )}
      </div>

      {/* Paste instructions */}
      <div>
        <label className="text-micro font-semibold uppercase tracking-wider text-content-tertiary mb-1.5 block">
          Step 3: Paste in your editor
        </label>
        <ol className="space-y-1 text-compact text-content-secondary list-decimal list-inside">
          {instructions.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      </div>

      {/* Test connection */}
      <div className="flex items-center gap-3">
        <Button
          size="sm"
          icon={<Zap className="w-3.5 h-3.5" />}
          onClick={testConnection}
          disabled={testStatus === 'testing' || !selectedModel}
        >
          {testStatus === 'testing' ? 'Testing...' : 'Test Connection'}
        </Button>
        {testStatus === 'success' && (
          <span className="flex items-center gap-1 text-compact text-success">
            <Check className="w-4 h-4" />
            Connected! Nova received the request using {selectedModel}.
          </span>
        )}
        {testStatus === 'error' && (
          <span className="flex items-center gap-1 text-compact text-danger">
            <AlertCircle className="w-4 h-4" />
            {testError}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function Editors() {
  const [tab, setTab] = useTabHash<EditorSlug>('continue', EDITOR_SLUGS)

  const { data: connections } = useQuery<ConnectionsResponse>({
    queryKey: ['editor-connections'],
    queryFn: () => apiFetch('/v1/editor-connections'),
    refetchInterval: 5_000,
  })

  const endpoint = connections?.endpoint ?? 'http://localhost:8001/v1'
  const authRequired = connections?.auth_required ?? false

  return (
    <div className="mx-auto max-w-4xl space-y-0">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg bg-accent-dim">
          <Code className="w-5 h-5 text-accent" />
        </div>
        <div>
          <h1 className="text-h3 text-content-primary">Connect Your Editor</h1>
          <p className="text-compact text-content-secondary">
            Use Nova as your AI backend in any editor
          </p>
        </div>
      </div>

      <div className="bg-surface-card rounded-lg border border-border-subtle glass-card dark:border-white/[0.08] overflow-hidden">
        {/* Zone 1: Connection monitor */}
        <ConnectionMonitor data={connections} />

        {/* Zone 2: Editor tabs */}
        <div className="flex border-b border-border-subtle overflow-x-auto">
          {EDITORS.map(editor => (
            <button
              key={editor.slug}
              onClick={() => setTab(editor.slug)}
              className={clsx(
                'px-4 py-3 text-compact font-medium whitespace-nowrap transition-colors border-b-2 -mb-px',
                tab === editor.slug
                  ? 'border-accent text-accent'
                  : 'border-transparent text-content-tertiary hover:text-content-secondary',
              )}
            >
              {editor.name}
            </button>
          ))}
        </div>

        {/* Zone 3: Config content */}
        <ConfigPanel
          key={tab}
          slug={tab}
          endpoint={endpoint}
          authRequired={authRequired}
        />
      </div>
    </div>
  )
}
