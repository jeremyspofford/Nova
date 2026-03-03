# Nova AI Platform — Roadmap

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
- Cancel from dashboard at any state

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

## 🔜 Phase 9 — Infrastructure + Triggers + Computer Use

**Infrastructure hardening:**
- Periodic Reaper — background `asyncio.create_task` replacing startup-only stale recovery
- Docker Compose profiles — `--profile mac`, `--profile gpu`, `--profile cpu`
- Webhook system — outbound POST on task/goal lifecycle events; persistent retry queue

**Triggered execution (Autonomy Level 3):**
- Inbound webhooks — GitHub PR opened → Nova reviews it automatically
- Cron scheduling — "run a security audit every Monday at 9am"
- Event subscriptions — watch a file path, a Slack channel, an email inbox

**Computer Use:**
- Screenshot capture + vision model routing
- Mouse/keyboard event dispatch
- Sandboxed Playwright browser — Nova can use web UIs, not just APIs
- Action replay / audit log

---

## 🧊 Icebox / Future

- **Capability-based YAML routing** — once Planning Agent assigns agents by role, formalize model requirements per role in a config file
- **Telegram / mobile client** — conversational interface via Telegram or React Native
- **Textual TUI** — terminal UI for goal submission and activity feed
- **Key-level model restrictions** — `sk-nova-*` keys scoped to specific providers
- **Multi-model A/B testing** — run two models on same subtask, Evaluation Agent picks the better output
- **Self-hosted Ollama parity** — full tool support for local models
- **Collaborative goals** — multiple users contributing context to a shared goal
