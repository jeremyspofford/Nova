# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Is Nova

Nova is a self-directed autonomous AI platform. Users define a goal; Nova breaks it into subtasks, executes them through a coordinated agent pipeline, and re-plans as needed. It runs as an 8-service Docker Compose stack.

## Architecture

**Services and ports:**
- **orchestrator** (8000) — Agent lifecycle, task queue, pipeline execution, MCP tool dispatch, DB migrations (FastAPI + asyncpg)
- **llm-gateway** (8001) — Multi-provider model routing via LiteLLM: Anthropic, OpenAI, Ollama, Groq, Gemini, Cerebras, OpenRouter, GitHub, Claude/ChatGPT subscription providers (FastAPI)
- **memory-service** (8002) — Embedding + hybrid semantic/keyword retrieval via pgvector (FastAPI + SQLAlchemy async)
- **chat-api** (8080) — WebSocket streaming bridge for external clients (FastAPI)
- **dashboard** (3000/5173) — React admin UI (Vite dev / nginx prod)
- **postgres** (5432) — pgvector-enabled PostgreSQL 16
- **recovery** (8888) — Backup/restore, factory reset, service management (FastAPI + asyncpg + Docker SDK). Only depends on postgres — stays alive when other services crash.
- **redis** (6379) — State, task queue (BRPOP), rate limiting, session memory

**Inter-service communication:** All HTTP. Orchestrator calls llm-gateway (`/complete`, `/stream`, `/embed`) and memory-service (`/api/v1/memories/*`). Dashboard proxies to orchestrator (`/api`), llm-gateway (`/v1`), and recovery (`/recovery-api`). Chat-api forwards to orchestrator's streaming endpoint. Dashboard depends only on recovery at startup — shows a startup screen while other services come online.

**Shared contracts:** `nova-contracts/` is a Pydantic-only package defining the API contract between services (chat, llm, memory, orchestrator models). Any service satisfying these models is a drop-in replacement.

**Quartet Pipeline:** 5-stage agent chain — Context → Task → Guardrail → Code Review → Decision. Runs via Redis BRPOP task queue with heartbeat (30s) and stale reaper (150s timeout). Pipeline code lives in `orchestrator/app/pipeline/`.

**Redis DB allocation:** orchestrator=db2, llm-gateway=db1, chat-api=db3, memory-service=db0.

## Build & Run Commands

```bash
# First-time setup (copies .env, detects GPU, pulls Ollama models, starts everything)
./scripts/setup.sh

# Dev with hot reload
make dev          # or: docker compose up --build --watch
make watch        # sync Python source into running containers
make logs         # tail all container logs
make ps           # container status

# Production
make build        # rebuild all images
make up           # start detached
make down         # stop all

# GPU overlays (auto-detected by setup.sh)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d   # NVIDIA
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d  # AMD ROCm

# Backup / Restore (emergency CLI — normally use the Recovery UI at /recovery)
make backup               # create a database backup to ./backups/
make restore              # list available backups
make restore F=<file>     # restore a specific backup
```

**Dashboard dev server:** Runs on port 5173 via Vite with proxy to backend services. Production uses nginx on port 3000.

**DB migrations:** Run automatically at orchestrator startup from `orchestrator/app/migrations/*.sql`. No Alembic — pure versioned SQL files run idempotently.

## Testing

No centralized test suite. Validation approaches:
- Dashboard: `cd dashboard && npm run build` (TypeScript compilation check)
- Each FastAPI service: `/health/live` and `/health/ready` endpoints
- Interactive: chat-api serves a test UI at `http://localhost:8080/`
- API docs: FastAPI auto-docs at `/docs` on each service
- memory-service has optional pytest/schemathesis dev dependencies

## Code Conventions

