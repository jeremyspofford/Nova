-- Migration 030: Chat Pod — dedicated pod for interactive chat interface
-- Idempotent: IF NOT EXISTS / ON CONFLICT DO NOTHING throughout.

-- ── Schema changes ──────────────────────────────────────────────────────────

-- Flag to mark one pod as the default chat interface target
ALTER TABLE pods ADD COLUMN IF NOT EXISTS is_chat_default BOOLEAN NOT NULL DEFAULT false;

-- Enforce at most one chat-default pod at the database level
CREATE UNIQUE INDEX IF NOT EXISTS idx_pods_chat_default
    ON pods (is_chat_default) WHERE is_chat_default = true;

-- ── Seed: Chat pod ──────────────────────────────────────────────────────────

INSERT INTO pods (name, description, is_chat_default, is_system_default, enabled)
VALUES (
    'Chat',
    'Interactive chat interface — the primary developer interface',
    true,
    false,
    true
)
ON CONFLICT (name) DO NOTHING;

-- ── Seed: Chat Agent ────────────────────────────────────────────────────────

INSERT INTO pod_agents (pod_id, name, role, description, position, temperature, max_tokens, timeout_seconds, max_retries, on_failure, run_condition, allowed_tools)
SELECT p.id,
       'Chat Agent',
       'chat',
       'Conversational agent with tool access and pipeline delegation',
       1,
       0.7,
       8192,
       120,
       1,
       'skip',
       '{"type":"always"}'::jsonb,
       NULL
FROM pods p
WHERE p.name = 'Chat'
ON CONFLICT (pod_id, position) DO NOTHING;
