import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, RefreshCw, Circle, CheckCircle2, XCircle, ChevronDown, ChevronRight } from 'lucide-react'
import {
  getMCPServers,
  createMCPServer,
  deleteMCPServer,
  reloadMCPServer,
  type MCPServer,
} from '../api'

// ── Status icon ───────────────────────────────────────────────────────────────

function StatusIcon({ server }: { server: MCPServer }) {
  if (!server.enabled)  return <Circle size={13} className="text-stone-300 dark:text-stone-600" />
  if (server.connected) return <CheckCircle2 size={13} className="text-emerald-500" />
  return <XCircle size={13} className="text-red-400" />
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
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-xl border border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 overflow-hidden">
      {/* Header row */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-stone-50 dark:hover:bg-stone-800 transition-colors"
        onClick={() => setExpanded(v => !v)}
      >
        <StatusIcon server={server} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-stone-900 dark:text-stone-100">{server.name}</span>
            <span className="rounded-full bg-stone-100 dark:bg-stone-800 px-2 py-0.5 text-xs text-stone-500 dark:text-stone-400">
              {server.transport}
            </span>
            {server.connected && (
              <span className="rounded-full bg-emerald-50 dark:bg-emerald-900/30 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-400">
                {server.tool_count} tool{server.tool_count !== 1 ? 's' : ''}
              </span>
            )}
            {!server.enabled && (
              <span className="rounded-full bg-stone-100 dark:bg-stone-800 px-2 py-0.5 text-xs text-stone-400 dark:text-stone-500">
                disabled
              </span>
            )}
          </div>
          {server.description && (
            <p className="mt-0.5 text-xs text-stone-400 dark:text-stone-500 truncate">{server.description}</p>
          )}
        </div>

        {/* Actions — stop propagation so click doesn't toggle expand */}
        <div className="flex items-center gap-2 ml-2" onClick={e => e.stopPropagation()}>
          <button
            onClick={onReload}
            disabled={reloading}
            title="Reload / reconnect"
            className="text-stone-400 dark:text-stone-500 hover:text-teal-700 dark:hover:text-teal-400 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={13} className={reloading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={onDelete}
            title="Remove server"
            className="text-stone-400 dark:text-stone-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
          >
            <Trash2 size={13} />
          </button>
        </div>

        {/* Expand chevron */}
        <div className="text-stone-300 dark:text-stone-600">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </div>

      {/* Expanded detail panel */}
      {expanded && (
        <div className="border-t border-stone-100 dark:border-stone-800 bg-stone-50 dark:bg-stone-800 px-4 py-3 space-y-2">
          {server.command && (
            <div className="text-xs">
              <span className="text-stone-400 dark:text-stone-500 mr-1">Command:</span>
              <code className="text-stone-700 dark:text-stone-300">
                {server.command}
                {server.args && server.args.length > 0 ? ' ' + server.args.join(' ') : ''}
              </code>
            </div>
          )}
          {server.url && (
            <div className="text-xs">
              <span className="text-stone-400 dark:text-stone-500 mr-1">URL:</span>
              <code className="text-stone-700 dark:text-stone-300">{server.url}</code>
            </div>
          )}
          {Object.keys(server.env || {}).length > 0 && (
            <div className="text-xs">
              <span className="text-stone-400 dark:text-stone-500 mr-1">Env vars:</span>
              <code className="text-stone-700 dark:text-stone-300">{Object.keys(server.env).join(', ')}</code>
            </div>
          )}

          {/* Tool chips */}
          {server.active_tools && server.active_tools.length > 0 && (
            <div className="pt-1">
              <p className="mb-1.5 text-xs text-stone-400 dark:text-stone-500">Available tools:</p>
              <div className="flex flex-wrap gap-1.5">
                {server.active_tools.map(t => (
                  <span
                    key={t}
                    className="rounded bg-teal-50 dark:bg-teal-900/30 px-2 py-0.5 text-xs font-mono text-teal-700 dark:text-teal-400"
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
    </div>
  )
}

// ── Add server form ───────────────────────────────────────────────────────────

function AddServerForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({
    name: '',
    description: '',
    transport: 'stdio',
    command: '',
    args: '',
    url: '',
    enabled: true,
  })
  const [envPairs, setEnvPairs] = useState<{ key: string; value: string }[]>([])

  const mutation = useMutation({
    mutationFn: createMCPServer,
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

  return (
    <div className="rounded-xl border border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 p-5 space-y-4">
      <p className="text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
        New MCP Server
      </p>

      {/* Name + transport */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs text-stone-400 dark:text-stone-500">Name *</label>
          <input
            value={form.name}
            onChange={e => set('name', e.target.value)}
            placeholder="e.g. filesystem, brave-search"
            className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-stone-400 dark:text-stone-500">Transport</label>
          <select
            value={form.transport}
            onChange={e => set('transport', e.target.value)}
            className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
          >
            <option value="stdio">stdio (subprocess)</option>
            <option value="http">http (remote)</option>
          </select>
        </div>
      </div>

      {/* Command / URL */}
      {form.transport === 'stdio' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs text-stone-400 dark:text-stone-500">Command *</label>
            <input
              value={form.command}
              onChange={e => set('command', e.target.value)}
              placeholder="e.g. npx, node, python3"
              className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-stone-400 dark:text-stone-500">
              Args <span className="text-stone-300 dark:text-stone-600">(space-separated)</span>
            </label>
            <input
              value={form.args}
              onChange={e => set('args', e.target.value)}
              placeholder="-y @modelcontextprotocol/server-filesystem /workspace"
              className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
            />
          </div>
        </div>
      ) : (
        <div>
          <label className="mb-1 block text-xs text-stone-400 dark:text-stone-500">URL *</label>
          <input
            value={form.url}
            onChange={e => set('url', e.target.value)}
            placeholder="http://localhost:3000"
            className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
          />
        </div>
      )}

      {/* Description */}
      <div>
        <label className="mb-1 block text-xs text-stone-400 dark:text-stone-500">Description</label>
        <input
          value={form.description}
          onChange={e => set('description', e.target.value)}
          placeholder="Optional — shown in the server card"
          className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
        />
      </div>

      {/* Env vars */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <label className="text-xs text-stone-400 dark:text-stone-500">Environment Variables</label>
          <button
            onClick={() => setEnvPairs(p => [...p, { key: '', value: '' }])}
            className="text-xs text-teal-700 dark:text-teal-400 hover:text-teal-500 dark:hover:text-teal-300"
          >
            + Add variable
          </button>
        </div>
        {envPairs.map((pair, i) => (
          <div key={i} className="mb-2 flex gap-2">
            <input
              value={pair.key}
              onChange={e =>
                setEnvPairs(p => p.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))
              }
              placeholder="KEY"
              className="flex-1 rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-3 py-1.5 text-xs text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
            />
            <input
              value={pair.value}
              onChange={e =>
                setEnvPairs(p => p.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
              }
              placeholder="value"
              className="flex-1 rounded-md border border-stone-300 dark:border-stone-600 bg-stone-50 dark:bg-stone-800 px-3 py-1.5 text-xs text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600"
            />
            <button
              onClick={() => setEnvPairs(p => p.filter((_, j) => j !== i))}
              className="shrink-0 text-stone-400 dark:text-stone-500 hover:text-red-600 dark:hover:text-red-400 px-1"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-t border-stone-100 dark:border-stone-800 pt-3">
        <label className="flex items-center gap-2 text-xs text-stone-600 dark:text-stone-400 cursor-pointer">
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
            className="rounded-md px-3 py-1.5 text-sm text-stone-500 dark:text-stone-400 hover:text-stone-900 dark:hover:text-stone-100"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!isValid || mutation.isPending}
            className="flex items-center gap-1.5 rounded-md bg-teal-700 px-4 py-1.5 text-sm text-white hover:bg-teal-500 disabled:opacity-40"
          >
            <Plus size={13} />
            {mutation.isPending ? 'Adding…' : 'Add Server'}
          </button>
        </div>
      </div>

      {mutation.isError && (
        <p className="text-xs text-red-600 dark:text-red-400">{String(mutation.error)}</p>
      )}
    </div>
  )
}

// ── MCP page ──────────────────────────────────────────────────────────────────

export function MCP() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)

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
    qc.invalidateQueries({ queryKey: ['mcp-servers'] })
  }

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-stone-900 dark:text-stone-100">MCP Servers</h1>
        <p className="mt-1 text-sm text-stone-400 dark:text-stone-500 max-w-2xl">
          Model Context Protocol servers extend what Nova can do by exposing additional tools.
          Any server that implements the{' '}
          <a
            href="https://modelcontextprotocol.io"
            target="_blank"
            rel="noopener noreferrer"
            className="text-teal-700 dark:text-teal-400 underline underline-offset-2"
          >
            MCP spec
          </a>{' '}
          — Anthropic's open standard — can be connected here. Nova namespaces each
          server's tools as{' '}
          <code className="rounded bg-stone-100 dark:bg-stone-800 px-1 py-0.5 text-xs text-stone-600 dark:text-stone-400">
            mcp__server__tool
          </code>{' '}
          so they're available alongside Nova's built-in file, shell, and git tools.
        </p>
      </div>

      {/* Add server button */}
      <button
        onClick={() => setShowForm(v => !v)}
        className="flex items-center gap-1.5 rounded-md bg-teal-700 px-4 py-2 text-sm text-white hover:bg-teal-500 transition-colors"
      >
        <Plus size={14} />
        {showForm ? 'Cancel' : 'Add Server'}
      </button>

      {/* Add server form */}
      {showForm && <AddServerForm onDone={handleFormDone} />}

      {/* Server list */}
      {isLoading && <p className="text-sm text-stone-400 dark:text-stone-500">Loading…</p>}
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
          <div className="rounded-xl border border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 p-10 text-center">
            <p className="text-sm font-medium text-stone-400 dark:text-stone-500">No MCP servers registered yet</p>
            <p className="mt-1 text-xs text-stone-300 dark:text-stone-600">
              Try the official{' '}
              <a
                href="https://github.com/modelcontextprotocol/servers"
                target="_blank"
                rel="noopener noreferrer"
                className="text-teal-600 dark:text-teal-400 underline underline-offset-2"
              >
                MCP server collection
              </a>{' '}
              for filesystem, Brave Search, Puppeteer, GitHub, and more.
            </p>
          </div>
        )}
      </div>

      {/* Quick-start examples */}
      {servers.length === 0 && !isLoading && (
        <div className="rounded-xl border border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 overflow-hidden">
          <div className="border-b border-stone-100 dark:border-stone-800 px-4 py-3">
            <p className="text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">
              Example Servers
            </p>
          </div>
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {[
              {
                name: 'filesystem',
                description: 'Read/write files in the workspace',
                command: 'npx',
                args: '-y @modelcontextprotocol/server-filesystem /workspace',
              },
              {
                name: 'brave-search',
                description: 'Web search via Brave API',
                command: 'npx',
                args: '-y @modelcontextprotocol/server-brave-search',
                env: 'BRAVE_API_KEY=your-key-here',
              },
              {
                name: 'github',
                description: 'GitHub repos, issues, PRs',
                command: 'npx',
                args: '-y @modelcontextprotocol/server-github',
                env: 'GITHUB_PERSONAL_ACCESS_TOKEN=your-token-here',
              },
            ].map(ex => (
              <div key={ex.name} className="px-4 py-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium text-stone-700 dark:text-stone-300">{ex.name}</span>
                  <span className="text-xs text-stone-400 dark:text-stone-500">{ex.description}</span>
                </div>
                <code className="text-xs text-stone-500 dark:text-stone-400">
                  {ex.command} {ex.args}
                </code>
                {ex.env && (
                  <div className="mt-0.5">
                    <code className="text-xs text-amber-600 dark:text-amber-400"># env: {ex.env}</code>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
