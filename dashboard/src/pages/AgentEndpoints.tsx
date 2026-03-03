import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Pencil, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import {
  getAgentEndpoints,
  createAgentEndpoint,
  updateAgentEndpoint,
  deleteAgentEndpoint,
  type AgentEndpoint,
  type AgentEndpointWrite,
} from '../api'

// ── Form ──────────────────────────────────────────────────────────────────────

const PROTOCOLS = ['a2a', 'acp', 'generic'] as const

const EMPTY_FORM: Omit<AgentEndpointWrite, 'input_schema' | 'output_schema' | 'metadata'> & {
  input_schema: string
  output_schema: string
} = {
  name: '',
  description: '',
  url: '',
  auth_token: '',
  protocol: 'a2a',
  input_schema: '',
  output_schema: '',
  enabled: true,
}

function EndpointForm({
  initial,
  endpointId,
  onDone,
  title = 'New Agent Endpoint',
}: {
  initial?: typeof EMPTY_FORM
  endpointId?: string
  onDone: () => void
  title?: string
}) {
  const [form, setForm] = useState(initial ?? EMPTY_FORM)
  const [schemaError, setSchemaError] = useState('')

  const mutation = useMutation({
    mutationFn: (data: Partial<AgentEndpointWrite>) =>
      endpointId ? updateAgentEndpoint(endpointId, data) : createAgentEndpoint(data),
    onSuccess: onDone,
  })

  const set = (key: string, value: unknown) =>
    setForm(f => ({ ...f, [key]: value }))

  const handleSubmit = () => {
    setSchemaError('')
    let input_schema: Record<string, unknown> = {}
    let output_schema: Record<string, unknown> = {}
    if (form.input_schema.trim()) {
      try { input_schema = JSON.parse(form.input_schema) } catch {
        setSchemaError('Input schema is not valid JSON')
        return
      }
    }
    if (form.output_schema.trim()) {
      try { output_schema = JSON.parse(form.output_schema) } catch {
        setSchemaError('Output schema is not valid JSON')
        return
      }
    }
    const payload: Partial<AgentEndpointWrite> = {
      name: form.name.trim(),
      description: form.description.trim(),
      url: form.url.trim(),
      protocol: form.protocol,
      input_schema,
      output_schema,
      enabled: form.enabled,
      metadata: {},
    }
    if (form.auth_token?.trim()) payload.auth_token = form.auth_token.trim()
    mutation.mutate(payload)
  }

  const isValid = form.name.trim() && form.url.trim()

  return (
    <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 p-5 space-y-4">
      <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
        {title}
      </p>

      {/* Name + protocol */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs text-neutral-500 dark:text-neutral-400">Name *</label>
          <input
            value={form.name}
            onChange={e => set('name', e.target.value)}
            placeholder="e.g. coding-agent, research-bot"
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-neutral-500 dark:text-neutral-400">Protocol</label>
          <select
            value={form.protocol}
            onChange={e => set('protocol', e.target.value)}
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
          >
            {PROTOCOLS.map(p => (
              <option key={p} value={p}>{p.toUpperCase()}</option>
            ))}
          </select>
        </div>
      </div>

      {/* URL */}
      <div>
        <label className="mb-1 block text-xs text-neutral-500 dark:text-neutral-400">Base URL *</label>
        <input
          value={form.url}
          onChange={e => set('url', e.target.value)}
          placeholder="https://agent.example.com"
          className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
        />
      </div>

      {/* Description */}
      <div>
        <label className="mb-1 block text-xs text-neutral-500 dark:text-neutral-400">Description</label>
        <input
          value={form.description}
          onChange={e => set('description', e.target.value)}
          placeholder="What does this agent do?"
          className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
        />
      </div>

      {/* Auth token */}
      <div>
        <label className="mb-1 block text-xs text-neutral-500 dark:text-neutral-400">
          Auth Token{' '}
          <span className="text-neutral-300 dark:text-neutral-600">(sent as Bearer — leave blank to clear)</span>
        </label>
        <input
          type="password"
          value={form.auth_token ?? ''}
          onChange={e => set('auth_token', e.target.value)}
          placeholder="sk-…"
          className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
        />
      </div>

      {/* Schemas (optional) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs text-neutral-500 dark:text-neutral-400">
            Input Schema <span className="text-neutral-300 dark:text-neutral-600">(JSON, optional)</span>
          </label>
          <textarea
            value={form.input_schema}
            onChange={e => set('input_schema', e.target.value)}
            rows={3}
            placeholder='{"type":"object","properties":{"task":{"type":"string"}}}'
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-xs font-mono text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600 resize-y"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-neutral-500 dark:text-neutral-400">
            Output Schema <span className="text-neutral-300 dark:text-neutral-600">(JSON, optional)</span>
          </label>
          <textarea
            value={form.output_schema}
            onChange={e => set('output_schema', e.target.value)}
            rows={3}
            placeholder='{"type":"object","properties":{"result":{"type":"string"}}}'
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-xs font-mono text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600 resize-y"
          />
        </div>
      </div>

      {schemaError && (
        <p className="text-xs text-red-600 dark:text-red-400">{schemaError}</p>
      )}

      {/* Footer */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-t border-neutral-100 dark:border-neutral-800 pt-3">
        <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400 cursor-pointer">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={e => set('enabled', e.target.checked)}
            className="rounded"
          />
          Enable endpoint
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
              ? (endpointId ? 'Saving…' : 'Adding…')
              : (endpointId ? 'Save Changes' : 'Add Endpoint')}
          </button>
        </div>
      </div>

      {mutation.isError && (
        <p className="text-xs text-red-600 dark:text-red-400">{String(mutation.error)}</p>
      )}
    </div>
  )
}

// ── Endpoint card ─────────────────────────────────────────────────────────────

function EndpointCard({
  endpoint,
  onDelete,
}: {
  endpoint: AgentEndpoint
  onDelete: () => void
}) {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)

  const initial = {
    name: endpoint.name,
    description: endpoint.description,
    url: endpoint.url,
    auth_token: '',
    protocol: endpoint.protocol as typeof PROTOCOLS[number],
    input_schema: Object.keys(endpoint.input_schema).length
      ? JSON.stringify(endpoint.input_schema, null, 2)
      : '',
    output_schema: Object.keys(endpoint.output_schema).length
      ? JSON.stringify(endpoint.output_schema, null, 2)
      : '',
    enabled: endpoint.enabled,
  }

  const handleEditDone = () => {
    setEditing(false)
    qc.invalidateQueries({ queryKey: ['agent-endpoints'] })
  }

  const protocolColor: Record<string, string> = {
    a2a: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/30',
    acp: 'text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/30',
    generic: 'text-neutral-500 dark:text-neutral-400 bg-neutral-100 dark:bg-neutral-800',
  }

  return (
    <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 overflow-hidden">
      {/* Header row */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
        onClick={() => !editing && setExpanded(v => !v)}
      >
        {/* Status dot */}
        <div className={`w-2 h-2 rounded-full shrink-0 ${endpoint.enabled ? 'bg-emerald-500' : 'bg-neutral-300 dark:bg-neutral-600'}`} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
              {endpoint.name}
            </span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${protocolColor[endpoint.protocol] ?? protocolColor.generic}`}>
              {endpoint.protocol.toUpperCase()}
            </span>
            {!endpoint.enabled && (
              <span className="rounded-full bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 text-xs text-neutral-500 dark:text-neutral-400">
                disabled
              </span>
            )}
          </div>
          {endpoint.description && (
            <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400 truncate">
              {endpoint.description}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 ml-2" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => { setEditing(v => !v); setExpanded(false) }}
            title="Edit endpoint"
            className="text-neutral-500 dark:text-neutral-400 hover:text-accent-700 dark:hover:text-accent-400 transition-colors"
          >
            <Pencil size={13} />
          </button>
          <button
            onClick={onDelete}
            title="Remove endpoint"
            className="text-neutral-500 dark:text-neutral-400 hover:text-red-600 dark:hover:text-red-400 transition-colors"
          >
            <Trash2 size={13} />
          </button>
        </div>

        {!editing && (
          <div className="text-neutral-300 dark:text-neutral-600">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </div>
        )}
      </div>

      {/* Edit form */}
      {editing && (
        <div className="border-t border-neutral-100 dark:border-neutral-800 bg-neutral-50/20 dark:bg-neutral-900/10 p-4">
          <EndpointForm
            initial={initial}
            endpointId={endpoint.id}
            onDone={handleEditDone}
            title="Edit Agent Endpoint"
          />
        </div>
      )}

      {/* Detail panel */}
      {expanded && !editing && (
        <div className="border-t border-neutral-100 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-800 px-4 py-3 space-y-2">
          <div className="text-xs flex items-center gap-1">
            <span className="text-neutral-500 dark:text-neutral-400">URL:</span>
            <code className="text-neutral-700 dark:text-neutral-300 flex-1 truncate">{endpoint.url}</code>
            <a
              href={endpoint.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
              className="shrink-0 text-neutral-400 hover:text-accent-600 dark:hover:text-accent-400"
              title="Open URL"
            >
              <ExternalLink size={11} />
            </a>
          </div>
          <div className="text-xs">
            <span className="text-neutral-500 dark:text-neutral-400 mr-1">Added:</span>
            <span className="text-neutral-700 dark:text-neutral-300">
              {new Date(endpoint.created_at).toLocaleString()}
            </span>
          </div>
          {Object.keys(endpoint.input_schema).length > 0 && (
            <div className="text-xs">
              <span className="text-neutral-500 dark:text-neutral-400 mr-1">Input schema:</span>
              <code className="text-neutral-700 dark:text-neutral-300">
                {JSON.stringify(endpoint.input_schema)}
              </code>
            </div>
          )}
          {Object.keys(endpoint.output_schema).length > 0 && (
            <div className="text-xs">
              <span className="text-neutral-500 dark:text-neutral-400 mr-1">Output schema:</span>
              <code className="text-neutral-700 dark:text-neutral-300">
                {JSON.stringify(endpoint.output_schema)}
              </code>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function AgentEndpoints() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [formKey, setFormKey] = useState(0)

  const { data: endpoints = [], isLoading, error } = useQuery({
    queryKey: ['agent-endpoints'],
    queryFn: getAgentEndpoints,
    refetchInterval: 30_000,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteAgentEndpoint,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-endpoints'] }),
  })

  const handleFormDone = () => {
    setShowForm(false)
    qc.invalidateQueries({ queryKey: ['agent-endpoints'] })
  }

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Agent Endpoints</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400 max-w-2xl">
          Connect Nova to external agent systems using{' '}
          <strong className="text-neutral-700 dark:text-neutral-300">A2A</strong>{' '}
          (Google Agent-to-Agent) or{' '}
          <strong className="text-neutral-700 dark:text-neutral-300">ACP</strong>{' '}
          (BeeAI Agent Communication Protocol). Nova delegates tasks to these
          endpoints as if they were tool calls, then streams the result back.
        </p>
      </div>

      {/* Add button */}
      <button
        onClick={() => {
          setFormKey(k => k + 1)
          setShowForm(v => !v)
        }}
        className="flex items-center gap-1.5 rounded-md bg-accent-700 px-4 py-2 text-sm text-white hover:bg-accent-500 transition-colors"
      >
        <Plus size={14} />
        {showForm ? 'Cancel' : 'Add Endpoint'}
      </button>

      {/* Add form */}
      {showForm && (
        <EndpointForm key={formKey} onDone={handleFormDone} />
      )}

      {/* List */}
      {isLoading && <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading…</p>}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{String(error)}</p>}

      <div className="space-y-3">
        {endpoints.map(ep => (
          <EndpointCard
            key={ep.id}
            endpoint={ep}
            onDelete={() => {
              if (confirm(`Remove agent endpoint "${ep.name}"?`)) {
                deleteMutation.mutate(ep.id)
              }
            }}
          />
        ))}

        {endpoints.length === 0 && !isLoading && (
          <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-card dark:bg-neutral-900 p-10 text-center">
            <p className="text-sm font-medium text-neutral-500 dark:text-neutral-400">
              No agent endpoints registered yet
            </p>
            <p className="mt-1 text-xs text-neutral-300 dark:text-neutral-600">
              Add an A2A or ACP endpoint to delegate tasks to external agent systems.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
