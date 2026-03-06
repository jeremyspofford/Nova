# Nova AI Platform — Roadmap

> Living document. Keep up to date as work progresses.
>
> **Last updated:** 2026-03-06
>
> **Vision:** A self-directed autonomous AI platform. You define a goal. Nova breaks it into
> subtasks, executes them through a coordinated pipeline of specialized agents with built-in
> safety rails, evaluates its own progress, re-plans as needed, and completes the goal — with
> minimal human intervention except when it genuinely needs a decision.
>
> Every phase below is a step toward that. Nothing is throwaway.

---

## Autonomy Levels

| Level | Description | Target Phase |
|---|---|---|
| **1 — Pipeline autonomy** | Quartet runs all 4 agents without human input. Escalates only on critical flags. | ✅ Designed (Phase 4) |
| **2 — Async execution** | Tasks run in the background. Submit and come back. Push notification on complete. | 🔜 Phase 4 |
| **3 — Triggered execution** | Tasks start from external events — git push, cron, webhook, Slack. | 🔜 Phase 9 |
| **4 — Self-directed** | Nova breaks goals into subtasks, executes them, evaluates results, re-plans, loops to completion. **This is the goal.** | 🔜 Phase 7 |

---

## ✅ Phase 1 — Core Platform

The foundation: seven containerised microservices communicating over HTTP.

| Service | Port | Role |
|---|---|---|
| LLM Gateway | 8001 | Model routing, provider abstraction, cost metadata |
| Orchestrator | 8000 | Agent lifecycle, tool dispatch, session state |
| Chat API | 8002 | WebSocket streaming, conversation history |
| Memory Service | 8003 | Embedding + semantic retrieval (ChromaDB) |
| Tool Registry | 8004 | Tool registration, schema validation |
| Model Registry | 8005 | Model metadata, provider mapping |
| Redis | 6379 | Agent state store, rate-limit counters |

**Delivered:**
- Multi-turn agent loop with tool use
- Streaming responses via SSE and WebSocket
- Pluggable tool system via Tool Registry
- `nova_context` injected into every agent's system prompt
- `models.yaml` — single source of truth for 39 registered model IDs

---

## ✅ Phase 2 — Auth, Billing & IDE Integration

| Feature | Status |
|---|---|
| API key auth (SHA-256 hashed, `sk-nova-*` format) | ✅ |
| Per-key rate limiting (Redis sliding window, RPM) | ✅ |
| `REQUIRE_AUTH=false` dev bypass | ✅ |
| Admin-only endpoints (key mgmt, usage reports) | ✅ |
| PostgreSQL — `api_keys` + `usage_events` tables | ✅ |
| Token counting + cost tracking (`LiteLLM.completion_cost`) | ✅ |
| Fire-and-forget usage logging (`asyncio.create_task`) | ✅ |
| OpenAI-compatible endpoint (`/v1/chat/completions`, `/v1/models`) | ✅ |
| Continue.dev / Cursor / Aider integration | ✅ |

---

## ✅ Phase 3 — Code & Terminal Tools

| Feature | Status |
|---|---|
| `list_dir`, `read_file`, `write_file` — workspace-scoped file I/O | ✅ |
| `run_shell` — subprocess execution with timeout + denylist | ✅ |
| `search_codebase` — ripgrep search, falls back to Python regex | ✅ |
| `git_status` / `git_diff` / `git_log` / `git_commit` | ✅ |
| Path traversal protection | ✅ |
| Docker workspace volume mount (`NOVA_WORKSPACE` → `/workspace`) | ✅ |

### ⏳ Needs End-to-End Testing (deferred)

1. `list_dir` root — confirm it sees actual files
2. `read_file` a source file — confirm content, truncation
3. `write_file` a change — verify it appears on host filesystem
4. `run_shell` test suite — confirm stdout/stderr capture and timeout kill
5. `search_codebase` for a function name — confirm file + line number
6. Git repo: `git_status` → change → `git_commit` → confirm in `git log`
7. Path traversal: `../../etc/passwd` → confirm rejected
8. Denylist: `sudo ls` → confirm blocked

**Phase 3b (after testing passes):**

### Phase 3b — Sandbox Tiers

Four named access levels for agent tool execution. Configured per-pod in the pod configuration (Phase 4). Ordered by escalating trust: isolated → nova → workspace → host.

| Tier | Config value | Filesystem access | Shell execution | Use case |
|------|-------------|-------------------|-----------------|----------|
| **Isolated** | `sandbox=isolated` | None — no mounts, ephemeral only | Ephemeral container per invocation (Docker or gVisor) | Pure computation, API calls, text tasks with no persistence needed |
| **Nova** | `sandbox=nova` | Nova installation directory mounted at `/nova` (config, prompts, models.yaml, .env) | In orchestrator container, path-constrained to `/nova` | Self-configuration — Nova updates its own settings, system prompts, and pod definitions |
| **Workspace** *(default)* | `sandbox=workspace` | Scoped to `NOVA_WORKSPACE` mounted at `/workspace` | In orchestrator container, path-constrained | Coding projects, file generation, working on a user-specified directory |
| **Host** | `sandbox=host` | Full host filesystem | Unrestricted subprocess in orchestrator container | DevOps, infra, system administration — explicit opt-in only |

**Current state:** Only `workspace` mode is functional. `run_shell` always executes in the orchestrator container. The `shell_sandbox` config field exists in `config.py` but is not yet read by the tool code.

**Implementation notes:**
- `isolated` requires spinning an ephemeral container per `run_shell` call — needs Docker socket or gVisor; Docker-in-Docker is fragile. gVisor preferred.
- `nova` tier mounts the Nova install directory (parent of `docker-compose.yml`) read-write at `/nova`. Path validation must reject traversal outside `/nova`. This tier enables conversational self-configuration but carries risk: a poorly-prompted agent could corrupt its own guardrails or `.env`. Dashboard should warn on save (same as `host`). A future hardening step could make `.env` and guardrail system prompts read-only within this tier, with writes only via a validated config API.
- `host` should require explicit confirmation in the dashboard UI before a pod can be saved with this tier — it is effectively unrestricted.
- Network isolation is a separate axis from filesystem isolation and should be addressed independently.
- The `NOVA_WORKSPACE` footgun: currently accepts any path including `/` or `~`. Should validate that workspace tier paths are not system roots.

- VS Code extension — sidebar panel, "Ask Nova" command, diff view

---

## ✅ Phase 5 — Dashboard (MVP)

Built with Vite + React + Tailwind + TanStack Query + recharts.

| Page | Status |
|---|---|
| **Overview** — live agent cards, auto-polls 5s | ✅ |
| **Usage** — monthly / weekly / daily / by-model charts with sort toggle | ✅ |
| **Keys** — create/revoke API keys, one-time reveal with copy | ✅ |
| **Models** — 39 models grouped by provider | ✅ |

---

## 🔜 Phase 4 — Quartet Pipeline + Async Queue + ClaudeCode Provider

> The execution foundation everything above sits on.
> Self-directed operation will trigger dozens of pipeline runs per goal —
> the ClaudeCode provider (subscription auth, zero API cost) is included here
> because autonomous operation without it will be expensive.

### A. Quartet Pipeline

The four-agent pipeline that executes every subtask safely:

```
Context Agent    →   curates relevant code, docs, prior task history
Task Agent       →   produces the actual output (code, config, answer)
Guardrail Agent  →   prompt injection, PII, credential leak, spec drift (Haiku-class)
Code Review      →   pass / needs_refactor / reject (loops back to Task, max 3 iter)
                         ↓ blocked + rejected
                     Decision Agent  →  ADR artifact + human escalation
```

Post-pipeline (parallel, best-effort, non-blocking):
- Documentation Agent, Diagramming Agent, Security Review Agent, Memory Extraction Agent

**Agent configurability (all stored in DB, editable in UI):**
- name, role, model, temperature, max_tokens, timeout_seconds, max_retries
- system_prompt override, task_description, allowed_tools[], on_failure behavior
- run_condition (always | never | on_flag | has_tag | and | or compound)
- output_schema (JSON), artifact_type

**Pod configurability:**
- name, description, enabled/disabled, default_model
- max_cost_usd, max_execution_seconds, require_human_review, escalation_threshold
- routing_keywords[], routing_regex, priority, fallback_pod_id

**Default pods shipped:**
| Pod | Agents | Use Case |
|---|---|---|
| Quartet (system default) | Context → Task → Guardrail → Code Review | All code/config tasks |
| Quick Reply | Task only | Fast answers, low-stakes queries |
| Research | Context → Task (web search tools) | Information gathering |
| Code Generation | Full Quartet + git tools | Production code, auto-commit on pass |
| Analysis | Context → Task (read-only tools) | Codebase audit, no writes |

### B. Redis Task Queue

- BRPOP async task dispatch — long tasks don't block the HTTP layer
- Task state machine (11 states): `submitted → queued → context_running → task_running → guardrail_running → review_running → pending_human_review → completing → complete | failed | cancelled`
- `pending_human_review` pauses the loop — task waits, doesn't fail
- `clarification_needed` — Context Agent detects ambiguous requests and pauses with questions before expensive Task Agent runs. User answers via `POST /clarify`, pipeline resumes from checkpoint with enriched input. No new tables — uses existing `status` (free-form text) and `metadata` (JSONB) columns.
- Cancel from dashboard at any state (including `clarification_needed`)

### C. New Database Tables

```sql
pods, pod_agents         -- pod + agent configuration (editable in UI)
tasks                    -- task submissions with goal_id, state, cost tracking
agent_sessions           -- per-agent lifecycle within a task
guardrail_findings       -- guardrail output, severity, resolution
code_reviews             -- per-iteration Code Review Agent verdicts
artifacts                -- outputs: code|config|doc|diagram|decision_record
audit_log                -- immutable log, BigSerial, 5-level severity
```

Alembic introduced here — schema is now complex enough to require tracked migrations.

### D. ClaudeCode Provider

Spawn `claude -p` subprocess using Claude Max subscription — zero API cost per call.

```python
# Strips ANTHROPIC_API_KEY from env to force subscription auth
proc = await asyncio.create_subprocess_exec(
    "claude", "-p", prompt,
    "--no-session-persistence", "--tools", "",
    env={k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"},
)
```

Provider priority order: `claude_code → anthropic → openai → ollama`

---

## 🔜 Phase 5b — Dashboard Enhancement (Pod Management + Full Visibility)

> The dashboard grows to expose everything Phase 4 produces.
> The pod management UI is how you configure, test, and tune the agent pipelines.

| Feature | Description |
|---|---|
| **Pods page** — list all pods, enable/disable, create/delete | Visual pipeline editor per pod |
| **Pipeline editor** — agents as cards in sequence, click to configure, drag to reorder | Right panel slides in with all per-agent settings |
| **Task Board** — submit goals/tasks, live state machine progress, cancel in-flight | |
| **Activity Feed** — real-time SSE event stream of all agent actions | |
| **Audit Log** — immutable guardrail findings and decisions | |
| **Review Queue** — human-in-the-loop: approve/reject escalated tasks | |
| **Session Replay** — step through any agent session message-by-message | |
| **Model Switcher** — dropdown in chat UI, persists to localStorage | |
| UI overhaul — visual polish across all pages | |

### Settings page expansion

| Feature | Description |
|---|---|
| **.env editor** | Masked inputs for secrets (API keys shown as `••••••`, reveal-on-click). Warns on save for values that require a service restart vs. those read at runtime. Backend endpoint reads/writes the actual `.env` file; requires `nova` sandbox tier or host access. |
| **models.yaml editor** | Add/remove Ollama models to auto-pull on startup. Pairs with the Ollama model manager below. |
| **System prompt editor** | Per-agent operational prompts editable in UI, separate from the persona field. Prerequisite for self-configuration via `nova` sandbox tier. |
| **Provider status panel** | For each configured provider (Anthropic, OpenAI, Ollama, Groq, Gemini, etc.): API key present, last successful call, ping latency, one-click test button. |
| **Ollama model manager** | List installed models with disk usage, pull new models by name, delete models. Handles "pull now" vs. the models.yaml "pull on startup". |
| **Memory browser** | Search, view, and delete stored memories. Essential before self-directed operation where Nova writes its own memories. |
| **Context budget editor** | Tune the `system/tools/memory/history/working` percentage split. Currently hardcoded in orchestrator config. |
| **Service health page** | Live status of all 7 services using existing `/health/live` and `/health/ready` endpoints. Replaces `make ps`. |
| **Log viewer** | SSE-streamed log tail, filterable by service and log level. |
| **Guardrail findings feed** | Dedicated view for guardrail findings — severity, resolution, agent context. Surfaced separately from the generic audit log. |

---

## 🔜 Phase 5c — Skills & Rules (Agent Extensibility)

> **Prerequisite:** Phase 4 (Quartet Pipeline) and Phase 5b (Pod Management UI) must be functional.
> Skills and Rules make agents configurable without code changes. Skills are reusable prompt
> templates shared across agents/pods. Rules are declarative behavior constraints that complement
> the Guardrail Agent with user-defined policies and pre-execution enforcement.

### Why this phase exists

Nova's existing extensibility is more mature than expected: `mcp_servers` table, per-agent `allowed_tools`, `platform_config` key-value store, and `agent_endpoints` for external agent delegation. But two things are genuinely missing:

1. **Skills** — `pod_agents.system_prompt` allows per-agent custom prompts, but skills can't be **shared** across agents/pods without duplicating text. The interactive chat path has no mechanism to pull in reusable prompt templates. No versioning, enable/disable, or parameterization.

2. **Rules** — The Guardrail Agent does post-hoc LLM-based review, but its checks are **hardcoded** in Python (prompt injection, PII, credential leak, spec drift). There's no **pre-execution** enforcement (can't block `rm -rf` before it runs). Users can't add custom rules without modifying source code.

### A. Skills System — Reusable Prompt Templates

**Schema: Migration `010_skills_rules.sql`**

```sql
CREATE TABLE IF NOT EXISTS skills (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,                -- prompt text, may have {{param}} placeholders
    scope       TEXT NOT NULL DEFAULT 'global', -- global | pod | agent
    parameters  JSONB NOT NULL DEFAULT '[]',  -- [{name, default, description}]
    category    TEXT NOT NULL DEFAULT 'custom', -- workflow | coding | review | safety | custom
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    priority    INTEGER NOT NULL DEFAULT 0,   -- higher = injected earlier
    is_system   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Scope join tables
CREATE TABLE IF NOT EXISTS skills_pods (
    skill_id UUID REFERENCES skills(id) ON DELETE CASCADE,
    pod_id   UUID REFERENCES pods(id) ON DELETE CASCADE,
    PRIMARY KEY (skill_id, pod_id)
);
CREATE TABLE IF NOT EXISTS skills_agents (
    skill_id     UUID REFERENCES skills(id) ON DELETE CASCADE,
    pod_agent_id UUID REFERENCES pod_agents(id) ON DELETE CASCADE,
    PRIMARY KEY (skill_id, pod_agent_id)
);
```

**API endpoints (in `pipeline_router.py`):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/skills` | List all skills |
| POST | `/api/v1/skills` | Create skill |
| PATCH | `/api/v1/skills/{id}` | Update skill |
| DELETE | `/api/v1/skills/{id}` | Delete skill |
| PUT | `/api/v1/skills/{id}/pods` | Set pod assignments |
| PUT | `/api/v1/skills/{id}/agents` | Set agent assignments |

**Integration: `orchestrator/app/pipeline/skills.py` (new)**

- `resolve_skills(pod_id, pod_agent_id)` → returns formatted `## Active Skills` prompt section
- Resolution order: global skills + pod-scoped skills + agent-scoped skills, ordered by priority
- **Pipeline path**: inject into `executor.py` `_run_agent()` before agent instantiation
- **Chat path**: inject global skills into `runner.py` `_build_nova_context()`
- Cache with 30s TTL (skills change rarely)

### B. Rules System — Declarative Behavior Constraints

**Schema (same migration `010_skills_rules.sql`):**

```sql
CREATE TABLE IF NOT EXISTS rules (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    rule_text    TEXT NOT NULL,                   -- human-readable constraint
    enforcement  TEXT NOT NULL DEFAULT 'soft',     -- soft | hard | both
    pattern      TEXT,                             -- regex for hard enforcement
    target_tools TEXT[],                           -- which tools pattern applies to (NULL = all)
    action       TEXT NOT NULL DEFAULT 'block',    -- block | warn | require_approval
    scope        TEXT NOT NULL DEFAULT 'global',
    category     TEXT NOT NULL DEFAULT 'custom',   -- safety | quality | compliance | workflow
    severity     TEXT NOT NULL DEFAULT 'high',     -- low | medium | high | critical
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    is_system    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Scope join tables (same pattern as skills)
CREATE TABLE IF NOT EXISTS rules_pods (...);
CREATE TABLE IF NOT EXISTS rules_agents (...);
```

**Two enforcement paths:**

1. **Soft (LLM-based)**: Rules injected into Guardrail Agent's system prompt via `resolve_guardrail_rules()`. Guardrail checks compliance as part of normal review.

2. **Hard (pre-execution)**: Rules with `pattern` checked in `execute_tool()` BEFORE tool runs. On match: block (return error to LLM), warn (run but log), or require_approval (pause for human).

**Seed rules (3 system defaults):**

| Rule | Enforcement | Action |
|------|-------------|--------|
| `no-rm-rf` — block recursive force delete | hard | block |
| `workspace-boundary` — stay within /workspace | soft | block |
| `no-secret-in-output` — no API keys in responses | soft | block |

**API endpoints:** Same CRUD pattern as skills: `GET/POST/PATCH/DELETE /api/v1/rules`, plus scope assignment endpoints.

**Integration: `orchestrator/app/pipeline/rules.py` (new)**