**Python (all backend services):**
- Async/await throughout (FastAPI + asyncpg + async Redis)
- Config via `pydantic_settings.BaseSettings` reading from `.env`
- Orchestrator uses raw asyncpg queries (no ORM); memory-service uses SQLAlchemy async
- Fault-tolerant: try/except + `logger.warning` — never crash on missing optional config
- Snake_case everywhere; JSONB for flexible fields; UUID primary keys; TIMESTAMPTZ

**React/TypeScript (dashboard):**
- Functional components only, TanStack Query for server state (staleTime=5s, retry=1)
- Tailwind CSS with stone/teal/amber/emerald palette; Lucide React icons
- API calls via `apiFetch<T>()` in `src/api.ts`; admin secret stored in localStorage

**API design:**
- Raw JSON responses (no `{ data: ... }` wrapper)
- Admin auth: `X-Admin-Secret` header
- API key auth: `Authorization: Bearer sk-nova-<hash>` or `X-API-Key`
- Streaming: SSE with JSON lines

## Key Configuration

- `.env` — DB password, admin secret, API keys for providers, `DEFAULT_CHAT_MODEL`, `NOVA_WORKSPACE`, `LOG_LEVEL`, `REQUIRE_AUTH`
- `models.yaml` — Ollama models to auto-pull on startup
- Context budgets in orchestrator config: system=10%, tools=15%, memory=40%, history=20%, working=15%

## Website & Documentation

Nova's website lives at `website/` (Astro/Starlight, nova.arialabs.ai). After completing feature work, check if any website content needs updating.

**Website structure:**
- `website/src/content/docs/` — Documentation pages (Starlight)
- `website/src/content/changelog/` — Release changelog entries
- `website/src/data/features.ts` — Landing page feature list and differentiators
- `website/src/components/` — Landing page components (Hero, FeatureCard, PipelineDiagram, etc.)
- `website/astro.config.mjs` — Sidebar structure (update when adding/removing docs)

**Code-to-docs mapping:**

| Changed area | Website content to check |
|---|---|
| `orchestrator/app/pipeline/` | `docs/pipeline.md` |
| `orchestrator/app/tools/`, MCP integration | `docs/mcp-tools.md` |
| `orchestrator/app/router.py`, API endpoints, `nova-contracts/` | `docs/api-reference.md` |
| `orchestrator/app/auth.py`, secrets, `REQUIRE_AUTH` | `docs/security.md` |
| `orchestrator/app/config.py`, `.env.example`, `models.yaml` | `docs/configuration.md` |
| `llm-gateway/` | `docs/services/llm-gateway.md`, `docs/inference-backends.md` |
| `memory-service/` | `docs/services/memory-service.md` |
| `chat-api/` | `docs/services/chat-api.md` |
| `dashboard/` | `docs/services/dashboard.md` |
| `recovery/` | `docs/services/recovery.md` |
| `orchestrator/` (general) | `docs/services/orchestrator.md` |
| `docker-compose*.yml`, `Makefile`, `scripts/setup.sh` | `docs/deployment.md`, `docs/quickstart.md` |
| GPU overlays, inference backends | `docs/inference-backends.md` |
| Service ports, inter-service URLs, new services | `docs/architecture.md` |
| Remote access (Cloudflare, Tailscale) | `docs/remote-access.md` |
| IDE integration (Continue, Cursor, Aider) | `docs/ide-integration.md` |
| Skills framework, `.claude/` config | `docs/skills-rules.md` |
| `docs/roadmap.md` | `docs/roadmap.md` |
| New major feature or capability | `data/features.ts` (landing page), `changelog/` (new entry) |
| New service or architectural change | `components/PipelineDiagram.astro`, `docs/architecture.md` |

**When to update docs:** New features, changed APIs/endpoints, new/changed env vars, new CLI commands, new services, changed ports, changed setup steps, new providers/backends.

**When to add a changelog entry:** After shipping a cohesive set of features (not every commit — group related changes into a release entry in `website/src/content/changelog/`).

**When to update landing page:** New differentiating capabilities, major architectural changes, new platform integrations. Update `features.ts` and relevant components.

**Skip** for internal refactors with no user-visible change.
