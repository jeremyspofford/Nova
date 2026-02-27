-- Nova Orchestrator: API key management + usage tracking
-- Idempotent: safe to execute on every startup (uses IF NOT EXISTS throughout)

CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    key_hash        TEXT NOT NULL UNIQUE,   -- SHA-256 of the raw sk-nova-... key
    key_prefix      TEXT NOT NULL,          -- first 12 chars shown in listings
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    rate_limit_rpm  INTEGER NOT NULL DEFAULT 60,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS usage_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_id      UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    agent_id        UUID,
    session_id      TEXT,
    model           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(12, 8),
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS usage_events_api_key_idx ON usage_events(api_key_id);
CREATE INDEX IF NOT EXISTS usage_events_agent_idx   ON usage_events(agent_id);
CREATE INDEX IF NOT EXISTS usage_events_created_idx ON usage_events(created_at DESC);
