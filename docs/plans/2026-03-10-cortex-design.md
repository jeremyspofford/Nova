# Cortex — Nova's Autonomous Brain

> Nova becomes a persistent autonomous entity with agency: it has goals, drives, self-improvement capability, and its own initiative. Cortex is a new service that gives Nova the ability to think and act on its own.

---

## Vision

Today Nova only acts when asked — you send a message or submit a task. Cortex changes this. Nova becomes an always-on entity that:

- Pursues user-set goals as its top priority
- Has internal drives (maintain, improve, learn, reflect) that fill idle time
- Can modify its own codebase, deploy changes, and roll back failures
- Narrates its work as a conversation stream you can follow and interact with
- Never stops thinking — shifts to cheaper/local models when budget tightens

Cortex replaces Phase 7 (Self-Directed Autonomy), Phase 7a (Self-Introspection), and Phase 8 (Autonomous Loop + Reinforcement) from the existing roadmap. Those phases described pieces of this; Cortex is the unified design.

---

## Architecture

### New Service: `cortex` (port 8100)

A separate container that only depends on postgres and redis. Like recovery, it survives crashes of other services — critical because Cortex needs to detect and fix failures in the orchestrator.

**Cortex does NOT run pipelines itself.** It uses the same HTTP APIs as the dashboard and chat-api to dispatch work to the orchestrator. This means:
- No special internal hooks — clean API boundary
- Cortex is a proof-of-concept for Nova's external API (if Cortex can operate Nova autonomously, so can any integration)
- The orchestrator doesn't know or care that tasks came from Cortex vs. a human

**Dependencies:**
- postgres (direct — for goals, drives, journal, cortex state)
- redis (direct — for budget tracking, heartbeat, inter-service signals)
- orchestrator (HTTP — to dispatch tasks, check health, read config)
- llm-gateway (HTTP — for its own LLM calls: planning, evaluation, reflection)
- memory-service (HTTP — to read/write knowledge)
- recovery (HTTP — for checkpoints, rollbacks, and service restarts)

**Redis DB allocation:** db5

### Identity & Authentication

Cortex needs to authenticate to other Nova services. On startup, Cortex self-provisions a dedicated API key (`sk-nova-cortex-...`) seeded in the `api_keys` table with a fixed UUID. This key:
- Authenticates all HTTP calls to orchestrator, llm-gateway, and memory-service
- Tags all `usage_events` with Cortex's `api_key_id`, enabling budget tracking and spend attribution
- Is created idempotently in the migration (no duplicates on restart)

For recovery API calls, Cortex uses the `ADMIN_SECRET` (same as dashboard).

### System User

Cortex operates as a synthetic system user seeded in the `users` table:
- Email: `cortex@system.nova`
- Role: `owner` (needs full access to dispatch tasks and manage goals)
- Status: `active`, no expiry
- Created idempotently in the cortex migration

This user owns the journal conversation and is the `created_by` for Cortex-initiated goals and tasks.

### Service Map

```
                    ┌─────────────┐
                    │   CORTEX    │  ← autonomous thinking loop
                    │   :8100     │
                    └──────┬──────┘
                           │ HTTP (same APIs as dashboard)
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        orchestrator   llm-gateway   memory-service
           :8000         :8001          :8002
              │            │            │
              └────────────┼────────────┘
                     ┌─────┴─────┐
                     ▼           ▼
                  postgres     redis
                   :5432       :6379
```

---

## The Thinking Cycle

Cortex runs a persistent loop. Each cycle:

### 1. PERCEIVE
- Check service health (orchestrator, llm-gateway, memory-service)
- Read incoming messages (user replies to journal, new goals submitted)
- Poll active task status (are dispatched tasks complete/failed?)
- Check budget state (spend vs. limits, provider availability)

### 2. EVALUATE
- Score each drive against current state
- Apply priority: user goals > health alerts > active work > self-improvement > learning > reflection
- Factor in budget: expensive actions deprioritized when budget is tight
- Result: a ranked list of candidate actions

