import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus, Trash2, RefreshCw, Circle, CheckCircle2, XCircle,
  ChevronDown, ChevronRight, Pencil, ExternalLink, Search,
} from 'lucide-react'
import {
  getMCPServers,
  createMCPServer,
  updateMCPServer,
  deleteMCPServer,
  reloadMCPServer,
  type MCPServer,
} from '../api'
import { MCP_CATALOG, ALL_TAGS, type CatalogEntry } from '../lib/mcp-catalog'
import Card from '../components/Card'
import { Input, Label, Select } from '../components/ui'

// ── Types ─────────────────────────────────────────────────────────────────────

interface EnvPair {
  key: string
  value: string
  required?: boolean
  label?: string
  hint?: string
}

interface PrefillValues {
  name: string
  description: string
  transport: 'stdio' | 'http'
  command: string
  args: string
  url: string
  enabled: boolean
  envPairs: EnvPair[]
  note?: string
}

const DEFAULT_FORM: PrefillValues = {
  name: '',
  description: '',
  transport: 'stdio',
  command: '',
  args: '',
  url: '',
  enabled: true,
  envPairs: [],
}

// ── Status icon ───────────────────────────────────────────────────────────────

function StatusIcon({ server }: { server: MCPServer }) {
  if (!server.enabled)  return <Circle size={13} className="text-neutral-300 dark:text-neutral-600" />
  if (server.connected) return <CheckCircle2 size={13} className="text-emerald-500" />
  return <XCircle size={13} className="text-red-400" />
}

// ── Server form (add or edit) ─────────────────────────────────────────────────

