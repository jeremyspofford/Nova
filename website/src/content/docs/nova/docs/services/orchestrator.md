---
title: "Orchestrator"
description: "Agent lifecycle management, pipeline execution, task queue, MCP tool dispatch, and database migrations. Port 8000."
---

The Orchestrator is Nova's central coordination service. It manages agent lifecycles, dispatches tasks through the Quartet Pipeline, maintains the Redis task queue, connects MCP tool servers, and runs database migrations at startup.

## Overview

| Property | Value |
|----------|-------|
| **Port** | 8000 |
| **Framework** | FastAPI + asyncpg |
| **Database** | PostgreSQL 16 (raw asyncpg queries, no ORM) |
| **State store** | Redis (db 2) |
| **Source** | `orchestrator/` |

## Key responsibilities

- **Agent lifecycle** -- create, list, update, delete agents stored in Redis
- **Task routing** -- accept tasks via REST, run them through the agent loop (tool-use + LLM), return results or stream via SSE
- **Quartet Pipeline** -- execute the 5-stage agent chain (Context, Task, Guardrail, Code Review, Decision) for async tasks
- **Task queue** -- Redis BRPOP-based async queue with heartbeat (30s) and stale task reaper (150s timeout)
- **MCP tool dispatch** -- load MCP server configurations from the database, connect to them at startup, and expose their tools to agents
- **API key management** -- create, list, and revoke API keys (SHA-256 hashed, `sk-nova-*` format)
- **DB migrations** -- apply versioned SQL migrations from `orchestrator/app/migrations/*.sql` at startup (idempotent, no Alembic)

## Key endpoints

### Agent lifecycle

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/agents` | API key | Create a new agent |
| GET | `/api/v1/agents` | API key | List all agents |
| GET | `/api/v1/agents/{id}` | API key | Get agent details |
| PATCH | `/api/v1/agents/{id}/config` | Admin | Update agent model, system prompt, fallback models |
| DELETE | `/api/v1/agents/{id}` | API key | Delete an agent |

### Task routing

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/tasks` | API key | Submit a task (synchronous) |
| POST | `/api/v1/tasks/stream` | API key | Submit a task (SSE streaming) |
| GET | `/api/v1/tasks/{id}` | API key | Get task result |

### Pipeline (async queue)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/pipeline/tasks` | API key | Submit task to the async pipeline queue |
| GET | `/api/v1/pipeline/tasks` | API key | List recent tasks (filterable) |
| GET | `/api/v1/pipeline/tasks/{id}` | API key | Get task status and output |
| POST | `/api/v1/pipeline/tasks/{id}/cancel` | API key | Cancel a queued/pending task |
| GET | `/api/v1/pipeline/tasks/{id}/findings` | API key | Guardrail findings for a task |
| GET | `/api/v1/pipeline/tasks/{id}/reviews` | API key | Code review verdicts |
| GET | `/api/v1/pipeline/tasks/{id}/artifacts` | API key | Artifacts produced by a task |
| POST | `/api/v1/pipeline/tasks/{id}/review` | API key | Approve/reject a pending human review |
| GET | `/api/v1/pipeline/queue-stats` | API key | Queue depth and dead-letter count |
| GET | `/api/v1/pipeline/dead-letter` | Admin | Inspect dead-letter queue |

### Chat (dashboard)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/chat/stream` | Admin | Streaming chat with the primary Nova agent |

### Pod and agent management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/pods` | API key | List all pods |
| POST | `/api/v1/pods` | Admin | Create a new pod |
| GET | `/api/v1/pods/{id}` | API key | Get pod details and agents |
| PATCH | `/api/v1/pods/{id}` | Admin | Update pod settings |
| DELETE | `/api/v1/pods/{id}` | Admin | Delete pod and its agents |
| GET | `/api/v1/pods/{id}/agents` | API key | List agents in a pod |
| POST | `/api/v1/pods/{id}/agents` | Admin | Add agent to pod |
| PATCH | `/api/v1/pods/{id}/agents/{aid}` | Admin | Update agent config |
| DELETE | `/api/v1/pods/{id}/agents/{aid}` | Admin | Remove agent from pod |

### MCP servers

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/mcp-servers` | API key | List registered MCP servers |
| POST | `/api/v1/mcp-servers` | Admin | Register a new MCP server |
| PATCH | `/api/v1/mcp-servers/{id}` | Admin | Update server config |
| DELETE | `/api/v1/mcp-servers/{id}` | Admin | Remove server |
| POST | `/api/v1/mcp-servers/{id}/reload` | Admin | Reconnect to server |

### Key management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/keys` | Admin | Create API key (raw key shown once) |
| GET | `/api/v1/keys` | Admin | List all keys |
| DELETE | `/api/v1/keys/{id}` | Admin | Revoke a key |

### Identity

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/identity` | Public | Get AI display name and greeting (used by dashboard UI) |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe (checks DB + Redis) |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | -- |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/2` |
| `ADMIN_SECRET` | Admin authentication secret | -- |
| `REQUIRE_AUTH` | Enforce API key auth | `false` |
| `DEFAULT_CHAT_MODEL` | Default model for interactive chat | -- |
| `NOVA_WORKSPACE` | Host path mounted at `/workspace` | -- |
| `LOG_LEVEL` | Logging level | `INFO` |
| `SHELL_SANDBOX` | Default sandbox tier (`isolated`/`nova`/`workspace`/`host`) | `workspace` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed origins | `*` |

## Startup sequence

1. Recover any Redis agents stuck in `running` state from a previous crash
2. Initialize the PostgreSQL connection pool and apply versioned schema migrations
3. Ensure one canonical primary agent exists; prune duplicates
4. Load MCP server configurations from the database and connect to enabled servers
5. Start background tasks: queue worker (BRPOP) and stale task reaper

## Implementation notes

- **Async throughout** -- all database access uses asyncpg with connection pooling; all Redis operations use `redis.asyncio`
- **No ORM** -- raw SQL queries via asyncpg for maximum performance and control
- **Tool registry** -- built-in tools (file I/O, shell, git, platform) are statically registered; MCP tools are dynamically loaded at runtime via `get_all_tools()`
- **Sandbox tiers** -- four access levels (isolated, nova, workspace, host) control filesystem and shell access per pod; configured via `SandboxTier` enum
- **Fault tolerant** -- all optional integrations wrapped in try/except with `logger.warning`; missing config never crashes the service
