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

### Phase 6 — Memory Overhaul

The memory system is the connective tissue for self-direction. The Planning Agent (Phase 7) depends on it.

**Three-tier architecture:**

| Tier | Store | Purpose |
|---|---|---|
| Session | Redis | Active context window, tool results, turn history |
| Structured | PostgreSQL | Facts (key-value + confidence), episodes (task summaries + lessons), project context |
| Semantic | pgvector | Embedding similarity search |

**Key deliverables:**

1. **Hybrid retrieval** — `70% cosine_similarity + 30% ts_rank` (full-text). Fixes pure vector search on exact keyword lookups. All inside PostgreSQL.
2. **ACT-R confidence decay** — `effective_confidence = base_confidence × (days_since_last_access ^ -0.5)`. Prevents stale info from contaminating planner context.
3. **`save_fact()` upsert** — `ON CONFLICT DO UPDATE` keyed on `(project_id, category, key)`. No duplicate facts across sessions.
4. **Embedding fallback chain** — `text-embedding-3-small` → Ollama `nomic-embed-text` (zero-pad 768→1536 dims).
5. **Memory Compaction Pipeline** — nightly asyncio task reads recent episodes from memory-service, runs a compaction LLM call, upserts distilled facts back.
6. **Memory Inspector** dashboard page — browse facts, episodes, project context; manually flag or delete stale entries.

---

## Future Phases

### Phase 7 — Self-Directed Autonomy (Goal Layer + Planning + Evaluation)

**This is the goal the entire platform is built toward.** User defines a goal; Nova works toward it autonomously.

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

## Known Gaps & Deferred Work

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

---

## Findings & Notes

- Migrations use pure SQL (no Alembic) — run idempotently at orchestrator startup
- Redis DB allocation: orchestrator=2, llm-gateway=1, chat-api=3, memory-service=0
- Context budget split: system 10%, tools 15%, memory 40%, history 20%, working 15%
- Reaper timeout: 150s no heartbeat = stale agent
- Task heartbeat: every 30s; tasks expire in Redis after 24h
- `REQUIRE_AUTH=false` bypasses API key validation for development
