# Nova-Suite Inventory — 2026-04-16

## Scope

A spec-first, then code-first read of `~/workspace/nova-suite/` to identify features worth porting into current Nova (`~/workspace/arialabs/nova/`). This is an inventory for port-or-skip decisions — not a defect audit of nova-suite itself.

**Reviewed:**
- `nova-suite/CLAUDE.md`
- All files in `nova-suite/docs/architecture/` (00–13, 15–18; missing 05, 06, 14)
- `nova-suite/services/api/` — FastAPI backend (routers, models, schemas, tool handlers, alembic migrations)
- `nova-suite/services/nova-lite/` — Python agent loop (triage, planner, executor, scheduler, summarizer)
- `nova-suite/services/board/` — React/Vite SPA (Chat, Activity, Settings panels)
- `nova-suite/infra/docker-compose.yml`
- Screenshots: `chat-list-triggers-success.png`, `settings-triggers-panel.png`, `final-settings.png`

**Cross-referenced against current Nova** via `orchestrator/app/`, `cortex/app/`, `dashboard/src/` and the migration files under `orchestrator/app/migrations/`.

**Out of scope:**
- Defect hunting in nova-suite code
- Architecture-level judgement on nova-suite's planes model — current Nova already has its own richer topology
- Features current Nova clearly does better (engram memory, multi-service pipeline, MCP, intel/knowledge workers, voice, chat-bridge)

---

## Architecture snapshot

Nova-suite is a **three-service + Postgres stack**: a FastAPI `api`, a Python `nova-lite` polling agent, a React `board` SPA. Much simpler than current Nova's 11-service stack. The whole codebase is in the low thousands of LOC; the `api` routers total ~1,170 LOC. The design pack envisioned integrating Home Assistant, n8n, Windmill, Nova Board, Nova-lite, Nova Policy, Nova Observe etc.; the **actual code implements roughly 30% of the spec** — primarily the agent loop, task/run/event data model, a chat-with-tool-calling UI, and a scheduler.

The interesting thing is that the *implemented* subset is **tightly focused and well-executed around one user story**: "chat with Nova, have it maintain scheduled triggers, watch activity run through." That's a coherent product slice, and it differs from current Nova in one important way: nova-suite's triggers are **user-visible, first-class, chat-managed primitives**.

---

## Per-feature inventory

### Feature 1 — Scheduled triggers (cron-based task scheduler)

| Field | Content |
|---|---|
| Feature | Scheduled triggers — cron-driven, free-standing, with tool-or-goal payloads |
| Spec quality | High — clean model, conservative defaults, good patch-first firing semantics |
| Implementation state | **Complete** — model, schema, migration, seed, router, polling loop, tool API, chat-driven CRUD, UI panel, `cronToHuman` formatter |
| Parity with current Nova | **Partial / Different-model** — current Nova has `goals.schedule_cron` (orchestrator/app/migrations/024_goal_schedules.sql), but triggers are NOT a first-class concept; they live as a column on goals, and there's no UI or chat-tool for creating an ad-hoc recurring task without inventing a whole goal |
| Recommendation | **Port spec + rebuild** — adopt the data model and the chat-driven CRUD pattern; rebuild in current Nova's style (asyncpg + orchestrator router) rather than copying SQLAlchemy code |
| Rationale | This is the feature Jeremy explicitly asked about ("create a task that runs at 9am every day"). Nova-suite's implementation is the cleanest, most self-contained demo of the end-to-end flow anywhere in either codebase — model → router → scheduler poller → tool handlers → chat CRUD → UI list. See depth analysis below. |

**Depth analysis — scheduler implementation:**