function ServerForm({
  initialValues,
  serverId,
  onDone,
  title = 'New MCP Server',
}: {
  initialValues?: PrefillValues
  serverId?: string
  onDone: () => void
  title?: string
}) {
  const vals = initialValues ?? DEFAULT_FORM
  const [form, setForm] = useState({
    name: vals.name,
    description: vals.description,
    transport: vals.transport,
    command: vals.command,
    args: vals.args,
    url: vals.url,
    enabled: vals.enabled,
  })
  const [envPairs, setEnvPairs] = useState<EnvPair[]>(vals.envPairs)

  const mutation = useMutation({
    mutationFn: (data: Parameters<typeof createMCPServer>[0]) =>
      serverId ? updateMCPServer(serverId, data) : createMCPServer(data),
    onSuccess: onDone,
  })

  const handleSubmit = () => {
    const env: Record<string, string> = {}
    for (const { key, value } of envPairs) {
      if (key.trim()) env[key.trim()] = value
    }
    mutation.mutate({
      name: form.name.trim(),
      description: form.description.trim(),
      transport: form.transport as MCPServer['transport'],
      command: form.command.trim() || null,
      args: form.args.trim() ? form.args.trim().split(/\s+/) : [],
      env,
      url: form.url.trim() || null,
      enabled: form.enabled,
    })
  }

  const isValid =
    form.name.trim() &&
    ((form.transport === 'stdio' && form.command.trim()) ||
      (form.transport === 'http' && form.url.trim()))

  const set = (key: string, value: unknown) =>
    setForm(f => ({ ...f, [key]: value }))

  // Check if required env vars are missing
  const missingRequired = envPairs
    .filter(p => p.required && !p.value.trim())
    .map(p => p.key)

  return (
    <Card className="p-5 space-y-4">
      <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
        {title}
      </p>

      {/* Note / warning box from catalog */}
      {vals.note && (
        <div className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2">
          <p className="text-xs text-amber-700 dark:text-amber-400">{vals.note}</p>
        </div>
      )}

      {/* Required env warning */}
      {missingRequired.length > 0 && (
        <div className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2">
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Fill in required variables before adding:{' '}
            <span className="font-mono font-medium">{missingRequired.join(', ')}</span>
          </p>
        </div>
      )}

      {/* Name + transport */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <Label>Name *</Label>
          <Input
            value={form.name}
            onChange={e => set('name', e.target.value)}
            placeholder="e.g. filesystem, brave-search"
          />
        </div>
        <div>
          <Label>Transport</Label>
          <Select
            value={form.transport}
            onChange={e => set('transport', e.target.value)}
          >
            <option value="stdio">stdio (subprocess)</option>
            <option value="http">http (remote)</option>
          </Select>
        </div>
      </div>

      {/* Command / URL */}
      {form.transport === 'stdio' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <Label>Command *</Label>
            <Input
              value={form.command}
              onChange={e => set('command', e.target.value)}
              placeholder="e.g. npx, uvx, node, python3"
            />
          </div>
          <div>
            <Label>
              Args <span className="text-neutral-300 dark:text-neutral-600">(space-separated)</span>
            </Label>
            <Input
              value={form.args}
              onChange={e => set('args', e.target.value)}
              placeholder="-y @modelcontextprotocol/server-filesystem /workspace"
            />
          </div>
        </div>
      ) : (
        <div>
          <Label>URL *</Label>
          <Input
            value={form.url}
            onChange={e => set('url', e.target.value)}
            placeholder="http://localhost:3000"
          />
        </div>
      )}

      {/* Description */}
      <div>
        <Label>Description</Label>
        <Input
          value={form.description}
          onChange={e => set('description', e.target.value)}
          placeholder="Optional — shown in the server card"
        />
      </div>

      {/* Env vars */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-xs text-neutral-500 dark:text-neutral-400">Environment Variables</label>
          <button
            onClick={() => setEnvPairs(p => [...p, { key: '', value: '' }])}
            className="text-xs text-accent-700 dark:text-accent-400 hover:text-accent-500 dark:hover:text-accent-300"
          >
            + Add variable
          </button>
        </div>
        {envPairs.map((pair, i) => (
          <div key={i} className={`mb-2 rounded-md ${pair.required ? 'border-l-2 border-amber-400 pl-2' : ''}`}>
            {pair.label && (
              <div className="mb-1 flex items-center gap-1">
                <span className="text-xs text-neutral-500 dark:text-neutral-400">{pair.label}</span>
                {pair.required && <span className="text-xs text-red-500">*</span>}
              </div>
            )}
            <div className="flex gap-2">
              <input
                value={pair.key}
                onChange={e =>
                  setEnvPairs(p => p.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))
                }
                placeholder="KEY"
                className="flex-1 rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-1.5 text-xs text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
              />
              <input
                value={pair.value}
                onChange={e =>
                  setEnvPairs(p => p.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                }
                placeholder={pair.required && !pair.value ? 'Required' : 'value'}
                className={`flex-1 rounded-md border px-3 py-1.5 text-xs outline-none focus:border-accent-600
                  ${pair.required && !pair.value.trim()
                    ? 'border-amber-400 dark:border-amber-600 bg-amber-50 dark:bg-amber-900/20 text-neutral-900 dark:text-neutral-100'
                    : 'border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100'
                  }`}
              />
              <button
                onClick={() => setEnvPairs(p => p.filter((_, j) => j !== i))}
                className="shrink-0 text-neutral-500 dark:text-neutral-400 hover:text-red-600 dark:hover:text-red-400 px-1"
              >
                ×
              </button>
            </div>
            {pair.hint && (
              <p className="mt-0.5 text-xs text-neutral-400 dark:text-neutral-500">{pair.hint}</p>
            )}
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-t border-neutral-100 dark:border-neutral-800 pt-3">
        <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400 cursor-pointer">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={e => set('enabled', e.target.checked)}
            className="rounded"
          />
          Connect immediately after adding
        </label>
        <div className="flex gap-2">
          <button
            onClick={onDone}
            className="rounded-md px-3 py-1.5 text-sm text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!isValid || mutation.isPending}
            className="flex items-center gap-1.5 rounded-md bg-accent-700 px-4 py-1.5 text-sm text-white hover:bg-accent-500 disabled:opacity-40"
          >
            <Plus size={13} />
            {mutation.isPending
              ? (serverId ? 'Saving…' : 'Adding…')
              : (serverId ? 'Save Changes' : 'Add Server')}
          </button>
        </div>
      </div>

      {mutation.isError && (
        <p className="text-xs text-red-600 dark:text-red-400">{String(mutation.error)}</p>
      )}
    </Card>
  )
}

// ── Server card ───────────────────────────────────────────────────────────────

function ServerCard({
  server,
  onDelete,
  onReload,
  reloading,
}: {
  server: MCPServer
  onDelete: () => void
  onReload: () => void
  reloading: boolean
}) {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)

  const existingEnvPairs: EnvPair[] = Object.entries(server.env || {}).map(([key, value]) => ({
    key,
    value,
  }))

  const initialValues: PrefillValues = {
    name: server.name,
    description: server.description ?? '',
    transport: server.transport,
    command: server.command ?? '',
    args: (server.args ?? []).join(' '),
    url: server.url ?? '',
    enabled: server.enabled,
    envPairs: existingEnvPairs,
  }

  const handleEditDone = () => {
    setEditing(false)
    qc.invalidateQueries({ queryKey: ['mcp-servers'] })
  }

  return (
    <Card className="overflow-hidden">
      {/* Header row */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
        onClick={() => !editing && setExpanded(v => !v)}
      >
        <StatusIcon server={server} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{server.name}</span>
            <span className="rounded-full bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 text-xs text-neutral-500 dark:text-neutral-400">
              {server.transport}
            </span>
            {server.connected && (
              <span className="rounded-full bg-emerald-50 dark:bg-emerald-900/30 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-400">
                {server.tool_count} tool{server.tool_count !== 1 ? 's' : ''}
              </span>
            )}
            {!server.enabled && (
              <span className="rounded-full bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 text-xs text-neutral-500 dark:text-neutral-400">
                disabled
              </span>
            )}
          </div>
          {server.description && (
            <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400 truncate">{server.description}</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 ml-2" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => { setEditing(v => !v); setExpanded(false) }}
            title="Edit server"
            className="text-neutral-500 dark:text-neutral-400 hover:text-accent-700 dark:hover:text-accent-400 transition-colors"
          >
            <Pencil size={13} />
          </button>
          <button
            onClick={onReload}
            disabled={reloading}
            title="Reload / reconnect"
            className="text-neutral-500 dark:text-neutral-400 hover:text-accent-700 dark:hover:text-accent-400 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={13} className={reloading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={onDelete}
            title="Remove server"
            className="text-neutral-500 dark:text-neutral-400 hover:text-red-600 dark:hover:text-red-400 transition-colors"
          >
            <Trash2 size={13} />
          </button>
        </div>

        {/* Expand chevron — hide in edit mode */}
        {!editing && (
          <div className="text-neutral-300 dark:text-neutral-600">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </div>
        )}
      </div>

      {/* Edit form */}
      {editing && (
        <div className="border-t border-neutral-100 dark:border-neutral-800 bg-neutral-50/20 dark:bg-neutral-900/10 p-4">
          <ServerForm
            initialValues={initialValues}
            serverId={server.id}
            onDone={handleEditDone}
            title="Edit MCP Server"
          />
        </div>
      )}

      {/* Expanded detail panel */}
      {expanded && !editing && (
        <div className="border-t border-neutral-100 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-800 px-4 py-3 space-y-2">
          {server.command && (
            <div className="text-xs">
              <span className="text-neutral-500 dark:text-neutral-400 mr-1">Command:</span>
              <code className="text-neutral-700 dark:text-neutral-300">
                {server.command}
                {server.args && server.args.length > 0 ? ' ' + server.args.join(' ') : ''}
              </code>
            </div>
          )}
          {server.url && (
            <div className="text-xs">
              <span className="text-neutral-500 dark:text-neutral-400 mr-1">URL:</span>
              <code className="text-neutral-700 dark:text-neutral-300">{server.url}</code>
            </div>
          )}
          {Object.keys(server.env || {}).length > 0 && (
            <div className="text-xs">
              <span className="text-neutral-500 dark:text-neutral-400 mr-1">Env vars:</span>
              <code className="text-neutral-700 dark:text-neutral-300">{Object.keys(server.env).join(', ')}</code>
            </div>
          )}

          {server.active_tools && server.active_tools.length > 0 && (
            <div className="pt-1">
              <p className="mb-1.5 text-xs text-neutral-500 dark:text-neutral-400">Available tools:</p>
              <div className="flex flex-wrap gap-1.5">
                {server.active_tools.map(t => (
                  <span
                    key={t}
                    className="rounded bg-accent-50 dark:bg-accent-900/30 px-2 py-0.5 text-xs font-mono text-accent-700 dark:text-accent-400"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}

          {server.connected === false && server.enabled && (
            <p className="text-xs text-red-500 dark:text-red-400">
              Not connected — click Reload to retry, or check the orchestrator logs.
            </p>
          )}
        </div>
      )}
    </Card>
  )
}

// ── Catalog card ─────────────────────────────────────────────────────────────

function CatalogCard({
  entry,
  onInstall,
}: {
  entry: CatalogEntry
  onInstall: (entry: CatalogEntry) => void
}) {
  return (
    <Card className="p-4 flex flex-col gap-3">
      <div className="flex-1">
        <div className="flex items-start justify-between gap-2">
          <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{entry.displayName}</span>
          {entry.docs && (
            <a
              href={entry.docs}
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
              className="shrink-0 text-neutral-400 dark:text-neutral-500 hover:text-accent-600 dark:hover:text-accent-400 transition-colors"
              title="Documentation"
            >
              <ExternalLink size={12} />
            </a>
          )}
        </div>
        <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400 leading-relaxed">{entry.description}</p>
        <div className="mt-2 flex flex-wrap gap-1">
          {entry.tags.map(tag => (
            <span
              key={tag}
              className="rounded-full bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 text-xs text-neutral-500 dark:text-neutral-400"
            >
              {tag}
            </span>
          ))}
        </div>
      </div>
      <button
        onClick={() => onInstall(entry)}
        className="w-full rounded-md bg-accent-700 px-3 py-1.5 text-xs text-white hover:bg-accent-500 transition-colors"
      >
        Install
      </button>
    </Card>
  )
}

// ── MCP page ──────────────────────────────────────────────────────────────────

export function MCP() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [prefill, setPrefill] = useState<PrefillValues | null>(null)
  const [formKey, setFormKey] = useState(0)
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const formRef = useRef<HTMLDivElement>(null)

  const { data: servers = [], isLoading, error } = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: getMCPServers,
    refetchInterval: 15_000,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteMCPServer,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mcp-servers'] }),
  })

  const reloadMutation = useMutation({
    mutationFn: reloadMCPServer,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mcp-servers'] }),
  })

  const handleFormDone = () => {
    setShowForm(false)
    setPrefill(null)
    qc.invalidateQueries({ queryKey: ['mcp-servers'] })
  }

  const handleInstall = (entry: CatalogEntry) => {
    const envPairs: EnvPair[] = entry.env.map(e => ({
      key: e.key,
      value: e.default ?? '',
      required: e.required,
      label: e.label,
      hint: e.description,
    }))
    const pf: PrefillValues = {
      name: entry.name,
      description: entry.description,
      transport: 'stdio',
      command: entry.command,
      args: entry.args.join(' '),
      url: '',
      enabled: true,
      envPairs,
      note: entry.note,
    }
    setPrefill(pf)
    setFormKey(k => k + 1)
    setShowForm(true)
    setTimeout(() => formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  // Auto-open catalog when no servers
  const effectiveCatalogOpen = catalogOpen || (servers.length === 0 && !isLoading)

  // Hide catalog entries that are already installed (match by name)
  const installedNames = new Set(servers.map(s => s.name.toLowerCase()))

  const filteredCatalog = MCP_CATALOG.filter(entry => {
    if (installedNames.has(entry.name.toLowerCase())) return false
    const matchesTag = !tagFilter || entry.tags.includes(tagFilter)
    const q = search.toLowerCase()
    const matchesSearch = !q ||
      entry.displayName.toLowerCase().includes(q) ||
      entry.description.toLowerCase().includes(q) ||
      entry.tags.some(t => t.includes(q))
    return matchesTag && matchesSearch
  })

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">MCP Servers</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400 max-w-2xl">
          Model Context Protocol servers extend what Nova can do by exposing additional tools.
          Any server that implements the{' '}
          <a
            href="https://modelcontextprotocol.io"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-700 dark:text-accent-400 underline underline-offset-2"
          >
            MCP spec
          </a>{' '}
          — Anthropic's open standard — can be connected here. Nova namespaces each
          server's tools as{' '}
          <code className="rounded bg-neutral-100 dark:bg-neutral-800 px-1 py-0.5 text-xs text-neutral-600 dark:text-neutral-400">
            mcp__server__tool
          </code>{' '}
          so they're available alongside Nova's built-in file, shell, and git tools.
        </p>
      </div>

      {/* Add server button */}
      <button
        onClick={() => {
          setPrefill(null)
          setFormKey(k => k + 1)
          setShowForm(v => !v)
        }}
        className="flex items-center gap-1.5 rounded-md bg-accent-700 px-4 py-2 text-sm text-white hover:bg-accent-500 transition-colors"
      >
        <Plus size={14} />
        {showForm ? 'Cancel' : 'Add Server'}
      </button>

      {/* Add / edit server form */}
      {showForm && (
        <div ref={formRef}>
          <ServerForm
            key={formKey}
            initialValues={prefill ?? undefined}
            onDone={handleFormDone}
            title={prefill ? `Install: ${prefill.name}` : 'New MCP Server'}
          />
        </div>
      )}

      {/* Server list */}
      {isLoading && <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading…</p>}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{String(error)}</p>}

      <div className="space-y-3">
        {servers.map(server => (
          <ServerCard
            key={server.id}
            server={server}
            onDelete={() => {
              if (confirm(`Remove MCP server "${server.name}"? This will disconnect it immediately.`)) {
                deleteMutation.mutate(server.id)
              }
            }}
            onReload={() => reloadMutation.mutate(server.id)}
            reloading={reloadMutation.isPending}
          />
        ))}

        {servers.length === 0 && !isLoading && (
          <Card className="p-10 text-center">
            <p className="text-sm font-medium text-neutral-500 dark:text-neutral-400">No MCP servers registered yet</p>
            <p className="mt-1 text-xs text-neutral-300 dark:text-neutral-600">
              Browse the catalog below or add a server manually.
            </p>
          </Card>
        )}
      </div>

      {/* MCP Catalog */}
      <Card className="overflow-hidden">
        {/* Catalog header */}
        <button
          className="w-full flex items-center justify-between px-4 py-3 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
          onClick={() => setCatalogOpen(v => !v)}
        >
          <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
            Browse MCP Catalog
          </p>
          {effectiveCatalogOpen ? <ChevronDown size={14} className="text-neutral-400" /> : <ChevronRight size={14} className="text-neutral-400" />}
        </button>

        {effectiveCatalogOpen && (
          <div className="border-t border-neutral-100 dark:border-neutral-800 p-4 space-y-4">
            {/* Search + tag filters */}
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative flex-1">
                <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search servers…"
                  className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 pl-8 pr-3 py-1.5 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
                />
              </div>
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setTagFilter(null)}
                  className={`rounded-full px-2.5 py-0.5 text-xs transition-colors ${
                    tagFilter === null
                      ? 'bg-accent-700 text-white'
                      : 'bg-neutral-100 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700'
                  }`}
                >
                  all
                </button>
                {ALL_TAGS.map(tag => (
                  <button
                    key={tag}
                    onClick={() => setTagFilter(t => (t === tag ? null : tag))}
                    className={`rounded-full px-2.5 py-0.5 text-xs transition-colors ${
                      tagFilter === tag
                        ? 'bg-accent-700 text-white'
                        : 'bg-neutral-100 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700'
                    }`}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            </div>

            {/* Grid */}
            {filteredCatalog.length === 0 ? (
              <p className="text-sm text-neutral-400 dark:text-neutral-500 text-center py-4">No matching servers.</p>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {filteredCatalog.map(entry => (
                  <CatalogCard
                    key={entry.id}
                    entry={entry}
                    onInstall={handleInstall}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