### 3. PLAN
- Break the chosen action into subtasks
- Query memory for lessons from similar past work
- For self-modification: identify affected services, plan checkpoint/rollback strategy
- For goals: decompose into pipeline-compatible tasks with dependencies

### 4. ACT
- Create checkpoint if the action is risky (DB backup via recovery API, git tag, config snapshot)
- Dispatch subtasks to orchestrator pipeline via `POST /api/v1/pipeline/tasks`
- Monitor execution — poll task status, handle failures
- For self-modification: restart affected services, verify health post-change

### 5. REFLECT
- Evaluate results: did the action advance the goal? Did health degrade?
- If health degraded: auto-rollback from checkpoint
- Write lessons to memory-service (what worked, what failed, what to do differently)
- Narrate outcome to journal conversation
- Update goal progress

### Cycle Timing
- Default: every 5 minutes when idle
- Immediate: when a user message arrives or a dispatched task completes
- Backoff: longer intervals when budget is tight or nothing needs attention
- Configurable via `platform_config` key `cortex.cycle_interval_seconds`

---

## The Five Drives

Drives are tendencies that influence what Cortex chooses to do when it has free cycles. Each drive produces candidate actions during the EVALUATE phase.

| Drive | Priority | Description | Example Actions |
|-------|----------|-------------|-----------------|
| **Serve** | 1 (highest) | Pursue user-set goals | Decompose goal, dispatch subtasks, report progress |
| **Maintain** | 2 | Keep Nova healthy | Check service health, fix degradation, ensure backups current |
| **Improve** | 3 | Make Nova's code better | Review own code, refactor, add tests, optimize performance |
| **Learn** | 4 | Build knowledge | Read docs, explore tools, study patterns in the codebase |
| **Reflect** | 5 | Learn from experience | Evaluate past actions, extract patterns, update strategies |

### Drive Implementation

Each drive is a module that:
1. Assesses its current urgency (0.0 → 1.0) based on signals
2. Proposes candidate actions with estimated cost (tokens/dollars)
3. Returns actions to the evaluator for ranking

```
serve.py    → checks for active goals, user messages
maintain.py → checks health endpoints, backup age, error rates
improve.py  → scans for code quality signals, test coverage gaps, TODOs
learn.py    → identifies knowledge gaps based on recent task failures
reflect.py  → checks if enough new experience has accumulated to warrant review
```

### Priority vs. Urgency

Each drive has a static **priority** (Serve=1 through Reflect=5) and a dynamic **urgency** score (0.0–1.0). The final ranking is `priority_weight * urgency`. This means:
- Serve normally wins because priority 1 × any urgency > priority 3 × moderate urgency
- But when health is degraded, Maintain's urgency spikes to 1.0, which can overtake Serve (e.g., priority 2 × 1.0 > priority 1 × 0.3 for a low-urgency goal)
- Improve/Learn/Reflect compete for idle time when Serve and Maintain have low urgency
- Budget state adjusts urgency: expensive actions score lower when budget is tight

---

## Goal Management

### Goals Table

