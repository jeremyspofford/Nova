# Nova AI Platform — Roadmap

> Living document. Restructured 2026-03-25.
>
> **Vision:** A self-directed autonomous AI platform. You define a goal. Nova breaks it into
> subtasks, executes them through a coordinated pipeline of specialized agents with built-in
> safety rails, evaluates its own progress, re-plans as needed, and completes the goal — with
> minimal human intervention except when it genuinely needs a decision.
>
> Previous roadmap with full historical design specs archived at `docs/roadmap-archive-2026-03.md`.

---

## Autonomy Levels

| Level | Description | Status |
|---|---|---|
| **1 — Pipeline autonomy** | Quartet runs all agents without human input. Escalates only on critical flags. | Delivered |
| **2 — Async execution** | Tasks run in background. Submit and come back. | Delivered |
| **3 — Self-aware** | Nova understands its own architecture, config, health; can inspect and modify itself. | Not Started |
| **4 — Triggered execution** | Tasks start from external events — git push, cron, webhook, Slack. | Partial (intel/knowledge polling) |
| **5 — Reactive** | Nova watches continuous streams, applies AI judgment, acts autonomously. | Not Started |
| **6 — Self-directed** | Nova breaks goals into subtasks, executes, evaluates, re-plans, loops to completion. | Partial (cortex exists, feedback loop missing) |

---

## What's Shipped

Everything below is deployed and functional. Nova runs as a 12-service Docker Compose stack
with PostgreSQL (pgvector), Redis, and optional profiles for bridges, knowledge, and inference backends.

### Core Platform & Orchestrator (Port 8000)

Agent lifecycle management with 11-state task machine. 66 auto-run SQL migrations (pure SQL, no Alembic). Task queue via Redis BRPOP with heartbeat (30s) and stale reaper (150s). Shared contracts library (`nova-contracts/`) defining Pydantic API shapes used by all services.

