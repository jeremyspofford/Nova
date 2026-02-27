-- Migration 005: Platform configuration store
--
-- Replaces the all-or-nothing env-var approach for runtime-tunable settings.
-- Editable from the dashboard without a container restart.
--
-- Design:
--   - key:        dot-namespaced identifier  (e.g. 'nova.persona')
--   - value:      JSONB so one column handles strings, numbers, booleans, null
--   - is_secret:  masks the value in dashboard API responses (future use)
--   - updated_at: for audit trail / cache invalidation

CREATE TABLE IF NOT EXISTS platform_config (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT 'null',
    description TEXT NOT NULL DEFAULT '',
    is_secret   BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed defaults. ON CONFLICT DO NOTHING so re-running the migration is safe
-- and existing user edits are never overwritten.
INSERT INTO platform_config (key, value, description) VALUES
    (
        'nova.name',
        '"Nova"',
        'Display name for this Nova instance'
    ),
    (
        'nova.persona',
        '""',
        'Personality / soul appended to every system prompt. Defines communication style, tone, and character. Leave blank to use the base system prompt only.'
    ),
    (
        'nova.greeting',
        '"Hello! I''m Nova. I have access to your workspace, can run shell commands, read and write files, and remember our previous conversations. What would you like to work on?"',
        'Opening message shown in the Chat page before the first user message'
    ),
    (
        'nova.default_model',
        'null',
        'Platform-wide default model override. When set, takes precedence over the NOVA_DEFAULT_MODEL environment variable. Use the model ID exactly as it appears on the Models page.'
    )
ON CONFLICT (key) DO NOTHING;

CREATE INDEX IF NOT EXISTS platform_config_updated_at_idx ON platform_config(updated_at);
