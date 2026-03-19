import type { AgentInfo, ApiKey, CodeReviewVerdict, GuardrailFinding, OAIModel, PipelineTask, Pod, PodAgent, UsageEvent } from './types'

// Admin secret is stored in localStorage so you can change it without
// rebuilding the dashboard. Default matches the dev .env value.
export const getAdminSecret = () =>
  localStorage.getItem('nova_admin_secret') ?? 'nova-admin-secret-change-me'

export const setAdminSecret = (s: string) =>
  localStorage.setItem('nova_admin_secret', s)

/** Get the current JWT access token if available. */
function getAccessToken(): string | null {
  try {
    const raw = localStorage.getItem('nova_auth_tokens')
    if (!raw) return null
    return JSON.parse(raw).accessToken ?? null
  } catch {
    return null
  }
}

/**
 * Build auth headers.
 *
 * When JWT auth is active (user logged in), only send the Bearer token.
 * The admin secret is a bootstrap/local-dev mechanism — it must NOT be sent
 * alongside JWT because it grants full admin access regardless of user role.
 * Fallback to admin secret only when no JWT exists (pre-auth local dev).
 */
export function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken()
  if (token) {
    return { 'Authorization': `Bearer ${token}` }
  }
  return { 'X-Admin-Secret': getAdminSecret() }
}

/** Try to refresh the access token using the stored refresh token. */
async function tryRefreshToken(): Promise<boolean> {
  try {
    const raw = localStorage.getItem('nova_auth_tokens')
    if (!raw) return false
    const { refreshToken } = JSON.parse(raw)
    if (!refreshToken) return false

    const resp = await fetch('/api/v1/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!resp.ok) return false
    const data = await resp.json()
    localStorage.setItem('nova_auth_tokens', JSON.stringify({
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
    }))
    return true
  } catch {
    return false
  }
}

export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const doFetch = async () => {
    const resp = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
        ...(options.headers ?? {}),
      },
    })
    return resp
  }

  let resp = await doFetch()

  // On 401/403 with JWT, try to refresh and retry once
  // 401 = UserDep auth failure, 403 = AdminDep auth failure (expired JWT)
  if ((resp.status === 401 || resp.status === 403) && getAccessToken()) {
    const refreshed = await tryRefreshToken()
    if (refreshed) {
      resp = await doFetch()
    }
  }

  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText)
    throw new Error(`${resp.status}: ${text}`)
  }
  // 204 No Content — return undefined
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

// ── Agents ────────────────────────────────────────────────────────────────────
export const getAgents = () => apiFetch<AgentInfo[]>('/api/v1/agents')

// ── Usage ─────────────────────────────────────────────────────────────────────
export const getUsage = (limit = 500) =>
  apiFetch<UsageEvent[]>(`/api/v1/usage?limit=${limit}`)

// ── Keys ──────────────────────────────────────────────────────────────────────
export const getKeys = () => apiFetch<ApiKey[]>('/api/v1/keys')

export const createKey = (name: string, rate_limit_rpm: number) =>
  apiFetch<ApiKey & { raw_key: string }>('/api/v1/keys', {
    method: 'POST',
    body: JSON.stringify({ name, rate_limit_rpm }),
  })

export const revokeKey = (id: string) =>
  apiFetch<void>(`/api/v1/keys/${id}`, { method: 'DELETE' })

// ── Models ────────────────────────────────────────────────────────────────────
export const getModels = () =>
  apiFetch<{ data: OAIModel[] }>('/v1/models')

// ── Pipeline Tasks ─────────────────────────────────────────────────────────────

export const submitPipelineTask = (
  user_input: string,
  pod_name?: string,
  model_override?: string,
  metadata: Record<string, unknown> = {},
) =>
  apiFetch<{ task_id: string; status: string; pod_name: string; queued_at: string }>(
    '/api/v1/pipeline/tasks',
    {
      method: 'POST',
      body: JSON.stringify({
        user_input,
        pod_name,
        metadata: { ...metadata, ...(model_override ? { model_override } : {}) },
      }),
    },
  )