- Multi-turn agent loop with tool use and streaming
- Pod/agent configuration stored in DB, editable via dashboard
- Intel router: feed CRUD, content ingestion, recommendations, comments
- Knowledge router: source CRUD, credential management, manual paste
- Goal management with maturation status tracking
- MCP server registration and tool dispatch
- API key auth (`sk-nova-*`, SHA-256 hashed) + admin auth + RBAC scaffolding
- OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/models`) for IDE integration

### LLM Gateway (Port 8001)

Multi-provider model routing with 27+ provider files.

- **Providers:** Ollama, Anthropic, OpenAI, Groq, Gemini, Cerebras, OpenRouter, GitHub Models, vLLM, SGLang, Claude/ChatGPT subscription, remote OpenAI-compatible
- **Routing strategies:** local-only, local-first, cloud-only, cloud-first
- **Intelligent routing:** Classifier-based (general/code/reasoning/creative/quick) with cascading classifier models (Ollama → Groq → Cerebras), per-category model preference lists, auto-fallback
- Auto model resolution with 30s caching, quality-ranked preference list
- Response caching (300s TTL), rate limiting (Redis sliding window)
- Token counting + cost tracking via LiteLLM
- SSE metadata events (model, category) before content deltas

### Engram Memory System (Port 8002)

Graph-based cognitive memory. 8 node types (fact, episode, entity, preference, procedure, schema, goal, self_model), typed/weighted edges, spreading activation retrieval.

- **Ingestion** — Async Redis queue worker decomposes raw text into structured engrams via LLM. Entity resolution, contradiction detection, edge creation. Backpressure via Semaphore(5).
- **Spreading Activation** — Graph traversal via recursive CTE. Seeds by cosine similarity, then spreads through weighted edges. <100ms.
- **Working Memory** — 5-tier slot system (pinned/sticky/refreshed/sliding/expiring) with token budgeting. Background cleanup every 5 min.
- **Consolidation** — 6-phase "sleep cycle": replay, pattern extraction, Hebbian learning, contradiction resolution, pruning/merging, self-model update. Mutex-protected, 3 triggers (idle/nightly/threshold).
- **Outcome Feedback** — Post-LLM scoring adjusts engram activation/importance.
- **Neural Router** — Full PyTorch training pipeline (878 lines, ScalarReranker + EmbeddingReranker). Activates organically after 200+ labeled retrieval observations.
- 3-tier embedding cache (Redis L1 → PostgreSQL L2 → Gateway L3) with write-through

### Quartet Pipeline

5-stage agent chain: Context → Task → Guardrail → Code Review → Decision.

- Redis BRPOP task dispatch with checkpointing
- 11 task states: `submitted → queued → context_running → task_running → guardrail_running → review_running → pending_human_review → completing → complete | failed | cancelled`
- Clarification support — Context Agent detects ambiguity, pauses for user input via `POST /clarify`
- Parallel agent groups (Guardrail + Code Review run concurrently)
- Per-agent configurability: model, temperature, max_tokens, timeout, system_prompt, allowed_tools, run_condition, output_schema
- Per-pod configurability: max_cost_usd, max_execution_seconds, require_human_review, routing_keywords/regex

### Cortex — Autonomous Brain (Port 8100)

Thinking loop with cognitive drives, goal management, and budget tracking.

- BRPOP hybrid loop with adaptive timeout (active fast → idle slow)
- One cycle: PERCEIVE → EVALUATE → PLAN → ACT → REFLECT
- 5 drives: Serve (user goals), Maintain (health), Improve (contradictions), Learn (consolidation), Reflect (self-model)
- Token budget tracking with tier-based throttling
- Goal management with iterations, success criteria, cost tracking
- Stimulus system: Redis BRPOP for event-driven reactivity
- Scheduler: periodic checks for idle goals, expired tasks
- Maturation: goals track stages (triaging → scoping → speccing → review → building → verifying)

### Intel System (Port 8110)

Autonomous AI ecosystem feed poller.

- 5 fetcher types: RSS, Reddit JSON, page change detection, GitHub trending, GitHub releases
- Configurable polling intervals per feed, exponential error backoff (capped 24h)
- Content dedup via hash, SSRF validation on all URLs
- Pushes to engram ingestion queue + intel notification queue
- 14 default feeds seeded by migration
- Orchestrator endpoints: feed CRUD, content ingestion, recommendations

### Knowledge Sources (Port 8120)

Autonomous personal knowledge crawler. Optional service (`--profile knowledge`).

- LLM-guided web crawler with BFS, relevance scoring, circuit breaker
- robots.txt compliance, per-domain rate limiting, SSRF validation per hop (including redirects)
- GitHub API extractor (profile, repos, READMEs, activity)
- Encrypted credential storage (AES-256-GCM envelope encryption via nova-worker-common)
- Credential health check background task (every 6h)
- Dashboard Sources page (Personal/Feeds/Shared tabs)
- Manual content paste → engram ingestion

### Chat System

- **Chat API** (Port 8080) — WebSocket streaming bridge (SSE-to-WebSocket), session management with conversation history, test UI at `/`
- **Chat Bridge** (Port 8090) — Telegram + Slack adapters with message relay, markdown conversion, context forwarding. Optional (`--profile bridges`)

### Dashboard (Port 3000/5173)

React admin UI with 20 functional pages. Vite + Tailwind (stone/teal/amber/emerald) + TanStack Query + Lucide React icons.

- **Core:** Overview (live agent cards), Chat (WebSocket streaming), Tasks (board + lifecycle)
- **Configuration:** Pods (CRUD + agent config), Models (39 models by provider), Goals (create/manage + maturation + recommendations)
- **Data:** Sources (knowledge + intel unified), Memory (engram explorer + graph viz + source attribution)
- **System:** MCP (server list + tool catalog), Settings (API keys, routing, auth, inference), Recovery (backup/restore)
- **Admin:** Keys, Users, Friction, AgentEndpoints, About, Invite, Login

### Recovery Service (Port 8888)

Dedicated backup/restore and service management. Only depends on postgres — stays alive when other services crash.

- PostgreSQL backup/restore to disk
- Factory reset
- Docker socket integration for container lifecycle management
- Ollama model management + hardware detection
- Backend lifecycle controller (start/stop/drain/health monitor)

### Managed Inference Backends

Full inference backend lifecycle with hardware-aware recommendations. Shipped across 4 sub-phases (12a-12d).

- **Backends:** Ollama, vLLM, SGLang, remote OpenAI-compatible endpoints
- **Hardware detection:** `detect_hardware.sh` → `data/hardware.json` → Redis sync (db7)
- **Lifecycle:** Start/stop via Docker Compose profiles, drain protocol (set draining → poll inflight → stop old → start new → wait healthy → set ready), health monitor (30s, 3 failures → restart with exponential backoff)
- **Model library:** Backend-aware Models page, HuggingFace catalog search, curated recommendations, VRAM-aware filtering
- **Onboarding wizard:** 6-step first-visit flow (hardware → engine → model → download → ready)
- **GPU monitoring:** nvidia-smi via docker exec, inference performance metrics (`GET /v1/inference/stats`)
- **Dashboard:** Local Inference settings section, GPU stats cards, recommendation banner

### Auth & Security

- API key auth (SHA-256 hashed, `sk-nova-*`) with per-key rate limiting (Redis sliding window)
- Admin-only endpoints, `REQUIRE_AUTH=false` dev bypass
- RBAC: 5 roles (Owner > Admin > Member > Viewer > Guest) with `RoleDep(min_role=...)` FastAPI dependency
- JWT claims with role + tenant_id (backwards-compatible `is_admin`)
- Guest isolation: no tools, no memory, no system context, admin-configured model allowlist
- OpenAI-compatible endpoints for Continue.dev, Cursor, Aider integration
- SSRF protection across all URL-handling services (intel, knowledge, orchestrator)

### Remote Access & Mobile

- Cloudflare Tunnel sidecar (`--profile cloudflare-tunnel`)
- Tailscale sidecar (`--profile tailscale`)
- PWA manifest + service worker (installable to home screen)
- WebSocket auth (API key on `/ws/chat`), CORS lockdown (`CORS_ALLOWED_ORIGINS`)
- HTTPS indicator in NavBar, setup wizard remote access selection

### Platform Hardening

Cross-cutting reliability work shipped across hardening phases:

- Structured JSON logging with async ContextVar correlation (task_id, agent_id) across all services
- Redis connection leak cleanup — every service with `get_redis()` has corresponding `close_redis()` in lifespan shutdown
- MCP tools visible to agents (replaced static `ALL_TOOLS` with `get_all_tools()`)
- Streaming token counts fixed (`stream_options={"include_usage": True}` for subscription providers)
- Reaper race condition fixed (Redis SADD dedup gate before LPUSH, CAS UPDATE in reaper)
- Gateway auto-resolves `OLLAMA_BASE_URL=auto` (probes host, falls back to Docker)
- Consolidation: 7-day review window, young edge protection (<7d immune to decay), mutex, phase isolation
- Ingestion: backpressure (Semaphore(5)), JSON validation before processing
- Model auto-resolution: decomposition/reconstruction/consolidation models default to `auto` with probe fallback
- Graceful shutdown: 15-second timeout for background tasks before cancellation

### Testing

- 150+ integration tests hitting real running services (no mocks)
- 18 test files covering: health, pipeline mechanics/behavior, SSRF, intel, knowledge, RBAC, inference backends, memory, recovery
- Tests create resources with `nova-test-` prefix, clean up via fixture teardown
- `make test` (full suite, ~2 min) / `make test-quick` (health only, ~0.4s)
- Dashboard: `cd dashboard && npm run build` (TypeScript compilation check)

---

## In Progress — Partially Delivered

### Pipeline Performance

Chat latency optimizations and intelligent routing shipped. Deeper pipeline optimizations remain.

**Delivered:**
- Skip tool pre-resolution for interactive chat (~40-50% first-token improvement)
- Auto model detection with quality-ranked preference list and 30s cached resolution
- Intelligent routing with classifier, per-category model maps, SSE metadata, Settings UI
- Ships disabled by default (`llm.intelligent_routing = false`), graceful fallback

**Remaining:**
| Optimization | Expected Impact |
|---|---|
| Prompt caching for Anthropic models (static pipeline system prompts) | 1-5s + 50-90% cost reduction on cached tokens |
| Right-size models per pipeline stage (Context → cheap, Task → best) | 3-8s savings |
| Speculative pipeline execution (overlap Guardrail with late Task Agent) | 3-7s overlap savings |
| Streaming-first chat (eliminate pre-resolution entirely) | Near-instant first token |
| Memory context pre-warming for active sessions (Redis cache, 60s TTL) | 200-500ms per message |
| Stage merging for simple tasks (skip Context Agent, give Task read-only tools) | 5-10s on simple tasks |
| Adaptive stage skipping via complexity classifier | 2-10s on eligible tasks |

Full design spec: `docs/superpowers/specs/2026-03-17-performance-optimization-design.md`

### Dashboard Enhancement

Pod management and core settings done. Advanced pipeline visibility and settings expansion remain.

**Delivered:**
- Pod management page with full CRUD and per-agent configuration
- Model switcher dropdown (persists to localStorage)
- Settings sections: API keys, routing strategy, auth, local inference, GPU stats, model recommendations
- Theme system with presets

**Remaining:**
- Pipeline editor — agents as draggable cards in sequence, click to configure
- Session replay — step through any agent session message-by-message
- Activity feed — real-time SSE event stream of all agent actions
- Review queue — human-in-the-loop approve/reject for escalated tasks
- .env editor — masked inputs for secrets, restart warnings for non-runtime values
- models.yaml editor — add/remove Ollama models for auto-pull
- Provider status panel — per-provider API key present, last call, ping, test button
- Context budget editor — tune system/tools/memory/history/working split
- Log viewer — SSE-streamed log tail, filterable by service and level
- Guardrail findings feed — dedicated view with severity, resolution, context

### Self-Directed Autonomy

Cortex brain loop works. The feedback loop that makes it actually autonomous is missing.

**Delivered:**
- Cortex thinking loop with adaptive timeout
- 5 cognitive drives with priority-based selection
- Goal management with iterations, success criteria, cost tracking
- Budget tracking with tier-based throttling
- Stimulus system for event-driven reactivity
- Scheduler for periodic health checks

**Remaining — Cortex gaps identified by audit:**

| Gap | Impact | Effort |
|---|---|---|
| **No task completion feedback** | Cortex dispatches tasks then never checks results. If task fails, cortex doesn't know. | 1-2 days |
| **Hardcoded outcome scores** | Reports 0.2 (failure) or 0.7 (success) — no actual measurement | 1 day |
| **No goal progress tracking** | `progress` field never updated, always 0.0 | 1 day |
| **No goal decomposition** | Can't break "build a feature" into subtask DAG. One blob per cycle. | 2-3 weeks |
| **Maturation pipeline stub** | Status columns exist but no executor transitions goals through phases | 2-3 days |
| **No learning from failures** | Writes reflections but never reads them back | 1 week |
| **Zero test coverage** | No cortex integration tests | 2 days |

### RBAC & Multi-Tenancy

Role schema and basic enforcement shipped. Full data isolation remains.

**Delivered (Phase 13a):**
- Role/tenant columns on users + invite_codes tables
- Tenants table (single row), audit_log table
- `RoleDep(min_role=...)` FastAPI dependency replacing `AdminDep`
- JWT claims with role + tenant_id
- Guest isolation: no tools, no memory, filtered model access
- User management endpoints + dashboard Users page
- Invite creation with role assignment

**Remaining:**
- `tenant_id` scaffolding on: tasks, memories, api_keys, usage_events
- All data queries scoped by tenant_id + user_id
- Memory service: tenant-scoped embedding retrieval (pgvector filter)
- Redis key namespacing (`tenant:{id}:` prefix)
- Per-user settings (appearance, default model, notifications)
- Role-based nav visibility (Guest sees Chat only, Viewer is read-only)
- Expiry check on every request + Redis deny-list for immediate revocation
- `/invite/{code}` route with registration flow
- Audit logging for role changes, invites, deactivations

Design: `docs/plans/2026-03-08-rbac-invitations-design.md`, `docs/plans/2026-03-10-phase13a-completion-design.md`

### Knowledge Sources Completion

Service is functional. Credential flow and dedup need finishing.

**Remaining:**
- Wire credential retrieval for authenticated crawls (`scheduler.py:111` TODO — encryption infra exists, just needs orchestrator API call to fetch + decrypt)
- Implement actual platform API health checks (call GitHub `/user` with token to verify validity)
- Per-source crawl dedup (track active crawl tasks to prevent duplicate concurrent crawls)
- Connect BuiltinCredentialProvider to the CredentialProvider ABC (make pluggable interface real)
- Future: GitLab, Bitbucket, social media extractors

---

## Priority Backlog

Ordered by dependency and impact on the autonomy vision. Detailed design specs for items marked with `[spec]` are preserved in `docs/roadmap-archive-2026-03.md`.

### ✅ P0: Pipeline Reliability Hardening `[spec]` — Delivered 2026-03-25

**Delivered in commits `f990eb8` (Tier 1) and `d0e30fc` (Tier 2).**

| Fix | Description | Status |
|---|---|---|
| Pydantic output models | `schemas.py` — typed models for all 5 pipeline agents, validated in `think_json()` | ✅ Delivered |
| Schema in retry prompt | `think_json()` retries with full JSON schema definition on validation failure | ✅ Delivered |
| Full stack traces | `traceback` TEXT column on `agent_sessions` (migration 044) | ✅ Delivered |
| Structured error objects | `error_context` JSONB on `tasks`: `{type, message, stage, model, elapsed_ms, retryable}` | ✅ Delivered |
| Always store agent output | `_last_raw_output` captured before raising parse errors, stored in `agent_sessions.output` | ✅ Delivered |
| Task state CAS transitions | `state_machine.py` — `VALID_TRANSITIONS` map, CAS `UPDATE ... WHERE status = $old` | ✅ Delivered |
| Terminal state protection | Terminal states (complete/failed/cancelled) have empty transition sets | ✅ Delivered |
| Structured error classification | `checkpoint.py` — classify by exception type, exponential backoff, old substring matching as fallback | ✅ Delivered |
| Heartbeat failure counter | 3 consecutive failures → `asyncio.Event` cancellation signal → pipeline abort | ✅ Delivered |
| Critical parallel group handling | Guardrail/code_review crash in parallel group now fails pipeline instead of silently continuing | ✅ Delivered |
| Prompt security — XML boundaries | Wrap user input in `<USER_REQUEST>` tags, escape code review feedback | Not yet |
| Checkpoint save retry | 3x retry with backoff before giving up | Not yet |

### 🔄 P0: Platform Self-Introspection `[spec]` — Partially Delivered 2026-03-26

**Diagnosis tools, self-knowledge, and read-only introspection delivered. Write tools and proactive behaviors remain.**

| Component | Description | Status |
|---|---|---|
| **Architecture context block** | `_build_self_knowledge()` in `runner.py` — services, ports, pipeline stages, memory, cortex, diagnostic tool usage instructions injected into chat system prompt. Gated on `NOVA_SELF_KNOWLEDGE` env var. | ✅ Delivered |
| **Task diagnosis tools** | `diagnosis_tools.py` — 5 tools: `diagnose_task`, `check_service_health`, `get_recent_errors`, `get_stage_output`, `get_task_timeline`. Registered in tool catalog under "Diagnosis" group. | ✅ Delivered |
| **Read-only platform tools** | `introspect_tools.py` — 4 tools: `get_platform_config` (namespace filter, secret masking), `list_knowledge_sources` (URLs/status/credentials), `list_mcp_servers` (connection status + tool catalogs), `get_user_profile`. Registered under "Introspect" group. | ✅ Delivered |
| **Write tools with confirmation** | `update_config`, `manage_providers`, `manage_mcp_servers` — preview + "Apply?" prompt | Not yet |
| **Proactive behaviors** | Health monitoring, config suggestions, capability discovery, self-diagnosis on error | Not yet |

Safety: read tools unrestricted, write tools require confirmation, service restarts require explicit approval, all self-modifications audit-logged, no source code modification.

### ✅ P1: Cortex Task Feedback Loop — Delivered 2026-03-25

**Delivered in commit `f990eb8` (Tier 1).**

- ✅ New TRACK phase in thinking cycle (between ACT and REFLECT) — `task_tracker.py` polls orchestrator for task completion
- ✅ Outcome scores based on actual task status: complete=0.8, complete+findings=0.6, failed=0.2, cancelled=0.1, timeout=0.5
- ✅ Goal progress updated based on iteration count vs max_iterations
- ✅ Failed task errors stored in goal `current_plan` metadata for next cycle's LLM planning
- Integration tests for cortex goal lifecycle — not yet
- Read prior reflections before planning — not yet (engrams are written but not explicitly queried back)

### P1: Skills & Rules System `[spec]`

**Why:** Agent extensibility without code changes. Skills = reusable prompt templates shared across agents/pods. Rules = declarative behavior constraints with pre-execution enforcement, complementing the Guardrail Agent.

**Deliverables:**
- `skills` table — name, content (with `{{param}}` placeholders), scope (global/pod/agent), parameters, priority
- `rules` table — rule_text, enforcement (soft/hard/both), pattern (regex), target_tools, action (block/warn/require_approval)
- `resolve_skills(pod_id, agent_id)` — formatted prompt section, 30s cache
- `check_hard_rules(tool_name, args)` — pre-execution enforcement in `execute_tool()`
- 3 seed rules: no-rm-rf (hard/block), workspace-boundary (soft/block), no-secret-in-output (soft/block)
- CRUD endpoints in pipeline_router.py + Skills/Rules dashboard pages

**Effort:** 2-3 weeks

### P2: Nova SDK & CLI `[spec]`

**Why:** External integration layer. Blocks CI/CD automation, scripting, and any non-browser client. Dashboard's `api.ts` duplicates HTTP logic that should live in a typed client.

**Deliverables:**
- `nova-sdk/` — Typed async Python client (httpx), resource modules for every API surface, SSE streaming helper
- `nova-cli/` — Typer + Rich terminal interface: `nova status`, `nova chat`, `nova task submit/list/show/cancel`, `nova pod`, `nova model`, `nova key`, `nova memory`, `nova config`, `nova queue`
- `dashboard/src/types.generated.ts` auto-generated from nova-contracts Pydantic models
- `make types` target for TypeScript generation
- Slim Docker image (`ghcr.io/arialabs/nova-cli:latest`, ~50MB) for CI/CD
- Config profiles (`~/.config/nova/config.toml`) for multiple Nova instances
- `--json` machine-readable output on every command
- TUI (Textual) as follow-up after CLI is stable

**Effort:** 6-8 weeks total

### P2: Browser Automation (Computer Use) `[spec]`

**Why:** Biggest utility gap vs competitors. Nova's agents can read/write files and run shell commands, but can't browse the web or interact with web UIs.

**Architectural decisions (resolved in spec):** CDP Screencast for viewport streaming, watch-only (no user interaction in v1), per-task ephemeral browser instances, Docker Compose profile sidecar.

**Deliverables:**
- Browser container image (Chromium + Playwright), Docker Compose `--profile browser`
- Browser tools: `browser_navigate`, `browser_click`, `browser_type`, `browser_scroll`, `browser_screenshot`, `browser_read_page`, `browser_devtools`, `browser_wait`, `browser_tabs`, `browser_evaluate`
- Vision loop: screenshot → vision model (Claude/GPT-4o) → decide action → execute via CDP → repeat
- Dashboard browser viewer: embedded viewport with CDP Screencast, action log sidebar
- Action recording: structured events as task artifacts, post-task replay

**Effort:** 2-3 weeks

### P3: Additional Chat Platforms

Extend chat-bridge adapter pattern. Each adapter is a module in the existing chat-bridge service.

- **Discord** — `discord.py`, channel-based or DM conversations, Docker Compose profile
- **WhatsApp** — Business API, requires approval
- **Matrix/Element** — self-hosted, privacy-focused
- Built-in chat improvements: conversation history sidebar, image/file upload, voice input (Web Speech API), push notifications (Web Push API)

### P3: Advanced Model Routing

- Vision/multimodal routing — detect images in messages, route to vision-capable models
- Long-context detection — route large contexts to models with higher token limits
- Separate chat vs pipeline model defaults
- Chat onboarding — first-run greeting helps users configure providers through conversation

---

## Future Vision

Brief descriptions only. Implementation deferred until prerequisites complete. Detailed design specs where noted (`[spec]`) are in `docs/roadmap-archive-2026-03.md`.

### MCP Integrations Hub `[spec]`
One-click integration dashboard for self-hosted services and developer tools. `mcp-servers.yaml` config file, auto-discovery on startup, health checks, hot-reload. Priority integrations: Filesystem, Docker, Home Assistant, GitHub, n8n, Brave Search. Bidirectional n8n pattern: n8n handles plumbing, Nova handles intelligence. Devices & Infrastructure dashboard for multi-machine visibility with WoL integration and device-aware inference routing.

### Reactive Event System `[spec]`
Redis Streams event bus with typed events, declarative subscription rules, AI-powered event classification. Cron scheduler with natural language parsing and persistent schedules. Event source adapters: webhook receiver, MQTT/IoT, camera/RTSP, file watcher, API poller, system metrics. Dashboard: event feed, notification center, alert modals, action history. Safety: rate limiting, quiet hours, circuit breakers, confirmation on destructive actions.

### Web IDE & Git Integration `[spec]`
code-server (VS Code in browser) as Docker Compose profile (`--profile ide`). Shares workspace volume with agents — file changes visible instantly. GitHub/GitLab OAuth for clone → branch → work → push → PR workflow. "Open in IDE" buttons on task artifacts. VS Code extension (sidebar, "Ask Nova" command, diff view) as separate distribution.

### Edge Computing `[spec]`
Raspberry Pi deployment profiles based on hardware detection: cloud-only (~800MB RAM, no local models), cloud-first with local memory (~1.2GB), distributed (UI on Pi, compute elsewhere). RDS support for offloading database. Docker Compose overlays per profile.

### Multi-Cloud Deployment `[spec]`
Terraform modules for AWS, DigitalOcean, GCP, Azure, Hetzner. Horizontal scaling of stateless services (orchestrator, gateway, memory-service) behind cloud load balancers. Fixed IPs via Terraform output for service discovery. Docker-based; Kubernetes deferred to SaaS phase.

### SaaS — Nova Cloud `[spec]`
Hosted offering at `nova.arialabs.ai`. Kubernetes deployment (horizontal pod autoscaling, pod disruption budgets), Stripe billing with Free/Pro/Enterprise tiers, email registration + OAuth, GDPR compliance (data export, deletion, cookie consent). Same codebase as self-hosted, gated by `NOVA_SAAS=true`. Prerequisites: managed inference (done) + multi-tenancy (in progress). Estimated infrastructure cost: ~$112/month base, break-even at ~9 Pro subscribers.

### Full Autonomous Loop
Planning Agent reads prior episode memory for proven approaches. Goal similarity matching seeds new plans from past successes. Structured `lessons_learned` engrams written after every goal. Long-horizon goals spanning multiple sessions. Self-assessment across goal history.

### Supernova — Structured Workflow Engine `[spec]`
Evaluate whether Nova should adopt structured development workflows (planning, TDD, systematic debugging, verification gates) as native orchestration-level capability vs prompt-level discipline. Two paths: adopt existing prompt-based workflows, or build native state-machine workflow engine integrating with cortex and engrams.

### Multi-Device Gateway Network
Distributed Nova instances sharing one memory backend via Tailscale. Per-device LLM routing config (Beelink: cloud-first, Dell: local-only, laptop: cloud-first + remote Ollama). WoL integration for on-demand GPU inference.

### Domain Restructuring
`arialabs.ai` as company website (landing + Nova product pages + docs at `/nova/docs/`). `nova.arialabs.ai` as private live instance behind Cloudflare Access with email auth. Docs migration with redirects from current URLs.

### Hierarchical Memory Transformer
Small fine-tuned transformer (~7B) that learns to BE the memory system — compression, storage, retrieval, reconstruction end-to-end. Replaces template reconstruction and potentially the Neural Router. High risk, high reward. Requires months of Engram Network operation for training data.

### Nova Browser — AI-Native Browsing
Privacy-first, AI-native browser experience integrated into Nova. Not a browser with AI bolted on — an AI platform where browsing is a first-class capability. Zero telemetry, no logging. Nova's agents can navigate sites, click, inspect network traffic, debug frontend, screenshot, and record sessions natively.

**Open architectural question (revisit post-platform-completion):**
- **Desktop app + embedded browser pane** — Electron/Tauri, browser as a tab/pane within Nova. Lightest lift, but users still need a separate daily browser.
- **Full Chromium shell** — Nova IS the browser (like Arc/Brave). Most ambitious, most differentiated, highest maintenance burden.
- **Split-pane hybrid** — Nova panels + browser side by side in one window. AI sees what you see in real time. No context switching.

Key capabilities: page annotation/highlighting, network inspector with AI analysis, DOM-aware AI assistance, session recording/replay, agent-driven browsing (user watches or takes over), built-in tracker/ad blocking. Supersedes the P2 Browser Automation (Computer Use) roadmap item — that becomes a subset of this vision.

Prerequisites: all current roadmap items complete. This is the capstone feature.

---

## Platform Review Findings (2026-03-26)

Comprehensive 5-discipline review (architecture, backend, frontend, security, testing). Full spec with per-finding remediation: `docs/specs/2026-03-26-platform-review-findings.md`.

### P0 — Fix immediately
| ID | Finding | Effort |
|---|---|---|
| SEC-2 | Reindex endpoint missing auth — unauthenticated DoS vector | 10 min |
| SEC-3 | SSRF in `web_fetch` tool — no URL validation, follows redirects into internal network | 30 min |
| SEC-4 | Trusted proxy header forgeable — IP spoofing bypasses auth | 1 hour |
| ARCH-4 | Embedding cache serves stale vectors from wrong model (no model filter on L2 lookup) | 30 min |
| BE-1 | MCP registry `_active_clients` dict mutated without lock — race on hot-reload | 30 min |

### P1 — Fix this week
| ID | Finding | Effort |
|---|---|---|
| SEC-1 | `REQUIRE_AUTH` defaults to false — all APIs open on fresh deploy | 15 min |
| SEC-7 | WebSocket no connection limit — DoS via connection flood | 2 hours |
| ARCH-1 | Dead letter queue unbounded — no TTL, cap, or alerting | 1 hour |
| ARCH-2 | Non-atomic SADD+LPUSH in enqueue_task — duplicate queue entries | 1 hour |
| ARCH-6 | Ingestion semaphore held over full process — effectively serial despite Semaphore(5) | 2 hours |
| BE-2 | Dead `pass` block in validate_invite — misleading dead code | 30 min |
| BE-3 | N+1 queries in list_recommendations — 60 queries per request | 30 min |
| BE-4 | Auth security bypasses (deny-list/expiry) logged at nothing | 30 min |
| FE-1 | Conversation delete fires immediately — no confirmation, permanent data loss | 30 min |
| FE-2 | API key save failure silent — user thinks key was saved | 15 min |
| FE-3 | Service restart failure silently swallowed — operator doesn't know it failed | 15 min |

### P2 — Fix this sprint
| ID | Finding | Effort |
|---|---|---|
| ARCH-3 | `working_memory_slots` never cleaned up — unbounded growth | 2 hours |
| ARCH-5 | `intel:new_items` queue written but never consumed — dead code | 1 hour |
| ARCH-7 | Orphaned comments/engram references after parent deletion | 2 hours |
| SEC-5 | Google OAuth bypasses invite-only registration | 1 hour |
| SEC-6 | No rate limiting on login/register — brute force possible | 2 hours |
| FE-4 | Modal missing `role="dialog"`, focus trap — accessibility gap across all dialogs | 2 hours |
| FE-6 | MCP reload spinner shared across all server cards | 15 min |
| FE-7 | Role change fires immediately — no confirmation on privilege change | 30 min |
| TEST-1 | No memory/engram tests — zero coverage of the central memory system | 4 hours |
| TEST-2 | No MCP server CRUD or introspect tool tests | 2 hours |
| TEST-3 | No JWT auth flow tests — login/register/refresh untested | 3 hours |

### P3 — Next cycle
| ID | Finding | Effort |
|---|---|---|
| ARCH-8 | `usage_events` and `messages` tables need partition strategy | 1 day |
| SEC-8 | Auto-generate admin secret at setup | 2 hours |
| FE-5 | Chat input accessibility (send button, textarea labels) | 1 hour |
| TEST-4 | Cortex integration tests (zero coverage) | 4 hours |
| TEST-5 | Fix weak/fake test patterns (artifacts no-op, soft asserts, hardcoded skips) | 3 hours |
| TEST-6 | Test isolation fixes (bulk delete pollution, state leaks, hardcoded URLs) | 2 hours |

---

## Known Gaps & Deferred Work

### Active Technical Debt

**Pipeline — resolved (2026-03-25):**
- ~~Agent output schemas not validated~~ — Pydantic models for all 5 stages, validated in `think_json()` (`schemas.py`)
- ~~Error context destroyed on failure~~ — stack traces, LLM messages, structured error_context JSONB preserved (migration 044)
- ~~Task state machine unvalidated~~ — CAS transitions via `state_machine.py`, terminal state protection
- ~~Recovery strategy uses substring matching~~ — structured error classification by type, exponential backoff, substring matching as fallback
- ~~Heartbeat loop swallows all exceptions~~ — failure counter, asyncio.Event cancellation after 3 failures
- ~~Parallel group exceptions silently dropped~~ — critical agents (guardrail, code_review) now fail pipeline on crash

**Pipeline — remaining:**
- Prompt injection in pipeline — user input interpolated directly into agent prompts (XML boundaries not yet added)
- Checkpoint save retry — not yet implemented

**Infrastructure:**
- No circuit breaker for LLM providers — failed providers not routed around
- DB connection pool has no idle validation — stale connections after Postgres restarts undetected
- Admin secret default (`nova-admin-secret-change-me`) accepted without warning in production
- Dead letter queue grows unbounded — no TTL, no cleanup, no archival
- Episodic memory partitions hardcoded through 2026-04 — need auto-creation

**Cortex — partially resolved (2026-03-25):**
- Zero test coverage — no integration tests for goals, drives, or thinking loop
- ~~Dispatches tasks without checking results~~ — TRACK phase polls orchestrator, reads results
- ~~Hardcoded outcome scores~~ — actual measurement based on task status (0.8/0.6/0.2/0.1/0.5)
- ~~`progress` field never updated~~ — updated based on iteration count vs max_iterations

### Deferred Features

| Feature | Notes |
|---|---|
| **Sandbox tiers** | Only `workspace` active. `isolated` (ephemeral container), `nova` (self-config), `host` (unrestricted) designed but not implemented. `shell_sandbox` config field exists but not read by tool code. |
| **End-to-end tool testing** | list_dir, read_file, write_file, run_shell, search_codebase, git workflow, path traversal, denylist — not yet validated with integration tests |
| **Post-pipeline agents** | Documentation, Diagramming, Security Review, Memory Extraction agents designed in Quartet spec but not built |
| **Default pods** | Quick Reply, Research, Code Generation, Analysis designed but only Quartet shipped |
| **ClaudeCode provider** | Spawn `claude -p` subprocess for zero API cost via Claude Max subscription. Designed, not implemented. |
| **Web Push notifications** | Task completion push via PWA service worker |
| **Key-level model restrictions** | `sk-nova-*` keys scoped to specific providers |
| **Multi-model A/B testing** | Run two models on same subtask, Evaluation Agent picks better output |
| **Collaborative goals** | Multiple users contributing context to shared goals (requires multi-tenancy + SaaS) |

---

## Competitive Landscape

> Updated 2026-03-25. Sourced from analysis of OpenClaw, CrewAI, LangGraph, OpenHands, AutoGPT, BabyAGI, smolagents, and the OpenAI Agents SDK.

### What Nova Has That Others Don't

| Capability | Description |
|---|---|
| **Engram Network** | Graph-based cognitive memory with spreading activation, consolidation cycles, entity resolution, contradiction detection, and neural re-ranker. Far ahead of any competitor's memory system. |
| **Quartet Pipeline** | 5-stage safety chain with guardrails on every task. Most platforms have no built-in safety. |
| **Cortex** | Autonomous brain with goals, 5 cognitive drives, budget tracking. No competitor has a comparable self-directed planning layer. |
| **Knowledge Acquisition** | Intel-worker + knowledge-worker for autonomous information gathering. Unique capability. |
| **Multi-provider routing** | 27+ providers including zero-cost subscription-based, with local/cloud strategies and intelligent classification. |
| **Recovery service** | Dedicated backup/restore that survives other service failures. |
| **Full admin dashboard** | 20-page production React UI with chat, tasks, memory graph, goal management, inference management. |

### Where Nova Lags

| Gap | Competitor Reference | Nova's Path |
|---|---|---|
| Self-awareness | OpenClaw: `openclaw doctor` + self-inspection | P0: Self-Introspection |
| Pipeline reliability | Unvalidated outputs, lost error context | P0: Pipeline Reliability |
| Browser automation | OpenClaw: CDP Chromium for autonomous web browsing | P2: Computer Use |
| Skill ecosystem | OpenClaw: 13,700+ community skills via ClawHub | P1: Skills & Rules |
| Messaging platforms | OpenClaw: 20+ platforms vs Nova's 2 | P3: Chat Platforms |
| Onboarding simplicity | `openclaw onboard --install-daemon` (single command) | P2: Nova CLI |
| Mobile/device integration | OpenClaw: iOS, Android, macOS native apps | Future |
| Voice I/O | OpenClaw: wake words, ElevenLabs TTS | Future |
| Agent-rendered UI | OpenClaw: Live Canvas interactive workspaces | Future |

### Key Takeaway

Nova doesn't need to replicate OpenClaw's breadth. The priority focus:
1. **Pipeline reliability** — autonomous operation must be trustworthy
2. **Self-awareness** — agents that can't diagnose themselves can't direct themselves
3. **Skill ecosystem** — extensibility without code changes

Those three close the biggest capability gap. Nova's cognitive architecture (engrams, cortex, quartet safety) is genuinely ahead — the gap is in utility and reliability, not intelligence.

### Market Context

- AI agent market: $7.84B (2025) → projected $52.62B by 2030 (46.3% CAGR)
- MCP becoming standard for tool integration — adopted by OpenAI, Anthropic, Cursor, Replit, VS Code
- Guardrails becoming legally mandatory (California SB 243/AB 489, Singapore Model AI Governance) — Nova's built-in Guardrail Agent is a competitive advantage
- Key research: Andrew Ng agentic patterns (GPT-3.5+agentic 95.1% vs GPT-4 zero-shot 67.0%), Anthropic "Building Effective Agents", CodeAct (code as action space, 20%+ improvement)

---

## Reference

### Key Design Specs (in archive)

| Topic | Archive Section |
|---|---|
| Pipeline reliability fixes | Phase 4c |
| Skills & Rules system (schema, API, integration) | Phase 5c |
| Nova SDK, CLI, TUI (full command tree, examples) | Phase 6c |
| Self-introspection tools and safety | Phase 7a |
| Supernova workflow engine evaluation | Phase 7b |
| MCP integrations hub (homelab, dev, infra) | Phase 8b |
| Browser automation (computer use) architecture | Phase 9 |
| Reactive event system | Phase 9a |
| Web IDE & git integration | Phase 9b |
| Edge computing deployment profiles | Phase 10 |
| Multi-cloud Terraform modules | Phase 11 |
| SaaS architecture and billing | Phase 14 |

### Research References

- Anthropic, "Building Effective Agents" — anthropic.com/research/building-effective-agents
- Andrew Ng agentic design patterns — GPT-3.5+agentic (95.1%) vs GPT-4 zero-shot (67.0%)
- CodeAct — arxiv.org/abs/2402.01030 (code as unified action space, ICML 2024)
- ReAct — arxiv.org/abs/2210.03629 (reasoning + acting)
- "Agents That Matter" — arxiv.org/abs/2407.01502 (cost-accuracy tradeoff)
- Generative Agents — arxiv.org/abs/2304.03442 (memory + reflection)
- Voyager — arxiv.org/abs/2305.16291 (skill library + self-verification)