Files of interest:
- Model: `nova-suite/services/api/app/models/scheduled_trigger.py` (20 lines — id, name, description, `cron_expression`, `active_hours_start/end`, `enabled`, `payload_template` JSON, `last_fired_at`)
- Schema & validation: `nova-suite/services/api/app/schemas/scheduled_trigger.py` — cron validated via `croniter.is_valid`; payload shape enforced as XOR `{tool, input}` or `{goal: str}`
- HTTP router: `nova-suite/services/api/app/routers/system.py` — GET/POST/PATCH/DELETE on `/system/triggers`
- Polling loop: `nova-suite/services/nova-lite/app/logic/scheduler.py` (92 lines) — `_is_due` computes `croniter(cron_expr, last_fired_at_or_epoch).get_next() ≤ now`. **Patch-first ordering**: `last_fired_at` is updated *before* posting the event, so a transient failure costs at most one missed fire rather than spamming
- Event-to-task path: `nova-suite/services/nova-lite/app/logic/triage.py` — scheduler-source fast path at lines 104–114 bypasses the LLM and invokes the target tool directly for `{tool}` payloads, or creates an LLM-planned task for `{goal}` payloads
- Chat-driven CRUD: `nova-suite/services/api/app/tools/scheduler_handlers.py` — `handle_scheduler_{create,list,update,delete}_trigger` dispatched through the chat tool-calling loop in `routers/conversations.py`
- Sensitive-tool confirmation: `SENSITIVE_TOOLS` set in `routers/conversations.py:32-36` intercepts create/update/delete trigger calls, persists a `pending_tool_call` on the conversation, emits a human-readable confirmation prompt, and only commits on explicit yes/no regex match (`CONFIRM_RE` / `DENY_RE`) on the next user message
- Data migration: `nova-suite/services/api/alembic/versions/0005_cron_schedules.py` — migrates the prior `interval_seconds` schema to `cron_expression`, including rewriting the seeded triggers' payload shape

**How a trigger actually fires:**

1. `nova-lite` runs `fire_due_triggers(client)` every tick (default 15s — `LOOP_INTERVAL_SECONDS`)
2. Patches `last_fired_at` to now
3. Posts an `Event` with `type=scheduled.{trigger_id}`, `source=scheduler`, and `payload` = `{**payload_template, trigger_id}`
4. Next tick, `triage.classify_and_create` picks up the new event; the `source == "scheduler"` fast path invokes the tool or creates a task directly
5. The resulting `Run` row (with `trigger_type="agent_loop"` or `"chat"` or `"scheduled"`) appears in the Activity feed

This is idiomatic, deterministic, and the LLM is removed from the hot path entirely for tool-backed triggers. For `{goal}` triggers, the LLM is re-inserted only to plan actions against the resulting task. That's the right split.

**Why port the spec but not the code:**

Current Nova is asyncpg + FastAPI; nova-suite is SQLAlchemy sync + SQLite fallback. The model and the patch-first firing idea transfer cleanly but the code itself wouldn't graft without translation. More importantly, current Nova's cortex already has `check_schedules()` (`cortex/app/scheduler.py`) — a parallel implementation. The right move is to either (a) generalize cortex's goal-scheduler to support free-standing triggers whose payload is a tool invocation, not just a goal, or (b) extract a trigger primitive that both goals and cortex stimuli can reference. Either way, the nova-suite data model (`cron_expression` + `payload_template` as `{tool,input}|{goal}`) is the right shape to copy.

---

### Feature 2 — Chat-driven tool CRUD with sensitive-tool confirmation

| Field | Content |
|---|---|
| Feature | Chat message → LLM tool call → server-side CRUD, with explicit confirmation gate for "sensitive" tools |
| Spec quality | High — the confirmation pattern is clean and deterministic |
| Implementation state | **Complete** — 3-turn synchronous tool loop, pending-call persistence on the conversation, regex-based yes/no parsing, 30-minute expiry, render helper for confirmation prompts |
| Parity with current Nova | **Worse** — current Nova has `ai_create_goal` with a `confirmed:bool` arg-based pattern (`orchestrator/app/tools/platform_tools.py:449-479`) but confirmation lives inside the one tool, not in the chat controller. nova-suite's pattern is more general |
| Recommendation | **Port spec** — adopt the conversation-level pending-tool-call pattern for current Nova's chat controller |
| Rationale | Nova-suite's implementation (`services/api/app/routers/conversations.py:29-152`) has a clean separation: the tool dispatcher runs immediately for benign tools, but sensitive tools get intercepted, a structured summary is rendered via `_render_confirmation`, and the pending call is persisted in `conversations.pending_tool_call` (JSONB). The next user turn is parsed by regex, not by asking the LLM. That's safer and more predictable than current Nova's in-tool `confirmed` flag approach, which relies on the LLM to remember to round-trip the confirmation. Worth adopting in current Nova's chat controller. |

**Key files:**
- `nova-suite/services/api/app/routers/conversations.py:103-152` — `_check_pending_confirmation` and `_render_confirmation`
- `nova-suite/services/api/app/models/conversation.py` — `pending_tool_call: JSONB`, `pending_tool_call_at: TIMESTAMPTZ` (from migration 0006)
- `nova-suite/services/api/app/routers/conversations.py:298-395` — Step A (confirmation) → Step B (tool loop) → Phase 2 (streamed reply) sequencing

---

### Feature 3 — Unified Run/Activity feed

