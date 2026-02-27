import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown, ChevronRight, RefreshCw, Layers,
  CheckCircle2, XCircle, Loader2, AlertTriangle, Zap,
  Thermometer, Hash, Clock, RotateCw, FileText, Cpu, Settings2, Plus, X as XIcon,
} from 'lucide-react'
import clsx from 'clsx'
import { getPods, getPod, updatePodAgent } from '../api'
import type { Pod, PodAgent } from '../types'
import { ModelPicker } from '../components/ModelPicker'

// ── Role badge ─────────────────────────────────────────────────────────────────

const ROLE_COLORS: Record<string, string> = {
  context:     'bg-sky-100 text-sky-700 border-sky-200',
  task:        'bg-teal-50 text-teal-700 border-teal-200',
  guardrail:   'bg-amber-100 text-amber-700 border-amber-200',
  code_review: 'bg-violet-100 text-violet-700 border-violet-200',
  decision:    'bg-emerald-100 text-emerald-700 border-emerald-200',
}

function RoleBadge({ role }: { role: string }) {
  const cls = ROLE_COLORS[role] ?? 'bg-stone-100 text-stone-600 border-stone-200'
  return (
    <span className={clsx('rounded-full border px-2 py-0.5 text-xs font-medium capitalize', cls)}>
      {role.replace('_', ' ')}
    </span>
  )
}

// ── On-failure badge ──────────────────────────────────────────────────────────

const FAILURE_ICON: Record<string, JSX.Element> = {
  abort:    <XCircle size={11} />,
  skip:     <AlertTriangle size={11} />,
  escalate: <Zap size={11} />,
}

// ── Agent row ──────────────────────────────────────────────────────────────────

function AgentRow({
  agent, podId, podDefaultModel,
}: {
  agent: PodAgent
  podId: string
  podDefaultModel?: string | null
}) {
  const [expanded, setExpanded] = useState(false)
  const qc = useQueryClient()

  const toggle = useMutation({
    mutationFn: () => updatePodAgent(podId, agent.id, {
      name: agent.name, role: agent.role, position: agent.position,
      model: agent.model ?? undefined, fallback_models: agent.fallback_models ?? [],
      temperature: agent.temperature,
      max_tokens: agent.max_tokens, timeout_seconds: agent.timeout_seconds,
      max_retries: agent.max_retries, system_prompt: agent.system_prompt ?? undefined,
      allowed_tools: agent.allowed_tools ?? undefined, on_failure: agent.on_failure,
      run_condition: agent.run_condition,
      artifact_type: agent.artifact_type ?? undefined,
      parallel_group: agent.parallel_group ?? undefined,
      enabled: !agent.enabled,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pod', podId] }),
  })

  return (
    <div className={clsx(
      'rounded-lg border transition-all',
      agent.enabled ? 'border-stone-200 bg-white' : 'border-stone-100 bg-stone-50 opacity-60',
    )}>
      {/* Summary row — click to expand, toggle stays separate */}
      <div className="flex items-center gap-3 px-3 py-2.5">
        {/* Expand button */}
        <button
          onClick={() => setExpanded(e => !e)}
          className="flex shrink-0 items-center gap-2 min-w-0 flex-1 text-left"
        >
          <span className="shrink-0 text-stone-400">
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </span>
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-stone-100 text-[10px] font-bold text-stone-400">
            {agent.position + 1}
          </span>
          <RoleBadge role={agent.role} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-stone-800">{agent.name}</p>
            {agent.model && (
              <p className="truncate text-xs text-stone-400">{agent.model}</p>
            )}
          </div>
        </button>

        {/* Right-side metadata (non-clickable) */}
        <span
          title={`On failure: ${agent.on_failure}`}
          className="hidden shrink-0 items-center gap-1 text-xs text-stone-400 sm:flex"
        >
          {FAILURE_ICON[agent.on_failure] ?? null}
          {agent.on_failure}
        </span>

        <span className="hidden rounded-full bg-stone-100 px-1.5 py-0.5 text-[10px] text-stone-400 sm:inline">
          {agent.allowed_tools ? `${agent.allowed_tools.length} tools` : 'all tools'}
        </span>

        {/* Enable/disable toggle */}
        <button
          onClick={e => { e.stopPropagation(); toggle.mutate() }}
          disabled={toggle.isPending}
          title={agent.enabled ? 'Disable agent' : 'Enable agent'}
          className="relative shrink-0 ml-1"
        >
          {toggle.isPending ? (
            <Loader2 size={14} className="animate-spin text-stone-400" />
          ) : (
            <div className={clsx(
              'h-4 w-7 rounded-full transition-colors',
              agent.enabled ? 'bg-teal-700' : 'bg-stone-200',
            )}>
              <div className={clsx(
                'absolute top-0.5 size-3 rounded-full bg-white shadow transition-all',
                agent.enabled ? 'left-3.5' : 'left-0.5',
              )} />
            </div>
          )}
        </button>
      </div>

      {/* Expanded config detail */}
      {expanded && (
        <div className="border-t border-stone-100 px-4 pb-4 pt-3 space-y-4">

          {/* Settings: temp, tokens, timeout, retries, on_failure, tools — all editable */}
          <AgentAdvancedSettings agent={agent} podId={podId} />

          {/* Model + fallbacks */}
          <AgentModelPicker agent={agent} podId={podId} podDefaultModel={podDefaultModel} />

          {/* System prompt */}
          <AgentSystemPrompt agent={agent} podId={podId} />

        </div>
      )}
    </div>
  )
}

// ── Small stat tile ────────────────────────────────────────────────────────────

function ConfigStat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-md bg-stone-50 border border-stone-100 px-3 py-2">
      <p className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-stone-400 mb-0.5">
        {icon} {label}
      </p>
      <p className="text-sm font-semibold text-stone-700">{value}</p>
    </div>
  )
}

