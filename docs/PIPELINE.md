# Nova AI Platform — Product Pipeline

> Living document. Keep up to date as work progresses.
>
> **Last updated:** 2026-02-27

---

## Completed Work

### Phase 1 — Core Platform ✅

Seven containerized microservices communicating over HTTP. Multi-turn agent loop with tool use, streaming responses (SSE + WebSocket), pluggable tool system, `nova_context` injected into every agent's system prompt, `models.yaml` as single source of truth for 39 model IDs across 9 providers.

### Phase 2 — Auth, Billing & IDE Integration ✅

- API key auth (SHA-256 hashed, `sk-nova-*` format) with per-key rate limiting (Redis sliding window)
- PostgreSQL `api_keys` + `usage_events` tables
- Token counting + cost tracking via `LiteLLM.completion_cost`
- Fire-and-forget usage logging
- OpenAI-compatible endpoint (`/v1/chat/completions`, `/v1/models`)
- IDE integration: Continue.dev, Cursor, Aider

### Phase 3 — Code & Terminal Tools ✅

- Workspace-scoped file I/O: `list_dir`, `read_file`, `write_file`
- `run_shell` — subprocess with timeout + denylist
- `search_codebase` — ripgrep, falls back to Python regex
- Git tools: `git_status`, `git_diff`, `git_log`, `git_commit`
- Path traversal protection, Docker workspace volume mount

### Phase 4 — Quartet Pipeline + Async Queue ✅

- **Quartet Pipeline:** Context → Task → Guardrail → Code Review → Decision agents
- **Redis task queue:** BRPOP async dispatch, 11-state machine, cancel support
- **Database migrations (001–005):** base schema, phase4 tables (pods, pod_agents, tasks, agent_sessions, guardrail_findings, code_reviews, artifacts, audit_log), fallback models + default prompts, MCP servers, platform config
- **Pipeline executor:** runs stages in order, respects model overrides per pod agent
- **Stale agent reaper:** background asyncio cleanup (>150s no heartbeat)

### Phase 5/5b — Dashboard ✅

9 pages: Overview, Tasks, Pods, Usage, Keys, Models, Chat, MCP, Settings. Built with Vite + React + TypeScript + Tailwind + TanStack Query + Recharts. Streaming chat with session continuity, pod management with per-agent advanced config, live task state machine, MCP server management.

### MCP Integration ✅

StdioMCPClient (JSON-RPC 2.0 over subprocess stdin/stdout). Tools namespaced as `mcp__{server_name}__{tool_name}`. Loaded at startup, stopped on shutdown.

### Platform Config / Persona ✅

`platform_config` table stores typed JSONB values. Nova persona appended to every agent context. Editable live in Settings without restart.

---

## Current Pipeline

*Nothing currently in progress.*

---

## Next Up

### Phase 5.5 — Hardening

Inserted based on competitive review. Building forward without a safety net (no tests, no observability) is the biggest risk to the platform. This phase addresses operational maturity before adding memory complexity.

1. **Test foundation** — pytest fixtures for orchestrator + memory-service; integration tests for pipeline execution, memory retrieval, auth
2. **Fix streaming token counts** — `orchestrator/app/agents/runner.py` returns 0 tokens for streaming responses; accumulate chunks or use LLM gateway response headers
3. **Fix reaper race condition** — `orchestrator/app/reaper.py` has TOCTOU race between UPDATE and enqueue_task; use Redis Lua script for atomic requeue
4. **Structured JSON logging** — across all services (replace unstructured string logs)
5. **Embedding cache activation** — wire up existing `embedding_cache` table in `memory-service/app/embedding.py` (table exists in schema but is never queried)
6. **Working memory cleanup job** — background task deleting expired rows from `working_memories` (expires_at column exists but nothing enforces it)

### Phase 6 — Memory Overhaul

The memory system is the connective tissue for self-direction. The Planning Agent (Phase 7) depends on it.

**Already built (not in scope):**
- 4-tier memory schema (working/episodic/semantic/procedural) — `memory-service/app/db/schema.sql`
- Hybrid RRF retrieval engine (70% vector + 30% keyword) — `memory-service/app/retrieval.py`
- HNSW indexes, tsvector GIN indexes, monthly partitioning for episodic table

**Remaining deliverables:**
1. **ACT-R confidence decay** — `effective_confidence = base_confidence × (days_since_last_access ^ -0.5)`. Prevents stale info from contaminating planner context.
2. **`save_fact()` upsert** — `ON CONFLICT DO UPDATE` keyed on `(project_id, category, key)`. No duplicate facts across sessions.
3. **Memory Compaction Pipeline** — background asyncio task reads recent episodes, runs a compaction LLM call, upserts distilled semantic facts.
4. **Automatic partition creation** — episodic partitions are hardcoded through 2026-04; need a startup hook or background job to create future partitions.
5. **Embedding fallback chain** — `text-embedding-3-small` → Ollama `nomic-embed-text` (zero-pad 768→1536 dims).
6. **Memory Inspector** dashboard page — browse facts, episodes, project context; manually flag or delete stale entries.