| Field | Content |
|---|---|
| Feature | Activity feed — every tool invocation (chat, scheduled, agent loop) is a Run row with `trigger_type`; UI shows them all in one reverse-chronological list |
| Spec quality | High — the `trigger_type` distinction ("agent_loop" vs "chat" vs future values) is the right primitive |
| Implementation state | **Complete** — Run model, `trigger_type` column (migration 0003), `/activity` router, React `ActivityFeed` with expandable input/output details, truncation-aware rendering |
| Parity with current Nova | **Missing-in-Nova** — current Nova tracks tool calls in the pipeline but there is no single "things that happened" user-visible feed; `dashboard/src/components/ActivityFeed.tsx` exists but covers different semantics (MessageBubble-adjacent only) |
| Recommendation | **Port spec** — adopt the Run + `trigger_type` model and surface one unified activity page |
| Rationale | nova-suite records *every* tool run regardless of source, gives each a human summary string, and exposes them all through one endpoint. Current Nova fragments this across pipeline runs, chat messages, cortex cycles, task history, etc. For a daily-driver assistant, the "what did Nova do today?" view matters more than any individual sub-surface. The data model is small — Run with `tool_name`, `trigger_type`, `input`, `output`, `status`, `summary`, `started_at`, `finished_at` — and grafts onto current Nova without much effort. |

---

### Feature 4 — Scheduler triggers Settings UI panel

| Field | Content |
|---|---|
| Feature | Read-only list of triggers with `cronToHuman` formatting, last-fired timestamp, enabled state, payload kind (tool/goal) |
| Spec quality | Medium — the "edit via chat" choice is clever but only if chat-driven CRUD is reliable |
| Implementation state | **Complete, read-only** — no edit/create/delete in the UI; explicit hint: "To add, edit, or remove triggers, ask Nova in chat" |
| Parity with current Nova | **Missing-in-Nova** — current Nova has `Goals.tsx` with `schedule_cron` but no standalone "scheduled things" surface |
| Recommendation | **Port spec** — add a similar read-only (or read-mostly) trigger list to current Nova's Settings once triggers are ported. `cronToHuman` is ~30 LOC and handles the 80% case |
| Rationale | The UI-minimal, chat-maximal approach fits Nova's ethos. Build the primitive and the list view; keep mutation through chat (with the pending-confirmation pattern from Feature 2) until mutation UI is actually needed. |

**Key file:** `nova-suite/services/board/src/lib/cron-to-nl.ts` — small but useful formatter.

---

### Feature 5 — Conversation pending-tool-call persistence

| Field | Content |
|---|---|
| Feature | `conversations.pending_tool_call` JSONB column + `pending_tool_call_at` timestamp with 30min expiry |
| Spec quality | High |
| Implementation state | **Complete** — migration 0006, model, reset-on-confirm/deny, regex-based verdict parsing |
| Parity with current Nova | **Missing-in-Nova** |
| Recommendation | **Port spec** — bundle with Feature 2 |
| Rationale | Covered in Feature 2; listed separately because it's a discrete schema addition that could be applied independently of the larger confirmation pattern. |

---

### Feature 6 — Nova system-health + daily-summary tools

| Field | Content |
|---|---|
| Feature | Two internal tools: `nova.system_health` (deterministic — disk/memory/stale tasks/failed-run rate thresholds) and `nova.daily_summary` (LLM-summarized digest of last N hours of events/runs/task transitions) |
| Spec quality | Medium — narrow, specific, but useful |
| Implementation state | **Complete** — handlers in `nova-suite/services/api/app/tools/nova_handlers.py`, seeded triggers that invoke them on cron |
| Parity with current Nova | **Worse** — current Nova has `/health` endpoints and an intel digest, but no "here's what happened in the last 24h" artifact stored as a Run |
| Recommendation | **Port spec only** — the specific thresholds and digest shape are useful, but the code would need to be rewritten against current Nova's tool system (MCP-backed, asyncpg-driven) and data model (engrams, not tasks) |
| Rationale | The idea — scheduled internal self-checks that escalate to tasks only when action is needed — is good product design for a daily driver. The implementation is ~90 LOC of straightforward threshold checks. Don't port the code; port the idea and the thresholds. |

---

### Feature 7 — Nova self-description tools (`describe_tools`, `describe_config`)

| Field | Content |
|---|---|
| Feature | Internal tools that return the enabled tool catalog (grouped by dotted prefix) and current config snapshot (providers, policies, trigger count, MTD spend) |
| Spec quality | Medium |
| Implementation state | **Complete** |
| Parity with current Nova | **Better-in-Nova (partial)** — current Nova has `orchestrator/app/tools/introspect_tools.py` and `diagnosis_tools.py` that cover similar ground but against the MCP-backed tool registry |
| Recommendation | **Skip** — current Nova's introspection tools are already richer |
| Rationale | Nothing to gain here; current Nova's MCP tool catalog already exposes this surface better. |