export const getPipelineTasks = (params: { status?: string; pod_id?: string; limit?: number } = {}) => {
  const qs = new URLSearchParams()
  if (params.status)  qs.set('status', params.status)
  if (params.pod_id)  qs.set('pod_id', params.pod_id)
  if (params.limit)   qs.set('limit', String(params.limit))
  return apiFetch<PipelineTask[]>(`/api/v1/pipeline/tasks?${qs}`)
}

export const getPipelineTask = (task_id: string) =>
  apiFetch<PipelineTask>(`/api/v1/pipeline/tasks/${task_id}`)

export const cancelPipelineTask = (task_id: string) =>
  apiFetch<{ task_id: string; status: string }>(
    `/api/v1/pipeline/tasks/${task_id}/cancel`,
    { method: 'POST' },
  )

export const reviewPipelineTask = (task_id: string, decision: 'approve' | 'reject', comment?: string) =>
  apiFetch<{ task_id: string; status: string; decision: string }>(
    `/api/v1/pipeline/tasks/${task_id}/review`,
    { method: 'POST', body: JSON.stringify({ decision, comment }) },
  )

export const getQueueStats = () =>
  apiFetch<{ queue_depth: number; dead_letter_depth: number }>('/api/v1/pipeline/queue-stats')

export const getTaskFindings = (task_id: string) =>
  apiFetch<GuardrailFinding[]>(`/api/v1/pipeline/tasks/${task_id}/findings`)

export const getTaskReviews = (task_id: string) =>
  apiFetch<CodeReviewVerdict[]>(`/api/v1/pipeline/tasks/${task_id}/reviews`)

export const deletePipelineTask = (task_id: string) =>
  apiFetch<void>(`/api/v1/pipeline/tasks/${task_id}`, { method: 'DELETE' })

export const bulkDeletePipelineTasks = (statuses = 'complete,failed,cancelled') =>
  apiFetch<{ deleted: number; statuses: string[] }>(
    `/api/v1/pipeline/tasks?status=${encodeURIComponent(statuses)}`,
    { method: 'DELETE' },
  )

export const clarifyPipelineTask = (task_id: string, answers: string[]) =>
  apiFetch<{ task_id: string; status: string }>(
    `/api/v1/pipeline/tasks/${task_id}/clarify`,
    { method: 'POST', body: JSON.stringify({ answers }) },
  )

// ── Pods ───────────────────────────────────────────────────────────────────────

export const getPods = () => apiFetch<Pod[]>('/api/v1/pods')

export const getPod = (pod_id: string) => apiFetch<Pod>(`/api/v1/pods/${pod_id}`)

export const createPod = (data: Partial<Pod>) =>
  apiFetch<Pod>('/api/v1/pods', { method: 'POST', body: JSON.stringify(data) })

export const updatePod = (pod_id: string, data: Partial<Pod>) =>
  apiFetch<Pod>(`/api/v1/pods/${pod_id}`, { method: 'PATCH', body: JSON.stringify(data) })

export const deletePod = (pod_id: string) =>
  apiFetch<void>(`/api/v1/pods/${pod_id}`, { method: 'DELETE' })

export const getPodAgents = (pod_id: string) =>
  apiFetch<PodAgent[]>(`/api/v1/pods/${pod_id}/agents`)