- `resolve_guardrail_rules(pod_id)` → formatted rules section for guardrail prompt
- `check_hard_rules(tool_name, arguments)` → `(allowed, violation_msg)`, called from `execute_tool()`
- Cache compiled regexes keyed on `rule.id + rule.updated_at`

### C. MCP Catalog Additions

Three new entries for Nova's MCP server catalog (agents can use these conversationally):

| Server | Why Nova's agents need it | Package |
|--------|--------------------------|---------|
| **Sentry** | Production error tracking — agents investigate errors, create issues | `@sentry/mcp-server-sentry` |
| **Playwright** | Agents test their own web output, scrape pages | `@anthropic-ai/mcp-playwright` |
| **Docker** | Agents inspect Nova's own containers, check logs | community `docker-mcp-server` |

### Dashboard Pages

**Skills page (`/skills`):**
- List all skills with scope badges (global / pod / agent)
- Create/edit with content editor (markdown-capable textarea)
- Parameter definition UI (name, default, description)
- Pod/agent assignment via multi-select
- System skills shown as non-editable
- Enable/disable toggle

**Rules page (`/rules`):**
- List all rules with enforcement type and severity badges
- Create/edit with regex pattern tester (live validation)
- Tool targeting (select which tools the rule applies to)
- System rules shown as non-deletable
- Enable/disable toggle
- "Test rule" button — paste a sample tool call, see if rule matches

### Files to Create/Modify

| File | Action |
|------|--------|
| `orchestrator/app/migrations/010_skills_rules.sql` | **New** — schema + seed rules |
| `orchestrator/app/pipeline/skills.py` | **New** — skill resolution + injection |
| `orchestrator/app/pipeline/rules.py` | **New** — rule resolution + hard enforcement |
| `orchestrator/app/pipeline_router.py` | Add CRUD endpoints for skills + rules |
| `orchestrator/app/pipeline/executor.py` | Inject skills into system prompts, rules into guardrail |
| `orchestrator/app/agents/runner.py` | Inject global skills into interactive chat context |
| `orchestrator/app/tools/__init__.py` | Add `check_hard_rules()` call in `execute_tool()` |
| `dashboard/src/api.ts` | Add skills + rules API functions |
| `dashboard/src/pages/Skills.tsx` | **New** — skill management page |
| `dashboard/src/pages/Rules.tsx` | **New** — rule management page |
| `dashboard/src/App.tsx` | Add `/skills` and `/rules` routes |
| `dashboard/src/components/NavBar.tsx` | Add Skills + Rules nav links |
| `dashboard/src/lib/mcp-catalog.ts` | Add Sentry, Playwright, Docker entries |

### Implementation Order

| Step | Deliverable |
|------|-------------|
| **1** | Migration `010_skills_rules.sql` (schema + seeds) |
| **2** | Backend: `skills.py` + `rules.py` modules |
| **3** | Backend: CRUD endpoints in `pipeline_router.py` |
| **4** | Backend: Pipeline integration (executor.py, runner.py, tools/__init__.py) |
| **5** | Dashboard: API functions |
| **6** | Dashboard: Skills page |
| **7** | Dashboard: Rules page |
| **8** | Dashboard: Route + nav registration |
| **9** | MCP catalog entries (Sentry, Playwright, Docker) |

### Testing & Validation

- [ ] `POST /api/v1/skills` creates a global skill → appears in agent system prompt
- [ ] Pod-scoped skill only applies to agents in that pod
- [ ] `POST /api/v1/rules` with `enforcement=hard` blocks matching tool calls
- [ ] Seed rules (`no-rm-rf`, `workspace-boundary`, `no-secret-in-output`) present after migration
- [ ] Skills page renders, CRUD works
- [ ] Rules page renders, system rules show as non-deletable
- [ ] MCP catalog shows Sentry, Playwright, Docker entries
- [ ] `cd dashboard && npm run build` passes

---

## ✅ Phase 5.5 — Hardening

> Operational maturity before adding memory complexity.

| Feature | Status |
|---|---|
| **Fix MCP tools invisible to agents** — replaced static `ALL_TOOLS` with `get_all_tools()` in `pipeline/agents/context.py`, `task.py`, and `agents/runner.py`; Context Agent allows `mcp__*` prefixed tools | ✅ |
| **Test foundation** — pytest fixtures + 9 test files across orchestrator (6) and memory-service (3); `asyncio_mode = "auto"` | ✅ |
| **Fix streaming token counts** — added `stream_options={"include_usage": True}` to Claude and ChatGPT subscription providers; read `chunk.usage` in stream loop | ✅ |
| **Fix reaper race condition** — Redis SET dedup gate in `enqueue_task()` (SADD before LPUSH, SREM after BRPOP); CAS UPDATE in `_reap_stuck_queued_tasks` | ✅ |
| **Structured JSON logging** — shared `JSONFormatter` in `nova-contracts/logging.py`; all 4 services use `configure_logging()`; async `ContextVar` correlation for task_id/agent_id | ✅ |
| **Embedding cache activation** — 3-tier cache (Redis L1 → PostgreSQL L2 → LLM Gateway L3) with write-through; batch optimization; tests | ✅ |
| **Working memory cleanup job** — background `cleanup_loop()` every 5 min; deletes expired `working_memories` rows; configurable interval; tests | ✅ |

---

## 🔜 Phase 6 — Memory Overhaul

> Memory is the connective tissue of self-direction.
> The Planning Agent (Phase 7) reads memory to avoid repeating mistakes and build on prior work.
> Good memory is what separates a system that gets smarter over time from one that starts fresh every run.

**Three-tier architecture:**

| Tier | Store | Purpose |
|---|---|---|
| Session | Redis | Active context window, tool results, turn history |
| Structured | PostgreSQL | Facts (key-value + confidence), episodes (task summaries + lessons), project context |
| Semantic | pgvector | Embedding similarity search |

**Key upgrades:**

1. **Hybrid retrieval** — `70% cosine_similarity + 30% ts_rank` (full-text). Fixes pure vector search on exact keyword lookups. All inside PostgreSQL, no extra service.

2. **ACT-R confidence decay** — facts age using cognitive science power-law:
   ```
   effective_confidence = base_confidence × (days_since_last_access ^ -0.5)
   ```
   Prevents stale information from contaminating Planning Agent context.

3. **`save_fact()` upsert** — `ON CONFLICT DO UPDATE` keyed on `(project_id, category, key)` — no duplicate facts across sessions.

4. **Embedding fallback chain** — `text-embedding-3-small` → Ollama `nomic-embed-text` (zero-pad 768→1536 dims).

5. **Memory Inspector page** (in dashboard) — browse facts, episodes, project context; manually flag or delete stale entries.

6. **Auto fact extraction** — after each conversation or pipeline task, automatically extract entities, decisions, and lessons learned from the output. Store as semantic facts so knowledge compounds across sessions without manual curation.

7. **"What do I know about X?" query endpoint** — `POST /api/v1/memories/knowledge` that combines semantic search, fact lookup, and cross-session consolidation into a single natural-language answer about a topic. Transforms memory from a retrieval system into a knowledge system.

8. **Cross-session consolidation** — background task that finds related episodic memories across sessions, merges overlapping facts, and promotes recurring patterns to higher-confidence semantic facts.

9. **Task history persistence** — completed task trees stored permanently with full reasoning traces: which agents ran, what they produced, what decisions were made, and why. Enables auditing how Nova reasoned through any task. Surfaced in the dashboard Task Board as "session replay".

---

## ✅ Phase 6b — Code Quality & DRY Cleanup

> Technical debt sweep before the complexity of self-directed autonomy.
> Investigation found most items already resolved incrementally during prior phases.
> Remaining fixes: `datetime.utcnow()` → `datetime.now(timezone.utc)` in chat-api,
> stale `review_running` comment in migration 002.

---

## 🔜 Phase 6c — Nova SDK, CLI/TUI & Documentation

> **Why now:** Every phase after this adds complexity (self-directed goals, triggers, computer use).
> Without a typed SDK, the dashboard and any new client duplicates HTTP logic.
> Without a CLI, Nova is trapped in the browser — unreachable from CI/CD, SSH sessions, and scripting.
> Without documentation, the platform is inaccessible to anyone who didn't build it.
>
> This phase establishes the **SDK as the single integration layer** that all clients build on,
> ships a **CLI/TUI that makes Nova usable from the terminal and CI pipelines**,
> and introduces a **documentation system that stays current as the platform evolves**.

### Architecture

```
┌──────────────────────────────────────────────────────┐
│               Nova Services (running)                │
│   orchestrator · llm-gateway · memory-service        │
└────────────────────────┬─────────────────────────────┘
                         │ HTTP / SSE
              ┌──────────┴──────────┐
              │   nova-contracts    │  ← Pydantic request/response types (exists)
              └──────────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │      nova-sdk       │  ← Typed async HTTP client (NEW)
              └──┬──────┬───────┬───┘
                 │      │       │
          ┌──────┴┐  ┌──┴──┐  ┌┴───────────┐
          │  CLI  │  │ TUI │  │  CI/CD &    │
          │(Typer)│  │(Tex │  │  scripts    │
          │       │  │tual)│  │             │
          └───────┘  └─────┘  └─────────────┘

   Dashboard (React) stays in sync via
     auto-generated TypeScript types
     from nova-contracts Pydantic models
```

**Three layers with clear responsibilities:**

| Layer | Package | Responsibility | Consumers |
|---|---|---|---|
| **Contracts** | `nova-contracts/` (exists) | Pydantic types defining every request, response, and event shape | All services, SDK, type generation |
| **SDK** | `nova-sdk/` (new) | Typed async HTTP client — how to talk to Nova programmatically | CLI, TUI, CI scripts, third-party integrations |
| **CLI/TUI** | `nova-cli/` (new) | Terminal presentation — formatting, streaming, interactive UI | Humans in terminals |

The SDK is the critical layer. It eliminates duplicated HTTP logic between the dashboard's `api.ts` and any new client. When an endpoint is added to the orchestrator, you update the contract, update the SDK, and every consumer gets it.

### A. nova-sdk — Typed Python Client

**Package:** `nova-sdk/` at repo root, installable as `pip install nova-sdk` (or from the mono-repo as a path dependency).

**Design principles:**
- Async-first (httpx async client), with sync wrappers for simple scripting
- Every method returns typed Pydantic models from `nova-contracts`
- Streaming methods yield typed event objects (not raw SSE strings)
- Auth handled once at client init — API key or admin secret
- Connection pooling, configurable timeouts, retry with backoff
- Zero dependency on any service internals — pure HTTP client

**Client structure:**

```python
from nova_sdk import NovaClient

async with NovaClient(
    url="https://nova.example.com",
    api_key="sk-nova-...",        # or admin_secret="..." for admin ops
    timeout=30.0,
) as nova:
    # Tasks
    task = await nova.tasks.submit("Fix the auth bug in login.py")
    task = await nova.tasks.get(task_id)
    tasks = await nova.tasks.list(status="running", limit=50)
    await nova.tasks.cancel(task_id)

    # Streaming
    async for event in nova.tasks.submit_stream("Refactor the logger"):
        print(event.delta, end="")  # typed StreamEvent, not raw string

    # Pipeline
    stats = await nova.pipeline.queue_stats()
    dead = await nova.pipeline.dead_letter()
    findings = await nova.pipeline.findings(task_id)
    reviews = await nova.pipeline.reviews(task_id)
    artifacts = await nova.pipeline.artifacts(task_id)
    await nova.pipeline.review(task_id, action="approve", comment="LGTM")

    # Chat
    async for event in nova.chat.stream("Explain the auth flow"):
        print(event.delta, end="")

    # Agents & Pods
    agents = await nova.agents.list()
    await nova.agents.update_config(agent_id, model="claude-sonnet-4-6")
    pods = await nova.pods.list()
    pod = await nova.pods.get(pod_id)

    # Models
    models = await nova.models.list()

    # Keys (admin)
    key = await nova.keys.create(name="ci-pipeline", rate_limit_rpm=60)
    await nova.keys.revoke(key_id)

    # Memory
    results = await nova.memory.search("authentication patterns", limit=10)
    await nova.memory.store(content="Always use parameterized queries", tier="procedural")
    memories = await nova.memory.browse(tier="semantic", limit=50)

    # MCP Servers (admin)
    servers = await nova.mcp.list()
    await nova.mcp.reload(server_id)

    # Config (admin)
    config = await nova.config.list()
    await nova.config.set("default_chat_model", "claude-sonnet-4-6")

    # Health
    status = await nova.health.check()  # all services at once
```

**Resource module pattern** (each file in `nova_sdk/resources/`):

```python
# nova_sdk/resources/tasks.py
class TasksResource:
    def __init__(self, http: HttpClient):
        self._http = http

    async def submit(self, goal: str, **kwargs) -> Task:
        resp = await self._http.post("/api/v1/pipeline/tasks", json={"goal": goal, **kwargs})
        return Task.model_validate(resp)

    async def submit_stream(self, goal: str, **kwargs) -> AsyncIterator[StreamEvent]:
        async for event in self._http.stream_sse("/api/v1/tasks/stream", json={"goal": goal, **kwargs}):
            yield StreamEvent.model_validate_json(event.data)

    async def list(self, status: str | None = None, limit: int = 50) -> list[Task]:
        ...

    async def get(self, task_id: str) -> TaskDetail:
        ...

    async def cancel(self, task_id: str) -> None:
        ...
```

**SSE streaming helper** (shared across all streaming endpoints):

```python
# nova_sdk/streaming.py
async def consume_sse(response: httpx.Response) -> AsyncIterator[SSEEvent]:
    """Parse SSE stream into typed events. Handles reconnection, [DONE] sentinel."""
    async for line in response.aiter_lines():
        if line.startswith("data: "):
            payload = line[6:]
            if payload == "[DONE]":
                return
            yield SSEEvent.model_validate_json(payload)
```

**Why this matters for the dashboard too:** Today `dashboard/src/api.ts` has its own `apiFetch<T>()` with hand-written URL construction. The TypeScript types are manually maintained. With this phase, we auto-generate `dashboard/src/types.generated.ts` from `nova-contracts` Pydantic models using a build step:

```bash
# In CI or as a make target
python -m nova_contracts.export_jsonschema > /tmp/nova-schema.json
npx json-schema-to-typescript /tmp/nova-schema.json > dashboard/src/types.generated.ts
```

This means: add a field to a Pydantic model → TypeScript types update automatically → dashboard gets type errors if it's out of sync. The dashboard's `api.ts` doesn't need to become a full SDK — it just gains accurate types.

### B. nova-cli — Terminal Interface

**Package:** `nova-cli/` at repo root. Installed as `pip install nova-cli` or `pipx install nova-cli`.

**Tech stack:**
- **Typer** — CLI framework with auto-generated help, shell completions, and argument validation
- **Rich** — tables, panels, progress bars, markdown rendering, syntax highlighting
- **httpx** — async HTTP (via the SDK)
- **nova-sdk** — all API calls go through the SDK, CLI never constructs HTTP requests directly

**The CLI is a thin presentation layer.** Every command is: parse args → call SDK method → format output. No business logic lives here.

**Command tree:**

```
nova
├── status                          # Health check all services + queue depth
├── chat [message]                  # Interactive streaming chat (or one-shot with arg)
│   ├── --model <model>             # Override model for this session
│   ├── --session <id>              # Resume a prior session
│   └── --no-stream                 # Wait for full response (for piping)
├── task
│   ├── submit <goal>               # Submit to pipeline queue
│   │   ├── --stream                # Stream output as it executes
│   │   ├── --wait                  # Block until complete, print result
│   │   ├── --pod <pod>             # Target specific pod
│   │   ├── --context <key:value>   # Inject structured context (repeatable)
│   │   └── --json                  # Output task object as JSON
│   ├── list                        # List tasks with status filter
│   │   ├── --status <status>       # Filter: queued/running/complete/failed/cancelled
│   │   └── --limit <n>
│   ├── show <task_id>              # Full detail: stages, findings, reviews, artifacts
│   ├── cancel <task_id>
│   ├── review <task_id>            # Approve/reject pending_human_review tasks
│   │   ├── --approve [comment]
│   │   └── --reject [comment]
│   ├── findings <task_id>          # List guardrail findings
│   ├── reviews <task_id>           # List code review verdicts
│   └── artifacts <task_id>         # List artifacts produced
├── pod
│   ├── list
│   ├── show <pod_id>               # Pod config + agent list
│   ├── create --name <n> [opts]
│   └── delete <pod_id>
├── agent
│   ├── list [--pod <pod_id>]
│   └── config <agent_id> [opts]    # Update model, system prompt, etc.
├── model
│   └── list [--provider <p>]       # Available models with context windows
├── key
│   ├── create --name <n> [--rpm N]
│   ├── list
│   └── revoke <key_id>
├── memory
│   ├── search <query>              # Hybrid vector+keyword search
│   │   ├── --tier <tier>
│   │   └── --limit <n>
│   ├── browse                      # Paginated browse
│   │   ├── --tier <tier>
│   │   ├── --agent <agent_id>
│   │   └── --limit/--offset
│   ├── store <content>             # Store a memory
│   │   └── --tier <tier>
│   └── delete <memory_id>
├── mcp
│   ├── list                        # Servers with connection status
│   ├── add --name <n> [opts]       # Register new server
│   ├── reload <server_id>          # Reconnect
│   └── remove <server_id>
├── config
│   ├── list                        # All platform config
│   ├── get <key>
│   ├── set <key> <value>
│   └── export                      # Dump all config as JSON (for import/backup)
├── queue                           # Queue depth + dead-letter inspection
│   ├── stats
│   └── dead-letter
├── usage [--limit N]               # Recent usage events
└── tui                             # Launch full interactive TUI (Phase 2)
```