// ── Inline system prompt editor ────────────────────────────────────────────────

function AgentSystemPrompt({ agent, podId }: { agent: PodAgent; podId: string }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState(agent.system_prompt ?? '')
  const [editing, setEditing] = useState(false)

  const save = useMutation({
    mutationFn: () => updatePodAgent(podId, agent.id, {
      name: agent.name, role: agent.role, enabled: agent.enabled,
      position: agent.position, model: agent.model ?? undefined,
      fallback_models: agent.fallback_models,
      temperature: agent.temperature, max_tokens: agent.max_tokens,
      timeout_seconds: agent.timeout_seconds, max_retries: agent.max_retries,
      allowed_tools: agent.allowed_tools ?? undefined, on_failure: agent.on_failure,
      run_condition: agent.run_condition,
      artifact_type: agent.artifact_type ?? undefined,
      parallel_group: agent.parallel_group ?? undefined,
      system_prompt: draft || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pod', podId] })
      setEditing(false)
    },
  })

  const cancel = () => {
    setDraft(agent.system_prompt ?? '')
    setEditing(false)
  }

  return (
    <div>
      {/* Header row */}
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1 text-xs font-medium text-stone-500">
          <FileText size={11} /> System Prompt
        </p>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="rounded px-2 py-0.5 text-[11px] font-medium text-teal-700 hover:bg-teal-50 border border-transparent hover:border-teal-200 transition-colors"
          >
            Edit
          </button>
        )}
      </div>

      {editing ? (
        /* ── Edit mode ─────────────────────────────────────────────────── */
        <div className="space-y-2">
          <textarea
            rows={8}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="Describe this agent's role, persona, and constraints…"
            className="w-full resize-y rounded-md border border-teal-400 bg-white px-3 py-2 font-mono text-xs text-stone-800 outline-none ring-2 ring-teal-200 placeholder:text-stone-400 focus:border-teal-600"
            autoFocus
          />
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-stone-400">{draft.length} chars</span>
            <div className="flex items-center gap-1.5">
              <button
                onClick={cancel}
                disabled={save.isPending}
                className="rounded-md border border-stone-200 px-3 py-1 text-xs text-stone-500 hover:bg-stone-100 disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={() => save.mutate()}
                disabled={save.isPending}
                className="flex items-center gap-1.5 rounded-md bg-teal-700 px-3 py-1 text-xs font-medium text-white hover:bg-teal-600 disabled:opacity-40"
              >
                {save.isPending
                  ? <><Loader2 size={11} className="animate-spin" /> Saving…</>
                  : 'Save'}
              </button>
            </div>
          </div>
          {save.isError && (
            <p className="text-[11px] text-red-600">Save failed — check console</p>
          )}
        </div>
      ) : (
        /* ── View mode ─────────────────────────────────────────────────── */
        agent.system_prompt ? (
          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-stone-50 border border-stone-100 px-3 py-2 font-mono text-xs text-stone-600 leading-relaxed">
            {agent.system_prompt}
          </pre>
        ) : (
          <button
            onClick={() => setEditing(true)}
            className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-stone-300 py-3 text-xs text-stone-400 hover:border-teal-400 hover:text-teal-600 transition-colors"
          >
            <FileText size={12} />
            No system prompt — click to add one
          </button>
        )
      )}
    </div>
  )
}

