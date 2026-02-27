import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import {
  Bot, RefreshCw, ListTodo, AlertCircle, CheckCircle2, ArrowRight,
  Pencil, Loader2, FileText, Cpu, Layers, Plug,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { getAgents, getPipelineTasks, patchAgentConfig, getQueueStats, getMCPServers } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import { ModelPicker } from '../components/ModelPicker'
import type { AgentInfo } from '../types'

// ── Pipeline summary strip ────────────────────────────────────────────────────

function PipelineSummary() {
  const { data: tasks = [] } = useQuery({
    queryKey: ['pipeline-tasks'],
    queryFn: () => getPipelineTasks({ limit: 100 }),
    refetchInterval: 10_000,
    staleTime: 5_000,
  })

  const ACTIVE = new Set(['queued','running','context_running','task_running',
    'guardrail_running','code_review_running','decision_running'])

  const activeTasks  = tasks.filter(t => ACTIVE.has(t.status)).length
  const reviewTasks  = tasks.filter(t => t.status === 'pending_human_review').length
  const recentDone   = tasks.filter(t => t.status === 'complete').length

  return (
    <div className="rounded-xl border border-stone-200 bg-white px-5 py-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-stone-400">
          <ListTodo size={12} /> Pipeline
        </p>
        <Link to="/tasks" className="flex items-center gap-1 text-xs text-teal-700 hover:text-teal-600">
          View all <ArrowRight size={11} />
        </Link>
      </div>
      <div className="flex gap-6">
        <div>
          <p className="text-2xl font-bold text-stone-900">{activeTasks}</p>
          <p className="text-xs text-stone-400">Active</p>
        </div>
        <div>
          <p className={`text-2xl font-bold ${reviewTasks > 0 ? 'text-amber-600' : 'text-stone-900'}`}>
            {reviewTasks}
          </p>
          <p className="text-xs text-stone-400 flex items-center gap-1">
            {reviewTasks > 0 && <AlertCircle size={10} className="text-amber-500" />}
            Needs Review
          </p>
        </div>
        <div>
          <p className="text-2xl font-bold text-emerald-700">{recentDone}</p>
          <p className="text-xs text-stone-400 flex items-center gap-1">
            <CheckCircle2 size={10} className="text-emerald-500" />
            Complete
          </p>
        </div>
      </div>
      {reviewTasks > 0 && (
        <Link
          to="/tasks"
          className="mt-3 flex items-center gap-1.5 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700 hover:bg-amber-100"
        >
          <AlertCircle size={12} />
          {reviewTasks} task{reviewTasks !== 1 ? 's' : ''} waiting for human review — click to review
          <ArrowRight size={11} className="ml-auto" />
        </Link>
      )}
    </div>
  )
}

// ── System Services panel ─────────────────────────────────────────────────────

function ServiceRow({
  icon: Icon,
  label,
  status,
  detail,
}: {
  icon: React.ElementType
  label: string
  status: 'ok' | 'degraded' | 'unknown'
  detail?: string
}) {
  const dot =
    status === 'ok'       ? 'bg-emerald-500' :
    status === 'degraded' ? 'bg-amber-500'   :
                            'bg-stone-300'

  return (
    <div className="flex items-center justify-between py-2 first:pt-0 last:pb-0">
      <div className="flex items-center gap-2 min-w-0">
        <Icon size={13} className="shrink-0 text-stone-400" />
        <span className="text-xs font-medium text-stone-700 truncate">{label}</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {detail && <span className="text-xs text-stone-400">{detail}</span>}
        <span className={`h-2 w-2 rounded-full ${dot}`} />
      </div>
    </div>
  )
}

function SystemServices() {
  const { data: queueStats, isError: queueError } = useQuery({
    queryKey: ['queue-stats'],
    queryFn: getQueueStats,
    refetchInterval: 10_000,
    staleTime: 5_000,
    retry: 1,
  })

  const { data: mcpServers = [] } = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: getMCPServers,
    refetchInterval: 15_000,
    staleTime: 10_000,
  })
  const enabledServers = mcpServers.filter(s => s.enabled)
  const connectedServers = mcpServers.filter(s => s.connected)
  const totalTools = connectedServers.reduce((sum, s) => sum + (s.tool_count ?? 0), 0)

  // Queue worker / reaper are inferred from orchestrator health:
  // if queue-stats responds, the asyncio tasks are alive.
  const orchestratorOk = !queueError && queueStats !== undefined
  const workerStatus: 'ok' | 'degraded' | 'unknown' = orchestratorOk ? 'ok' : 'unknown'
  const reaperStatus: 'ok' | 'degraded' | 'unknown' = orchestratorOk ? 'ok' : 'unknown'

  const mcpStatus: 'ok' | 'degraded' | 'unknown' =
    enabledServers.length === 0     ? 'unknown'  :
    connectedServers.length === enabledServers.length ? 'ok' : 'degraded'

  return (
    <div className="rounded-xl border border-stone-200 bg-white px-5 py-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-stone-400">
          <Cpu size={12} /> System Services
        </p>
        <Link to="/mcp" className="flex items-center gap-1 text-xs text-teal-700 hover:text-teal-600">
          MCP config <ArrowRight size={11} />
        </Link>
      </div>

      <div className="divide-y divide-stone-100">
        <ServiceRow
          icon={Layers}
          label="Queue Worker"
          status={workerStatus}
          detail={queueStats ? `depth ${queueStats.queue_depth}` : undefined}
        />
        <ServiceRow
          icon={RefreshCw}
          label="Reaper"
          status={reaperStatus}
          detail="stale-agent recovery"
        />
        <ServiceRow
          icon={Plug}
          label="MCP Servers"
          status={mcpStatus}
          detail={
            enabledServers.length === 0
              ? 'none configured'
              : `${connectedServers.length}/${enabledServers.length} connected · ${totalTools} tools`
          }
        />
      </div>
    </div>
  )
}