---

### Feature 8 — Agent-loop architecture (triage → plan → execute → summarize)

| Field | Content |
|---|---|
| Feature | Polling loop: classify event → create task → plan tool actions → execute → summarize |
| Spec quality | High (spec 05-nova-lite-spec.md is referenced but **missing from the repo**) |
| Implementation state | **Complete** — `nova-suite/services/nova-lite/app/main.py:58-91` |
| Parity with current Nova | **Far worse** — current Nova has the Quartet pipeline (Context → Task → Guardrail → Code Review → Decision) with heartbeats, stale reaping, Redis BRPOP queue, and 30s heartbeat cadence |
| Recommendation | **Skip** — current Nova's pipeline is the production-grade successor |
| Rationale | Nova-suite's loop is the simpler ancestor. The Quartet pipeline in current Nova supersedes it on every dimension (async, distributed, multi-agent review, tool registry depth). No value in porting the simpler version. |

---

### Feature 9 — Local+fallback LLM provider pattern

| Field | Content |
|---|---|
| Feature | Seeded dual Ollama providers (`ollama-local` primary + `ollama-local-fallback`) with automatic fallback-on-exception in `route_with_tools` |
| Spec quality | Medium |
| Implementation state | **Complete** — `nova-suite/services/api/app/tools/seed.py:9-70` + `llm_client.py:89-124` |
| Parity with current Nova | **Better-in-Nova** — current Nova's `llm-gateway` is a full multi-provider router with LiteLLM, runtime strategy config, and health-aware routing |
| Recommendation | **Skip** |
| Rationale | Current Nova already does this better with LiteLLM and runtime routing strategy. |

---

### Feature 10 — Home Assistant light.turn_on/off tools

| Field | Content |
|---|---|
| Feature | Direct HA REST calls via `ha.light.turn_on` and `ha.light.turn_off` tools, with `HA_BASE_URL` + `HA_TOKEN` env config |
| Spec quality | High (08-state-spec.md is thorough) |
| Implementation state | **Partial** — 2 tools implemented (light on/off), rest of the state-sync/entity-model design unimplemented |
| Parity with current Nova | **Missing-in-Nova** — current Nova has no Home Assistant integration |
| Recommendation | **Port spec (08-state-spec.md), rebuild against MCP** |
| Rationale | HA integration is the most compelling "daily driver" capability nova-suite explored. But porting code is the wrong move: in current Nova the right integration shape is MCP-backed (an HA MCP server) rather than hand-coded HTTP calls in `tools/handlers.py`. The spec's entity-model approach — mirror selected HA entities, emit events on state change, use service calls for writes — is worth keeping. |

---

### Feature 11 — Shell/fs/http tools (shell.run, fs.list, fs.read, http.request)

| Field | Content |
|---|---|
| Feature | Workspace-scoped shell execution, file read, directory listing, generic HTTP request |
| Spec quality | Low — exposing raw shell with only cwd-sandboxing via `realpath` is risky |
| Implementation state | **Complete** |
| Parity with current Nova | **Different approach** — current Nova routes these through MCP servers (filesystem, git, etc.) with explicit permission handling |
| Recommendation | **Skip** |
| Rationale | Current Nova's MCP-driven approach is a safer, more general pattern. nova-suite's `realpath`-based cwd escape check is the only guard between the LLM and arbitrary shell commands — current Nova correctly rejects that model. |

---

### Feature 12 — Task/Event/Approval/Tool/Run/BoardColumn data models

| Field | Content |
|---|---|
| Feature | Eight-model schema described in `15-16-data-models-and-apis.md`: Event, Task, Tool, Run, Approval, BoardColumn, Entity, LLMProviderProfile |
| Spec quality | High — well-scoped, explicit fields, consistent conventions |
| Implementation state | **Complete** — all 8 SQLAlchemy models exist with matching Pydantic schemas |
| Parity with current Nova | **Different model** — current Nova uses engrams + pipeline tasks + orchestrator tasks; no board columns, no approvals as first-class, no explicit event log, no entity mirror |
| Recommendation | **Port spec (partial)** — the Event, Run, and Approval shapes are the strongest; Task is partially already covered by current Nova's orchestrator tasks |
| Rationale | Current Nova has made different architectural choices (engrams as the knowledge substrate, task pipelines instead of a board) that are richer overall. But specific shapes — especially `Event.correlation_id` + durable event log, and the `Approval` model as a first-class task sibling — are worth considering as additions. The 7-column board (Inbox/Ready/Running/Waiting/Needs Approval/Done/Failed) is a UX frame current Nova doesn't have but may want for visible task state. |