// ── Inline advanced settings editor ───────────────────────────────────────────

const ON_FAILURE_OPTIONS = ['abort', 'skip', 'escalate'] as const

function AgentAdvancedSettings({ agent, podId }: { agent: PodAgent; podId: string }) {
  const qc = useQueryClient()
  const [editing, setEditing]           = useState(false)
  const [onFailure, setOnFailure]       = useState(agent.on_failure)
  const [temperature, setTemperature]   = useState(String(agent.temperature))
  const [maxTokens, setMaxTokens]       = useState(String(agent.max_tokens))
  const [timeout, setTimeout_]          = useState(String(agent.timeout_seconds))
  const [maxRetries, setMaxRetries]     = useState(String(agent.max_retries))
  const [tools, setTools]               = useState<string[] | null>(agent.allowed_tools)
  const [toolInput, setToolInput]       = useState('')

  const addTool = () => {
    const t = toolInput.trim()
    if (!t) return
    setTools(prev => [...(prev ?? []), t])
    setToolInput('')
  }

  const removeTool = (idx: number) =>
    setTools(prev => (prev ?? []).filter((_, i) => i !== idx))

  const cancel = () => {
    setOnFailure(agent.on_failure)
    setTemperature(String(agent.temperature))
    setMaxTokens(String(agent.max_tokens))
    setTimeout_(String(agent.timeout_seconds))
    setMaxRetries(String(agent.max_retries))
    setTools(agent.allowed_tools)
    setToolInput('')
    setEditing(false)
  }

  const save = useMutation({
    mutationFn: () => updatePodAgent(podId, agent.id, {
      name: agent.name, role: agent.role, enabled: agent.enabled,
      position: agent.position, model: agent.model ?? undefined,
      fallback_models: agent.fallback_models,
      system_prompt: agent.system_prompt ?? undefined,
      run_condition: agent.run_condition,
      artifact_type: agent.artifact_type ?? undefined,
      parallel_group: agent.parallel_group ?? undefined,
      on_failure: onFailure,
      temperature: parseFloat(temperature) || agent.temperature,
      max_tokens: parseInt(maxTokens) || agent.max_tokens,
      timeout_seconds: parseInt(timeout) || agent.timeout_seconds,
      max_retries: parseInt(maxRetries) || agent.max_retries,
      allowed_tools: tools,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pod', podId] })
      setEditing(false)
    },
  })

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1 text-xs font-medium text-stone-500">
          <Settings2 size={11} /> Settings
        </p>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="rounded px-2 py-0.5 text-[11px] font-medium text-teal-700 hover:bg-teal-50 border border-transparent hover:border-teal-200 transition-colors"
          >
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="space-y-3 rounded-md border border-teal-200 bg-teal-50/20 p-3">

          {/* On-failure + numeric fields */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {/* On failure */}
            <div className="col-span-2 sm:col-span-1">
              <label className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-stone-400">
                On Failure
              </label>
              <select
                value={onFailure}
                onChange={e => setOnFailure(e.target.value)}
                className="w-full rounded-md border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-800 outline-none focus:border-teal-600"
              >
                {ON_FAILURE_OPTIONS.map(o => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>

            {/* Temperature */}
            <div>
              <label className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-stone-400">
                Temperature
              </label>
              <input
                type="number" step="0.05" min="0" max="2"
                value={temperature}
                onChange={e => setTemperature(e.target.value)}
                className="w-full rounded-md border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-800 outline-none focus:border-teal-600"
              />
            </div>

            {/* Max tokens */}
            <div>
              <label className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-stone-400">
                Max Tokens
              </label>
              <input
                type="number" min="1"
                value={maxTokens}
                onChange={e => setMaxTokens(e.target.value)}
                className="w-full rounded-md border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-800 outline-none focus:border-teal-600"
              />
            </div>

            {/* Timeout */}
            <div>
              <label className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-stone-400">
                Timeout (s)
              </label>
              <input
                type="number" min="1"
                value={timeout}
                onChange={e => setTimeout_(e.target.value)}
                className="w-full rounded-md border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-800 outline-none focus:border-teal-600"
              />
            </div>

            {/* Max retries */}
            <div>
              <label className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-stone-400">
                Max Retries
              </label>
              <input
                type="number" min="0" max="10"
                value={maxRetries}
                onChange={e => setMaxRetries(e.target.value)}
                className="w-full rounded-md border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-800 outline-none focus:border-teal-600"
              />
            </div>
          </div>

          {/* Allowed tools */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-[10px] font-medium uppercase tracking-wide text-stone-400">
                Allowed Tools
              </label>
              <button
                onClick={() => setTools(t => t === null ? [] : null)}
                className="text-[10px] text-teal-700 hover:underline"
              >
                {tools === null ? 'Restrict to list' : 'Allow all tools'}
              </button>
            </div>
            {tools === null ? (
              <p className="text-xs italic text-stone-400">All tools allowed (no restriction)</p>
            ) : (
              <div className="space-y-1.5">
                <div className="flex flex-wrap gap-1 min-h-6">
                  {tools.length === 0 && (
                    <span className="text-xs italic text-stone-400">No tools — add one below</span>
                  )}
                  {tools.map((t, i) => (
                    <span key={i} className="flex items-center gap-0.5 rounded-full bg-stone-100 border border-stone-200 pl-2 pr-1 py-0.5 text-[11px] text-stone-700">
                      {t}
                      <button onClick={() => removeTool(i)} className="ml-0.5 rounded-full hover:bg-stone-300 p-0.5">
                        <XIcon size={9} />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-1">
                  <input
                    type="text"
                    placeholder="tool name…"
                    value={toolInput}
                    onChange={e => setToolInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTool() } }}
                    className="flex-1 rounded-md border border-stone-300 bg-white px-2 py-1 text-xs text-stone-800 outline-none focus:border-teal-600 placeholder:text-stone-400"
                  />
                  <button
                    onClick={addTool}
                    disabled={!toolInput.trim()}
                    className="flex items-center gap-0.5 rounded-md border border-stone-300 px-2 py-1 text-xs text-stone-600 hover:bg-stone-100 disabled:opacity-40"
                  >
                    <Plus size={11} /> Add
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-1.5">
            <button
              onClick={cancel}
              disabled={save.isPending}
              className="rounded-md border border-stone-200 px-3 py-1 text-xs text-stone-500 hover:bg-stone-100 disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending}
              className="flex items-center gap-1.5 rounded-md bg-teal-700 px-3 py-1 text-xs font-medium text-white hover:bg-teal-600 disabled:opacity-40"
            >
              {save.isPending ? <><Loader2 size={11} className="animate-spin" /> Saving…</> : 'Save'}
            </button>
          </div>
          {save.isError && (
            <p className="text-[11px] text-red-600">Save failed — check console</p>
          )}
        </div>
      ) : (
        /* View mode — compact summary of settings */
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <ConfigStat icon={<Thermometer size={12} />} label="Temperature" value={String(agent.temperature)} />
          <ConfigStat icon={<Hash size={12} />} label="Max Tokens" value={agent.max_tokens.toLocaleString()} />
          <ConfigStat icon={<Clock size={12} />} label="Timeout" value={`${agent.timeout_seconds}s`} />
          <ConfigStat icon={<RotateCw size={12} />} label="Max Retries" value={String(agent.max_retries)} />
        </div>
      )}
    </div>
  )
}

// ── Inline model + fallback editor ────────────────────────────────────────────

function AgentModelPicker({
  agent, podId, podDefaultModel,
}: {
  agent: PodAgent
  podId: string
  podDefaultModel?: string | null
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [primary, setPrimary] = useState<string | null>(agent.model ?? null)
  const [fallbacks, setFallbacks] = useState<string[]>(agent.fallback_models ?? [])

  const hasChanges =
    primary !== (agent.model ?? null) ||
    JSON.stringify(fallbacks) !== JSON.stringify(agent.fallback_models ?? [])

  const save = useMutation({
    mutationFn: () => updatePodAgent(podId, agent.id, {
      name: agent.name, role: agent.role, enabled: agent.enabled,
      position: agent.position, temperature: agent.temperature,
      max_tokens: agent.max_tokens, timeout_seconds: agent.timeout_seconds,
      max_retries: agent.max_retries,
      system_prompt: agent.system_prompt ?? undefined,
      allowed_tools: agent.allowed_tools ?? undefined,
      on_failure: agent.on_failure, run_condition: agent.run_condition,
      artifact_type: agent.artifact_type ?? undefined,
      parallel_group: agent.parallel_group ?? undefined,
      model: primary ?? undefined,
      fallback_models: fallbacks,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pod', podId] })
      setEditing(false)
    },
  })

  const cancel = () => {
    setPrimary(agent.model ?? null)
    setFallbacks(agent.fallback_models ?? [])
    setEditing(false)
  }

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1 text-xs font-medium text-stone-500">
          <Cpu size={11} /> Model
        </p>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="rounded px-2 py-0.5 text-[11px] font-medium text-teal-700 hover:bg-teal-50 border border-transparent hover:border-teal-200 transition-colors"
          >
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="space-y-3">
          <ModelPicker
            primaryModel={primary}
            fallbackModels={fallbacks}
            onChange={(p, f) => { setPrimary(p); setFallbacks(f) }}
            podDefaultModel={podDefaultModel}
          />
          <div className="flex items-center justify-end gap-1.5">
            <button
              onClick={cancel}
              disabled={save.isPending}
              className="rounded-md border border-stone-200 px-3 py-1 text-xs text-stone-500 hover:bg-stone-100 disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending || !hasChanges}
              className="flex items-center gap-1.5 rounded-md bg-teal-700 px-3 py-1 text-xs font-medium text-white hover:bg-teal-600 disabled:opacity-40"
            >
              {save.isPending ? <><Loader2 size={11} className="animate-spin" /> Saving…</> : 'Save'}
            </button>
          </div>
          {save.isError && (
            <p className="text-[11px] text-red-600">Save failed — check console</p>
          )}
        </div>
      ) : (
        <div className="space-y-0.5">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-stone-400">Primary:</span>
            {agent.model ? (
              <span className="font-mono text-stone-700">{agent.model}</span>
            ) : (
              <span className="italic text-stone-400">
                inherit{podDefaultModel ? ` (${podDefaultModel.split('/').pop()})` : ''}
              </span>
            )}
          </div>
          {(agent.fallback_models ?? []).length > 0 ? (
            <p className="text-xs text-stone-400">
              Fallbacks:{' '}
              <span className="font-mono text-stone-500">
                {(agent.fallback_models ?? []).join(' → ')}
              </span>
            </p>
          ) : (
            <p className="text-xs italic text-stone-400">No fallbacks configured</p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Pod detail (expanded) ──────────────────────────────────────────────────────

function PodDetail({ podId }: { podId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['pod', podId],
    queryFn: () => getPod(podId),
    staleTime: 10_000,
  })

  if (isLoading) return (
    <div className="flex items-center gap-2 py-4 pl-6 text-xs text-stone-400">
      <Loader2 size={12} className="animate-spin" /> Loading agents…
    </div>
  )

  if (isError || !data) return (
    <p className="py-4 pl-6 text-xs text-red-600">Failed to load agents</p>
  )

  const agents = data.agents ?? []

  if (agents.length === 0) return (
    <p className="py-4 pl-6 text-xs text-stone-400">No agents configured in this pod.</p>
  )

  return (
    <div className="mt-2 space-y-1.5 pl-4 pt-1 border-t border-stone-200">
      {/* Column headers */}
      <div className="flex gap-3 px-3 py-1 text-[10px] uppercase tracking-wider text-stone-400">
        <span className="w-5 shrink-0">#</span>
        <span className="w-24 shrink-0">Role</span>
        <span className="flex-1">Name / Model</span>
        <span className="w-16 text-right">On Fail</span>
        <span className="w-14 text-right">Tools</span>
        <span className="w-7" />
      </div>
      {agents
        .sort((a, b) => a.position - b.position)
        .map(agent => (
          <AgentRow
            key={agent.id}
            agent={agent}
            podId={podId}
            podDefaultModel={data.default_model ?? null}
          />
        ))}
    </div>
  )
}

// ── Pod card ───────────────────────────────────────────────────────────────────

const REVIEW_LABELS: Record<string, string> = {
  always:         'Always',
  never:          'Never',
  on_escalation:  'On Escalation',
}

const THRESHOLD_COLORS: Record<string, string> = {
  low:      'text-emerald-700',
  medium:   'text-amber-600',
  high:     'text-orange-600',
  critical: 'text-red-600',
}

function PodCard({ pod }: { pod: Pod }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className={clsx(
      'rounded-xl border transition-all',
      pod.enabled ? 'border-stone-200 bg-white' : 'border-stone-200/50 bg-white/40',
    )}>
      {/* Header */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left"
      >
        {/* Expand chevron */}
        <span className="shrink-0 text-stone-400">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>

        {/* Pod status dot */}
        <span className={clsx(
          'size-2 shrink-0 rounded-full',
          pod.enabled ? 'bg-emerald-500' : 'bg-stone-400',
        )} />

        {/* Name */}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="font-medium text-stone-900">{pod.name}</span>
            {!pod.enabled && (
              <span className="text-xs text-stone-400">disabled</span>
            )}
          </div>
          {pod.description && (
            <p className="truncate text-xs text-stone-400">{pod.description}</p>
          )}
        </div>

        {/* Agent count */}
        <span className="flex shrink-0 items-center gap-1 text-xs text-stone-400">
          <Layers size={11} />
          {pod.active_agent_count ?? 0} agents
        </span>

        {/* Model */}
        {pod.default_model && (
          <span className="hidden shrink-0 rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-400 sm:inline">
            {pod.default_model.split('/').pop()}
          </span>
        )}

        {/* Human review setting */}
        <div className="hidden shrink-0 items-center gap-1 text-xs sm:flex">
          <span className="text-stone-400">Review:</span>
          <span className="text-stone-500">{REVIEW_LABELS[pod.require_human_review] ?? pod.require_human_review}</span>
        </div>

        {/* Escalation threshold */}
        <span className={clsx(
          'hidden shrink-0 text-xs font-medium capitalize sm:inline',
          THRESHOLD_COLORS[pod.escalation_threshold] ?? 'text-stone-500',
        )}>
          {pod.escalation_threshold}
        </span>

        {/* Routing keywords */}
        {(pod.routing_keywords?.length ?? 0) > 0 && (
          <div className="hidden shrink-0 gap-1 sm:flex">
            {(pod.routing_keywords ?? []).slice(0, 3).map(kw => (
              <span key={kw} className="rounded-full bg-stone-100 px-1.5 py-0.5 text-[10px] text-stone-400">
                {kw}
              </span>
            ))}
            {(pod.routing_keywords?.length ?? 0) > 3 && (
              <span className="text-[10px] text-stone-400">+{(pod.routing_keywords?.length ?? 0) - 3}</span>
            )}
          </div>
        )}
      </button>

      {/* Expanded agent list */}
      {expanded && (
        <div className="px-4 pb-4">
          <PodDetail podId={pod.id} />
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function Pods() {
  const qc = useQueryClient()

  const { data: pods = [], isLoading, isFetching, isError } = useQuery({
    queryKey: ['pods'],
    queryFn: getPods,
    staleTime: 15_000,
  })

  const enabled  = pods.filter(p => p.enabled)
  const disabled = pods.filter(p => !p.enabled)

  return (
    <div className="space-y-6 px-4 py-8 sm:px-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-stone-900">Pod Manager</h1>
          <p className="text-sm text-stone-400">Inspect and configure agent pipeline pods</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['pods'] })}
            disabled={isFetching}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-stone-500 hover:bg-stone-100 hover:text-stone-900 disabled:opacity-40"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Summary strip */}
      <div className="flex gap-6 rounded-xl border border-stone-200 bg-white px-5 py-3 text-sm">
        <div>
          <span className="text-stone-400">Total pods</span>
          <span className="ml-2 font-semibold text-stone-900">{pods.length}</span>
        </div>
        <div>
          <CheckCircle2 size={13} className="mr-1 inline text-emerald-700" />
          <span className="text-stone-400">Enabled</span>
          <span className="ml-2 font-semibold text-emerald-700">{enabled.length}</span>
        </div>
        <div>
          <XCircle size={13} className="mr-1 inline text-stone-400" />
          <span className="text-stone-400">Disabled</span>
          <span className="ml-2 font-semibold text-stone-500">{disabled.length}</span>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-stone-400">
          <Loader2 size={14} className="animate-spin" /> Loading pods…
        </div>
      )}

      {isError && (
        <div className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-600">
          Failed to load pods — check your admin secret and API connectivity.
        </div>
      )}

      {/* Enabled pods */}
      {enabled.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-stone-400">Active Pods</h2>
          {enabled.map(pod => <PodCard key={pod.id} pod={pod} />)}
        </div>
      )}

      {/* Disabled pods */}
      {disabled.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-stone-400">Disabled Pods</h2>
          {disabled.map(pod => <PodCard key={pod.id} pod={pod} />)}
        </div>
      )}

      {!isLoading && pods.length === 0 && (
        <div className="flex flex-col items-center gap-3 py-20 text-stone-400">
          <Layers size={32} />
          <p className="text-sm">No pods found</p>
          <p className="text-xs text-stone-400">
            Pods are created via the orchestrator API or by running database migrations.
          </p>
        </div>
      )}

      <p className="text-xs text-stone-400">
        To create or delete pods, use <code className="text-stone-400">POST /api/v1/pods</code> with your admin secret.
      </p>
    </div>
  )
}