```sql
CREATE TABLE goals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
        -- active, paused, completed, failed, cancelled
    priority        INTEGER NOT NULL DEFAULT 0,
    progress        REAL NOT NULL DEFAULT 0.0,  -- 0.0 to 1.0
    current_plan    JSONB,       -- ordered subtask list from planning phase
    iteration       INTEGER NOT NULL DEFAULT 0,
    max_iterations  INTEGER DEFAULT 50,
    max_cost_usd    REAL,
    cost_so_far_usd REAL NOT NULL DEFAULT 0.0,
    check_interval_seconds INTEGER DEFAULT 3600, -- for standing goals; NULL = check every cycle
    last_checked_at TIMESTAMPTZ,
    parent_goal_id  UUID REFERENCES goals(id),
    created_by      TEXT NOT NULL DEFAULT 'user', -- 'user' or 'cortex'
    tenant_id       UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Goal Lifecycle
1. User submits goal (via dashboard, chat, or API)
2. Cortex picks it up in next PERCEIVE cycle
3. PLAN phase: decomposes into subtasks, creates plan
4. ACT phase: dispatches first subtask to pipeline
5. On subtask completion: REFLECT evaluates progress, updates plan
6. Loop until: goal complete, budget exceeded, max iterations hit, or escalation needed
7. Cortex narrates progress to journal throughout

### Standing Goals
Some goals never complete — they're ongoing directives:
- "Keep test coverage above 80%"
- "Respond to Telegram messages within 5 minutes"
- "Monitor infrastructure health"

These have `status = 'active'` and `max_iterations = NULL`. Standing goals include a `check_interval_seconds` field (default: 3600) to prevent expensive re-checks every cycle. Cortex only evaluates a standing goal when `check_interval_seconds` has elapsed since the last check.

---

## Self-Modification

### Workspace Access

The pipeline's file tools are scoped to `NOVA_WORKSPACE`. For self-modification, Cortex needs the pipeline to access Nova's own source tree. This is handled by setting `NOVA_WORKSPACE` to the repo root (`.`) in the Docker Compose config. The orchestrator volume mount becomes:

```yaml
volumes:
  - .:/workspace
```

This gives the pipeline read/write access to all Nova source code. The guardrail agent provides the safety layer — it reviews all file changes before they're applied.

### How Cortex Modifies Nova

Cortex can modify any part of Nova's codebase through the orchestrator's pipeline:
1. Cortex creates a pipeline task: "Refactor memory-service/app/router.py to reduce complexity"
2. The quartet pipeline executes it — Context Agent reads the code, Task Agent writes changes, Guardrail checks safety, Code Review validates quality
3. On pipeline completion, Cortex verifies health and narrates the change

### Safety: Checkpoint → Change → Verify → Rollback

```
1. PRE-CHANGE
   ├── Create DB backup via recovery API
   ├── Git tag: cortex/pre-change/{timestamp}
   ├── Snapshot current config
   └── Record health baseline (all /health/ready endpoints)

2. APPLY CHANGE
   ├── Pipeline executes the modification
   ├── Git commit with cortex/ prefix in message
   └── Restart affected service(s) via recovery API (POST /api/v1/recovery/services/{name}/restart)

3. VERIFY (within 5 minutes)
   ├── Poll /health/ready on all services
   ├── Run integration test suite (make test-quick minimum)
   ├── Compare health metrics to baseline
   └── If degraded → ROLLBACK

4. ROLLBACK (automatic)
   ├── Git revert the cortex/ commit
   ├── Restore config snapshot
   ├── Restart affected services
   ├── Restore DB backup if schema was changed
   └── Log failure to memory + journal
