// ── Recommended Ollama Models ────────────────────────────────────────────────

export interface RecommendedModel {
  name: string
  category: 'general' | 'reasoning' | 'code' | 'embedding' | 'vision'
  description: string
  sizeGB: number    // approximate download size in GB
  required?: boolean
}

export const RECOMMENDED_OLLAMA_MODELS: RecommendedModel[] = [
  // Embedding (required)
  { name: 'nomic-embed-text',        category: 'embedding', sizeGB: 0.3, description: '768-dim embeddings for memory service', required: true },

  // General — small to large
  { name: 'qwen2.5:1.5b',            category: 'general',   sizeGB: 1.0, description: 'Starter — CPU-friendly' },
  { name: 'llama3.2:3b',             category: 'general',   sizeGB: 1.9, description: 'Fast, good for simple tasks' },
  { name: 'gemma3:4b',               category: 'general',   sizeGB: 3.0, description: 'Google, multimodal capable' },
  { name: 'mistral:7b',              category: 'general',   sizeGB: 4.1, description: 'Mistral AI, well-rounded' },
  { name: 'qwen2.5:7b',              category: 'general',   sizeGB: 4.4, description: 'Multilingual, strong' },
  { name: 'llama3.1:8b',             category: 'general',   sizeGB: 4.7, description: 'Meta, high quality' },
  { name: 'gemma3:12b',              category: 'general',   sizeGB: 8.0, description: 'Google, very capable' },
  { name: 'phi4:14b',                category: 'general',   sizeGB: 9.0, description: 'Microsoft, strong reasoning' },
  { name: 'gemma3:27b',              category: 'general',   sizeGB: 17.0, description: 'Google, excellent quality' },
  { name: 'qwen2.5:32b',             category: 'general',   sizeGB: 20.0, description: 'Multilingual, very strong' },
  { name: 'qwen2.5:72b',             category: 'general',   sizeGB: 47.0, description: 'Frontier-class local model' },
  { name: 'llama3.1:70b',            category: 'general',   sizeGB: 43.0, description: 'Meta, near cloud quality' },
  { name: 'mistral-large-3:123b',    category: 'general',   sizeGB: 72.0, description: 'Mistral flagship, 128k context' },

  // Reasoning
  { name: 'deepseek-r1:8b',          category: 'reasoning', sizeGB: 4.7, description: 'Chain-of-thought reasoning' },
  { name: 'deepseek-r1:14b',         category: 'reasoning', sizeGB: 9.0, description: 'Stronger chain-of-thought' },
  { name: 'deepseek-r1:32b',         category: 'reasoning', sizeGB: 20.0, description: 'Deep reasoning, needs GPU' },
  { name: 'deepseek-r1:70b',         category: 'reasoning', sizeGB: 43.0, description: 'Best local reasoning model' },

  // Code
  { name: 'qwen2.5-coder:7b',        category: 'code',      sizeGB: 4.4, description: 'Code generation and editing' },
  { name: 'qwen2.5-coder:14b',       category: 'code',      sizeGB: 9.0, description: 'Stronger code generation' },
  { name: 'devstral-small-2:24b',     category: 'code',      sizeGB: 14.0, description: 'Mistral code agent' },
  { name: 'qwen2.5-coder:32b',       category: 'code',      sizeGB: 20.0, description: 'Best local coding model' },

  // Vision
  { name: 'llava:7b',                category: 'vision',    sizeGB: 4.5, description: 'Image understanding' },
  { name: 'llava:13b',               category: 'vision',    sizeGB: 8.0, description: 'Better image understanding' },
  { name: 'llava:34b',               category: 'vision',    sizeGB: 20.0, description: 'Best local vision model' },
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
