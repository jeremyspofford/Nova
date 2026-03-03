-- Migration 006: Agent Endpoints (ACP/A2A outbound delegation)
--
-- Stores external agent systems that Nova can delegate tasks to.
-- Both ACP (BeeAI/IBM) and A2A (Google) define a standard envelope:
-- POST a task to an external agent endpoint, poll or stream the result back.
-- From Nova's perspective each endpoint is treated as a callable tool.

CREATE TABLE IF NOT EXISTS agent_endpoints (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    -- Base URL of the external agent system (e.g. https://agent.example.com)
    url             TEXT NOT NULL,
    -- Optional Bearer token sent as Authorization header on outbound calls
    auth_token      TEXT,
    -- Protocol hint: 'a2a' (Google) | 'acp' (BeeAI/IBM) | 'generic'
    protocol        TEXT NOT NULL DEFAULT 'a2a',
    -- Optional JSON Schema describing the expected task input
    input_schema    JSONB NOT NULL DEFAULT '{}',
    -- Optional JSON Schema describing the expected task output
    output_schema   JSONB NOT NULL DEFAULT '{}',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS agent_endpoints_enabled_idx ON agent_endpoints(enabled);
CREATE INDEX IF NOT EXISTS agent_endpoints_name_idx    ON agent_endpoints(name);
