// ── Recommended Ollama Models ────────────────────────────────────────────────

export interface RecommendedModel {
  name: string
  category: 'general' | 'reasoning' | 'code' | 'embedding' | 'vision'
  description: string
  required?: boolean
}

export const RECOMMENDED_OLLAMA_MODELS: RecommendedModel[] = [
  { name: 'qwen2.5:1.5b',       category: 'general',   description: 'Starter — 1.5B, ~1 GB, CPU-friendly' },
  { name: 'llama3.2:3b',        category: 'general',   description: '3B params, ~1.9 GB, fast' },
  { name: 'llama3.1:8b',        category: 'general',   description: '8B params, ~4.7 GB, high quality' },
  { name: 'qwen2.5:7b',         category: 'general',   description: '7B params, ~4.4 GB, multilingual' },
  { name: 'deepseek-r1:8b',     category: 'reasoning', description: '8B, ~4.7 GB, chain-of-thought' },
  { name: 'qwen2.5-coder:7b',   category: 'code',      description: '7B, ~4.4 GB, code generation' },
  { name: 'nomic-embed-text',   category: 'embedding', description: '768-dim embeddings for memory service', required: true },
  { name: 'llava:7b',           category: 'vision',    description: '7B, ~4.5 GB, image understanding' },
]

/** Provider display order for the Models page. */
export const CLOUD_PROVIDER_ORDER = [
  'claude-max', 'anthropic', 'openai', 'chatgpt',
  'groq', 'gemini', 'cerebras', 'openrouter', 'github',
]

// ── Task Pipeline ────────────────────────────────────────────────────────────

/** Task statuses that indicate the pipeline is actively processing. */
export const ACTIVE_TASK_STATUSES = new Set([
  'queued', 'running', 'context_running', 'task_running',
  'guardrail_running', 'code_review_running', 'decision_running',
])

/** Visual config for task pipeline status badges (distinct from agent StatusBadge). */
export const TASK_STATUS_CONFIG: Record<string, { label: string; className: string; pulse?: boolean }> = {
  queued:              { label: 'Queued',        className: 'bg-neutral-200 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300' },
  running:             { label: 'Running',       className: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400', pulse: true },
  context_running:     { label: 'Context',       className: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400', pulse: true },
  task_running:        { label: 'Task',          className: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400', pulse: true },
  guardrail_running:   { label: 'Guardrail',     className: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400', pulse: true },
  code_review_running: { label: 'Code Review',   className: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400', pulse: true },
  decision_running:    { label: 'Decision',      className: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400', pulse: true },
  complete:            { label: 'Complete',      className: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400' },
  failed:              { label: 'Failed',        className: 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400' },
  cancelled:           { label: 'Cancelled',     className: 'bg-neutral-400/30 dark:bg-neutral-600/30 text-neutral-500 dark:text-neutral-400' },
  pending_human_review:{ label: 'Needs Review',  className: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400', pulse: true },
}
