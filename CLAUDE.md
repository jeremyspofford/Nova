# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Is Nova

Nova is a self-directed autonomous AI platform. Users define a goal; Nova breaks it into subtasks, executes them through a coordinated agent pipeline, and re-plans as needed. It runs as a 9-service Docker Compose stack.

## Architecture

**Services and ports:**
- **orchestrator** (8000) — Agent lifecycle, task queue, pipeline execution, MCP tool dispatch, DB migrations (FastAPI + asyncpg)
- **llm-gateway** (8001) — Multi-provider model routing via LiteLLM: Anthropic, OpenAI, Ollama, Groq, Gemini, Cerebras, OpenRouter, GitHub, Claude/ChatGPT subscription providers (FastAPI)
- **memory-service** (8002) — Embedding + hybrid semantic/keyword retrieval via pgvector (FastAPI + SQLAlchemy async)
- **chat-api** (8080) — WebSocket streaming bridge for external clients (FastAPI)
- **chat-bridge** (8090) — Multi-platform chat integration: Telegram, Slack (FastAPI + httpx + redis). Optional, start with `--profile bridges`.
- **dashboard** (3000/5173) — React admin UI (Vite dev / nginx prod)
- **postgres** (5432) — pgvector-enabled PostgreSQL 16 (data bind-mounted to `./data/postgres/`)
- **recovery** (8888) — Backup/restore, factory reset, service management (FastAPI + asyncpg + Docker SDK). Only depends on postgres — stays alive when other services crash.
- **cortex** (8100) — Autonomous brain: thinking loop, goals, drives, budget tracking (FastAPI + asyncpg)
- **redis** (6379) — State, task queue (BRPOP), rate limiting, session memory (data bind-mounted to `./data/redis/`)

**Inter-service communication:** All HTTP. Orchestrator calls llm-gateway (`/complete`, `/stream`, `/embed`) and memory-service (`/api/v1/engrams/*`). Dashboard proxies to orchestrator (`/api`), llm-gateway (`/v1`), recovery (`/recovery-api`), and cortex (`/cortex-api`). Chat-api forwards to orchestrator's streaming endpoint. Chat-bridge calls orchestrator (`/api/v1/tasks/stream`) to relay messages from external platforms. Cortex calls orchestrator (task dispatch, goal management), llm-gateway (planning, evaluation), and memory-service (read/write knowledge). Dashboard depends only on recovery at startup — shows a startup screen while other services come online.

**Shared contracts:** `nova-contracts/` is a Pydantic-only package defining the API contract between services (chat, llm, memory, orchestrator models). Any service satisfying these models is a drop-in replacement.

**Quartet Pipeline:** 5-stage agent chain — Context → Task → Guardrail → Code Review → Decision. Runs via Redis BRPOP task queue with heartbeat (30s) and stale reaper (150s timeout). Pipeline code lives in `orchestrator/app/pipeline/`.

**Redis DB allocation:** orchestrator=db2, llm-gateway=db1, chat-api=db3, memory-service=db0, chat-bridge=db4, cortex=db5, recovery=db7.

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

