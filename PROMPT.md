You are continuing development of **Nova AI Platform** — a self-directed autonomous AI platform.
The project lives at: ~/workspace/nova (clone from your git repo)

---

## Project Vision
Nova is a multi-service AI platform where you define a goal and Nova autonomously breaks it into
subtasks, executes them through a coordinated pipeline of specialized agents with safety rails,
evaluates progress, re-plans, and completes — with minimal human intervention.

---

## Tech Stack & Architecture

### Backend Services (Docker Compose)
| Service | Port | Role |
|---|---|---|
| orchestrator | 8000 | Agent lifecycle, tool dispatch, session state, API keys, pipeline queue, MCP |
| llm-gateway | 8001 | Model routing — Anthropic, OpenAI, Ollama, Groq, Gemini, Claude Max subscription, etc. |
| memory-service | 8002 | Embedding + semantic retrieval via pgvector |
| chat-api | 8080 | WebSocket streaming for external clients |
| dashboard | 3000 | React admin UI (nginx) |
| postgres | 5432 | pgvector/pgvector:pg16 — agents, api_keys, usage_events, pods, tasks, mcp_servers, platform_config |
| redis | 6379 | Agent state, task queue (BRPOP), rate limiting, session memory |
| ollama | 11434 | Local model serving (dev) |

**Run with:** `make dev` or `docker compose up --build --watch`

### Frontend Dashboard
- Vite + React + TypeScript + Tailwind + TanStack Query + Recharts
- Admin secret auth: stored in localStorage as `nova_admin_secret`
- All API calls go through `apiFetch()` in `dashboard/src/api.ts`
- Vite proxy: `/api` → `http://localhost:8000` (configured in `vite.config.ts`)

---

## What Has Been Built (Phases Completed)

### Phase 1-3 ✅ (pre-existing)
- 7-service microservice platform
- Tool system: list_dir, read_file, write_file, run_shell, search_codebase, git tools
- API key auth (SHA-256 hashed, sk-nova-* format) with rate limiting
- Usage tracking with token cost via LiteLLM
- OpenAI-compatible endpoint for IDE integration (Cursor, Continue.dev, Aider)

### Phase 4 ✅ (completed in our sessions)
- **Quartet Pipeline**: Context → Task → Guardrail → Code Review → Decision agents
- **Redis task queue**: BRPOP async dispatch, 11-state machine, cancel support
- **Database migrations** (005 total):
  - 001: base schema (agents, api_keys, usage_events)
  - 002: phase4 schema (pods, pod_agents, tasks, agent_sessions, guardrail_findings, code_reviews, artifacts, audit_log)
  - 003: fallback_models column + default system prompts per agent role
  - 004: mcp_servers table (stdio/http transport, JSONB args/env)
  - 005: platform_config table (key, value JSONB, is_secret) — seeded with nova.name, nova.persona, nova.greeting, nova.default_model
- **Executor** (`orchestrator/app/pipeline/executor.py`): runs pipeline stages, respects model overrides per pod agent
- **Stale agent reaper** (`orchestrator/app/reaper.py`): background asyncio task cleans up stuck agents

### Phase 5 / 5b ✅ (dashboard — completed in our sessions)
Dashboard pages at `dashboard/src/pages/`:

| Page | Route | Status |
|---|---|---|
| Overview | / | Live agent cards + PipelineSummary + SystemServices panel |
| Tasks | /tasks | Submit tasks, live state machine, cancel, SSE stream |
| Pods | /pods | Pod management, per-agent config (AgentAdvancedSettings) |
| Usage | /usage | Charts by day/week/month/model with recharts |
| Keys | /keys | Create/revoke API keys |
| Models | /models | 39 models grouped by provider |
| Chat | /chat | Streaming chat with Nova, model selector, session continuity |
| MCP | /mcp | MCP server management (add/delete/reload/connect status) |
| Settings | /settings | Nova identity (name, persona, greeting), default model override |

### MCP Integration ✅
- `orchestrator/app/pipeline/tools/mcp_client.py` — StdioMCPClient (JSON-RPC 2.0 over subprocess stdin/stdout)
- `orchestrator/app/pipeline/tools/registry.py` — module-level _active_clients dict, load/connect/disconnect/reload
- Tools namespaced as `mcp__{server_name}__{tool_name}`
- Loaded at startup (`main.py` lifespan), stopped on shutdown

### Platform Config / Persona ✅
- `platform_config` table stores typed values as JSONB
- Nova's persona from `nova.persona` key is appended to every agent context as a `## Persona` block
- Fault-tolerant: `_get_platform_persona()` returns "" on any failure so missing key never breaks agent turns
- Editable live in Settings page without restart