---

## Future Phases

### Phase 7 — Self-Directed Autonomy (Goal Layer + Planning + Evaluation)

**This is the goal the entire platform is built toward.** User defines a goal; Nova works toward it autonomously.

**Prerequisites:** Tool sandboxing must be improved before agents run unsupervised.

**New components:**

| Component | Description |
|---|---|
| Goal Store | PostgreSQL `goals` table — status, progress %, current subtask, iteration count, cost so far |
| Planning Agent | Takes goal + memory + codebase state → ordered subtask list. Re-plans after every Evaluation report |
| Evaluation Agent | Assesses whether a subtask advanced the goal, determines next action, writes memory |
| Loop Controller | Orchestrates Planning → Queue → Quartet → Evaluation cycle. Enforces budget/iteration limits. Triggers human escalation |
| Goal Dashboard page | Submit goals, watch loop progress, inspect planner's current plan, see evaluation history |

**Safety mechanisms:** budget limit per goal, iteration limit with escalation, guardrail agent on every subtask, evaluation agent verifies genuine progress, human review queue as escalation point.

### Phase 8 — Full Autonomous Loop + Reinforcement

Self-direction v2: Nova learns from its own history.

- Planning Agent reads prior episode memory to avoid repeating mistakes
- Evaluation Agent produces structured `lessons_learned` written to memory after every goal
- Goal similarity matching — new goals start from proven prior approaches
- Long-horizon goals spanning multiple sessions, surviving restarts
- Self-assessment across goals to surface patterns

### Phase 9 — Infrastructure + Triggers + Computer Use

**Infrastructure hardening:**
- Periodic Reaper replacing startup-only stale recovery
- Docker Compose profiles (`--profile mac`, `--profile gpu`, `--profile cpu`)
- Webhook system — outbound POST on task/goal lifecycle events with retry queue

**Triggered execution (Autonomy Level 3):**
- Inbound webhooks — e.g. GitHub PR opened → auto-review
- Cron scheduling — "run a security audit every Monday at 9am"
- Event subscriptions — watch file paths, Slack channels, email inboxes

**Computer Use:**
- Screenshot capture + vision model routing
- Mouse/keyboard event dispatch
- Sandboxed Playwright browser
- Action replay / audit log

---

## Competitive Insights — Features to Adopt

Sourced from analysis of OpenClaw, IronClaw, PicoClaw, NanoClaw, CrewAI, LangGraph, MetaGPT, OpenHands, AutoGPT, BabyAGI, and the OpenAI Agents SDK.

| Feature | Inspiration | Description | Target Phase |
|---|---|---|---|
| **Tool sandboxing** | IronClaw (WASM), NanoClaw (containers) | Docker-in-Docker or gVisor for `run_shell`; agents running unsupervised need containment | Before Phase 7 |
| **Graph-based execution / DAG** | LangGraph | Implement `parallel_group` support in pipeline executor for parallel stages (field exists in schema, executor ignores it) | Phase 6 or 7 |
| **Agent Swarms / dynamic teams** | NanoClaw | Allow dynamic agent composition instead of fixed pipeline order; agents can recruit specialists mid-task | Phase 7+ |
| **Agent handoff protocol** | OpenAI Swarm/Agents SDK | Let agents dynamically delegate to other agents mid-task instead of fixed sequential pipeline | Phase 7+ |
| **Execution cost estimation** | CrewAI Enterprise | Predict token cost before running a task; enforce real-time budget caps, not just post-hoc tracking | Phase 7 |
| **Replay/debug mode** | LangGraph | Expose pipeline checkpoints in dashboard for step-by-step inspection of completed tasks | Phase 6 |
| **HTTP MCP transport** | Ecosystem trend | Add HTTP/SSE transport alongside existing stdio; enables remote MCP servers | Phase 6 |
| **Outbound webhooks** | CrewAI | POST on task lifecycle events (completed, failed, escalated); pull forward from Phase 9 | Phase 6 or 7 |
| **Priority queue** | LangGraph | Redis sorted set for task priority levels; high-priority tasks shouldn't wait behind batch jobs | Phase 5.5 or 6 |
| **OpenTelemetry tracing** | LangGraph, CrewAI | Distributed tracing across all 5 services for task lifecycle observability | Phase 5.5 |

---

## Known Gaps & Deferred Work

### Bugs & Technical Debt