export const updatePodAgent = (pod_id: string, agent_id: string, data: Partial<PodAgent>) =>
  apiFetch<PodAgent>(`/api/v1/pods/${pod_id}/agents/${agent_id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

export const patchAgentConfig = (
  agent_id: string,
  data: { model?: string | null; system_prompt?: string | null; fallback_models?: string[] },
) =>
  apiFetch<AgentInfo>(`/api/v1/agents/${agent_id}/config`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

// ── Direct chat (admin stream) ────────────────────────────────────────────────

export interface ContentBlock {
  type: 'text' | 'image_url'
  text?: string
  image_url?: { url: string }
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string | ContentBlock[]
}

export interface StreamChatOptions {
  output_style?: string
  custom_instructions?: string
  web_search?: boolean
  deep_research?: boolean
  conversation_id?: string
}

/** Metadata emitted by intelligent routing before content deltas. */
export interface StreamMeta {
  model?: string
  category?: string
}

/** Activity step emitted during processing (before content deltas). */
export interface ActivityStep {
  step: string       // "classifying" | "memory" | "model" | "generating"
  state: 'running' | 'done'
  detail?: string
  elapsed_ms?: number
  model?: string
  category?: string | null
}

export type StreamEvent = string | { meta: StreamMeta } | { status: ActivityStep }

/**
 * Stream a chat turn directly with the primary Nova agent.
 * Uses the admin secret — no API key required.
 *
 * Yields text deltas (strings) and optional routing metadata events.
 * Pass the sessionId back on the next call to continue the same conversation thread.
 */
export async function* streamChat(
  messages: ChatMessage[],
  model?: string,
  sessionId?: string,
  options?: StreamChatOptions,
): AsyncGenerator<StreamEvent, void, unknown> {
  const resp = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({
      messages,
      model,
      session_id: sessionId,
      ...options,
    }),
  })

  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText)
    throw new Error(`${resp.status}: ${text}`)
  }

  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''
    for (const event of events) {
      const line = event.trim()
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6)
      if (data === '[DONE]') return
      if (data.startsWith('{')) {
        try {
          const parsed = JSON.parse(data) as Record<string, unknown>
          if (parsed.error) throw new Error(String(parsed.error))
          if (parsed.t !== undefined) {
            yield parsed.t as string
            continue
          }
          if (parsed.status) {
            yield { status: parsed.status as ActivityStep }
            continue
          }
          if (parsed.meta) {
            yield { meta: parsed.meta as StreamMeta }
            continue
          }
        } catch {
          if (data) yield data
        }
      } else if (data) {
        yield data
      }
    }
  }
}

// ── MCP Servers ────────────────────────────────────────────────────────────────

export interface MCPServer {
  id: string
  name: string
  description: string
  transport: 'stdio' | 'http'
  command: string | null
  args: string[]
  env: Record<string, string>
  url: string | null
  enabled: boolean
  created_at: string
  metadata: Record<string, unknown>
  // Runtime status fields (populated by list endpoint, not in DB)
  connected?: boolean
  tool_count?: number
  active_tools?: string[]
}

export const getMCPServers = () =>
  apiFetch<MCPServer[]>('/api/v1/mcp-servers')

export const createMCPServer = (data: Partial<MCPServer>) =>
  apiFetch<MCPServer & { connected: boolean }>('/api/v1/mcp-servers', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const updateMCPServer = (id: string, data: Partial<MCPServer>) =>
  apiFetch<MCPServer & { connected: boolean }>(`/api/v1/mcp-servers/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

export const deleteMCPServer = (id: string) =>
  apiFetch<void>(`/api/v1/mcp-servers/${id}`, { method: 'DELETE' })

export const reloadMCPServer = (id: string) =>
  apiFetch<{ name: string; connected: boolean; tool_count: number; tools: string[] }>(
    `/api/v1/mcp-servers/${id}/reload`,
    { method: 'POST' },
  )

// ── Agent Endpoints (ACP/A2A outbound delegation) ────────────────────────────

export interface AgentEndpoint {
  id: string
  name: string
  description: string
  url: string
  protocol: 'a2a' | 'acp' | 'generic'
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  enabled: boolean
  created_at: string
  metadata: Record<string, unknown>
  // auth_token is never returned by the API; pass it only on create/update
}

export interface AgentEndpointWrite extends Omit<AgentEndpoint, 'id' | 'created_at'> {
  auth_token?: string
}

export const getAgentEndpoints = () =>
  apiFetch<AgentEndpoint[]>('/api/v1/agent-endpoints')

export const createAgentEndpoint = (data: Partial<AgentEndpointWrite>) =>
  apiFetch<AgentEndpoint>('/api/v1/agent-endpoints', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const updateAgentEndpoint = (id: string, data: Partial<AgentEndpointWrite>) =>
  apiFetch<AgentEndpoint>(`/api/v1/agent-endpoints/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

export const deleteAgentEndpoint = (id: string) =>
  apiFetch<void>(`/api/v1/agent-endpoints/${id}`, { method: 'DELETE' })

// ── Goals ────────────────────────────────────────────────────────────────────

export interface Goal {
  id: string
  title: string
  description: string | null
  status: 'active' | 'paused' | 'completed' | 'failed' | 'cancelled'
  priority: number
  progress: number
  current_plan: unknown | null
  iteration: number
  max_iterations: number | null
  max_cost_usd: number | null
  cost_so_far_usd: number
  check_interval_seconds: number | null
  last_checked_at: string | null
  parent_goal_id: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export const getGoals = (status?: string) => {
  const qs = status ? `?status=${status}` : ''
  return apiFetch<Goal[]>(`/api/v1/goals${qs}`)
}

export const getGoal = (id: string) =>
  apiFetch<Goal>(`/api/v1/goals/${id}`)

export const createGoal = (data: { title: string; description?: string; priority?: number; max_cost_usd?: number }) =>
  apiFetch<Goal>('/api/v1/goals', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const updateGoal = (id: string, data: Partial<Goal>) =>
  apiFetch<Goal>(`/api/v1/goals/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

export const deleteGoal = (id: string) =>
  apiFetch<void>(`/api/v1/goals/${id}`, { method: 'DELETE' })

// ── Cortex ───────────────────────────────────────────────────────────────────

export interface CortexStatus {
  status: string
  current_drive: string | null
  cycle_count: number
  last_cycle_at: string | null
}

export interface CortexDrive {
  name: string
  priority: number
  urgency: number
  description: string
}

export const getCortexStatus = () =>
  apiFetch<CortexStatus>('/cortex-api/api/v1/cortex/status')

export const pauseCortex = () =>
  apiFetch<{ status: string }>('/cortex-api/api/v1/cortex/pause', { method: 'POST' })

export const resumeCortex = () =>
  apiFetch<{ status: string }>('/cortex-api/api/v1/cortex/resume', { method: 'POST' })

export const getCortexDrives = () =>
  apiFetch<{ drives: CortexDrive[] }>('/cortex-api/api/v1/cortex/drives')

export interface BudgetStatus {
  daily_budget_usd: number
  daily_spend_usd: number
  remaining_usd: number
  percent_used: number
  budget_exceeded: boolean
  tier: string
}

export const getCortexBudget = () =>
  apiFetch<BudgetStatus>('/cortex-api/api/v1/cortex/budget')

export interface JournalEntry {
  id: string
  role: string
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

export const getCortexJournal = (limit = 20) =>
  apiFetch<{ entries: JournalEntry[] }>(`/cortex-api/api/v1/cortex/journal?limit=${limit}`)

// ── Provider status ──────────────────────────────────────────────────────────

export interface ProviderStatus {
  slug: string
  name: string
  type: 'subscription' | 'free' | 'paid' | 'local'
  available: boolean
  model_count: number
  default_model: string
}

export const getProviderStatus = () =>
  apiFetch<ProviderStatus[]>('/v1/health/providers')

export const testProvider = (slug: string) =>
  apiFetch<{ ok: boolean; latency_ms: number; error?: string }>(
    `/v1/health/providers/${slug}/test`, { method: 'POST' })

export interface OllamaStatus {
  healthy: boolean
  base_url: string
  routing_strategy: string
  wol_configured: boolean
  wol_last_sent_seconds_ago: number | null
  gpu_available: boolean
}

export const getOllamaStatus = () =>
  apiFetch<OllamaStatus>('/v1/health/providers/ollama/status')

// ── Model Discovery ──────────────────────────────────────────────────────────

export interface DiscoveredModel {
  id: string
  registered: boolean
}

export interface ProviderModelList {
  slug: string
  name: string
  type: 'local' | 'subscription' | 'free' | 'paid'
  available: boolean
  auth_methods: string[]
  models: DiscoveredModel[]
}

export interface OllamaPulledModel {
  name: string
  size: number
  parameter_size: string
  quantization_level: string
  digest: string
  modified_at: string
}

export const discoverModels = (refresh = false) =>
  apiFetch<ProviderModelList[]>(`/v1/models/discover${refresh ? '?refresh=true' : ''}`)

export interface ResolvedModel {
  model: string
  source: 'auto' | 'explicit'
}

export const resolveModel = () =>
  apiFetch<ResolvedModel>('/v1/models/resolve')

export const getOllamaPulled = () =>
  apiFetch<OllamaPulledModel[]>('/v1/models/ollama/pulled')

export const pullOllamaModel = (name: string) =>
  apiFetch<{ status: string; model: string }>('/v1/models/ollama/pull', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })

export const deleteOllamaModel = (name: string) =>
  apiFetch<{ status: string; model: string }>(`/v1/models/ollama/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })

// ── Tool catalog ──────────────────────────────────────────────────────────────

export interface ToolInfo { name: string; description: string }
export interface ToolCategory { category: string; source: 'builtin' | 'mcp'; tools: ToolInfo[] }

export const getAvailableTools = () => apiFetch<ToolCategory[]>('/api/v1/tools')

// ── Platform configuration ────────────────────────────────────────────────────

export interface PlatformConfigEntry {
  key: string
  /** Decoded value — string, number, boolean, or null */
  value: string | number | boolean | null
  description: string
  is_secret: boolean
  updated_at: string | null
}

export const getPlatformConfig = () =>
  apiFetch<PlatformConfigEntry[]>('/api/v1/config')

/**
 * Update a single platform config entry.
 * Pass the value as a JSON-encoded string:
 *   updatePlatformConfig('nova.persona', '"My custom persona"')
 *   updatePlatformConfig('nova.default_model', 'null')
 */
export const updatePlatformConfig = (key: string, value: string) =>
  apiFetch<PlatformConfigEntry>(`/api/v1/config/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    body: JSON.stringify({ value }),
  })

// ── Identity ─────────────────────────────────────────────────────────────────

export interface NovaIdentity {
  name: string
  greeting: string
}

export const getNovaIdentity = () =>
  apiFetch<NovaIdentity>('/api/v1/identity')

// ── Dashboard overview endpoints ─────────────────────────────────────────────

export interface PipelineStats {
  active_count: number
  queued_count: number
  completed_today: number
  completed_this_week: number
  failed_today: number
  success_rate_7d: number
  avg_duration_ms: number
}

export interface UsageSummary {
  total_cost_usd: number
  total_requests: number
  by_model: Array<{ model: string; cost_usd: number; requests: number }>
  by_day: Array<{ date: string; cost_usd: number; requests: number }>
  vs_previous_period_pct: number
}

export interface HealthOverview {
  services: Array<{ name: string; status: string; latency_ms: number }>
  avg_latency_ms: number
  overall_status: string
}

export interface ActivityEvent {
  id: number
  event_type: string
  service: string
  severity: string
  summary: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface PipelineLatency {
  avg_total_ms: number
  p50_ms: number
  p95_ms: number
  by_stage: Array<{ stage: string; avg_ms: number }>
}

export interface GoalStats {
  active: number
  completed: number
  failed: number
  paused: number
  success_rate: number
  avg_iterations: number
  avg_cost_usd: number
  total_cost_usd: number
}

export interface RoutingStats {
  by_model: Array<{ model: string; requests: number; avg_tokens: number; avg_latency_ms: number; cost_usd: number }>
  fallback_rate_pct: number
  category_distribution: Record<string, number>
}

export const getPipelineStats = () =>
  apiFetch<PipelineStats>('/api/v1/pipeline/stats')

export const getUsageSummary = (period: string) =>
  apiFetch<UsageSummary>(`/api/v1/usage/summary?period=${period}`)

export const getHealthOverview = () =>
  apiFetch<HealthOverview>('/api/v1/health/overview')

export const getActivityFeed = (limit = 20) =>
  apiFetch<ActivityEvent[]>(`/api/v1/activity?limit=${limit}`)

export const getPipelineLatency = () =>
  apiFetch<PipelineLatency>('/api/v1/pipeline/stats/latency')

export const getGoalStats = () =>
  apiFetch<GoalStats>('/api/v1/goals/stats')

export const getRoutingStats = (period = '7d') =>
  apiFetch<RoutingStats>(`/api/v1/models/routing-stats?period=${period}`)

