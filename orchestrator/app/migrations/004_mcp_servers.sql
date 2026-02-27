-- Migration 004: MCP (Model Context Protocol) server registry
--
-- Stores configuration for external tool servers that expose additional
-- capabilities to Nova agents via the MCP stdio/http transports.
-- Tools from connected servers are namespaced: mcp__{server_name}__{tool_name}

CREATE TABLE IF NOT EXISTS mcp_servers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    -- Transport type: 'stdio' (subprocess) | 'http' (remote HTTP+SSE)
    transport       TEXT NOT NULL DEFAULT 'stdio',
    -- stdio transport: the executable to spawn (e.g. 'npx', 'node', 'python3')
    command         TEXT,
    -- stdio transport: argument list passed to the executable
    args            JSONB NOT NULL DEFAULT '[]',
    -- stdio transport: extra environment variables passed to the subprocess
    env             JSONB NOT NULL DEFAULT '{}',
    -- http transport: the base URL of the MCP server
    url             TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS mcp_servers_enabled_idx  ON mcp_servers(enabled);
CREATE INDEX IF NOT EXISTS mcp_servers_name_idx     ON mcp_servers(name);