- **Streaming token counts broken** — `orchestrator/app/agents/runner.py` returns 0 tokens for streaming responses; usage tracking is broken for the primary interaction mode
- **Reaper race condition** — `orchestrator/app/reaper.py` TOCTOU between UPDATE and enqueue_task can cause double-queuing
- **No circuit breaker for LLM providers** — if a provider is down, requests fail immediately instead of routing to fallback
- **DB connection pool has no idle validation** — stale connections after Postgres restarts aren't detected
- **Admin secret default not rejected in production** — `nova-admin-secret-change-me` is accepted without warning
- **`parallel_group` field exists but is ignored** — pipeline executor runs everything sequentially regardless
- **Contracts not enforced** — `nova-contracts` Pydantic models exist but aren't validated at service boundaries; agent responses are unchecked dicts
- **Embedding cache unused** — `embedding_cache` table exists in memory-service schema but is never queried or written to

### Phase 3 — End-to-End Tool Testing (deferred)

Not yet validated with integration tests:
1. `list_dir` root — confirm it sees actual files
2. `read_file` — confirm content + truncation behavior
3. `write_file` — verify changes appear on host filesystem
4. `run_shell` — confirm stdout/stderr capture and timeout kill
5. `search_codebase` — confirm file + line number results
6. Git workflow: `git_status` → change → `git_commit` → verify in `git log`
7. Path traversal: `../../etc/passwd` → confirm rejected
8. Denylist: `sudo ls` → confirm blocked

### Phase 3b — Docker sandbox mode for `run_shell` (currently host mode only)

### VS Code Extension (deferred)

Sidebar panel, "Ask Nova" command, diff view. Mentioned in Phase 3b.

---

## Icebox / Ideas

- **Capability-based YAML routing** — formalize model requirements per agent role in config
- **Telegram / mobile client** — conversational interface
- **Textual TUI** — terminal UI for goal submission and activity feed
- **Key-level model restrictions** — `sk-nova-*` keys scoped to specific providers
- **Multi-model A/B testing** — two models on same subtask, Evaluation Agent picks better output
- **Self-hosted Ollama parity** — full tool support for local models
- **Collaborative goals** — multiple users contributing context to a shared goal
- **ClaudeCode provider** — spawn `claude -p` subprocess using Claude Max subscription for zero API cost per call (designed in Phase 4, not yet implemented)
- **Post-pipeline agents** — Documentation Agent, Diagramming Agent, Security Review Agent, Memory Extraction Agent (designed, not built)
- **Default pods** — Quick Reply, Research, Code Generation, Analysis (designed in Phase 4, only Quartet default shipped)
- **Skills framework** (from NanoClaw) — modular instruction sets stored as files, loaded per-task context

---

## Competitive Landscape Summary

### What Nova Has That Others Don't

- **Quartet pipeline with safety rails on every task** — most platforms have no built-in guardrail or code review step
- **9-provider LLM routing** including subscription-based (Claude Max, ChatGPT) for zero API cost
- **Full admin dashboard** — most open-source platforms are CLI-only
- **Hybrid RRF retrieval** — more sophisticated than the pure-vector approach used by competitors
- **4-tier memory schema** — working/episodic/semantic/procedural with proper indexes
- **MCP integration** — ahead of most; only NanoClaw and OpenAI Agents SDK have this

### Where Nova Lags

- **Testing** — zero tests vs. mature test suites in all major platforms
- **Observability** — no structured logging, tracing, or metrics vs. LangGraph's built-in tracing
- **Tool sandboxing** — host execution vs. IronClaw's WASM and NanoClaw's container isolation
- **Dynamic agent composition** — fixed pipeline vs. NanoClaw's Agent Swarms and CrewAI's dynamic crews
- **Edge deployment** — Docker-only vs. PicoClaw's 10MB footprint on RISC-V

---

## Findings & Notes

- Migrations use pure SQL (no Alembic) — run idempotently at orchestrator startup
- Redis DB allocation: orchestrator=2, llm-gateway=1, chat-api=3, memory-service=0
- Context budget split: system 10%, tools 15%, memory 40%, history 20%, working 15%
- Reaper timeout: 150s no heartbeat = stale agent
- Task heartbeat: every 30s; tasks expire in Redis after 24h
- `REQUIRE_AUTH=false` bypasses API key validation for development
- Memory service hybrid retrieval (RRF) is already implemented — was listed as Phase 6 but is done
- Episodic partitions are hardcoded through 2026-04; need auto-creation
- `parallel_group` DB field exists but executor runs everything sequentially
- AI agent market: $7.84B in 2025, projected $52.62B by 2030 (46.3% CAGR)
- MCP (Model Context Protocol) is becoming the standard for tool integration — adopted by OpenAI, Anthropic, Cursor, Replit, VS Code
- Guardrails are mandatory in 2026 (California SB 243/AB 489, Singapore Model AI Governance Framework) — Nova's built-in Guardrail Agent is a competitive advantage