**Global flags (all commands):**
- `--url <url>` — Nova instance URL (default: `NOVA_URL` env var, fallback `http://localhost:8000`)
- `--key <key>` — API key (default: `NOVA_API_KEY` env var)
- `--admin-secret <s>` — Admin secret (default: `NOVA_ADMIN_SECRET` env var)
- `--json` — Machine-readable JSON output (every command supports this)
- `--no-color` — Disable Rich formatting
- `--timeout <seconds>` — Request timeout override
- `--profile <name>` — Named config profile (see Configuration below)

**Configuration file** (`~/.config/nova/config.toml`):

```toml
[default]
url = "http://localhost:8000"
admin_secret = "from-env"   # special value meaning read from NOVA_ADMIN_SECRET

[profiles.staging]
url = "https://nova-staging.internal:8000"
api_key = "sk-nova-..."

[profiles.prod]
url = "https://nova.internal:8000"
api_key = "sk-nova-..."
```

Usage: `nova --profile staging task list` or `NOVA_PROFILE=staging nova task list`.

**Auth resolution order:** CLI flag → env var → config profile → default profile. Admin secret and API key are separate — some commands need admin (key management, config), others work with a regular API key.

**Output modes — every command supports both:**
1. **Human mode (default):** Rich tables, colored status badges, markdown rendering, progress spinners
2. **Machine mode (`--json`):** Raw JSON, one object per line for streaming, suitable for `jq` pipelines

**Example human output:**

```
$ nova status
┌─────────────────────────────────────────────┐
│ Nova Platform Status                        │
├──────────────────┬────────┬─────────────────┤
│ Service          │ Status │ Details         │
├──────────────────┼────────┼─────────────────┤
│ orchestrator     │ ● UP   │ 3 active tasks  │
│ llm-gateway      │ ● UP   │ 12 models       │
│ memory-service   │ ● UP   │ 1,847 memories  │
│ postgres         │ ● UP   │                 │
│ redis            │ ● UP   │ queue: 2        │
└──────────────────┴────────┴─────────────────┘
```

**Example machine output:**

```
$ nova --json task list --status running
{"task_id": "abc-123", "status": "running", "stage": "guardrail_running", "goal": "Fix auth bug", "created_at": "..."}
{"task_id": "def-456", "status": "running", "stage": "task_running", "goal": "Add tests", "created_at": "..."}
```

### C. CI/CD Integration — The Killer Use Case

The CLI + SDK enables Nova as an automated participant in CI/CD pipelines. The primary use case: **a failed pipeline triggers Nova to investigate, fix, and open a merge request.**

**Slim Docker image:**

```dockerfile
# nova-cli.Dockerfile
FROM python:3.12-slim
RUN pip install nova-cli
# ~50MB image — just Python + httpx + typer + rich
# No postgres, no redis, no dashboard — pure HTTP client
ENTRYPOINT ["nova"]
```

Published as `ghcr.io/arialabs/nova-cli:latest` alongside the main Nova images.

**GitLab pipeline recovery example:**

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - nova-recover  # only runs when earlier stages fail

build:
  stage: build
  script: make build

test:
  stage: test
  script: make test

nova-investigate-and-fix:
  stage: nova-recover
  when: on_failure                              # only triggers on failure
  image: ghcr.io/arialabs/nova-cli:latest
  variables:
    NOVA_URL: $NOVA_URL                         # from CI/CD variables
    NOVA_API_KEY: $NOVA_API_KEY
  script:
    # Collect failure context
    - |
      nova task submit --wait --json \
        --context "repo:${CI_PROJECT_URL}" \
        --context "branch:${CI_COMMIT_REF_NAME}" \
        --context "commit:${CI_COMMIT_SHA}" \
        --context "pipeline:${CI_PIPELINE_URL}" \
        --context "failed_job:${CI_JOB_NAME}" \
        --context "log:$(cat /tmp/test-output.log | tail -200)" \
        "A CI pipeline failed. Investigate the failure from the log output. \
         Clone the repo, check out the branch, understand the error, write a fix, \
         and open a GitLab merge request with the fix. \
         Include the error analysis in the MR description."
  artifacts:
    paths:
      - nova-result.json
    when: always
```

**What Nova does with this task:**
1. **Context Agent** — assembles repo context, reads the failure log, identifies relevant files
2. **Task Agent** — analyzes the error, writes a fix, creates a branch, opens the MR (using git tools + a GitLab MCP server or agent endpoint)
3. **Guardrail Agent** — checks the fix doesn't introduce security issues, credential leaks, or spec drift
4. **Code Review Agent** — reviews the fix quality, may loop back for refinement
5. **Decision Agent** — if confidence is low, escalates to human review queue instead of auto-merging

**GitHub Actions equivalent:**

```yaml
nova-recover:
  runs-on: ubuntu-latest
  if: failure()
  container:
    image: ghcr.io/arialabs/nova-cli:latest
  env:
    NOVA_URL: ${{ secrets.NOVA_URL }}
    NOVA_API_KEY: ${{ secrets.NOVA_API_KEY }}
  steps:
    - name: Investigate and fix
      run: |
        nova task submit --wait \
          --context "repo:${{ github.repository }}" \
          --context "branch:${{ github.ref_name }}" \
          --context "run:${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" \
          "Investigate this CI failure and open a PR with a fix."