### Chat Endpoint ✅
- `POST /api/v1/chat/stream` (AdminDep) — separate from `/api/v1/tasks/stream` (ApiKeyDep)
- Streaming via SSE using `fetch()` async generator `streamChat()` in api.ts
- Session ID generated once per conversation, passed to memory service for continuity

### Favicon ✅
- `dashboard/public/nova-icon.png` — star-burst icon
- Referenced in `dashboard/index.html` as `<link rel="icon">` + `<link rel="apple-touch-icon">`

---

## Key File Reference

### Orchestrator (Python/FastAPI)

orchestrator/app/
├── main.py # lifespan: DB init → MCP load → queue worker → reaper
├── router.py # /api/v1/agents, /chat/stream, /config (platform config endpoints)
├── pipeline_router.py # /api/v1/pods, /tasks, /mcp-servers
├── agents/runner.py # run_agent_turn_streaming, _build_nova_context, _get_platform_persona
├── pipeline/
│ ├── executor.py # runs pipeline stages in order per pod config
│ ├── agents/
│ │ ├── task.py # TaskAgent — uses run_agent_turn_raw with ALL_TOOLS
│ │ ├── context.py # ContextAgent
│ │ ├── guardrail.py # GuardrailAgent
│ │ ├── code_review.py
│ │ └── decision.py
│ └── tools/
│ ├── mcp_client.py # StdioMCPClient
│ └── registry.py # MCP server registry
├── tools/init.py # ALL_TOOLS, get_all_tools() (+ MCP), execute_tool()
└── migrations/001-005 # SQL migrations, run automatically at startup


### Dashboard (React/TypeScript)

dashboard/src/
├── api.ts # All API functions + interfaces
├── types.ts # AgentInfo, Pod, PodAgent, PipelineTask, etc.
├── App.tsx # Routes
├── components/
│ ├── NavBar.tsx # All nav links
│ ├── ModelPicker.tsx # Primary + fallback model selector component
│ └── StatusBadge.tsx
└── pages/ # All pages listed above


---

## Auth Pattern
- **Admin endpoints**: `X-Admin-Secret: <NOVA_ADMIN_SECRET>` (env var, default: `nova-admin-secret-change-me`)
- **API key endpoints**: `Authorization: Bearer sk-nova-<hash>` or `X-API-Key: sk-nova-<hash>`
- Dashboard stores admin secret in `localStorage.getItem('nova_admin_secret')`

---

## Pending / Next Work

### Immediate (agreed upon, not started)
1. **Memory Compaction Pipeline** — background agent that distills episodic memories into semantic facts
   - Design: nightly asyncio task, reads recent episodes from memory-service, runs a compaction LLM call, upserts facts back
   - This is the "Phase 6" memory overhaul from the roadmap

### Phase 6 Memory Overhaul (roadmap)
- Three-tier: Redis (session) + PostgreSQL (structured facts/episodes) + pgvector (semantic)
- Hybrid retrieval: 70% cosine_similarity + 30% ts_rank full-text
- ACT-R confidence decay: `effective_confidence = base_confidence × (days_since_last_access ^ -0.5)`
- Memory Inspector dashboard page

### Phase 7 (roadmap)
- Goal Layer, Planning Agent, Evaluation Agent, Loop Controller
- Self-directed: submit a goal, Nova executes until complete

---

## Development Notes
- `make dev` = `docker compose up --build --watch` (hot reload for orchestrator + llm-gateway)
- TypeScript build: `cd dashboard && npm run build` (should be zero errors)
- Migrations run automatically at orchestrator startup (no Alembic, pure SQL)
- Models are defined in `models.yaml` (39 models, 9 providers)
- The `workspace/` directory is mounted at `/workspace` inside the orchestrator container
- `.env` file holds secrets (POSTGRES_PASSWORD, NOVA_ADMIN_SECRET, API keys, etc.)

---

## Style Guidelines (to maintain consistency)
- Python: async/await throughout, FastAPI + asyncpg, fault-tolerant with try/except + logger.warning
- React: functional components only, TanStack Query for all server state, Tailwind for styling
- DB schema: snake_case, JSONB for flexible fields, UUID PKs, timestamps with timezone
- API responses: raw JSON arrays/objects (no `{ data: ... }` wrapper) from `apiFetch<T>()`
- Icons: lucide-react throughout
- Colors: stone (neutrals), teal (primary actions/active states), amber (warnings), emerald (success)