---

### Feature 13 — Seed-on-startup upsert pattern

| Field | Content |
|---|---|
| Feature | `seed_tools`, `seed_llm_providers`, `seed_board_columns`, `seed_scheduled_triggers` — all upsert-on-startup with deliberate divergence (triggers preserve user data, tools/columns overwrite) |
| Spec quality | Medium |
| Implementation state | **Complete** — `nova-suite/services/api/app/tools/seed.py` |
| Parity with current Nova | **Different** — current Nova uses SQL migrations for schema and data; seeding happens at migration-run time |
| Recommendation | **Skip (pattern not worth adopting)** |
| Rationale | Current Nova's migration-driven approach is production-safer. The "refresh display fields only, preserve runtime config on existing rows" rule in `seed_scheduled_triggers` is a good idea but belongs in a migration, not a lifespan hook. |

---

### Feature 14 — Board/Kanban UI (7-column)

| Field | Content |
|---|---|
| Feature | Board columns: Inbox/Ready/Running/Waiting/Needs Approval/Done/Failed/Cancelled with status-based column mapping |
| Spec quality | High (06-nova-board-spec.md is referenced but **missing from the repo**) |
| Implementation state | **Partial** — backend is complete (router, columns, move endpoint, seed); **frontend has no board UI** — board SPA routes only to Chat/Activity/Settings |
| Parity with current Nova | **Missing-in-Nova** |
| Recommendation | **Skip for now** — this is a UX frame that's useful but not a prerequisite for daily-driver readiness |
| Rationale | Without the frontend, this is half a feature. The Quartet pipeline already surfaces task state through pipeline stage logs. If a user-visible task board becomes a priority, design it fresh against engram-backed tasks rather than inheriting the nova-suite schema. |

---

### Feature 15 — n8n/Windmill workflow adapter (Feature 5 of roadmap)

| Field | Content |
|---|---|
| Feature | External workflow engines exposed as `Tool` records with `adapter_type=n8n|windmill`; adapter service translates Nova `Run` → external job + webhooks |
| Spec quality | High (07-workflow-spec.md is thorough) |
| Implementation state | **Missing** — not implemented, only spec'd |
| Parity with current Nova | **Different approach** — current Nova uses MCP for external integrations |
| Recommendation | **Skip** — current Nova's MCP model is the richer alternative |
| Rationale | n8n/Windmill as pluggable engines made sense for nova-suite's "strangler" strategy; current Nova's MCP-first design covers the same ground with a standardized protocol. |

---

### Feature 16 — Deployment onboarding assistant (v2)

| Field | Content |
|---|---|
| Feature | Hardware survey → topology recommendation → IaC generation |
| Spec quality | Medium — hand-wavy but gestures at something useful |
| Implementation state | **Missing** — only in `10-v2-onboarding-spec.md` |
| Parity with current Nova | **Different need** — current Nova has `scripts/setup.sh` with GPU detection |
| Recommendation | **Skip** |
| Rationale | Interesting aspiration but not a priority, and current Nova's setup.sh already handles the MVP case. |

---

## Summary

- **16 discoverable features** in nova-suite spanning implemented, partially-implemented, and spec-only.
- **Most valuable port:** the **scheduled triggers feature**, specifically the data model (`cron_expression` + XOR `{tool, input}` or `{goal}` payload), the patch-first cron firing loop, and the chat-driven CRUD with per-conversation pending-tool-call confirmation. Port these as specs, rebuild in current Nova's idiom (asyncpg + cortex scheduler + MCP tools). Secondary wins: the unified Run/activity feed with `trigger_type`, and the sensitive-tool confirmation pattern generalized across the chat controller.
- **Scheduler verdict:** **Port spec, rebuild fresh.** The nova-suite scheduler is the cleanest end-to-end demo of "create a task that runs at 9am every day" anywhere in either codebase — cron expression → poller → event → tool invocation → run row → activity feed. But copying the SQLAlchemy/sync code into current Nova would be awkward; translate it to asyncpg, either as a new `scheduled_triggers` table the orchestrator owns and cortex polls, or by generalizing the existing `goals.schedule_cron` to support tool-payloads (not just goal-plan payloads). The payload-shape XOR (`{tool, input}` vs `{goal}`) and the patch-first firing order are the two non-obvious decisions worth preserving.