```

**Other CI/CD use cases beyond failure recovery:**
- **PR review:** `nova task submit "Review this PR for security issues" --context "diff:$(git diff main...HEAD)"`
- **Release notes:** `nova task submit "Generate release notes from commits since last tag" --context "log:$(git log v1.2.0..HEAD --oneline)"`
- **Dependency audit:** `nova task submit "Audit dependencies for known vulnerabilities" --context "lockfile:$(cat package-lock.json)"`
- **Scheduled maintenance:** cron-triggered `nova task submit "Run a code quality sweep on the auth module"`

### D. TUI — Interactive Terminal Dashboard (Phase 2 of CLI)

Built with **Textual** (from the Rich team — same styling primitives as the CLI). Launched via `nova tui`.

**Why Textual:** It's Python, it reuses Rich's rendering, it has a CSS-like layout system, and it imports `nova-sdk` directly. No language boundary.

**Layout:**

```
┌─────────────────────────────────────────────────────────────┐
│ Nova TUI                              ● orch ● llm ● mem   │
├────────────┬────────────────────────────────────────────────┤
│            │                                                │
│  Tasks     │  Task: abc-123                                 │
│  ────────  │  Goal: Fix authentication bug                  │
│  ● abc-123 │  Status: guardrail_running                     │
│  ● def-456 │                                                │
│  ○ ghi-789 │  ■ Context  ■ Task  □ Guard  ○ Review  ○ Dec  │
│  ✓ jkl-012 │                                                │
│            │  ── Output ──────────────────────────────────── │
│  Pods      │  Found the issue in auth/login.py:42.          │
│  ────────  │  The bcrypt comparison uses == instead of      │
│  Quartet   │  constant-time comparison. Fixing...           │
│  Research  │                                                │
│            │                                                │
├────────────┴────────────────────────────────────────────────┤
│ > nova task submit "Add rate limiting to /login endpoint"   │
└─────────────────────────────────────────────────────────────┘
```

**TUI features:**
- Live-updating task list with status indicators (websocket or polling)
- 5-stage pipeline progress bar per task
- Streaming output pane for active tasks
- Service health indicators in the header
- Command bar at the bottom for quick actions
- Task detail panel with findings, reviews, artifacts tabs
- Human review approval directly from the TUI
- Chat panel (toggle with a keybinding)
- Memory browser panel

**Implementation note:** The TUI reuses the SDK entirely. Every widget is: poll SDK method → render with Textual widgets. The TUI is implemented **after** the CLI is stable because it depends on the same SDK and adds only presentation complexity.

### E. Keeping Dashboard & CLI in Sync — The Contract Pipeline

The core problem: `dashboard/src/api.ts` and `nova-sdk` both talk to the same APIs. Without a shared contract, they drift.

**Solution: auto-generated TypeScript types from Pydantic models.**

```
nova-contracts/             (source of truth — Pydantic models)
       │
       ├──→ nova-sdk/        (Python client — imports contracts directly)
       │
       └──→ JSON Schema      (exported via Pydantic's .model_json_schema())
              │
              └──→ dashboard/src/types.generated.ts  (via json-schema-to-typescript)
```

**Build step (added to `Makefile`):**

```makefile
types:  ## Generate TypeScript types from nova-contracts
	python -c "from nova_contracts import export_all_schemas; export_all_schemas('tmp/schemas')"
	npx json-schema-to-typescript tmp/schemas/*.json -o dashboard/src/types.generated.ts
```

**What this gives you:**
- Add a field to a Pydantic model → re-run `make types` → TypeScript types update → dashboard gets compile errors if it uses the old shape
- The SDK uses contracts natively (Python imports) — zero drift by construction
- CI can enforce this: `make types && git diff --exit-code dashboard/src/types.generated.ts` fails if someone forgot to regenerate

**What this does NOT do:** It doesn't auto-generate the dashboard's fetch calls or the SDK's HTTP methods. Those are still hand-written. But the types ensure they agree on shapes, which is where 90% of drift bugs come from.

### F. Documentation System

Nova currently has: `README.md` (quick start), `CLAUDE.md` (AI instructions), `docs/roadmap.md` (this file), `docs/ide-integration.md`. That's it. There's no API reference, no architecture guide, no user guide, no contributor docs.

**Documentation strategy — three tiers:**

#### Tier 1: Auto-Generated Reference Docs (always current)

These are generated from code and can never go stale:

| Doc | Source | Tool | Output |
|---|---|---|---|
| **API Reference** | FastAPI route definitions + Pydantic models | FastAPI's built-in OpenAPI export + [Redoc](https://github.com/Redocly/redoc) or [Scalar](https://github.com/scalar/scalar) | Static HTML hosted at `/docs` on each service (already exists as Swagger), plus a unified exported reference |
| **CLI Reference** | Typer command definitions | `typer utils docs --output` or custom export | Markdown file auto-generated from command tree with all flags, args, and help text |
| **SDK Reference** | Docstrings + type annotations on `nova-sdk` | [pdoc](https://pdoc.dev) or [mkdocstrings](https://mkdocstrings.github.io) | Python API docs with examples |
| **TypeScript Types** | nova-contracts export | json-schema-to-typescript | `types.generated.ts` with JSDoc comments |
| **Configuration Reference** | `pydantic_settings.BaseSettings` classes across all services | Custom export script | Table of every env var, its type, default, and description |
| **Database Schema** | `orchestrator/app/migrations/*.sql` | Schema dump + [SchemaSpy](https://schemaspy.org) or [dbdocs](https://dbdocs.io) | ER diagram + table/column reference |

**Implementation:** A `make docs` target that runs all generators and outputs to `docs/generated/`. CI runs `make docs` and either publishes to GitHub Pages or bundles into the dashboard as a `/docs` route.

#### Tier 2: Hand-Written Guides (versioned in `docs/`)

These require human authorship but should be maintained alongside the code they describe:

| Doc | Purpose | Location |
|---|---|---|
| **Architecture Guide** | Service topology, inter-service communication, data flow diagrams, Redis DB allocation, context budget split | `docs/architecture.md` |
| **Getting Started** | Expand current README: prerequisites, first task, first pipeline run, connecting an IDE | `docs/getting-started.md` |
| **CLI User Guide** | Workflows and examples beyond `--help`: CI/CD setup, scripting patterns, config profiles | `docs/cli-guide.md` |
| **Self-Hosting Guide** | Production deployment: reverse proxy, TLS, GPU setup, resource sizing, backup strategy | `docs/self-hosting.md` |
| **Pod & Agent Configuration** | How to design pods, configure agents, tune models, set up routing — the "admin playbook" | `docs/pods-and-agents.md` |
| **MCP Integration Guide** | How to add MCP servers, write custom tools, use the tool catalog | `docs/mcp-guide.md` |
| **Memory System** | Tier explanations, when to use each, how retrieval works, compaction, confidence decay | `docs/memory.md` |
| **Contributing** | Repo structure, development setup, code conventions, PR workflow | `CONTRIBUTING.md` |

#### Tier 3: Living Docs (in-app and contextual)

| Doc | Description |
|---|---|
| **`nova --help` / `nova <cmd> --help`** | Auto-generated from Typer. First thing users see. Must be excellent. |
| **Dashboard tooltips & help text** | Contextual guidance in the UI — "What is a pod?", "What does the guardrail agent check?" |
| **`CLAUDE.md`** | Already exists. Kept current as the AI-readable project reference. |
| **OpenAPI / Swagger UI** | Already exists at `/docs` on each service. Useful for API exploration. |
| **`nova docs`** | CLI command that opens the documentation site in the default browser |
| **`nova docs <topic>`** | CLI shortcut: `nova docs cli`, `nova docs pods`, `nova docs memory` — opens the relevant page |

**Documentation site tooling:**

[MkDocs Material](https://squidfunk.github.io/mkdocs-material/) is the recommended choice:
- Markdown source files (matches existing `docs/` convention)
- Auto-generates nav from file structure
- Supports admonitions, tabs, code annotations, search
- `mkdocs-gen-files` plugin can inject auto-generated reference docs at build time
- Deploys as static HTML to GitHub Pages, Cloudflare Pages, or a `/docs` route in the dashboard
- Used by FastAPI, Pydantic, Textual, and most Python projects in this ecosystem

**`mkdocs.yml` structure:**

```yaml
site_name: Nova Documentation
theme:
  name: material
  palette:
    - scheme: default
      primary: teal        # matches dashboard palette
nav:
  - Home: index.md
  - Getting Started: getting-started.md
  - Architecture: architecture.md
  - User Guides:
    - CLI: cli-guide.md
    - Dashboard: dashboard-guide.md
    - Pods & Agents: pods-and-agents.md
    - Memory: memory.md
    - MCP Integration: mcp-guide.md
  - CI/CD Integration: ci-cd.md
  - Self-Hosting: self-hosting.md
  - Reference:
    - API: generated/api-reference.md
    - CLI Commands: generated/cli-reference.md
    - SDK: generated/sdk-reference.md
    - Configuration: generated/config-reference.md
    - Database Schema: generated/schema-reference.md
  - Contributing: contributing.md
  - Roadmap: roadmap.md
plugins:
  - search
  - gen-files          # injects auto-generated docs at build time
  - mkdocstrings       # Python docstring → docs
```

**Makefile targets:**

```makefile
docs:           ## Generate all reference docs + build site
docs-serve:     ## Live preview at localhost:8000
docs-publish:   ## Deploy to GitHub Pages
```

### Implementation Order

This phase is internally ordered to maximize value at each step:

| Step | Deliverable | Why this order |
|---|---|---|
| **1** | **Expand `nova-contracts`** — add missing request/response models for all endpoints (pipeline, pods, MCP, config, memory browse, health). Add `export_all_schemas()` for TypeScript generation. | Everything else depends on complete contracts. |
| **2** | **Build `nova-sdk`** — typed async client with resource modules for every API surface. SSE streaming helper. Auth handling. Tests against a mock server. | SDK is the foundation for CLI, TUI, and CI scripts. Building it first means we can validate the API surface before adding presentation. |
| **3** | **TypeScript type generation** — `make types` pipeline from contracts → JSON Schema → `types.generated.ts`. Update dashboard imports. | Quick win that immediately prevents dashboard/backend drift. |
| **4** | **Build `nova-cli`** — Typer app, all commands, Rich formatting, `--json` mode, config profiles, shell completions. | Primary user-facing deliverable. Depends on SDK being stable. |
| **5** | **`nova-cli` Docker image** — slim image, CI/CD example configs for GitLab and GitHub Actions. | Unlocks the CI/CD use case. Just packaging — no new code. |
| **6** | **Documentation site** — MkDocs Material setup, auto-generated reference docs, initial hand-written guides (architecture, getting started, CLI guide, CI/CD guide). | Documentation benefits from everything above being built — we document what exists rather than what's planned. |
| **7** | **TUI (`nova tui`)** — Textual app with task list, pipeline visualizer, chat panel, command bar. | Most complex presentation layer. Built last because it depends on a stable SDK and benefits from CLI command patterns already established. |

### What Ships

| Artifact | Description |
|---|---|
| `nova-contracts/` | Expanded with full request/response types + JSON Schema export |
| `nova-sdk/` | New package — typed async Python client for all Nova APIs |
| `nova-cli/` | New package — terminal CLI with all commands listed above |
| `nova-cli` Docker image | `ghcr.io/arialabs/nova-cli:latest` — ~50MB slim image for CI/CD |
| `dashboard/src/types.generated.ts` | Auto-generated TypeScript types from contracts |
| `make types` | Makefile target to regenerate TS types |
| `make docs` / `make docs-serve` | Documentation site build + preview |
| `docs/` site | MkDocs Material site with auto-generated reference + hand-written guides |
| CI/CD examples | GitLab CI and GitHub Actions example configs in `docs/ci-cd.md` |

---

## 🔜 Phase 7 — Self-Directed Autonomy (Goal Layer + Planning + Evaluation)

> **This is the goal the entire platform is built toward.**
> You define a goal. Nova works toward it. You come back when it's done — or when it needs you.

### Architecture

```
User: "Improve test coverage in auth module to 80%"
                    │
                    ▼
         ┌─────────────────────┐
         │     Goal Layer      │
         │  goal_store: tracks │
         │  goal, progress,    │
         │  iteration history  │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │   Planning Agent    │  ◄── reads memory (lessons from prior runs)
         │                     │  ◄── reads codebase state (Phase 3 tools)
         │  Goal → subtasks    │
         │  Re-plans on each   │
         │  Evaluation report  │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │   Task Queue        │
         │   (Redis BRPOP)     │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Quartet Pipeline   │  ← safety rails on every unit of work
         │  (per subtask)      │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Evaluation Agent   │  → writes lessons to memory
         │                     │  → reports progress delta to Goal Layer
         │  advanced? yes/no   │
         │  what's next?       │
         │  escalate? why?     │
         └────┬───────────┬────┘
              │           │
              ▼           ▼
       Continue loop   Human escalation
       (back to        (blocked / uncertain /
       Planner)         budget exceeded /
                        goal complete)
```

### New Components

| Component | Description |
|---|---|
| **Goal Store** | PostgreSQL `goals` table — status, progress %, current subtask, iteration count, cost so far |
| **Planning Agent** | New agent role — takes goal + memory + codebase state → ordered subtask list. Re-plans after every Evaluation report |
| **Evaluation Agent** | New agent role — assesses whether a subtask advanced the goal, determines next action, writes memory |
| **Loop Controller** | Orchestrates the Planning → Queue → Quartet → Evaluation cycle. Enforces budget/iteration limits. Triggers human escalation |
| **Goal Dashboard page** | Submit goals, watch loop progress in real time, inspect Planning Agent's current plan, see evaluation history |

### Safety Mechanisms for Autonomous Operation

- **Budget limit** per goal — hard stop at max_cost_usd
- **Iteration limit** — Planning Agent must escalate after N iterations without progress
- **Guardrail Agent** on every subtask — autonomous ≠ unchecked
- **Evaluation Agent** determines if a subtask genuinely advanced the goal — prevents runaway loops
- **Human review queue** — escalation point, not a failure state

---

## 🔜 Phase 8 — Full Autonomous Loop + Reinforcement

> Self-direction v2: Nova learns from its own history.
> The Planning Agent uses memory of prior goal runs to produce better plans from the start.

- Planning Agent reads prior episode memory: "last time I tried to improve test coverage, the approach that worked was X, the one that failed was Y"
- Evaluation Agent produces structured `lessons_learned` written to memory after every goal
- Goal similarity matching — when a new goal resembles a prior one, the plan starts from the proven approach rather than scratch
- Long-horizon goals: goals can span multiple sessions, resume after human review, survive restarts
- Self-assessment: Nova can evaluate its own overall performance across goals and surface patterns

---

## 🔜 Remote Access + Mobile

Secure remote access and PWA support — access Nova from your phone or any device.

| Feature | Status |
|---|---|
| WebSocket auth (API key on `/ws/chat`) | ✅ |
| CORS lockdown (configurable `CORS_ALLOWED_ORIGINS`) | ✅ |
| HTTPS indicator in NavBar | ✅ |
| Cloudflare Tunnel sidecar (`profiles: ["cloudflare-tunnel"]`) | ✅ |
| Tailscale sidecar (`profiles: ["tailscale"]`) | ✅ |
| PWA manifest + service worker (installable to home screen) | ✅ |
| Setup wizard remote access selection | ✅ |
| Web Push notifications for task completion | 🔜 Phase 4+ |

### Multi-Device Gateway Network

> Nova as a distributed personal AI network. Each device runs its own Nova gateway
> with different LLM backends, sharing one memory backend. Chat through the same
> PWA regardless of which gateway you're hitting.

**Architecture:**

```
Phone (PWA)
↓ HTTPS (Cloudflare Tunnel / Tailscale)
├── Mini-PC Nova  → Cloud APIs + WoL → Dell Ollama
├── Work Laptop Nova → Cloud APIs + Dell Ollama via Tailscale
└── Dell Nova → Local Ollama only
↑
All instances share one memory-service (on mini-PC)
```

**Per-device LLM routing config:**

| Device | `LLM_ROUTING_STRATEGY` | Ollama endpoint | Notes |
|---|---|---|---|
| Mini-PC (Beelink) | `cloud-first` | Dell via WoL | Always-on gateway, wakes Dell on demand |
| Dell Desktop | `local-only` | `localhost:11434` | GPU box, no cloud spend |
| Work Laptop | `cloud-first` | Dell via Tailscale | Remote Ollama when Dell is awake |

**What exists:**
- LiteLLM gateway already routes by strategy (`local-only`/`local-first`/`cloud-only`/`cloud-first`)
- WoL integration already wakes Dell on demand
- Cloudflare Tunnel and Tailscale profiles in docker-compose
- PWA manifest + service worker already shipped

**What's needed:**
- [ ] Mobile-responsive chat UI (dashboard is desktop-optimized)
- [ ] Per-instance `.env` templates for each device profile
- [ ] Shared memory: all instances point `NOVA_MEMORY_URL` at mini-PC's memory-service via Tailscale
- [ ] Device-aware inference routing in llm-gateway or orchestrator
- [ ] Documentation: `docs/deployment-distributed.md`

**Minimal viable path:** Run Nova on mini-PC with `cloud-only` routing. No Ollama needed. Chat via PWA from phone. Validate the pattern, then add Dell Ollama routing.

---

## 🔜 Domain Restructuring & Website Migration

**Current state:** `nova.arialabs.ai` hosts the Astro/Starlight documentation site.

**Target state:**

| Domain | Purpose |
|---|---|
| `arialabs.ai` | Aria Labs company website — landing page, about, team. Nova is the main product section. |
| `arialabs.ai/nova/` | Nova product pages — features, quickstart, docs, changelog, roadmap |
| `arialabs.ai/nova/docs/...` | All current documentation migrated here |
| `nova.arialabs.ai` | Live Nova instance (private, behind Cloudflare Access with email auth) |

**Why this change:**
- `arialabs.ai` is the company — it should be the company site, not blank/parked
- `nova.arialabs.ai` as a live instance is more valuable than as a docs site
- Docs belong under the company domain where they can grow with additional products
- Dogfooding: accessing your own Nova from your phone at `nova.arialabs.ai` validates the product

**`nova.arialabs.ai` — Private instance:**
- Cloudflare Tunnel from Beelink → `nova.arialabs.ai`
- Cloudflare Access policy: email-based auth (whitelist your email)
- PWA installable to phone home screen
- When SaaS launches (Phase 14), personal instance moves to `home.nova.arialabs.ai` or `jeremy.nova.arialabs.ai`, and `nova.arialabs.ai` becomes the SaaS app. This is a 2-minute DNS swap.

**`arialabs.ai` — Company site:**
- Migrate existing Astro/Starlight site from `nova.arialabs.ai` to `arialabs.ai`
- Add company-level landing page (Aria Labs branding, mission, link to Nova)
- Nova docs at `arialabs.ai/nova/docs/...`
- Starlight base path config: `base: '/nova'` in `astro.config.mjs`
- Can host future products under `arialabs.ai/other-product/` if needed

**Migration steps:**
- [ ] Update `astro.config.mjs`: set `base: '/nova'`, update `site` to `https://arialabs.ai`
- [ ] Create company landing page at `arialabs.ai` root (can be minimal — logo, tagline, link to Nova)
- [ ] Set up redirects from `nova.arialabs.ai/docs/*` → `arialabs.ai/nova/docs/*` (Cloudflare Page Rules or `_redirects`)
- [ ] Update all internal links and references to the new URL structure
- [ ] Deploy company site to `arialabs.ai` (Cloudflare Pages or similar)
- [ ] Set up Cloudflare Tunnel: Beelink → `nova.arialabs.ai`
- [ ] Configure Cloudflare Access policy on `nova.arialabs.ai` (email whitelist)
- [ ] Install PWA on phone, verify full access from mobile
- [ ] Update GitHub repo links, README, CLAUDE.md references

**Order of operations:**
1. Migrate docs site first (ensure no broken links)
2. Then point `nova.arialabs.ai` at Beelink
3. These can happen in either order, but docs migration is lower risk

---

## 🔜 Phase 8b — MCP Integrations Hub (Self-Hosted Ecosystem)

**Motivation:** Nova already has MCP tool dispatch in the orchestrator. The next step is making it trivial to connect Nova to the self-hosted services and developer tools people already run — turning Nova into the AI brain of your homelab. Goal: **one-click install with minimal configuration** for each integration.

**Architecture:**

- `mcp-servers.yaml` config file listing enabled MCP servers with connection details
- Dashboard UI page to browse, enable/disable, and configure MCP servers
- Each integration ships as a Docker Compose profile or sidecar container with a pre-configured MCP bridge
- Auto-discovery: on startup, orchestrator reads `mcp-servers.yaml` and registers all tools from enabled servers
- Health checks: orchestrator periodically pings MCP server endpoints, dashboard shows status

**One-click install flow:**

1. User browses "Integrations" page in the dashboard
2. Clicks "Enable" on an integration (e.g., Home Assistant)
3. Dashboard prompts for minimal config (e.g., HA URL + long-lived access token)
4. Config written to `mcp-servers.yaml`, orchestrator hot-reloads
5. Integration tools immediately available to agents

### Homelab Integrations (Priority Tier)

| MCP Server | What Nova Gets | Config Required | Priority |
|---|---|---|---|
| **Home Assistant** | Device control, automations, sensor queries, scene management | HA URL + long-lived access token | High |
| **n8n** | Trigger/build workflows, check execution status, bidirectional orchestration | n8n URL + API key | High |
| **Nextcloud** | File management, calendar, contacts, notes | Nextcloud URL + app password | Medium |
| **Paperless-ngx** | Document search, tagging, OCR'd content retrieval | Paperless URL + API token | Medium |
| **Immich** | Photo search, album management, facial recognition queries | Immich URL + API key | Medium |
| **Gitea / Forgejo** | Local repo management, issues, PRs, code search | Gitea URL + API token | Medium |
| **Uptime Kuma** | Service health monitoring, downtime alerts, status pages | Uptime Kuma URL + API key | Low |
| **Portainer** | Container lifecycle management, stack deployment, resource monitoring | Portainer URL + API key | Low |

### Developer Productivity Integrations

| MCP Server | What Nova Gets | Config Required | Priority |
|---|---|---|---|
| **GitHub** | Issues, PRs, repos, actions, code search | GitHub PAT | High |
| **Linear** | Project/task tracking, issue management, sprint planning | Linear API key | Medium |
| **Notion** | Knowledge base queries, page creation, database operations | Notion integration token | Medium |
| **Slack** | Send/read messages, channel management, notifications | Slack bot token | Medium |
| **Discord** | Send/read messages, channel management, bot interactions | Discord bot token | Low |

### System & Infrastructure Integrations

| MCP Server | What Nova Gets | Config Required | Priority |
|---|---|---|---|
| **Filesystem** | Direct file read/write on the host (beyond workspace) | Mount path(s) | High |
| **Docker** | Container lifecycle, image management, log access | Docker socket mount | High |
| **Cloudflare** | DNS management, tunnel configuration, custom domain self-deployment | Cloudflare API token + zone ID | High |
| **SSH** | Remote command execution on other machines (e.g., Dell GPU box) | SSH key path + host list | Medium |
| **Prometheus / Grafana** | Metrics queries, dashboard creation, alert management | Prometheus/Grafana URL | Low |

### Knowledge & Research Integrations

| MCP Server | What Nova Gets | Config Required | Priority |
|---|---|---|---|
| **Brave Search** | Web search without API key hassles | Brave API key | High |
| **Playwright** | Browser automation, web scraping, page interaction | None (bundled container) | High |
| **Qdrant** | External vector search (supplement to Nova's built-in memory) | Qdrant URL | Low |
| **SQLite / PostgreSQL** | Query arbitrary databases, data analysis | Connection string(s) | Low |

### Recommendations

**Start with these 5** — they cover the most common self-hosted + dev workflows:

1. **Filesystem + Docker** — immediate utility, Nova can inspect and manage its own environment
2. **Home Assistant** — killer demo for personal AI; "turn off the lights when I say goodnight"
3. **GitHub** — already using it for Nova development; mature MCP server exists
4. **Brave Search** — gives Nova web access for research tasks
5. **n8n** — bidirectional orchestration; n8n triggers Nova tasks, Nova triggers n8n workflows

**n8n bidirectional pattern:**
- Nova → n8n: Nova calls n8n's webhook/API to trigger workflows (e.g., "deploy this", "notify me", "run this ETL")
- n8n → Nova: n8n workflow hits Nova's webhook endpoint (Phase 9) to submit tasks (e.g., "new PR opened → Nova reviews it")
- Combined: n8n handles the plumbing (email, webhooks, data transforms), Nova handles the intelligence (analysis, generation, decisions)

### Devices & Infrastructure Dashboard

**Motivation:** Nova runs across multiple physical machines (Beelink always-on, Dell GPU box via WoL, potentially Pi or NAS). There's currently no visibility into what's connected, what's available, and what capabilities each device brings. The Devices page makes Nova aware of its own physical infrastructure.

**Dashboard page: "Devices"**

Displays all registered devices in a grid/list with real-time status:

| Column | Description |
|---|---|
| **Device name** | User-defined label (e.g., "Beelink", "Dell GPU Box") |
| **Status** | Online / Sleeping / Offline (with last-seen timestamp) |
| **Role** | Primary host, GPU inference, edge sensor, storage, etc. |
| **Hardware** | CPU, RAM, GPU (if any), disk capacity |
| **Services** | Running containers/services with health indicators |
| **Models** | Installed inference models (for GPU/inference devices) |
| **Network** | IP address, latency from Nova, WoL MAC address |
| **Resources** | Live CPU%, RAM%, GPU VRAM% utilization |

**Per-device actions:**
- **Wake** button for WoL-capable sleeping devices
- **SSH terminal** (if SSH MCP integration is enabled)
- **View containers** (if Docker MCP integration is enabled)
- **Browse files** (if Filesystem MCP integration is enabled)

**Device registration:**
- Lightweight heartbeat agent (single binary or Python script) runs on each device
- Reports hardware specs, running services, resource usage every 30s to Nova's orchestrator
- Alternative: agentless mode — Nova polls devices via SSH or Docker API (no software install on remote devices)
- Devices stored in a `devices` table in postgres
- First-time registration: device appears as "New" in dashboard, user assigns name/role

**Smart routing integration:**
- Orchestrator checks device status before routing inference requests
- If Dell GPU box is sleeping and a task needs GPU inference → auto-wake via WoL, wait for Ollama ready, then route
- If a device goes offline → orchestrator falls back to cloud providers or queues the task
- MCP server availability tied to device status: if device hosting an MCP server goes offline, those tools are marked unavailable

**Implementation:**
- [ ] `devices` table in postgres: id, name, role, hardware_specs (JSONB), network_info (JSONB), last_heartbeat, status, wol_mac
- [ ] Heartbeat endpoint: `POST /api/devices/heartbeat` (device agent calls this periodically)
- [ ] Agentless polling: orchestrator pings devices via SSH/Docker API on a schedule
- [ ] WoL integration: `POST /api/devices/{id}/wake` sends magic packet
- [ ] Dashboard Devices page with real-time status grid
- [ ] Device-aware inference routing in llm-gateway or orchestrator

### Custom Domain Self-Deployment (via Cloudflare MCP)

**Motivation:** Nova already supports Cloudflare Tunnel for remote access, but setup requires manual `cloudflared` configuration. With the Cloudflare MCP server, Nova can configure its own public access — a user who owns a domain can tell Nova to deploy itself at `nova.mydomain.com` and Nova handles the rest.

**User experience:**

1. User enables Cloudflare integration on the Integrations page (API token + zone ID)
2. In Settings → Remote Access, user sees a new "Custom Domain" option
3. User enters desired subdomain (e.g., `nova`) — Nova shows it will create `nova.mydomain.com`
4. User confirms → Nova uses Cloudflare MCP to:
   - Create a Cloudflare Tunnel pointing to Nova's dashboard (port 3000)
   - Create a DNS CNAME record: `nova.mydomain.com` → tunnel
   - Configure SSL (Cloudflare provides automatic HTTPS)
   - Store tunnel credentials in Nova's config
5. Nova is now accessible at `https://nova.mydomain.com` with zero manual DNS/tunnel config

**What Nova configures via Cloudflare MCP:**

| Action | Cloudflare API | Purpose |
|---|---|---|
| Create tunnel | `POST /tunnels` | Encrypted tunnel from Nova host to Cloudflare edge |
| Add DNS record | `POST /dns_records` | CNAME pointing subdomain to tunnel |
| Configure ingress | Tunnel config | Route `nova.mydomain.com` → `localhost:3000` |
| Enable SSL | Zone settings | Full (strict) SSL mode |
| Optional: Access policy | Cloudflare Access | Add email-based auth in front of Nova |

**Configuration in `.env` / Settings:**

```
# Cloudflare integration
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_ZONE_ID=...
NOVA_CUSTOM_DOMAIN=nova.mydomain.com    # set by Nova after deployment
```

**Safety:**
- Nova only modifies DNS records it created (tagged with `nova-managed: true` in record comments)
- "Undeploy" button in Settings removes the tunnel + DNS record
- Dry-run mode: shows what Nova would configure before doing it
- Never touches existing DNS records or other tunnels

**Integration with setup.sh:**
- If Cloudflare API token is provided during setup, offer custom domain configuration
- `setup.sh` can prompt: "Do you want Nova accessible at a custom domain? (requires Cloudflare-managed domain)"

### Implementation

**Step 1: MCP server config system**
- [ ] `mcp-servers.yaml` schema: name, transport (stdio/HTTP/SSE), command/URL, env vars, enabled flag
- [ ] Orchestrator loads config at startup, registers tools from each enabled server
- [ ] Hot-reload: orchestrator watches config file or exposes `POST /api/mcp/reload`
- [ ] Health check endpoint per MCP server: `GET /api/mcp/servers` returns status of each

**Step 2: Dashboard Integrations page**
- [ ] Grid/list view of available integrations with icons, descriptions, status (enabled/disabled/error)
- [ ] Enable/disable toggle per integration
- [ ] Config modal: minimal form fields per integration (URL, API key, etc.)
- [ ] Connection test button: verify credentials and connectivity before saving
- [ ] Tool browser: show which tools each integration provides

**Step 3: Docker Compose profiles for bundled servers**
- [ ] `profiles: ["mcp-filesystem"]` — filesystem MCP server with configurable mount paths
- [ ] `profiles: ["mcp-playwright"]` — Playwright MCP server with Chromium
- [ ] `profiles: ["mcp-docker"]` — Docker MCP server with socket mount
- [ ] Each profile adds a lightweight sidecar container running the MCP server
- [ ] `setup.sh` integration: detect available services, offer to enable integrations

**Step 4: Community integration docs**
- [ ] `docs/integrations/` directory with per-integration setup guides
- [ ] Each guide: what it does, prerequisites, config, example prompts, troubleshooting
- [ ] Template for community-contributed integrations

### Testing & Validation

**MCP Integrations:**
- [ ] Enable 3+ MCP servers simultaneously, verify all tools register without conflicts
- [ ] Hot-reload: add a new server to `mcp-servers.yaml`, verify tools appear without restart
- [ ] Dashboard: enable/disable/configure an integration, verify config persists
- [ ] Connection test: verify failure feedback for bad credentials
- [ ] Agent can use tools from multiple MCP servers in a single task
- [ ] Health check correctly reports server status (up/down/error)

**Devices & Infrastructure:**
- [ ] Device heartbeat agent registers a new device, appears in dashboard within 30s
- [ ] Device goes offline → status updates to "Offline" within 2 heartbeat intervals
- [ ] WoL: "Wake" button sends magic packet, device comes online, status updates
- [ ] Agentless mode: Nova polls a device via SSH, correctly reports hardware specs and running services
- [ ] Inference routing: task needing GPU routes to Dell when online, falls back to cloud when offline
- [ ] Device detail view shows live resource utilization (CPU%, RAM%, GPU%)

**Custom Domain:**
- [ ] Cloudflare MCP creates tunnel + DNS record, Nova accessible at custom domain within 60s
- [ ] SSL works automatically (HTTPS with valid cert)
- [ ] "Undeploy" removes tunnel + DNS record cleanly
- [ ] Dry-run mode shows planned changes without executing
- [ ] Existing DNS records are never modified or deleted

### Success Criteria

- [ ] User can enable a new integration in <60 seconds from the dashboard (one-click + config)
- [ ] At least 5 integrations working end-to-end (Filesystem, Docker, GitHub, Brave Search, Home Assistant or n8n)
- [ ] MCP server failures don't crash the orchestrator — graceful degradation
- [ ] Dashboard shows real-time status of all configured integrations
- [ ] Adding a new community integration requires only a YAML entry + optional Docker profile (no code changes)
- [ ] Devices page shows accurate real-time status of all registered devices
- [ ] User with a Cloudflare-managed domain can deploy Nova at a custom subdomain with zero manual DNS config
- [ ] WoL + smart routing: sleeping GPU device auto-wakes when inference is needed, task completes without manual intervention

---

## 🔜 Phase 9 — Infrastructure + Triggers + Computer Use

**Infrastructure hardening:**
- Periodic Reaper — background `asyncio.create_task` replacing startup-only stale recovery
- Docker Compose profiles — `--profile mac`, `--profile gpu`, `--profile cpu`
- Webhook system — outbound POST on task/goal lifecycle events; persistent retry queue

**Triggered execution (Autonomy Level 3):**
- Inbound webhooks — GitHub PR opened → Nova reviews it automatically
- Cron scheduling — "run a security audit every Monday at 9am"
- Event subscriptions — watch a file path, a Slack channel, an email inbox

**Computer Use — Live Browser Automation:**

> **Status: Requires architectural decisions before implementation.** The four open questions below
> must be discussed and resolved before work begins on this subsystem.

Nova gets a real browser it can see and control. Users watch it work in real-time from the dashboard. The agent uses vision models to understand what's on screen and decides what to do next — navigate, click, type, scroll, inspect DevTools. Every action is recorded for audit and replay.

**Architecture overview:**

```
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard                                                       │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Live Browser Viewer                                    │     │
│  │  (WebSocket-streamed viewport frames)                   │     │
│  │                                                         │     │
│  │  ┌───────────────────────────────────────────────────┐  │     │
│  │  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  │     │
│  │  │ ░░  Live view of what Nova sees and does        ░░ │  │     │
│  │  │ ░░  in the browser — navigation, clicks, forms  ░░ │  │     │
│  │  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  │     │
│  │  └───────────────────────────────────────────────────┘  │     │
│  │  Action log: [navigate google.com] [click #search] ... │     │
│  └────────────────────────────────────────────────────────┘     │
└──────────────────────┬──────────────────────────────────────────┘
                       │ WebSocket (viewport frames + action events)
                       │
┌──────────────────────┴──────────────────────────────────────────┐
│ Orchestrator                                                     │
│                                                                   │
│  Vision Loop:                                                     │
│  1. browser_screenshot → capture current page                     │
│  2. Send screenshot to vision model (Claude, GPT-4o)              │
│  3. Model decides next action (click, type, scroll, navigate)     │
│  4. Execute action via CDP                                        │
│  5. Wait for page settle → repeat                                 │
│                                                                   │
│  Browser Tools (registered in tool catalog):                      │
│  • browser_navigate(url)                                          │
│  • browser_click(selector | coordinates)                          │
│  • browser_type(selector, text)                                   │
│  • browser_scroll(direction, amount)                              │
│  • browser_screenshot() → returns image for vision model          │
│  • browser_read_page() → returns page text/DOM snapshot           │
│  • browser_devtools(query) → inspect DOM, network, console        │
│  • browser_wait(condition) → wait for selector, navigation, idle  │
│  • browser_tabs() → list/switch/close tabs                        │
└──────────────────────┬──────────────────────────────────────────┘
                       │ CDP (Chrome DevTools Protocol) over WebSocket
                       │
┌──────────────────────┴──────────────────────────────────────────┐
│ Browser Container (Chromium + Playwright)                         │
│                                                                   │
│  Headless or headed Chromium instance                             │
│  Exposes CDP endpoint for orchestrator control                    │
│  Screencast API streams viewport frames                           │
│  Sandboxed: --no-sandbox, seccomp, network-restricted optional    │
└──────────────────────────────────────────────────────────────────┘
```

**Dashboard browser viewer features:**
- Embedded live viewport in a dashboard page (or panel within Tasks)
- Real-time frame streaming — see exactly what the agent sees
- Action overlay — highlight where Nova is clicking, what it's typing
- Action log sidebar — timestamped sequence of every browser action
- Task association — viewer is scoped to a specific task's browser session
- Screenshot gallery — all screenshots captured during the task, browsable after completion

**Vision loop — how the agent "sees":**
- Agent calls `browser_screenshot()` → gets a PNG/JPEG of the current viewport
- Screenshot sent to a vision-capable model (Claude with vision, GPT-4o) as part of the tool result
- Model reasons about what's on screen and decides the next action
- Actions executed via CDP → page updates → next screenshot → loop
- `browser_read_page()` as a cheaper alternative when vision isn't needed (returns extracted text, DOM structure, or accessibility tree)

**Action recording and replay:**
- Every browser action stored as a structured event: `{timestamp, action, params, screenshot_before, screenshot_after}`
- Stored as task artifacts (artifact_type: `browser_recording`)
- Replayable in the dashboard — step through the sequence with before/after screenshots
- Exportable as Playwright test scripts for CI regression testing

**Browser tools registered in the tool catalog:**

| Tool | Description |
|---|---|
| `browser_navigate` | Navigate to URL, wait for load |
| `browser_click` | Click element by CSS selector, XPath, or x/y coordinates |
| `browser_type` | Type text into a focused element or specified selector |
| `browser_scroll` | Scroll page or element (up/down/left/right, by pixels or pages) |
| `browser_screenshot` | Capture viewport screenshot, return as image for vision model |
| `browser_read_page` | Extract page content as text, DOM snapshot, or accessibility tree |
| `browser_devtools` | Query Chrome DevTools — DOM inspection, network requests, console logs, performance |
| `browser_wait` | Wait for selector to appear, navigation to complete, or network idle |
| `browser_tabs` | List open tabs, switch between tabs, open/close tabs |
| `browser_evaluate` | Execute JavaScript in the page context (sandboxed) |

### Open Architectural Decisions

> **These must be discussed and resolved before implementation begins.**

#### Decision 1: Dashboard viewport streaming approach

How does the user watch Nova use the browser in real-time?

| Option | How it works | Pros | Cons | Recommendation |
|---|---|---|---|---|
| **A. CDP Screencast** | Use Chrome's `Page.startScreencast` API to stream JPEG frames via CDP. Orchestrator forwards frames over WebSocket to the dashboard. | Lightweight — no extra infrastructure. We already have CDP access for browser control. Agent needs screenshots anyway, so frames are a byproduct. | Lower frame rate (5-15 fps typical). No direct user interaction with the viewport. Frame quality depends on JPEG compression settings. | **Recommended for v1.** Simplest path, leverages existing CDP connection, and watch-only is the right starting point. |
| **B. noVNC** | Run a VNC server (e.g. x11vnc) inside the browser container with a virtual framebuffer (Xvfb). Dashboard embeds a noVNC client (JavaScript VNC viewer). | True pixel-perfect live view. Built-in support for user interaction (click/type in the viewer). Mature ecosystem. | Heavier — needs Xvfb + window manager + VNC server in the container. More moving parts. Extra protocol layer (VNC) on top of CDP. | Better for Phase 2 if interactive user control is needed. |
| **C. WebRTC** | Stream the browser viewport as a WebRTC video stream. | Lowest latency, adaptive bitrate, real-time feel. | Most complex to set up. Needs STUN/TURN for non-local deployments. Overkill for an admin watching an agent work. | Over-engineered for this use case. |

#### Decision 2: User interaction model

Can the user interact with the browser, or just watch?

| Option | Description | Pros | Cons | Recommendation |
|---|---|---|---|---|
| **A. Watch-only** | Dashboard shows a read-only live viewport. User observes but cannot click, type, or intervene. | Simple to build. No conflict between agent and user input. No input forwarding needed. | User can't help if agent is stuck. Can't "nudge" the agent by clicking the right thing. | **Recommended for v1.** Avoids the complexity of shared control. Agent can be guided via the existing human review queue instead. |
| **B. Pause-and-takeover** | User can pause the agent's browser actions, interact with the browser manually, then resume the agent. | User can unblock stuck agents. Useful for authentication flows (user logs in, then hands back). | Needs pause/resume state machine. Must handle mid-action interrupts cleanly. More complex UI. | Good for v2. Design the CDP connection so this is possible later. |
| **C. Shared control** | Both user and agent can interact simultaneously. | Maximum flexibility. | Race conditions (agent clicks while user types). Very hard to get right. Confusing UX. | Not recommended — the conflict handling isn't worth it. |

#### Decision 3: Browser lifecycle

How are browser instances created and destroyed?

| Option | Description | Pros | Cons | Recommendation |
|---|---|---|---|---|
| **A. Per-task ephemeral** | Each task that needs a browser gets a fresh Chromium instance. Destroyed when the task completes. | Clean state — no session leakage between tasks. Simple mental model. Easy cleanup. Security: no cookies/credentials persist. | Startup cost (~2-3s for cold Chromium). Resource allocation per task. | **Recommended.** Browser tasks are inherently long-running (seconds to minutes), so 2-3s startup is negligible. Clean state is critical for an autonomous system. |
| **B. Persistent pool** | Pre-warmed browser instances recycled across tasks. Pool manager assigns instances and cleans state between uses. | Fast — no startup delay. Efficient resource usage for burst workloads. | Must guarantee clean state between tasks (clear cookies, storage, close tabs, reset permissions). Session leakage is a security risk. Pool sizing and lifecycle complexity. | Only worthwhile if browser tasks become high-frequency. Not needed for v1. |
| **C. Long-lived sidecar** | Single browser instance always running, shared across all tasks sequentially. | Simplest infrastructure. Always ready. | No isolation between tasks. If one task corrupts browser state, all subsequent tasks are affected. Can't run concurrent browser tasks. | Too fragile for autonomous agents. |

#### Decision 4: Where does the browser container run?

| Option | Description | Pros | Cons | Recommendation |
|---|---|---|---|---|
| **A. Docker Compose profile sidecar** | Browser runs as a service in `docker-compose.yml` under `--profile browser`. Started with `docker compose --profile browser up`. Always running when enabled. Orchestrator connects via CDP over the Docker network. | Simple setup. No Docker socket access needed. Consistent with existing service architecture. Easy to enable/disable. | Uses resources even when no browser task is running (unless using per-task lifecycle). Single instance limits concurrency. | **Recommended for v1.** Fits the existing Docker Compose architecture. Use the profile so it's opt-in — users who don't need browser capabilities don't pay the resource cost. |
| **B. On-demand container** | Orchestrator spawns a browser container when a task needs one, destroys it after. Requires Docker socket access or a container management API. | Perfect resource efficiency — only runs when needed. Natural per-task isolation. | Needs Docker socket mount (security concern) or a sidecar container manager. Adds startup latency. More complex orchestration. | Better for production/multi-tenant deployments. Phase 2 consideration. |
| **C. In the orchestrator container** | Install Chromium directly in the orchestrator's Docker image. Playwright runs in-process. | Zero network overhead. Simplest code path. | Bloats orchestrator image significantly (~400MB for Chromium). Security: browser exploits could compromise the orchestrator. No isolation. | Not recommended — violates service separation. |

### Implementation outline (pending decisions)

Assuming the recommended options (CDP Screencast, watch-only, per-task ephemeral, Docker Compose profile sidecar):

| Step | Deliverable |
|---|---|
| **1** | Browser container image — Chromium + Playwright server, exposes CDP endpoint, Docker Compose profile |
| **2** | Browser tools — `browser_navigate`, `browser_click`, `browser_type`, `browser_scroll`, `browser_screenshot`, `browser_read_page` registered in tool catalog |
| **3** | Vision loop integration — `browser_screenshot` returns image, orchestrator routes to vision-capable model |
| **4** | CDP Screencast forwarding — orchestrator WebSocket endpoint streams viewport frames to dashboard |
| **5** | Dashboard browser viewer — embedded viewport component with action log, linked to active task |
| **6** | Action recording — structured event log stored as task artifacts, viewable post-task |
| **7** | DevTools tools — `browser_devtools`, `browser_evaluate` for DOM/network/console inspection |
| **8** | Action replay — dashboard component to step through recorded browser sessions |

---

## 🔜 Phase 9b — Integrated Web IDE & Git Workspace

**Motivation:** Nova already has file tools, git tools, and a mounted workspace volume — but users have no way to *see* the code Nova is writing without SSH or a local editor. Adding a web-based IDE turns Nova from "an AI platform you talk to" into "a complete development environment where AI works alongside you." This is especially powerful for Pi (Phase 10) and cloud (Phase 11) users who may not have a local IDE at all.

**Target users:**
- Developers who want to review/edit Nova's output in real time
- Pi users accessing Nova from a tablet, phone, or thin client
- Cloud-hosted Nova users who need a full IDE without local installs
- Teams who want GitHub/GitLab integration for repo-based workflows

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Dashboard                                                    │
│  ┌──────────────┐  ┌──────────────────────────────────────┐ │
│  │ Task Board    │  │ Web IDE (code-server iframe)         │ │
│  │ Agent Feed    │  │                                      │ │
│  │ Pipeline View │  │  ┌──────────────────────────────┐   │ │
│  │               │  │  │ VS Code in browser            │   │ │
│  │ "Open in IDE" │──│  │ Same workspace volume as      │   │ │
│  │  buttons on   │  │  │ Nova agents — live file sync  │   │ │
│  │  artifacts    │  │  └──────────────────────────────┘   │ │
│  └──────────────┘  └──────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │     code-server         │  ← VS Code in browser
              │  (Docker Compose svc)   │     codercom/code-server
              │                         │
              │  volumes:               │
              │   - workspace:/project  │  ← Same volume as orchestrator
              └─────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │  GitHub / GitLab API    │  ← OAuth integration
              │  Clone, branch, push    │     via recovery or orchestrator
              └─────────────────────────┘
```

### Tier 1: Web IDE via code-server (Core Deliverable)

**What:** Add [code-server](https://github.com/coder/code-server) as a Docker Compose profile service.

```yaml
# docker-compose.yml
code-server:
  <<: *nova-common
  profiles: ["ide"]
  image: codercom/code-server:latest
  environment:
    PASSWORD: ${CODE_SERVER_PASSWORD:-nova}
    DEFAULT_WORKSPACE: /home/coder/project
  volumes:
    - ${NOVA_WORKSPACE:-./workspace}:/home/coder/project:rw
  ports:
    - "8443:8080"
  healthcheck:
    <<: *nova-healthcheck
    test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
```

**Key design decisions:**
- **Profile-gated** (`--profile ide`) — opt-in, doesn't consume resources unless enabled
- **Same workspace volume** — agents write files, user sees them instantly in the editor
- **Password from `.env`** — setup script configures this
- **nginx proxy** — `/ide/` route proxied to code-server (WebSocket support required)

**Dashboard integration:**
- New "IDE" nav item (only visible when code-server profile is active)
- Embedded iframe or "Open in new tab" link
- "Open in IDE" button on task artifacts (code files, configs)
- File path links in agent activity feed open directly in the IDE

**nginx config addition:**
```nginx
location /ide/ {
    set $codeserver http://code-server:8080;
    proxy_pass $codeserver/;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";  # WebSocket support
    proxy_set_header Host $host;
}
```

### Tier 2: Git Integration (GitHub / GitLab)

**OAuth flow in dashboard Settings → Git section:**

| Step | Description |
|---|---|
| **1. Connect** | User clicks "Connect GitHub" → OAuth redirect → token stored in DB (encrypted) |
| **2. List repos** | Dashboard shows user's repos (public + private) |
| **3. Clone** | User picks a repo → cloned into workspace volume → appears in IDE |
| **4. Branch** | Nova creates a feature branch for each task (configurable) |
| **5. Work** | Nova agents read/write files in the cloned repo |
| **6. Review** | User reviews changes in the web IDE's built-in diff view |
| **7. Push** | User (or Nova) commits and pushes back to origin |
| **8. PR** | Optional: Nova opens a PR with task summary as description |

**Supported providers:**

| Provider | Auth Method | API |
|---|---|---|
| **GitHub** | GitHub App or OAuth App | REST v3 + GraphQL v4 |
| **GitLab** | OAuth2 | REST v4 |
| **Gitea** | OAuth2 | REST v1 |
| **Bitbucket** | OAuth2 | REST v2 |

**Git settings in dashboard:**
- Connected accounts (GitHub, GitLab, etc.) with connect/disconnect
- Default branch naming: `nova/<task-id>-<slug>` (configurable)
- Auto-push on task completion (toggle)
- Auto-PR on task completion (toggle)
- PR template (markdown, with `{{task_summary}}`, `{{agent_findings}}` variables)

**New orchestrator endpoints:**

```
POST   /api/git/clone          { repo_url, branch?, path? }
POST   /api/git/checkout       { branch }
POST   /api/git/commit         { message, files[]? }
POST   /api/git/push           { remote?, branch? }
POST   /api/git/create-pr      { title, body, base, head }
GET    /api/git/status          → { branch, changed_files[], ahead, behind }
GET    /api/git/repos           → list from connected provider
GET    /api/git/branches        → list branches in current repo
```

### Tier 3: VS Code Extension (Separate Distribution)

For power users who prefer native VS Code over the web IDE.

**Extension features:**
- **Nova sidebar panel** — task list, agent activity feed, pipeline status
- **"Ask Nova" command** — send selected code/file as context to a new task
- **Diff view** — review Nova's proposed changes before accepting
- **Status bar** — connection status, active task count, model in use
- **CodeLens** — inline "Explain with Nova" / "Refactor with Nova" on functions
- **Terminal integration** — `nova task submit "..."` from the integrated terminal

**Extension talks to Nova via:**
- nova-sdk (Phase 6c) over HTTP
- SSE for real-time updates (task progress, agent activity)
- WebSocket for streaming responses

**Distribution:**
- VS Code Marketplace (free)
- Also works with VSCodium, Cursor, Windsurf (same extension API)

### Workflow: End-to-End Example

```
1. User enables IDE profile:
   docker compose --profile ide up -d

2. User opens Nova dashboard → Settings → Git → "Connect GitHub"
   → OAuth flow → token saved

3. User goes to dashboard → IDE → "Clone Repo"
   → Picks "myorg/backend-api" → Cloned to /workspace/backend-api

4. User submits task: "Add rate limiting to POST /api/users (100 req/min)"

5. Quartet pipeline executes:
   - Context Agent reads the repo, finds relevant files
   - Task Agent writes rate limiting middleware + tests
   - Guardrail Agent checks for security issues
   - Code Review Agent approves

6. Files appear instantly in the web IDE (same workspace volume)

7. User reviews diff in IDE, makes minor tweaks

8. User clicks "Push & Open PR" in dashboard
   → Nova commits, pushes to nova/task-42-rate-limiting branch
   → Opens PR with task summary + guardrail findings as description

9. Team reviews PR on GitHub as normal
```

### What We're NOT Building

- **Not forking VS Code** — Cursor/Windsurf have 50+ engineer teams maintaining forks. Not worth it.
- **Not building a custom editor** — Code editors are a solved problem. We use code-server.
- **Not replacing GitHub/GitLab** — Nova integrates with them, doesn't compete with them.
- **Not adding CI/CD** — That's the user's existing pipeline. Nova opens PRs, CI runs on the PR.

### Settings Page Updates

**New "IDE & Git" section in Settings:**
- IDE status (running / not enabled)
- "Enable IDE" button (runs `docker compose --profile ide up -d`)
- IDE password configuration
- Connected Git accounts (GitHub, GitLab, etc.)
- Default branch naming pattern
- Auto-push / auto-PR toggles
- PR template editor

### Testing & Validation

- [ ] code-server starts and serves VS Code in browser
- [ ] Workspace volume shared — file written by orchestrator appears in IDE within 1s
- [ ] nginx proxy works for IDE (including WebSocket for terminal)
- [ ] GitHub OAuth flow: connect → list repos → clone → push → PR
- [ ] GitLab OAuth flow: same as above
- [ ] "Open in IDE" button from task artifact navigates to correct file
- [ ] IDE works on Pi 4 (code-server supports ARM64)
- [ ] IDE accessible from cloud deployment (Phase 11)

### Success Criteria

- [ ] Web IDE usable within 5 minutes of enabling the profile
- [ ] GitHub clone-to-PR workflow works end-to-end without leaving the browser
- [ ] File changes from Nova agents visible in IDE within 1 second
- [ ] Works on ARM64 (Pi) and x86_64
- [ ] VS Code extension connects to Nova and shows task status

### Implementation Order

| Step | Deliverable | Effort |
|---|---|---|
| **1** | code-server Docker Compose service (profile: ide) | Small |
| **2** | nginx proxy for `/ide/` with WebSocket support | Small |
| **3** | Dashboard "IDE" page (iframe embed + "Open in IDE" links) | Small |
| **4** | Git clone/push/status endpoints in orchestrator | Medium |
| **5** | GitHub OAuth flow in dashboard Settings | Medium |
| **6** | GitLab OAuth flow | Medium |
| **7** | Auto-branch + auto-PR on task completion | Medium |
| **8** | VS Code extension (sidebar, commands, CodeLens) | Large |

---

## 🔜 Phase 10 — Edge Computing & Single-Board Deployment (Raspberry Pi)

**Motivation:** Compete with open-source platforms like OpenClaw that can run on constrained hardware. Enable Nova to run on a Raspberry Pi 4 (4GB RAM) or similar single-board computers by providing multiple deployment profiles, resource optimization, and intelligent fallback strategies.

**Target users:**
- Hobbyists with Pi 4 / Pi 5 who want local orchestration + cloud LLMs
- Users in bandwidth-constrained regions who can't run full compute locally
- Educational / maker communities (Pi is cheap, accessible)
- Anyone who wants to avoid buying expensive hardware

### Deployment Profiles

Nova setup script detects hardware and offers three profiles:

**Profile 1: Cloud-only (minimal local footprint)**
- Runs: orchestrator, llm-gateway, recovery, dashboard
- Skips: memory-service (no local embeddings), ollama (no local models)
- Database: RDS or other cloud-hosted PostgreSQL
- Resource usage: ~800MB RAM
- Trade-off: No semantic memory (keyword-only search), all LLM calls → cloud APIs
- Use case: Pi 4 with 2-4GB RAM, no local compute

**Profile 2: Cloud-first with local memory (balanced)**
- Runs: orchestrator, llm-gateway, memory-service, recovery, dashboard
- Skips: ollama
- Database: RDS or cloud PostgreSQL
- memory-service: Works against cloud DB, handles embedding inference locally
- Resource usage: ~1.2GB RAM (postgres now remote)
- Trade-off: Memory/semantic search works, but queries go to cloud DB; LLMs go to cloud
- Use case: Pi 4 with 4GB RAM, wants semantic search but no local model serving
- Environment: `LLM_ROUTING_STRATEGY=cloud-only`, `DATABASE_URL=<RDS>`

**Profile 3: Distributed architecture (full-featured)**
- Pi runs: dashboard, recovery (UI layer only)
- Another machine (laptop, NUC, VPS) runs: orchestrator, llm-gateway, memory-service
- Database: Shared PostgreSQL (local or cloud)
- Resource usage on Pi: ~300MB (just HTTP proxy + recovery sidecar)
- Trade-off: Requires second device, but gets full Nova features locally on that device
- Use case: User has multiple machines and wants lightweight UI on Pi, powerful compute elsewhere
- Environment: Dashboard API proxies to remote orchestrator + llm-gateway

### Hardware Detection & Setup Flow

**New setup.sh logic:**

```bash
# Detect hardware
TOTAL_RAM=$(free -h | awk 'NR==2 {print $2}')
CPU_CORES=$(nproc)

# Recommend profile
if [ "$TOTAL_RAM" -lt "4GB" ]; then
  echo "Detected <4GB RAM. Recommend Cloud-only profile."
  echo "Available profiles:"
  echo "  1. Cloud-only (minimal, ~800MB)"
  echo "  2. Distributed (run compute on another machine)"
  read -p "Choose profile (1 or 2): " PROFILE
elif [ "$TOTAL_RAM" -lt "8GB" ]; then
  echo "Detected <8GB RAM. Recommend Cloud-first with memory."
  echo "Available profiles:"
  echo "  1. Cloud-first (local memory, cloud LLM, ~1.2GB)"
  echo "  2. Distributed (UI on Pi, compute elsewhere)"
  echo "  3. Local (full local, may be slow)"
  read -p "Choose profile (1-3): " PROFILE
else
  echo "Sufficient RAM for full local deployment."
  read -p "Use full local (y) or distributed (n)? " LOCAL_MODE
fi

# Generate appropriate docker-compose overlay
case $PROFILE in
  1) cp docker-compose.cloud-only.yml docker-compose.override.yml ;;
  2) cp docker-compose.cloud-first.yml docker-compose.override.yml ;;
  3) cp docker-compose.distributed.yml docker-compose.override.yml ;;
esac

# Prompt for cloud config (RDS, cloud fallback, etc.)
if [ "$PROFILE" != "3" ]; then
  read -p "Use AWS RDS for database? (y/n): " USE_RDS
  if [ "$USE_RDS" = "y" ]; then
    read -p "RDS endpoint (e.g., nova.xxxxx.us-east-1.rds.amazonaws.com): " RDS_HOST
    echo "DATABASE_URL=postgresql+asyncpg://nova:${POSTGRES_PASSWORD}@${RDS_HOST}:5432/nova" >> .env
  fi
fi
```

### Docker Compose Overlays

**docker-compose.cloud-only.yml**
- Excludes: memory-service, ollama
- postgres: replaced with environment variable pointing to RDS
- orchestrator, llm-gateway, recovery, dashboard only
- All services use `LLM_ROUTING_STRATEGY=cloud-only`

**docker-compose.cloud-first.yml**
- Excludes: ollama
- postgres: can be local or RDS
- memory-service uses local pgvector but queries hit RDS
- llm-gateway: `LLM_ROUTING_STRATEGY=cloud-first`

**docker-compose.distributed.yml**
- Pi runs: dashboard + recovery
- Environment: `ORCHESTRATOR_URL=http://<remote-machine>:8000`
- dashboard proxies `/api/*` to remote orchestrator
- memory-service & llm-gateway run on remote machine

### Settings Page Updates

**New "Deployment" section in Settings:**
- Display current profile (Cloud-only / Cloud-first / Distributed)
- Show hardware specs (RAM, CPU cores) for user awareness
- "Migrate to different profile" button (guides through RDS setup, etc.)

**LLM Routing section conditional rendering:**
- Cloud-only: Hide Ollama, WoL, local model options
- Cloud-first: Show Ollama status but mark as "disabled" (optional), show local memory config
- Distributed: Show "remote orchestrator" status instead of local services

### Database Configuration

**Option A: Local PostgreSQL (default for full-featured)**
- Works on Pi 4+ with 4GB RAM
- Setup: `docker-compose up postgres`
- Backup: Via recovery service UI

**Option B: AWS RDS (recommended for Pi)**
- Setup: One-time AWS account + RDS creation
- Cost: ~$15-20/month for micro instance (eligible for free tier first year)
- Benefit: 2GB local memory freed up; automatic backups; high availability
- Setup flow: User provides RDS endpoint, Nova adds it to `.env`
- Connection pooling: Use RDS Proxy to avoid connection exhaustion (Pi has limited resources)

**Option C: Other cloud databases**
- Supabase (managed Postgres), CockroachDB, PlanetScale, etc.
- Any PostgreSQL-compatible service works
- `DATABASE_URL` is agnostic to provider

### Memory-Service Optimization for Pi

- Disable embedding model caching (saves RAM)
- Use smaller embedding model if available (e.g., DistilBERT instead of nomic-embed-text)
- Keyword-only retrieval in cloud-only profile (skip vector search entirely)
- Connection pooling: Limit to 2-3 DB connections instead of default 5

### Testing & Validation

- [ ] Deploy on actual Pi 4 (4GB) with each profile
- [ ] Measure startup time, memory usage, latency
- [ ] Test cold-start (Pi offline, comes back online) with cloud DB
- [ ] Verify dashboard loads and proxies to remote orchestrator (distributed mode)
- [ ] Stress test: 5 concurrent tasks on cloud-only profile

### Documentation

- **docs/deployment-edge.md** — Pi-specific guide, profile selection flowchart, hardware requirements
- **docs/deployment-rds.md** — Step-by-step AWS RDS setup (terraform config optional)
- **docs/deployment-distributed.md** — How to run dashboard on Pi, orchestrator elsewhere
- Update CLAUDE.md: Mention profiles, RDS option, deployment topology

### Success Criteria

- [ ] Pi 4 with 4GB RAM can run cloud-only profile with <15s startup
- [ ] Dashboard responsive with remote orchestrator (latency <200ms)
- [ ] Setup script detects hardware and recommends profile (>95% accuracy)
- [ ] RDS migration is documented and tested

---

## 🔜 Phase 11 — Multi-Cloud Deployment & Scaling

**Motivation:** Nova currently assumes single-machine or single-datacenter deployment. This phase enables:
1. Running Nova services across multiple cloud providers (AWS, GCP, Azure, Hetzner, Linode, DigitalOcean, etc.)
2. Horizontal scaling of stateless services (orchestrator, llm-gateway, memory-service)
3. Multi-region redundancy
4. Load balancing across instances
5. Kubernetes-first deployment (eventually)

**Target users:**
- Teams running Nova for production workloads
- Users wanting geographic distribution (low latency, data sovereignty)
- Organizations scaling from hobby → production
- Companies leveraging existing cloud infrastructure

### Deployment Targets

**Target clouds (in priority order):**
1. **AWS** (widest adoption, mature tooling) — ECS, RDS, ElastiCache, ALB
2. **DigitalOcean** (affordable, simple, popular with developers) — Droplets, Managed Postgres, Managed Redis, Load Balancer
3. **Linode / Akamai** (good price-to-performance, API-first) — Linode Kubernetes Engine, Managed DB
4. **Hetzner** (European datacenter, cost-effective) — Cloud Servers, volumes, load balancer
5. **GCP** (strong if user already in ecosystem) — Cloud Run, Cloud SQL, Memorystore
6. **Azure** (enterprise adoption) — Container Instances, Database for PostgreSQL, Cache for Redis
7. **Heroku** (simplicity-first, smallest setup friction) — Apps, Postgres, Redis add-ons

### Deployment Patterns

#### Pattern 1: Single Cloud, Single Machine (Status Quo)
- All 8 services on one VM (or Docker Compose stack)
- Current architecture
- Works for hobby / small-scale use

#### Pattern 2: Single Cloud, Horizontally Scaled
- Stateless services (orchestrator, llm-gateway, memory-service) behind load balancer
- Shared stateful services (postgres, redis, recovery) on managed services
- Example: 3x orchestrator instances, 1x shared RDS, 1x managed Redis
- Cost: ~$50-100/month on DigitalOcean / Linode
- Cloud provider: supports docker / kubernetes

#### Pattern 3: Multi-Region, Single Cloud
- Primary region: Full deployment
- Secondary regions: Read replicas, failover orchestrators
- Database: Read replicas in each region; primary writes to main region
- LLM gateway: Local instances in each region for lower latency
- Use case: Global user base, data residency requirements
- Cost: ~$200-300/month for 2-region setup

#### Pattern 4: Multi-Cloud Hybrid
- Production on AWS (stability, scale)
- Failover on DigitalOcean (cost-effective backup)
- Database: Primary on AWS RDS, replica on DigitalOcean Postgres
- LLM gateway routes to both clouds (cost optimization)
- Use case: Hedge provider risk, lock-in avoidance
- Cost: ~$150-250/month

#### Pattern 5: Kubernetes (Future, Phase 12)
- Nova services as Helm chart
- Deploy to any K8s cluster (EKS, GKE, AKS, DigitalOcean K8s, Linode K8s)
- Horizontal pod autoscaling based on task queue length
- Service mesh (Istio optional) for inter-service routing
- Not in Phase 11 — Phase 11 focuses on Docker-based single-cloud scaling

### Infrastructure-as-Code

**Terraform modules (one per provider):**

```
terraform/
  ├── aws/
  │   ├── main.tf               # ECS, RDS, ElastiCache, ALB
  │   ├── variables.tf          # Instance type, region, availability zones
  │   └── outputs.tf            # Load balancer DNS, RDS endpoint, etc.
  ├── digitalocean/
  │   ├── main.tf               # Droplets, Managed Postgres, Managed Redis
  │   └── variables.tf
  ├── gcp/
  │   ├── main.tf               # Cloud Run, Cloud SQL, Memorystore
  │   └── variables.tf
  ├── azure/
  │   ├── main.tf               # Container Instances, Azure Database for PostgreSQL
  │   └── variables.tf
  ├── hetzner/
  │   ├── main.tf               # Cloud Servers, managed services
  │   └── variables.tf
  └── common/
      ├── docker-compose.tf      # Shared Docker Compose overlay
      ├── networking.tf          # Load balancer, DNS
      └── monitoring.tf          # Prometheus, Grafana (optional Phase 11.5)
```

**Example: Terraform for DigitalOcean (single region, horizontally scaled)**

```hcl
# terraform/digitalocean/main.tf
resource "digitalocean_app" "nova_orchestrator" {
  name             = "nova-orchestrator"
  instance_count   = var.orchestrator_replicas  # 3
  instance_size_slug = "basic-xs"               # ~$5/month each
}

resource "digitalocean_database_cluster" "postgres" {
  name       = "nova-postgres"
  engine     = "pg"
  version    = "16"
  size       = "db-s-1vcpu-1gb"                 # ~$15/month
  region     = var.region
  node_count = 1
}

resource "digitalocean_redis_cluster" "cache" {
  name       = "nova-redis"
  size       = "db-s-1vcpu-1gb"                 # ~$15/month
  region     = var.region
  num_nodes  = 1
}

resource "digitalocean_loadbalancer" "nova" {
  name   = "nova-lb"
  region = var.region

  forwarding_rule {
    entry_protocol  = "http"
    entry_port      = 80
    target_protocol = "http"
    target_port     = 8000  # orchestrator
  }

  healthcheck {
    protocol = "http"
    port     = 8000
    path     = "/health/live"
  }
}
```

### Setup & Deployment

**New setup flow for multi-cloud:**

```bash
./setup --cloud

# Prompts:
# 1. Which cloud? (aws / do / gcp / azure / hetzner / linode)
# 2. Deployment pattern? (single-machine / horizontally-scaled / multi-region)
# 3. Region / availability zone?
# 4. Number of orchestrator replicas? (1, 3, 5)
# 5. Postgres size? (micro / small / medium)
# 6. Redis size?

# Generates:
# - terraform/chosen-cloud/terraform.tfvars
# - .env with cloud-specific database URLs
# - shell script to run terraform apply + docker-compose pull

# User runs:
# bash ./deploy-to-cloud.sh
```

### Service Discovery & Load Balancing

**Challenge:** In a multi-machine setup, services need to find each other.

**Solution 1: Cloud Load Balancer (recommended for Phase 11)**
- Provider's load balancer sits in front of orchestrator, llm-gateway, memory-service
- Services use provider-specific DNS names (e.g., `postgres.c.example.com`)
- Drawback: Load balancer cost, latency, limited session affinity

**Solution 2: Consul / Etcd (Phase 12, advanced)**
- Service mesh for inter-service discovery and routing
- Phase 11 explicitly skips this (keep it simple)

**Solution 3: Fixed IPs & ENV (simplest)**
- Terraform outputs fixed IPs for each service
- docker-compose gets IPs injected via `.env`
- Works well for small clusters (up to 10 instances)
- Recommended for Phase 11

### Managed Services Configuration

Each cloud provider has different names and configurations:

| Service | AWS | DigitalOcean | GCP | Azure |
|---|---|---|---|---|
| **PostgreSQL** | RDS | Managed Postgres | Cloud SQL | Database for PostgreSQL |
| **Redis** | ElastiCache | Managed Redis | Memorystore | Cache for Redis |
| **Load Balancer** | ALB / NLB | Load Balancer | Cloud Load Balancing | Azure Load Balancer |
| **Container Orchestration** | ECS (Docker) | App Platform (Docker) | Cloud Run (containers) | Container Instances |
| **Cost monitoring** | AWS Cost Explorer | Billing API | GCP Billing | Azure Cost Management |

### Scaling Metrics & Auto-Scaling

**When to scale orchestrator:**
- Task queue depth > 10
- CPU utilization > 70%
- Memory usage > 80%

**When to scale llm-gateway:**
- Concurrent requests > 20
- Response latency > 2s
- Provider rate-limit errors increasing

**When to scale memory-service:**
- Database query latency > 500ms
- Embedding queue size > 100

**Implementation (Phase 11):**
- Manual scaling (update Terraform, re-apply)
- Phase 12: Auto-scaling groups (AWS ASG, DigitalOcean App Platform scaling)

### Cost Estimation & Monitoring

**Add cost estimation to dashboard:**
- Display current deployment topology
- Show estimated monthly cost
- "Cost breakdown" — per service, per region, per provider
- "Scale scenario" tool — what if we add 1 more region? +$X/month

**Providers to track:**
- Managed database costs
- Load balancer costs
- Data transfer (cross-region is expensive!)
- Compute instance costs

### Backup & Disaster Recovery

**Backup strategy (cloud-native):**
- PostgreSQL: Managed provider backup (AWS RDS automated backup, GCP Cloud SQL backup)
- Redis: Snapshot daily, stored in object storage (S3, Cloud Storage, Azure Blob)
- Recovery service: Still runs on a sidecar instance, provides manual restore UI

**Disaster recovery targets:**
- RTO (Recovery Time Objective): 15 minutes
- RPO (Recovery Point Objective): 1 hour (latest backup)

**Testing:**
- Quarterly DR drill: Destroy prod cluster, restore from backup, verify data integrity

### Documentation

- **docs/deployment-cloud.md** — Cloud provider comparison table, choosing a provider
- **docs/deployment-terraform.md** — Terraform usage, customizing variables, dry-run
- **docs/scaling.md** — When to scale, how to scale, cost optimization
- **docs/disaster-recovery.md** — Backup strategy, restore process, DR testing
- Update CLAUDE.md: Add "Multi-Cloud" section, mention Terraform

### Testing & Validation

- [ ] Deploy on AWS ECS with 2x orchestrator, 1x RDS
- [ ] Deploy on DigitalOcean App Platform (simplest cloud)
- [ ] Deploy on GCP Cloud Run (serverless, different model)
- [ ] Run load test: 100 concurrent tasks across 3-orchestrator cluster
- [ ] Verify failover: Kill 1 orchestrator, tasks re-queue correctly
- [ ] Test database failover: Simulate RDS outage, recovery behavior

### Success Criteria

- [ ] Cloud setup (Terraform) takes <30 minutes from zero to running
- [ ] Cost per month on DigitalOcean is <$50 (3x app, managed DB, managed Redis)
- [ ] Horizontal scaling of orchestrator is transparent to users (no code changes)
- [ ] Disaster recovery tested and documented
- [ ] At least 2 cloud providers fully supported (AWS, DigitalOcean)

---

## 🔜 Phase 12 — Modular Local Inference Backends + GPU Upgrade

**Motivation:** Nova is designed for parallel autonomous workflows — multiple tasks execute concurrently via Redis BRPOP. But Ollama serializes inference requests: when 5 tasks call the LLM simultaneously, they queue behind each other. For Nova to be an always-on AI replacement (chat + autonomous workflows + coding sessions concurrently), the inference layer must handle parallel requests efficiently. This phase also addresses multi-tenancy inference needs (Phase 13).

Nova should ship with **multiple inference backend options** — each has different strengths, and users should pick the right one (or run several) based on their hardware and workload. All four expose OpenAI-compatible APIs, and LiteLLM already abstracts the provider layer, so adding backends is a configuration concern, not an architecture change.

### Inference Backend Comparison

| Capability | Ollama | vLLM | llama.cpp (llama-server) | SGLang |
|-----------|--------|------|--------------------------|--------|
| **Concurrent batching** | Sequential queue (OLLAMA_NUM_PARALLEL limited) | Continuous batching — interleaves tokens across requests | Limited parallel slots via `-np` flag | Continuous batching + RadixAttention |
| **Multi-user serving** | Latency degrades linearly | Near-constant latency up to batch capacity | Better than Ollama, worse than vLLM/SGLang | Best-in-class for shared-prefix workloads |
| **VRAM efficiency** | Loads/unloads full models | PagedAttention — packs KV caches efficiently | Manual KV cache sizing, efficient for single model | RadixAttention — caches common prefixes (system prompts) across requests |
| **Model switching** | Hot-swap via `ollama pull`, evicts from VRAM | Single model per instance, restart to switch | Single model per instance | Single model per instance |
| **Quantization** | GGUF (widest variety, community models) | GPTQ, AWQ, FP8, GGUF (recent) | GGUF native (fastest GGUF inference) | GPTQ, AWQ, FP8, GGUF |
| **Structured output** | JSON mode (basic) | Outlines-based JSON schema enforcement | GBNF grammars (powerful, verbose) | Native JSON schema + regex constraints |
| **CPU inference** | Yes (good) | GPU only | Yes (excellent — original purpose) | GPU only |
| **Setup complexity** | Single binary, trivial | Python env, more config | Single binary, moderate flags | Python env, similar to vLLM |
| **Best for** | Model exploration, single-user, quick testing | Multi-tenant production serving, high throughput | CPU-only deployments, edge, GGUF specialization | Agent workloads (prefix caching wins big when agents share system prompts) |
| **Docker image** | `ollama/ollama` | `vllm/vllm-openai` | `ghcr.io/ggerganov/llama.cpp:server` | `lmsysorg/sglang` |

### Why SGLang is especially interesting for Nova

SGLang's **RadixAttention** automatically caches shared prefixes across requests. In Nova's architecture, every pipeline agent (Context, Task, Guardrail, Code Review) has a system prompt that's identical across all task executions. With 5 parallel tasks running the same pod, that's 20 agent calls sharing large system prompt prefixes. SGLang caches these in a radix tree — subsequent requests skip re-computing attention for the shared prefix. This is a significant speedup for exactly Nova's workload pattern.

### Recommended Backend Strategy

| Workload | Recommended Backend | Why |
|----------|-------------------|-----|
| **Single user, model experimentation** | Ollama | Hot-swap models, widest GGUF library, zero config |
| **Multi-tenant chat (Phase 13)** | vLLM or SGLang | Continuous batching handles concurrent users efficiently |
| **Parallel agent pipelines** | SGLang | RadixAttention prefix caching across agents sharing system prompts |
| **CPU-only / edge deployment (Phase 10)** | llama.cpp | Best CPU performance, smallest footprint |
| **Coding sessions (multiple concurrent)** | vLLM or SGLang | Long contexts + concurrent requests need batching |
| **Hybrid (recommended default)** | Ollama + SGLang | Ollama for variety, SGLang as primary serving engine |

### Hardware

**Current:** Dell PC with NVIDIA RTX 3060 Ti (8 GB VRAM) — runs Ollama over LAN, woken via WoL

**Target:** Upgrade to NVIDIA RTX 3090 (24 GB VRAM)
- Same PCIe slot, same power connector style as 3060 Ti
- Fits standard ATX cases — verify Dell case clearance (2.5-slot cooler) and PSU wattage (350W TDP, need 750W+ PSU)
- 24 GB VRAM enables: 70B Q4 model, or 30B Q8 model, or multiple concurrent 13B contexts

**Why RTX 3090:**
| GPU | VRAM | Price (used) | Verdict |
|-----|------|-------------|---------|
| **RTX 3090** | **24 GB** | **~$700-800** | **Best VRAM/dollar. Same generation as 3060 Ti — guaranteed driver compat. Recommended.** |
| RTX 3090 Ti | 24 GB | ~$800-900 | Marginal gain, 450W TDP. Not worth premium. |
| RTX 4090 | 24 GB | ~$1600-1800 | ~40% faster compute, same VRAM. 2x price. Overkill for 2-user household. |
| RTX 4080 | 16 GB | ~$900 | Less VRAM for more money. Bad value for inference. |
| RTX A5000 | 24 GB | ~$1200 | Workstation card. Same VRAM at higher cost. No advantage for inference. |

### Implementation

**Step 1: Hardware upgrade**
- Purchase RTX 3090 (used/refurbished)
- Verify Dell case dimensions (length clearance for 3090 cooler) and PSU wattage before purchasing
- Install GPU, verify with `nvidia-smi`

**Step 2: Docker Compose profiles for all backends**

Each backend gets its own Docker Compose profile. Users enable what they need — run one, two, or all four simultaneously on different ports.

```yaml
# Existing
ollama:
  image: ollama/ollama
  profiles: ["local-ollama"]
  ports: ["11434:11434"]

# New backends
vllm:
  image: vllm/vllm-openai:latest
  profiles: ["local-vllm"]
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
  volumes:
    - vllm-models:/root/.cache/huggingface
  environment:
    - MODEL=${VLLM_MODEL:-meta-llama/Llama-3.1-70B-Instruct-AWQ}
    - MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN:-4096}
    - GPU_MEMORY_UTILIZATION=0.90
  ports: ["8003:8000"]

sglang:
  image: lmsysorg/sglang:latest
  profiles: ["local-sglang"]
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
  volumes:
    - sglang-models:/root/.cache/huggingface
  environment:
    - MODEL_PATH=${SGLANG_MODEL:-meta-llama/Llama-3.1-70B-Instruct-AWQ}
    - MEM_FRACTION_STATIC=0.88
  ports: ["8004:30000"]

llama-cpp:
  image: ghcr.io/ggerganov/llama.cpp:server
  profiles: ["local-llamacpp"]
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
  volumes:
    - llamacpp-models:/models
  environment:
    - LLAMA_ARG_MODEL=/models/${LLAMACPP_MODEL:-model.gguf}
    - LLAMA_ARG_CTX_SIZE=${LLAMACPP_CTX_SIZE:-4096}
    - LLAMA_ARG_N_GPU_LAYERS=99
    - LLAMA_ARG_PARALLEL=${LLAMACPP_PARALLEL:-4}
  ports: ["8005:8080"]
```

**Step 3: LLM Gateway integration**
- LiteLLM already supports all four as OpenAI-compatible providers with custom base URLs
- Add each backend as a provider in `llm-gateway` config
- Routing strategy configurable per-model: which backend serves which model
- Dashboard settings page: configure active backends, assign models to backends

**Step 4: Setup script integration**
- `./setup` detects GPU and offers backend selection:
  - No GPU → Ollama (CPU) or llama.cpp (CPU)
  - GPU detected → recommend SGLang or vLLM for production, Ollama for experimentation
  - Multi-backend → enable both Ollama (model variety) + SGLang (primary serving)
- Selected profiles written to `.env` (`COMPOSE_PROFILES=local-ollama,local-sglang`)

**Step 5: Dashboard backend management**
- Models page shows which backend serves each model
- Backend health status (running/stopped/error) with VRAM usage
- "Start/stop backend" controls (via recovery service Docker API)
- Benchmark button: run a quick concurrent-request test against each active backend

### Testing & Validation

- [ ] RTX 3090 installed, `nvidia-smi` shows 24 GB VRAM
- [ ] Each backend starts independently via its Docker Compose profile
- [ ] LLM Gateway routes to each backend correctly
- [ ] Benchmark: 5 concurrent chat completions — compare latency across all 4 backends
- [ ] Benchmark: 3 parallel pipeline tasks — measure SGLang prefix caching speedup
- [ ] Verify multiple backends can coexist (e.g., Ollama on CPU + SGLang on GPU)
- [ ] Setup script correctly detects GPU and recommends backends
- [ ] Dashboard shows backend status and model assignments

### Success Criteria

- [ ] 5 concurrent inference requests on SGLang/vLLM complete with <2x single-request latency (vs Ollama's ~5x)
- [ ] 70B Q4 model loads and serves on RTX 3090 via at least 2 backends
- [ ] Nova pipeline runs 3 parallel tasks without inference bottleneck
- [ ] Setup script offers all 4 backend options with smart defaults
- [ ] User can switch backends without code changes (config only)

---

## 🔜 Phase 13 — Multi-Tenancy

**Motivation:** Nova is currently single-user. To support multiple people (starting with a 2-person household — Jeremy and wife), Nova needs user isolation: separate chat histories, memory spaces, API keys, preferences, and usage tracking. Wife's use case: personal chatbot + UX Designer workflow assistant.

**This phase has two sub-phases: planning (13a) and implementation (13b).**

> **Early scaffolding strategy:** Add `tenant_id` columns and Redis key prefixes *before* this phase,
> defaulting to a single value. This makes the data layer tenant-aware without building the full
> multi-tenancy UI/auth. When Phase 13 arrives, the schema is already partitioned — only the auth
> layer, UI scoping, and migration logic need building. Key areas to scaffold early:
> - `tenant_id` column on: conversations, tasks, memories, api_keys, usage_events, pods
> - Redis key namespace: prefix all keys with `tenant:{id}:`
> - nova-contracts: tenant context flows through shared Pydantic models
> - Memory service: pgvector similarity search filters by tenant (critical for isolation)

### Phase 13a — Multi-Tenancy Design

Before writing code, produce a design document (`docs/plans/multi-tenancy-design.md`) covering:

**Identity & Auth:**
- How do users authenticate? Options: local username/password, OAuth (Google), passkey, or invite-link with shared admin secret
- Session management: JWT tokens? Cookie-based sessions? How do they interact with existing `X-Admin-Secret` admin auth?
- User roles: admin (full access, can manage other users) vs. user (own data only)

**Data Isolation:**
- Chat history: per-user conversations (currently global in orchestrator DB)
- Memory: per-user memory spaces in memory-service (currently shared pgvector collection)
- API keys: keys already have no user association — add `user_id` FK
- Usage tracking: per-user usage reports and cost attribution
- Tasks/pipelines: per-user task queues, or shared queue with user context?
- Pods: shared pod definitions (admin-managed) vs. per-user custom pods
- Settings: which settings are global (admin) vs. per-user (appearance, default model, notification prefs)?

**UX Design:**
- Login screen / user switcher
- Dashboard scoped to current user's data
- Admin panel for user management
- Wife's UX Designer persona: should this be a pre-configured pod with UX-specific system prompts, tools, and memory?

**Infrastructure Impact:**
- Database schema changes (add `users` table, add `user_id` FK to conversations, memories, tasks, api_keys, usage_events)
- Memory service: tenant-scoped embedding collections
- Redis: namespace keys by user ID
- LLM Gateway: per-user rate limits? Per-user provider preferences?
- Recovery service: per-user backup scope or global only?

**Migration Strategy:**
- How to migrate existing single-user data to the first user account
- Backwards compatibility: single-user mode should still work (no login required when only 1 user)

### Phase 13b — Multi-Tenancy Implementation

Implement the design from 13a. Likely deliverables:

- [ ] `users` table with hashed passwords, roles, preferences
- [ ] Login/registration UI in dashboard
- [ ] JWT or session-based auth middleware across all services
- [ ] `user_id` column added to: conversations, tasks, memories, api_keys, usage_events
- [ ] Dashboard scoped to authenticated user's data
- [ ] Admin panel: user CRUD, usage-per-user, global settings
- [ ] Per-user settings (appearance, default model, notifications)
- [ ] Memory service tenant isolation (user-scoped collections)
- [ ] Redis key namespacing by user ID
- [ ] Migration: existing data assigned to initial admin user
- [ ] Pre-built "UX Designer" pod with relevant system prompts and tools
- [ ] Single-user mode preserved: if only 1 user exists, skip login

### Success Criteria

- [ ] Two users can chat simultaneously with isolated histories
- [ ] User A cannot see User B's conversations, memories, or tasks
- [ ] Admin can view all users' usage and manage accounts
- [ ] Existing single-user installations upgrade seamlessly (data migrated to first user)
- [ ] Wife can use a UX Designer-optimized pod with relevant context and tools

---

## 🔜 Phase 14 — SaaS & Hosted Offering (Nova Cloud)

**Motivation:** Self-hosting is a barrier. Many potential users want to try Nova without provisioning hardware, managing Docker Compose, or configuring GPU drivers. A hosted offering at `nova.arialabs.ai` unlocks three revenue streams: casual users who want a quick AI assistant (Free), power users who want the full pipeline without ops work (Pro), and enterprise teams evaluating before self-hosting (Enterprise). The hosted version also serves as a live demo — users who outgrow it self-host, driving adoption of both paths.

**Prerequisites:** Phase 12 (concurrent inference backends) + Phase 13 (multi-tenancy). Phase 12 provides the serving infrastructure for multiple concurrent users. Phase 13 provides user isolation, auth, and per-user data scoping.

**This phase has two sub-phases: architecture design (14a) and implementation (14b).**

### Phase 14a — SaaS Architecture Design

Before writing code, produce a design document (`docs/plans/saas-architecture-design.md`) covering:

**Platform Identity:**
- App URL: `nova.arialabs.ai`
- Branding: "Nova Cloud" (hosted) vs "Nova" (self-hosted)
- Same codebase — not a fork. SaaS-specific behavior gated by `NOVA_SAAS=true` environment variable

**Infrastructure Architecture:**

| Component | Self-Hosted (current) | Nova Cloud (SaaS) |
|---|---|---|
| **Orchestration** | Docker Compose | Kubernetes (managed — DigitalOcean DOKS or similar) |
| **Database** | Local PostgreSQL container | Managed PostgreSQL (DO Managed DB or Supabase) |
| **Redis** | Local Redis container | Managed Redis (DO Managed Redis or Upstash) |
| **Object Storage** | Docker volumes | S3-compatible (DO Spaces or R2) |
| **LLM Inference** | Self-hosted Ollama/vLLM/SGLang | Cloud providers (Anthropic, OpenAI, Groq, etc.) — no self-hosted GPU initially |
| **Ingress** | Direct port access | Kubernetes Ingress + Cloudflare (already on arialabs.ai) |
| **TLS** | Optional (Cloudflare tunnel) | Required — cert-manager + Let's Encrypt |
| **Monitoring** | Docker logs | Prometheus + Grafana + OpenTelemetry |

**Kubernetes Justification:**
This is the "real need" for Kubernetes identified earlier — multi-tenant SaaS requires horizontal scaling, rolling deployments, health-based restart, resource limits per service, and namespace isolation for enterprise tenants. Docker Compose cannot provide these at SaaS scale.

**Helm Chart Structure:**
Single Helm chart deploys Nova in both modes. Values files control the difference:

```
nova-helm/
├── Chart.yaml
├── values.yaml                  # defaults (self-hosted)
├── values-saas.yaml             # SaaS overrides
├── values-saas-staging.yaml     # staging overrides
├── templates/
│   ├── orchestrator/
│   ├── llm-gateway/
│   ├── memory-service/
│   ├── chat-api/
│   ├── dashboard/
│   ├── recovery/
│   ├── billing/                 # SaaS only (conditional)
│   ├── ingress.yaml
│   └── _helpers.tpl
```

Self-hosted users can deploy via `helm install nova ./nova-helm` as an alternative to Docker Compose. SaaS deploys via `helm install nova ./nova-helm -f values-saas.yaml`.

**Tenant Isolation Model:**
- **Free / Pro tiers:** Shared infrastructure — all users on the same Kubernetes namespace, isolated at the database level (row-level security via `user_id` from Phase 13)
- **Enterprise tier:** Dedicated Kubernetes namespace per organization — separate DB schema or database, separate Redis namespace, resource quotas. Enables data residency requirements

**Plan Tiers:**

| Feature | Free | Pro ($20/mo) | Enterprise (custom) |
|---|---|---|---|
| **Messages/month** | 100 | Unlimited | Unlimited |
| **Pipeline tasks/month** | 10 | 200 | Unlimited |
| **Models** | GPT-4o-mini, Claude Haiku | All cloud models | All + custom fine-tunes |
| **Memory storage** | 50 MB | 5 GB | Unlimited |
| **File uploads** | 10 MB | 500 MB | Unlimited |
| **API access** | No | Yes (rate-limited) | Yes (higher limits) |
| **Concurrent tasks** | 1 | 5 | Configurable |
| **Pods** | Default only | Custom pods | Custom + shared org pods |
| **Support** | Community | Email (48h) | Dedicated (SLA) |
| **Data export** | Manual | One-click | API + scheduled |

**Billing & Metering:**

Extend the existing `usage_events` table from Phase 2:
- Add `billable_units` and `billing_category` columns
- Categories: `llm_tokens`, `pipeline_task`, `memory_storage`, `file_storage`
- Metering service aggregates usage per user per billing period

Stripe integration:
- `stripe_customer_id` and `stripe_subscription_id` on users table
- Stripe Checkout for subscription creation
- Stripe webhooks for: `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`
- Dunning: 3 retry attempts over 7 days → downgrade to Free (preserve data for 30 days)

Plan enforcement middleware:
- Check plan limits on each API request (message count, task count, storage)
- Return `402 Payment Required` with upgrade prompt when limit exceeded
- Cache plan limits in Redis (TTL 60s) to avoid DB lookup on every request

**Onboarding Flow:**

1. **Registration:** Email + password, or OAuth (Google, GitHub). Email verification required. CAPTCHA on registration form
2. **Welcome wizard (3 steps):**
   - Step 1: "What will you use Nova for?" (coding, research, writing, general) — sets default pod
   - Step 2: Choose display name and avatar
   - Step 3: First chat message (pre-filled prompt based on Step 1 selection)
3. **First chat:** Lands in chat with the selected pod, system sends a welcome message explaining capabilities

**Security & Compliance:**

- Row-level security (RLS) on all tenant tables — enforced at DB level, not just application level
- Encryption: TLS in transit (required), AES-256 at rest for stored files, bcrypt for passwords
- JWT auth with short-lived access tokens (15 min) + refresh tokens (7 days)
- Audit log: all admin actions, auth events, data access logged to append-only table
- GDPR compliance:
  - Data export: user can download all their data as JSON/ZIP
  - Data deletion: "Delete my account" removes all user data within 30 days (immediate soft-delete, hard-delete via scheduled job)
  - Cookie consent banner (minimal — only auth cookies, no tracking)
- SOC 2 Type II: target for Year 2 (not launch requirement, but design with it in mind)
- Rate limiting: per-user, per-IP, and global circuit breakers

**Ops & Monitoring:**

- Prometheus: scrape all service `/metrics` endpoints (request latency, error rate, queue depth, active users)
- Grafana dashboards: service health, user activity, billing metrics, LLM provider latency
- OpenTelemetry: distributed tracing across all services (correlate a user request through orchestrator → llm-gateway → memory-service)
- Alerting: PagerDuty or Opsgenie for P1 (service down, data loss risk), Slack for P2 (high error rate, provider degradation)
- Status page: `status.arialabs.ai` — Upptime or Betteruptime, shows service health and incident history
- Cost tracking: per-user LLM cost attribution, monthly cost report, alerts when spend exceeds thresholds

**Self-Hosted ↔ SaaS Relationship:**

- Separate instances — SaaS is not a "managed version" of a user's self-hosted install
- Same codebase, same Docker images, different config
- Data portability: users can export all data from Nova Cloud and import into self-hosted (and vice versa)
- Export format: JSON archive (conversations, memories, pods, settings, API keys without secrets)
- Import tool in recovery service: `POST /api/v1/import` accepts the export archive
- No "sync" between SaaS and self-hosted — intentionally one-way export/import to keep architecture simple

### Phase 14b — SaaS Implementation

Implement the design from 14a in 7 steps:

**Step 1: Kubernetes migration**
- [ ] Create Helm chart with templates for all 8 services
- [ ] HPA (Horizontal Pod Autoscaler) on orchestrator and llm-gateway (CPU/memory + custom metrics)
- [ ] PDB (Pod Disruption Budget) — at least 1 replica of each service always running
- [ ] Managed PostgreSQL and Redis (connection string via Helm values)
- [ ] S3-compatible storage for file uploads and backups
- [ ] CI/CD pipeline: GitHub Actions → build images → push to registry → helm upgrade (staging → production)
- [ ] Staging environment: `staging.nova.arialabs.ai` with synthetic test data

**Step 2: Billing & metering**
- [ ] `billing` service (new microservice or module within orchestrator — decide in 14a)
- [ ] `usage_events` extension: `billable_units`, `billing_category` columns
- [ ] Stripe integration: customer creation, checkout session, webhook handler
- [ ] Plan enforcement middleware on orchestrator API routes
- [ ] Billing dashboard page: current plan, usage meters, invoices, upgrade/downgrade
- [ ] Dunning flow: failed payment → retry → downgrade → data retention

**Step 3: Registration & onboarding**
- [ ] Registration endpoint with email verification (SendGrid or Resend)
- [ ] OAuth providers: Google, GitHub (via Passport.js or custom)
- [ ] Welcome wizard UI (3-step flow)
- [ ] CAPTCHA integration (hCaptcha or Turnstile)
- [ ] Account settings: change password, manage OAuth connections, delete account

**Step 4: Landing page & marketing site**
- [ ] Pricing page at `nova.arialabs.ai/pricing` with tier comparison table
- [ ] "Get Started" CTA → registration flow
- [ ] Status page at `status.arialabs.ai`
- [ ] SEO: meta tags, OpenGraph, structured data
- [ ] Update existing website to link to Nova Cloud

**Step 5: Security hardening**
- [ ] Row-level security policies on PostgreSQL
- [ ] Audit log table and middleware
- [ ] GDPR: data export endpoint, account deletion flow, cookie consent
- [ ] Penetration test (self-administered or contracted)
- [ ] Incident response runbook (`docs/runbooks/incident-response.md`)

**Step 6: Ops & observability**
- [ ] Prometheus + Grafana deployed via Helm (or managed — Grafana Cloud)
- [ ] OpenTelemetry SDK integrated into all Python services
- [ ] Centralized logging (Loki or managed equivalent)
- [ ] Alerting rules: service health, error rate, billing failures
- [ ] Cost tracking dashboard: per-user LLM spend, infrastructure cost

**Step 7: Launch sequence**

| Stage | Audience | Duration | Plan Tiers | Purpose |
|---|---|---|---|---|
| **Alpha** | Invite-only (10-20 users) | 4-6 weeks | Free only | Stability testing, UX feedback, find data isolation bugs |
| **Beta** | Open registration | 4-8 weeks | Free only | Scale testing, onboarding flow validation, marketing site live |
| **GA** | Public | Ongoing | Free + Pro | Revenue starts, billing fully operational |
| **Enterprise** | Outbound sales | GA + 3 months | All tiers | Dedicated namespaces, SLA, custom integrations |

**Cost Estimation (DigitalOcean baseline):**

| Resource | Spec | Monthly Cost |
|---|---|---|
| DOKS cluster | 3-node, 2 vCPU / 4 GB each | ~$72 |
| Managed PostgreSQL | 1 GB RAM, 10 GB storage | ~$15 |
| Managed Redis | 1 GB RAM | ~$15 |
| DO Spaces (S3) | 250 GB | ~$5 |
| Container Registry | Basic | ~$5 |
| Monitoring (Grafana Cloud) | Free tier | $0 |
| Domain + Cloudflare | Existing | $0 |
| LLM API costs | Pass-through to providers | Variable (billed to users) |
| SendGrid (email) | Free tier (100/day) | $0 |
| Stripe fees | 2.9% + $0.30 per transaction | Variable |
| **Total base infrastructure** | | **~$112/month** |
| **With 3090 GPU node (optional)** | 1 GPU droplet for local models | **+$62/month** |
| **Total (with GPU)** | | **~$174/month** |

Break-even: ~9 Pro subscribers ($20 × 9 = $180/month) covers base infrastructure. LLM API costs are passed through (metered per-token, marked up ~20%).

### Testing & Validation

- [ ] Helm chart deploys successfully to staging cluster (`helm install --dry-run` + actual deploy)
- [ ] HPA scales orchestrator from 1 → 3 replicas under load
- [ ] Full billing lifecycle: register → subscribe (Pro) → use → invoice → pay → renew
- [ ] Data isolation: User A's data is invisible to User B at DB level (not just UI)
- [ ] Load test: 50 concurrent users, 10 concurrent pipeline tasks — response times <2s for chat, <30s for pipeline
- [ ] Failover: kill a pod, verify auto-restart and zero downtime
- [ ] OWASP ZAP scan: no critical/high findings
- [ ] Data export → import round-trip: export from SaaS, import to local Docker Compose, verify all data present

### Success Criteria

- [ ] New user can register, verify email, complete onboarding, and send first chat message in <2 minutes
- [ ] Stripe billing works end-to-end: subscribe, use, get invoiced, pay, see receipt
- [ ] 50 concurrent users with acceptable performance (<2s chat latency, <30s pipeline)
- [ ] Plan limits enforced: Free user hitting 100 message limit gets 402 with upgrade prompt
- [ ] Zero data leakage: penetration test confirms tenant isolation
- [ ] Auto-scaling: HPA responds to load within 60 seconds
- [ ] Infrastructure cost stays under $200/month at launch (before GPU node)
- [ ] Launch sequence completed: Alpha → Beta → GA with documented learnings at each stage
- [ ] Data export/import works: user can move from Nova Cloud to self-hosted (and back) without data loss

---

- **Capability-based YAML routing** — once Planning Agent assigns agents by role, formalize model requirements per role in a config file
- **Web Push notifications** — notify on task completion when accessing via PWA (requires Phase 4 async tasks)
- **Key-level model restrictions** — `sk-nova-*` keys scoped to specific providers
- **Multi-model A/B testing** — run two models on same subtask, Evaluation Agent picks the better output
- **Self-hosted Ollama parity** — full tool support for local models
- **Collaborative goals** — multiple users contributing context to a shared goal (prerequisite: Phase 13 multi-tenancy, Phase 14 SaaS for cross-instance collaboration)
- **ClaudeCode provider** — spawn `claude -p` subprocess using Claude Max subscription for zero API cost per call (designed in Phase 4, not yet implemented)
- **Post-pipeline agents** — Documentation Agent, Diagramming Agent, Security Review Agent, Memory Extraction Agent (designed, not built)
- **Default pods** — Quick Reply, Research, Code Generation, Analysis (designed in Phase 4, only Quartet default shipped)
- **Nova Cloud as inference/memory backend for self-hosted instances** — self-hosted Nova connects to Nova Cloud via API key for cloud model access and remote memory sync, without migrating fully to SaaS (prerequisite: Phase 14 SaaS)
- **Skills framework** (from NanoClaw) — modular instruction sets stored as files, loaded per-task context
- **VS Code Extension** — sidebar panel, "Ask Nova" command, diff view → **Moved to Phase 9b**

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

- **MCP tools invisible to agents** — pipeline agents and interactive runner import static `ALL_TOOLS` (built-ins only); `get_all_tools()` exists but nothing calls it. Tracked in Phase 5.5 and Phase 6b.
- **Streaming token counts broken** — `orchestrator/app/agents/runner.py` returns 0 tokens for streaming responses; usage tracking is broken for the primary interaction mode
- **Reaper race condition** — `orchestrator/app/reaper.py` TOCTOU between UPDATE and enqueue_task can cause double-queuing
- **No circuit breaker for LLM providers** — if a provider is down, requests fail immediately instead of routing to fallback
- **DB connection pool has no idle validation** — stale connections after Postgres restarts aren't detected
- **Admin secret default not rejected in production** — `nova-admin-secret-change-me` is accepted without warning
- **`parallel_group` field exists but is ignored** — pipeline executor runs stages sequentially within a task. Note: multiple *tasks* already run in parallel via Redis BRPOP; the bottleneck is Ollama serializing inference requests (addressed in Phase 12)
- **Contracts not enforced** — `nova-contracts` Pydantic models exist but aren't validated at service boundaries; agent responses are unchecked dicts
- **Embedding cache fixed** — `embedding_cache` write-through was broken by SQLAlchemy `::cast` syntax; fixed with `CAST(x AS type)` syntax (2026-03-06)

### Phase 3 — End-to-End Tool Testing (partially addressed)

Integration test suite added (2026-03-06): 35 tests covering health probes, agent CRUD, task submission,
memory CRUD/search/facts, LLM gateway model listing, recovery backups, and pipeline execution.
Run via `make test` or `make test-quick`.

Still not yet validated with integration tests:
1. `list_dir` root — confirm it sees actual files
2. `read_file` — confirm content + truncation behavior
3. `write_file` — verify changes appear on host filesystem
4. `run_shell` — confirm stdout/stderr capture and timeout kill
5. `search_codebase` — confirm file + line number results
6. Git workflow: `git_status` → change → `git_commit` → verify in `git log`
7. Path traversal: `../../etc/passwd` → confirm rejected
8. Denylist: `sudo ls` → confirm blocked

### Phase 3b — Sandbox Tiers (deferred)

Four named access levels (isolated → nova → workspace → host). Only `workspace` mode is functional. See Phase 3b section above for full design.

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

- **Testing** — integration test suite exists (35 tests across all services) but no unit tests, property tests, or CI pipeline yet
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