# Cleanup (NEVER run raw docker system prune — use these instead)
make prune                # remove containers, images, build cache (preserves ALL volumes)
make prune-all            # backup DB first, then prune + remove model cache volumes
```

**Dashboard dev server:** Runs on port 5173 via Vite with proxy to backend services. Production uses nginx on port 3000.

**DB migrations:** Run automatically at orchestrator startup from `orchestrator/app/migrations/*.sql`. No Alembic — pure versioned SQL files run idempotently.

## Testing

```bash
make test          # Full integration suite (35 tests, ~2 min, requires services running)
make test-quick    # Health endpoints only (~0.4s)
```

Integration tests live in `tests/` at the repo root. They hit real running services over HTTP/WebSocket — no mocks. Pipeline tests are opt-in (skipped unless an LLM provider is configured). Tests create resources with `nova-test-` prefix and clean up via fixture teardown.

Additional validation:
- Dashboard: `cd dashboard && npm run build` (TypeScript compilation check)
- Each FastAPI service: `/health/live` and `/health/ready` endpoints
- Interactive: chat-api serves a test UI at `http://localhost:8080/`
- API docs: FastAPI auto-docs at `/docs` on each service

## Code Conventions

**Python (all backend services):**
- Async/await throughout (FastAPI + asyncpg + async Redis)
- Config via `pydantic_settings.BaseSettings` reading from `.env`
- Orchestrator uses raw asyncpg queries (no ORM); memory-service uses SQLAlchemy async
- Fault-tolerant: try/except + `logger.warning` — never crash on missing optional config
- **Log levels matter:** ERROR for unrecoverable failures, WARNING for recoverable issues that affect functionality, INFO for state changes, DEBUG for detailed flow. Never log critical failures at DEBUG — they become invisible in production (LOG_LEVEL=INFO).
- **Redis cleanup:** Every service with `get_redis()` must have a corresponding `close_redis()` called in the FastAPI lifespan shutdown path. Connection leaks accumulate across restarts.
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

## Engram Memory System

The old 4-tier memory (working/episodic/semantic/procedural) has been replaced by the **Engram Network** — a graph-based cognitive memory system. Code lives in `memory-service/app/engram/`.

**Key components:**
- **Ingestion** (`ingestion.py`) — Async Redis queue worker decomposes raw text into structured engrams via LLM. Backpressure via `Semaphore(5)`.
- **Spreading Activation** (`activation.py`) — Graph traversal retrieval via recursive CTE. Seeds by cosine similarity, then spreads through weighted edges.
- **Working Memory** (`working_memory.py`) — Five-tier slot system (pinned, sticky, refreshed, sliding, expiring) with token budgeting.
- **Consolidation** (`consolidation.py`) — Background "sleep cycle" with 6 phases: replay, pattern extraction, Hebbian learning, contradiction resolution, pruning/merging, self-model update. Mutex-protected.
- **Neural Router** (`neural_router/`) — Learned ML re-ranker (PyTorch). Trains on retrieval feedback after 200+ labeled observations.
- **Outcome Feedback** (`outcome_feedback.py`) — Post-LLM scoring adjusts engram activation/importance.

**API:** All endpoints at `/api/v1/engrams/` — `POST /ingest`, `POST /context` (main entry point for orchestrator), `POST /activate`, `POST /consolidate`, `GET /stats`, `GET /graph`.

**Orchestrator integration:** `run_agent_turn()` calls `POST /api/v1/engrams/context` for memory, then `POST /mark-used` for feedback. New exchanges are pushed to Redis `engram:ingestion:queue` for async decomposition.

**LLM models default to "auto"** — decomposition, reconstruction, and consolidation models auto-resolve by probing the gateway for available models. Override via `ENGRAM_DECOMPOSITION_MODEL` etc. in `.env`.

## Runtime Configuration (Redis)

Several settings are runtime-configurable via Redis (db 1, prefix `nova:config:`), overridable from the Dashboard UI:

| Key | Values | Effect |
|---|---|---|
| `inference.backend` | `ollama`, `vllm`, `sglang`, `none` | Which local inference backend the gateway uses |
| `inference.state` | `ready`, `starting`, `error`, `draining` | Whether local inference is accepting requests |
| `llm.routing_strategy` | `local-first`, `local-only`, `cloud-first`, `cloud-only` | How the gateway routes requests between local and cloud |
| `llm.ollama_url` | URL | Runtime Ollama endpoint override |

**Gotcha:** Stale Redis config values survive container restarts. If inference is broken, check `inference.state` and `inference.backend` in Redis before debugging code. The gateway resolves `OLLAMA_BASE_URL=auto` at startup but Redis overrides take precedence at runtime.

## Key Configuration

- `.env` — DB password, admin secret, API keys for providers, `DEFAULT_CHAT_MODEL`, `NOVA_WORKSPACE`, `LOG_LEVEL`, `REQUIRE_AUTH`
- `OLLAMA_BASE_URL` — Set to `auto` (probes host, falls back to Docker), `host` (always use host machine), or explicit URL
- `POSTGRES_DATA_DIR` / `REDIS_DATA_DIR` — Host bind-mount paths for critical data (default: `./data/postgres`, `./data/redis`). Immune to `docker volume prune`.
- `models.yaml` — Ollama models to auto-pull on startup
- Context budgets in orchestrator config: system=10%, tools=15%, memory=40%, history=20%, working=15%

## Debugging

Quick diagnostics when something is broken:

```bash
# Container status
docker compose ps

# Service health (all at once)
for p in 8000 8001 8002 8080 8100 8888; do echo -n "localhost:$p → "; curl -sf -m 2 http://localhost:$p/health/ready | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "DOWN"; done

# Redis config state (stale values are a common root cause)
docker compose exec redis redis-cli -n 1 MGET nova:config:inference.backend nova:config:inference.state nova:config:llm.routing_strategy

# Queue depths
docker compose exec redis redis-cli -n 2 LLEN nova:queue:tasks
docker compose exec redis redis-cli -n 0 LLEN engram:ingestion:queue

# Memory system health
curl -s http://localhost:8002/api/v1/engrams/stats | python3 -m json.tool

# Recent errors across all services
docker compose logs --tail 30 2>&1 | grep -i "error\|exception" | tail -20
```

## Website & Documentation

Nova's website lives at `website/` (Astro/Starlight, arialabs.ai). The site serves both the Aria Labs company landing page and Nova product pages/docs. After completing feature work, check if any website content needs updating.

**Website structure:**
- `website/src/content/docs/nova/docs/` — Documentation pages (Starlight, served at arialabs.ai/nova/docs/)
- `website/src/content/changelog/` — Release changelog entries
- `website/src/data/features.ts` — Landing page feature list and differentiators
- `website/src/components/` — Landing page components (Hero, FeatureCard, PipelineDiagram, etc.)
- `website/astro.config.mjs` — Sidebar structure (update when adding/removing docs)

**Code-to-docs mapping:**

| Changed area | Website content to check |
|---|---|
| `orchestrator/app/pipeline/` | `nova/docs/pipeline.md` |
| `orchestrator/app/tools/`, MCP integration | `nova/docs/mcp-tools.md` |
| `orchestrator/app/router.py`, API endpoints, `nova-contracts/` | `nova/docs/api-reference.md` |
| `orchestrator/app/auth.py`, secrets, `REQUIRE_AUTH` | `nova/docs/security.md` |
| `orchestrator/app/config.py`, `.env.example`, `models.yaml` | `nova/docs/configuration.md` |
| `llm-gateway/` | `nova/docs/services/llm-gateway.md`, `nova/docs/inference-backends.md` |
| `memory-service/` | `nova/docs/services/memory-service.md` |
| `chat-api/` | `nova/docs/services/chat-api.md` |
| `dashboard/` | `nova/docs/services/dashboard.md` |
| `recovery/` | `nova/docs/services/recovery.md` |
| `cortex/` | (new — no docs yet) |
| `orchestrator/` (general) | `nova/docs/services/orchestrator.md` |
| `docker-compose*.yml`, `Makefile`, `scripts/setup.sh` | `nova/docs/deployment.md`, `nova/docs/quickstart.md` |
| GPU overlays, inference backends | `nova/docs/inference-backends.md` |
| Service ports, inter-service URLs, new services | `nova/docs/architecture.md` |
| Remote access (Cloudflare, Tailscale) | `nova/docs/remote-access.md` |
| IDE integration (Continue, Cursor, Aider) | `nova/docs/ide-integration.md` |
| Skills framework, `.claude/` config | `nova/docs/skills-rules.md` |
| `docs/roadmap.md` | `nova/docs/roadmap.md` |
| New major feature or capability | `data/features.ts` (landing page), `changelog/` (new entry) |
| New service or architectural change | `components/PipelineDiagram.astro`, `nova/docs/architecture.md` |

**When to update docs:** New features, changed APIs/endpoints, new/changed env vars, new CLI commands, new services, changed ports, changed setup steps, new providers/backends.

**When to add a changelog entry:** After shipping a cohesive set of features (not every commit — group related changes into a release entry in `website/src/content/changelog/`).

**When to update landing page:** New differentiating capabilities, major architectural changes, new platform integrations. Update `features.ts` and relevant components.

**Skip** for internal refactors with no user-visible change.
