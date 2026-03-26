-- Migration 044: Rich error context for post-mortem debugging
-- Adds structured error context to agent_sessions and tasks so pipeline
-- failures preserve stack traces, LLM conversation history, and token/model info.

-- ── agent_sessions: traceback, messages, token_count, model_used ─────────────

ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS traceback TEXT;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS messages JSONB;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS token_count INTEGER;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS model_used TEXT;

-- ── tasks: structured error_context ──────────────────────────────────────────
-- tasks.error is already TEXT (no length limit) — no ALTER needed.

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS error_context JSONB;