// ── Inline agent config editor ────────────────────────────────────────────────

function AgentEditor({ agent }: { agent: AgentInfo }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [systemPrompt, setSystemPrompt] = useState(agent.config.system_prompt ?? '')
  const [primaryModel, setPrimaryModel] = useState<string | null>(agent.config.model ?? null)
  const [fallbackModels, setFallbackModels] = useState<string[]>(
    agent.config.fallback_models ?? [],
  )

  const save = useMutation({
    mutationFn: () =>
      patchAgentConfig(agent.id, {
        model: primaryModel,
        system_prompt: systemPrompt || null,
        fallback_models: fallbackModels,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      setOpen(false)
    },
  })

  const cancel = () => {
    setSystemPrompt(agent.config.system_prompt ?? '')
    setPrimaryModel(agent.config.model ?? null)
    setFallbackModels(agent.config.fallback_models ?? [])
    setOpen(false)
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-stone-300 py-2 text-xs text-stone-400 hover:border-teal-400 hover:text-teal-600 transition-colors"
      >
        <Pencil size={11} /> Edit model &amp; system prompt
      </button>
    )
  }

  return (
    <div className="space-y-4 rounded-md border border-teal-200 bg-teal-50/30 p-3">

      {/* Model + fallbacks */}
      <ModelPicker
        primaryModel={primaryModel}
        fallbackModels={fallbackModels}
        onChange={(p, f) => { setPrimaryModel(p); setFallbackModels(f) }}
      />

      {/* System prompt */}
      <div>
        <label className="mb-1 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-stone-400">
          <FileText size={10} /> System Prompt
        </label>
        <textarea
          rows={6}
          value={systemPrompt}
          onChange={e => setSystemPrompt(e.target.value)}
          placeholder="Describe this agent's role, persona, and constraints…"
          className="w-full resize-y rounded-md border border-stone-300 bg-white px-3 py-2 font-mono text-xs text-stone-800 outline-none placeholder:text-stone-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
        />
        <p className="mt-0.5 text-[10px] text-stone-400">{systemPrompt.length} chars</p>
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
          {save.isPending
            ? <><Loader2 size={11} className="animate-spin" /> Saving…</>
            : 'Save changes'}
        </button>
      </div>
      {save.isError && (
        <p className="text-[11px] text-red-600">Save failed — check console</p>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function Overview() {
  const { data: agents = [], isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['agents'],
    queryFn: getAgents,
    refetchInterval: 5000,
  })

  const active = agents.filter(a => a.status !== 'stopped')

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-stone-900">Overview</h1>
          <p className="text-sm text-stone-400">
            {active.length} active agent{active.length !== 1 ? 's' : ''} · auto-refreshes every 5s
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 rounded-md border border-stone-300 px-3 py-1.5 text-xs text-stone-500 hover:border-stone-400 hover:text-stone-800 disabled:opacity-40"
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {/* ── Summary strips ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <PipelineSummary />
        <SystemServices />
      </div>

      {isLoading && <p className="text-sm text-stone-400">Loading agents…</p>}
      {error && <p className="text-sm text-red-600">Failed to load agents: {String(error)}</p>}

      {active.length === 0 && !isLoading && (
        <div className="rounded-xl border border-dashed border-stone-300 p-12 text-center">
          <Bot size={32} className="mx-auto mb-3 text-stone-400" />
          <p className="text-sm text-stone-400">
            No active agents. The primary agent is created on orchestrator startup.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {active.map(agent => (
          <div key={agent.id} className="rounded-xl border border-stone-200 bg-white p-5 space-y-3">
            {/* Header */}
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate font-medium text-stone-900">{agent.config.name}</p>
                <p className="truncate text-xs text-stone-400 mt-0.5">{agent.config.model}</p>
              </div>
              <StatusBadge status={agent.status} />
            </div>

            {/* Metadata */}
            <div className="space-y-1 text-xs text-stone-400">
              <p>
                <span className="text-stone-500">Last active: </span>
                {agent.last_active
                  ? formatDistanceToNow(new Date(agent.last_active), { addSuffix: true })
                  : 'never'}
              </p>
              <p>
                <span className="text-stone-500">Created: </span>
                {formatDistanceToNow(new Date(agent.created_at), { addSuffix: true })}
              </p>
              <p className="font-mono text-stone-400 truncate">{agent.id}</p>
            </div>

            {/* Fallbacks summary (view mode) */}
            {(agent.config.fallback_models ?? []).length > 0 && (
              <p className="text-xs text-stone-400">
                <span className="text-stone-500">Fallbacks: </span>
                <span className="font-mono">
                  {(agent.config.fallback_models ?? []).join(' → ')}
                </span>
              </p>
            )}

            {/* Tools */}
            {agent.config.tools.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {agent.config.tools.map(t => (
                  <span key={t} className="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-500">
                    {t}
                  </span>
                ))}
              </div>
            )}

            {/* Inline editor */}
            <AgentEditor agent={agent} />
          </div>
        ))}
      </div>
    </div>
  )
}
