---
title: "Architecture"
description: "Nova's multi-service Docker Compose architecture, inter-service communication, and tech stack."
---

Nova runs as a multi-service Docker Compose stack. Each service has a single responsibility and communicates over HTTP.

## Services

| Service | Port | Role |
|---------|------|------|
| **orchestrator** | 8000 | Agent lifecycle, task queue, pipeline execution, MCP tool dispatch, DB migrations |
| **llm-gateway** | 8001 | Multi-provider model routing via LiteLLM (Anthropic, OpenAI, Ollama, Groq, Gemini, Cerebras, OpenRouter, GitHub, Claude/ChatGPT subscription providers) |
| **memory-service** | 8002 | Embedding + hybrid semantic/keyword retrieval via pgvector |
| **chat-api** | 8080 | WebSocket streaming bridge for external clients |
| **dashboard** | 3000 / 5173 | React admin UI (nginx in production, Vite dev server in development) |
| **postgres** | 5432 | pgvector-enabled PostgreSQL 16 |
| **redis** | 6379 | State, task queue (BRPOP), rate limiting, session memory |
| **recovery** | 8888 | Backup/restore, factory reset, service management. Only depends on postgres -- stays alive when other services crash. |
| **chat-bridge** | 8090 | Multi-platform chat integration (Telegram, Slack). Opt-in via `bridges` profile. |

## Inter-service communication

All communication between services is HTTP. Here's who calls who:

```
dashboard ──proxy──▶ orchestrator  (/api)
          ──proxy──▶ llm-gateway   (/v1)
          ──proxy──▶ recovery      (/recovery-api)

chat-api ──────────▶ orchestrator  (streaming endpoint)

chat-bridge ───────▶ orchestrator  (streaming endpoint, agent API)
            ───────▶ redis         (session mapping, db 4)

orchestrator ──────▶ llm-gateway   (/complete, /stream, /embed)
             ──────▶ memory-service (/api/v1/memories/*)
             ──────▶ redis          (task queue, state)

recovery ──────────▶ postgres      (backup/restore)
         ──────────▶ Docker API    (service management)
```

The dashboard depends only on the recovery service at startup. It shows a startup screen while other services come online, so users always have visibility into system state.

## Tech stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python, FastAPI, asyncpg, asyncio |
| **Frontend** | Vite, React, TypeScript, Tailwind CSS, TanStack Query |
| **Database** | PostgreSQL 16 + pgvector |
| **Queue** | Redis (BRPOP task dispatch) |
| **Containers** | Docker Compose with hot reload (watch mode) |
| **Model routing** | LiteLLM (multi-provider abstraction) |

## Shared contracts

The `nova-contracts/` package defines the API contract between services using Pydantic models (chat, LLM, memory, orchestrator). Any service satisfying these models is a drop-in replacement. This is a Pydantic-only package with no runtime dependencies on any service.

## Database

Nova uses two different database access patterns:

| Service | Access layer | Reason |
|---------|-------------|--------|
| **orchestrator** | Raw asyncpg queries | Performance-critical task queue operations, no ORM overhead |
| **memory-service** | SQLAlchemy async | Complex vector queries benefit from ORM expressiveness |

**Migrations** run automatically at orchestrator startup from `orchestrator/app/migrations/*.sql`. These are pure versioned SQL files that run idempotently -- no Alembic.

All tables use UUID primary keys, TIMESTAMPTZ for timestamps, and JSONB for flexible fields.

## Redis DB allocation

Each service uses a dedicated Redis database to avoid key collisions:

| Redis DB | Service |
|----------|---------|
| 0 | memory-service |
| 1 | llm-gateway |
| 2 | orchestrator |
| 3 | chat-api |
| 4 | chat-bridge |

## API design

- Raw JSON responses (no `{ data: ... }` wrapper)
- Admin auth: `X-Admin-Secret` header
- API key auth: `Authorization: Bearer sk-nova-<hash>` or `X-API-Key`
- Streaming: Server-Sent Events (SSE) with JSON lines
- Auto-generated API docs at `/docs` on each FastAPI service