```

### Service Restart Handling

When Cortex modifies a service's code, it restarts that service via recovery API. Special cases:
- **Orchestrator restart:** Cortex must wait for in-flight pipeline tasks to complete (poll task status) before restarting. After restart, verify health before dispatching new work.
- **Cortex self-modification:** Cortex detects changes targeting `cortex/` paths. It commits the change, then requests recovery to restart the cortex container. On restart, Cortex reads its last checkpoint and verifies its own health.
- **Recovery service:** Cortex cannot modify recovery (it's the safety net). Changes to recovery require manual deployment.

### What Cortex Cannot Do
- Modify its own running code in the same cycle (must restart itself via recovery)
- Modify the recovery service (safety net must remain human-controlled)
- Delete data without checkpoint (enforced by pre-change hook)
- Exceed budget (hard stop, shifts to local models)
- Bypass guardrails (all changes go through the quartet pipeline)

---

## Journal Conversation

Cortex's primary interface is a persistent conversation stream — it narrates everything it does and why.

### Implementation
- Stored as a conversation in the existing `conversations` table, owned by the `cortex@system.nova` system user
- Reserved conversation ID seeded in migration (deterministic UUID)
- Messages use the existing message format (role, content, metadata)
- Cortex writes assistant messages narrating its actions
- User writes user messages to redirect, ask questions, or give feedback
- Dashboard gets a "Cortex" page showing this conversation in the chat UI

### Message Types (via metadata)
| Type | Description | Push to chat-bridge? |
|------|-------------|---------------------|
| `narration` | Status update, what Cortex is doing | No |
| `progress` | Goal progress report | No |
| `completion` | Task/goal completed | Yes (medium) |
| `question` | Cortex needs user input | Yes (high) |
| `escalation` | Failure, rollback, or blocked | Yes (high) |
| `reflection` | Lessons learned, pattern discovered | No |

### Notification Delivery

Chat-bridge currently only handles inbound messages (Telegram/Slack → orchestrator). Cortex needs outbound push. Implementation:
- New endpoint on chat-bridge: `POST /api/v1/notify` — accepts `{platform, message, priority}`
- Cortex calls this endpoint for `completion`, `question`, and `escalation` messages
- Chat-bridge sends via Telegram Bot API / Slack Web API (already has credentials configured)
- Fallback: if chat-bridge is unavailable, notification is logged to journal only

### Interaction Model
- User can reply to any message in the journal to give feedback
- Cortex reads replies in the PERCEIVE phase and adjusts behavior
- "Stop working on X" → Cortex pauses the goal
- "Focus on Y instead" → Cortex reprioritizes
- "Why did you do Z?" → Cortex explains its reasoning

---

## Cost Management

### Model Tiering by Activity

| Activity | Model Class | Examples |
|----------|-------------|---------|
| User goals | Best available | Opus, Sonnet, GPT-4o |
| Planning & evaluation | Mid-tier | Haiku, Groq Llama, Gemini Flash |
| Self-improvement | Mid-tier | Haiku, Groq Llama, Gemini Flash |
| Learning & reflection | Cheap | Haiku, local Ollama |
| Health checks | None (HTTP only) | Direct endpoint calls |

### Budget-Aware Routing
- Cortex tracks daily spend via usage_events table
- When spend approaches budget: shift all background work to local models
- When budget exceeded: only health monitoring continues (no LLM calls)
- Local fallback: Ollama on Dell via LAN (WoL if needed)
- Budget resets daily (configurable: daily, weekly, monthly)

### Config Keys
```
cortex.enabled                  = true
cortex.cycle_interval_seconds   = 300
cortex.daily_budget_usd         = 5.00
cortex.model_tier.user_goals    = "auto"
cortex.model_tier.background    = "haiku"
cortex.model_tier.reflection    = "local"
```

---

## Database Changes

### New Tables
- `goals` — goal tracking (see schema above)
- `goal_tasks` — maps goals to pipeline tasks (goal_id, task_id, sequence, status)
- `cortex_state` — singleton row:

```sql
CREATE TABLE cortex_state (
    id              BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),  -- enforces singleton
    status          TEXT NOT NULL DEFAULT 'running',  -- running, paused
    current_drive   TEXT,
    cycle_count     BIGINT NOT NULL DEFAULT 0,
    last_cycle_at   TIMESTAMPTZ,
    last_checkpoint JSONB,  -- {backup_id, git_tag, config_snapshot, health_baseline}
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO cortex_state DEFAULT VALUES;
```

### Modified Tables
- `tasks.goal_id` — FK to goals (column already exists, just needs the reference)
- `SubmitPipelineTaskRequest` — add optional `goal_id` field, wired through to `INSERT INTO tasks`

### New Migration
Next available migration number — creates goals, goal_tasks, cortex_state tables. Seeds system user + API key + journal conversation. Adds FK on tasks.goal_id.

---

## API Endpoints

### Goal Management (on orchestrator, used by dashboard + cortex)
```
POST   /api/v1/goals              — create a goal
GET    /api/v1/goals              — list goals (with status filter)
GET    /api/v1/goals/{id}         — goal detail + plan + linked tasks
PATCH  /api/v1/goals/{id}         — update (pause, resume, cancel, reprioritize)
DELETE /api/v1/goals/{id}         — cancel and archive
```

### Cortex Control (on cortex service)
```
GET    /api/v1/cortex/status      — current state, active drive, cycle info
POST   /api/v1/cortex/pause       — pause autonomous operation
POST   /api/v1/cortex/resume      — resume autonomous operation
GET    /api/v1/cortex/journal     — journal conversation (paginated)
POST   /api/v1/cortex/journal     — user message to journal
GET    /api/v1/cortex/drives      — current drive urgency scores
GET    /health/live               — liveness
GET    /health/ready              — readiness
```

---

## Dashboard Changes

### New: Cortex Page
- Journal conversation view (full chat UI, can send messages)
- Sidebar: active goals with progress bars, drive urgency meters, current cycle status
- Controls: pause/resume cortex, submit new goal

### Modified: Goals Section
- Goals can be created from the Cortex page or from a new "Goals" nav item
- Goal detail view shows: plan, linked tasks, progress history, cost

### Nav Addition
- New nav item: "Cortex" (between Chat and Tasks) — visible to Member+ roles

### Proxy Configuration
- Dashboard nginx: add `/cortex-api` proxy path → `http://cortex:8100`
- Vite dev proxy: add matching entry in `vite.config.ts`

---

## Docker Compose Addition

```yaml
cortex:
  build: ./cortex
  ports:
    - "8100:8100"
  environment:
    - DATABASE_URL=postgresql://...
    - REDIS_URL=redis://redis:6379/5
    - ORCHESTRATOR_URL=http://orchestrator:8000
    - LLM_GATEWAY_URL=http://llm-gateway:8001
    - MEMORY_SERVICE_URL=http://memory-service:8002
    - RECOVERY_URL=http://recovery:8888
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy
  restart: unless-stopped
```

Does NOT depend on orchestrator at startup (like recovery) — starts independently and waits for orchestrator to become healthy before dispatching work.

---

## Implementation Order

1. **Service scaffold** — FastAPI app, health endpoints, Docker setup, compose integration, system user + API key seeding
2. **Goals table + API** — migration, CRUD endpoints on orchestrator, `goal_id` on pipeline task submission, dashboard goals page
3. **Cost management (stub)** — budget tracking via `usage_events`, model tier config. Needed early because the thinking cycle references budget state.
4. **Thinking cycle** — the core loop: perceive → evaluate → plan → act → reflect
5. **Serve drive** — goal decomposition, subtask dispatch, progress tracking
6. **Journal conversation** — narration, dashboard Cortex page, notification delivery via chat-bridge
7. **Maintain drive** — health monitoring, alerting, basic self-healing
8. **Self-modification** — checkpoint/rollback system, code change pipeline, service restart via recovery
9. **Improve drive** — code review, refactoring, test generation
10. **Learn drive** — knowledge acquisition, doc reading
11. **Reflect drive** — experience evaluation, pattern extraction
12. **Cost management (full)** — local fallback, WoL, budget-aware routing refinement

---

## Relationship to Existing Roadmap

| Existing Phase | Cortex Coverage |
|----------------|-----------------|
| Phase 7 (Self-Directed Autonomy) | Fully replaced — goal layer, planning, evaluation, loop controller |
| Phase 7a (Self-Introspection) | Incorporated — Cortex's PERCEIVE phase + Maintain drive |
| Phase 8 (Autonomous Loop + Reinforcement) | Incorporated — Reflect drive + memory-based learning |
| Phase 4 (Pipeline) | Prerequisite — Cortex dispatches to existing pipeline |
| Phase 6 (Memory) | Prerequisite — Cortex reads/writes memory for learning |

---

## Success Criteria

- [ ] Cortex runs as a persistent service, survives orchestrator restarts
- [ ] User can submit a goal and Cortex decomposes + executes it through the pipeline
- [ ] Cortex narrates its work in a journal conversation viewable in the dashboard
- [ ] Cortex can modify Nova's own code through the pipeline with checkpoint/rollback
- [ ] Health degradation after self-modification triggers automatic rollback
- [ ] Budget limits are enforced — Cortex shifts to local models when budget tightens
- [ ] Urgent messages (failures, questions) push to Telegram/Slack
- [ ] User can pause/resume Cortex and redirect it via journal replies
- [ ] Cortex learns from past actions (writes lessons to memory, reads them for planning)
