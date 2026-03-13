# Cortex Integration + Proactivity Engine — Design Spec

**Status:** Draft
**Phase:** 6c (Engram Network Phase 6, Task 3)
**Date:** 2026-03-12

## 1. Overview

Transform Cortex from a polling-based thinking loop into a **stimulus-driven autonomous brain** with deep engram memory integration. Nova gains true proactivity: event-driven reactivity, user-scheduled recurring goals, and idle-time memory consolidation — all mediated through the existing drive system.

### Design Principles

- **Stimulus → Drive → Action**: Events and schedules don't trigger actions directly. They raise drive urgency scores, and the drive system decides what to do. This prevents dumb-cron behavior while keeping scheduled tasks reliable.
- **Goals are the universal unit**: Recurring tasks, one-off reminders, and long-running objectives are all goals with different scheduling parameters. One concept for users to learn.
- **Memory makes Cortex context-aware**: Cortex reads engrams during PERCEIVE, writes observations as engrams during REFLECT, and triggers consolidation during idle periods. It learns from its own past behavior.
- **Budget gates everything**: No action exceeds budget. Cheap/none tiers suppress low-priority drives. The stimulus queue accumulates but doesn't force spend.

## 2. Architecture

### 2.1 Stimulus Queue (BRPOP Hybrid)

Replace Cortex's fixed-interval `asyncio.sleep` loop with a `BRPOP`-based hybrid that wakes on stimuli or times out for periodic drive evaluation.

```
┌──────────────┐  LPUSH   ┌─────────────────────┐  BRPOP    ┌───────────┐
│ orchestrator  │────────→│  cortex:stimuli      │←─────────│  cortex    │
│ memory-svc    │         │  (Redis list, db5)   │  timeout  │  loop.py  │
│ chat-bridge   │         └─────────────────────┘  = adapt  └───────────┘
│ cortex itself │              ↑                        │
│ (schedules)   │──────────────┘                        ▼
└──────────────┘                               PERCEIVE → EVALUATE
                                               → PLAN → ACT → REFLECT
```

**Stimulus format** (JSON dict pushed to Redis list):

```json
{
  "type": "message.received | goal.schedule_due | health.degraded | consolidation.complete | engram.contradiction | budget.tier_change | goal.created | goal.deadline_approaching",
  "source": "orchestrator | memory-service | cortex | chat-bridge",
  "payload": {},
  "priority": 0,
  "timestamp": "2026-03-12T10:30:00Z",
  "tenant_id": null
}
```

**Loop behavior:**

```python
async def thinking_loop():
    timeout = settings.CORTEX_CYCLE_INTERVAL  # start at 300s
    while True:
        # Block until stimulus arrives OR timeout expires
        result = await redis.brpop("cortex:stimuli", timeout=timeout)

        # Drain all pending stimuli (batch processing)
        stimuli = []
        if result:
            stimuli.append(json.loads(result[1]))
            # Drain remaining without blocking
            while (extra := await redis.rpop("cortex:stimuli")):
                stimuli.append(json.loads(extra))

        # Run cycle with stimuli context
        outcome = await run_cycle(stimuli=stimuli)

        # Adaptive timeout
        if stimuli or outcome.action_taken:
            timeout = 30          # active: check again soon
        elif outcome.any_drive_above(0.3):
            timeout = 60          # mild interest: moderate
        else:
            timeout = min(timeout * 2, settings.CORTEX_MAX_IDLE_INTERVAL)  # idle: back off
```

### 2.2 Stimulus Emitters

Services push stimuli to `cortex:stimuli` (Redis db5) via a shared helper.

| Service | Stimulus Type | When |
|---|---|---|
| orchestrator | `message.received` | New user message in any conversation |
| orchestrator | `goal.created` | User creates a goal via API or chat |
| memory-service | `consolidation.complete` | Consolidation cycle finishes |
| memory-service | `engram.contradiction` | Contradiction detected during ingestion |
| cortex | `goal.schedule_due` | Self-injected when a scheduled goal is due |
| cortex | `budget.tier_change` | Budget tier transitions (e.g., mid → cheap) |
| chat-bridge | `message.received` | External platform message (Telegram, Slack) |
| any service | `health.degraded` | Health check failure (optional) |

**Emitter helper** (shared via `nova-contracts` or duplicated as a thin function):

```python
async def emit_stimulus(redis, type: str, source: str, payload: dict = None, priority: int = 0):
    stimulus = {
        "type": type,
        "source": source,
        "payload": payload or {},
        "priority": priority,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await redis.lpush("cortex:stimuli", json.dumps(stimulus))
```

### 2.3 Goals with Schedules

Extend the existing `goals` table with scheduling fields. No new tables.

**Migration (new columns on `goals`):**

```sql
ALTER TABLE goals ADD COLUMN schedule_cron TEXT;          -- cron expression (e.g., "0 8 * * 1-5")
ALTER TABLE goals ADD COLUMN schedule_next_at TIMESTAMPTZ; -- next scheduled execution
ALTER TABLE goals ADD COLUMN schedule_last_ran_at TIMESTAMPTZ;
ALTER TABLE goals ADD COLUMN max_completions INTEGER;     -- NULL = unlimited, 1 = one-shot
ALTER TABLE goals ADD COLUMN completion_count INTEGER DEFAULT 0;
ALTER TABLE goals ADD COLUMN created_via TEXT DEFAULT 'api'; -- 'api' | 'chat' | 'cortex'
```

**Schedule evaluation** happens during Cortex's PERCEIVE phase:

```python
async def check_schedules(pool) -> list[Stimulus]:
    """Find goals with schedule_next_at <= now and emit stimuli."""
    rows = await pool.fetch("""
        SELECT id, title, priority FROM goals
        WHERE status = 'active'
          AND schedule_cron IS NOT NULL
          AND schedule_next_at <= now()
          AND (max_completions IS NULL OR completion_count < max_completions)
    """)
    stimuli = []
    for row in rows:
        stimuli.append({
            "type": "goal.schedule_due",
            "source": "cortex",
            "payload": {"goal_id": str(row["id"]), "title": row["title"]},
            "priority": row["priority"],
        })
        # Advance schedule_next_at
        next_at = croniter(row["schedule_cron"]).get_next(datetime)
        await pool.execute(
            "UPDATE goals SET schedule_next_at = $1, schedule_last_ran_at = now() WHERE id = $2",
            next_at, row["id"],
        )
    return stimuli
```

**Chat-based goal creation:**

The orchestrator already has `POST /api/v1/goals`. For chat-based creation, the agent pipeline detects intent and calls the goals API. Example flow:

```
User: "Remind me to check deploy health every morning at 8am"
  → Agent detects scheduling intent
  → POST /api/v1/goals {
      title: "Check deploy health",
      description: "Review service health dashboards and report any issues",
      schedule_cron: "0 8 * * *",
      priority: 3,
      created_via: "chat"
    }
  → emit_stimulus("goal.created", ...)
  → Cortex picks it up, confirms in journal
```

**Dashboard visibility:**

Goals API already supports `GET /api/v1/goals` with status filtering. The dashboard shows:
- All goals with schedule info (cron expression, next run, last run, completion count)
- Drive history per goal (when Cortex last worked on it, outcome)
- Ability to pause/resume/edit scheduled goals

### 2.4 Engram Memory Integration (Level 3)

Three integration points: PERCEIVE reads, REFLECT writes, idle triggers consolidation.

#### 2.4.1 PERCEIVE — Memory-Informed Context

Before drive evaluation, Cortex queries the engram network for relevant context:

```python
async def perceive_with_memory(http: httpx.AsyncClient, stimuli: list, goal_context: str) -> dict:
    # Build a query from current stimuli + active goal
    query_parts = []
    if goal_context:
        query_parts.append(f"Current goal: {goal_context}")
    for s in stimuli[:5]:  # Top 5 stimuli by priority
        query_parts.append(f"{s['type']}: {json.dumps(s['payload'])}")
    query = " | ".join(query_parts) or "general system status and pending work"

    # Call engram context endpoint
    resp = await http.post(f"{MEMORY_SERVICE_URL}/api/v1/engrams/context", json={
        "query": query,
        "session_id": "cortex-perceive",
    })
    if resp.status_code == 200:
        data = resp.json()
        return {
            "memory_context": data["context"],
            "engram_ids": data.get("engram_ids", []),
            "retrieval_log_id": data.get("retrieval_log_id"),
        }
    return {"memory_context": "", "engram_ids": [], "retrieval_log_id": None}
```

This memory context feeds into the LLM planning call, so Cortex knows:
- What it learned last time it worked on this goal
- User preferences relevant to the task
- Past outcomes of similar actions

#### 2.4.2 REFLECT — Write Observations as Engrams

After each cycle, Cortex ingests its reflection as an engram:

```python
async def reflect_to_engrams(http: httpx.AsyncClient, cycle_result: dict):
    """Ingest cycle outcome into engram network for long-term learning."""
    if not cycle_result.get("action_taken"):
        return  # Don't clutter memory with idle cycles

    raw_text = (
        f"Cortex cycle #{cycle_result['cycle_count']}: "
        f"Drive '{cycle_result['drive']}' won (urgency {cycle_result['urgency']:.2f}). "
        f"Action: {cycle_result['action_summary']}. "
        f"Outcome: {cycle_result['outcome']}."
    )

    await http.post(f"{MEMORY_SERVICE_URL}/api/v1/engrams/ingest", json={
        "raw_text": raw_text,
        "source_type": "cortex",
        "source_id": "cortex-reflect",
        "metadata": {
            "drive": cycle_result["drive"],
            "goal_id": cycle_result.get("goal_id"),
            "budget_tier": cycle_result.get("budget_tier"),
        },
    })
```

Over time, this creates a memory trail of Cortex's decisions. During future PERCEIVE calls, spreading activation can surface "last time I tried X, the outcome was Y" — enabling genuine learning from experience.

#### 2.4.3 Idle Consolidation — The Sleeping Brain

When Cortex has nothing to do (all drives below threshold, no stimuli), it triggers memory consolidation instead of sleeping:

```python
# In the main cycle, after drive evaluation
if not winning_drive and budget_tier != "none":
    # Nothing urgent — use idle time for memory maintenance
    if await _should_consolidate(http):
        log.info("Idle cycle: triggering memory consolidation")
        await http.post(f"{MEMORY_SERVICE_URL}/api/v1/engrams/consolidate")
        outcome = CycleOutcome(drive="maintain", action="idle_consolidation", ...)
```

The `_should_consolidate` check prevents over-consolidating:

```python
async def _should_consolidate(http) -> bool:
    resp = await http.get(f"{MEMORY_SERVICE_URL}/api/v1/engrams/consolidation-log?limit=1")
    if resp.status_code != 200:
        return False
    entries = resp.json().get("entries", [])
    if not entries:
        return True  # Never consolidated
    last = datetime.fromisoformat(entries[0]["created_at"])
    return (datetime.now(timezone.utc) - last).total_seconds() > 1800  # 30 min minimum
```

#### 2.4.4 Mark-Used Feedback

When Cortex uses engram context during planning, it reports which engrams influenced its decision:

```python
# After LLM planning call, if memory context was provided
if retrieval_log_id and engram_ids_used:
    await http.post(f"{MEMORY_SERVICE_URL}/api/v1/engrams/mark-used", json={
        "retrieval_log_id": retrieval_log_id,
        "engram_ids_used": engram_ids_used,
    })
```

This feeds the Neural Router training pipeline, improving retrieval quality for Cortex's queries over time.

## 3. Modified Drive System

### 3.1 Stimulus-Aware Drive Evaluation

Drives receive the current stimulus batch and use it to modulate urgency:

```python
class DriveContext:
    stimuli: list[dict]          # Current batch
    memory_context: str          # From engram PERCEIVE
    budget_tier: str             # Current tier
    cycle_count: int
    time_since_last_cycle: float # Seconds

async def assess(self, ctx: DriveContext) -> DriveResult:
    """Each drive implements this with stimulus awareness."""
    ...
```

### 3.2 Drive Modifications

**serve** (priority 1) — Enhanced with stimulus reactivity:
- `message.received` stimulus → urgency boost (+0.3)
- `goal.schedule_due` stimulus → urgency = 0.9 (near-guaranteed execution)
- `goal.created` stimulus → urgency boost (+0.2)
- Existing: stale goals still raise urgency organically

**maintain** (priority 2) — Enhanced with consolidation:
- `health.degraded` stimulus → urgency = 0.7 (same as before, but immediate)
- `consolidation.complete` with issues → urgency boost
- Idle state (no other drives active) → suggest consolidation
- New: checks memory-service health alongside existing checks

**improve** (priority 3) — No longer a stub:
- `engram.contradiction` stimulus → urgency = 0.4 (investigate and resolve)
- Neural router `ready_for_training` signal → urgency = 0.3
- Self-model maturity changes → urgency = 0.2

**learn** (priority 4) — Enhanced with memory:
- Existing: capability gap signals from Redis
- New: queries engrams for past learning attempts on same gap
- Avoids repeating failed approaches (memory-informed)

**reflect** (priority 5) — No longer a stub:
- After N cycles without reflection → urgency rises (0.1 per 10 cycles, cap 0.5)
- `budget.tier_change` to "none" → urgency = 0.6 (good time to reflect on spend)
- Writes reflection engrams summarizing recent drive patterns

### 3.3 Drive Context from Memory

Each drive's `assess()` receives the memory context string. Drives can parse it for relevant signals:

```python
# serve drive example
async def assess(self, ctx: DriveContext) -> DriveResult:
    base_urgency = await self._check_goals_and_messages(ctx)

    # Check if memory mentions past failures with current goal
    if ctx.memory_context and self.current_goal_title:
        if "failed" in ctx.memory_context.lower() and self.current_goal_title.lower() in ctx.memory_context.lower():
            # Past failure — add caution, suggest different approach
            self.proposed_action += " (note: previous attempt failed, try alternative approach)"

    return DriveResult(urgency=base_urgency, ...)
```

## 4. Implementation Plan

### Phase A: Stimulus Queue Infrastructure (2 tasks)

1. **Stimulus emitter helper** — Add `emit_stimulus()` to `nova-contracts` or as a thin utility in each service. Redis db5 key `cortex:stimuli`.

2. **Rewrite Cortex loop** — Replace `asyncio.sleep` in `loop.py` with `BRPOP` hybrid. Drain batch, adaptive timeout, pass stimuli to `run_cycle()`.

### Phase B: Goal Scheduling (3 tasks)

3. **Migration** — Add schedule columns to `goals` table (`schedule_cron`, `schedule_next_at`, `schedule_last_ran_at`, `max_completions`, `completion_count`, `created_via`).

4. **Schedule checker** — New function in Cortex's PERCEIVE phase. Queries due goals, self-injects `goal.schedule_due` stimuli, advances `schedule_next_at` via `croniter`.

5. **Goals API update** — Extend `POST/PATCH /api/v1/goals` to accept schedule fields. Validate cron expressions. Compute initial `schedule_next_at` on create.

### Phase C: Engram Memory Integration (3 tasks)

6. **PERCEIVE with memory** — Cortex queries `POST /api/v1/engrams/context` during perception. Memory context passed to drive evaluation and LLM planning.

7. **REFLECT to engrams** — After action cycles, ingest reflection as engram via `POST /api/v1/engrams/ingest` with `source_type="cortex"`.

8. **Idle consolidation** — When no drives win and budget allows, trigger `POST /api/v1/engrams/consolidate`. Respect 30-min cooldown.

### Phase D: Drive Enhancements (3 tasks)

9. **Stimulus-aware drives** — Update `DriveContext` to carry stimuli. Each drive's `assess()` checks relevant stimulus types to modulate urgency. Wire `serve` to react to `message.received` and `goal.schedule_due`.

10. **Activate improve + reflect drives** — Implement real logic (contradiction handling, periodic reflection). Remove stub returns.

11. **Memory-informed drives** — Drives receive memory context and use it to avoid repeating past failures, inform action proposals.

### Phase E: Stimulus Emitters (2 tasks)

12. **Orchestrator emitters** — Emit `message.received` on new chat messages. Emit `goal.created` on goal creation.

13. **Memory-service emitters** — Emit `consolidation.complete` after consolidation. Emit `engram.contradiction` during ingestion when contradictions are found.

### Phase F: Dashboard + Chat (2 tasks)

14. **Dashboard goals view** — Show schedule info, last run, next run, completion count, drive history. Pause/resume/edit controls.

15. **Chat-based goal creation** — Agent pipeline tool or intent detection for creating goals with schedules from natural language.

## 5. Data Flow: Complete Proactive Cycle

```
User: "Summarize my deploy logs every morning at 8am"
  │
  ▼
Orchestrator: detect intent → POST /api/v1/goals
  { title: "Summarize deploy logs", schedule_cron: "0 8 * * *", ... }
  → emit_stimulus("goal.created")
  │
  ▼
Cortex loop: BRPOP wakes on stimulus
  → PERCEIVE: read budget, check schedules, query engrams
  → EVALUATE: serve drive urgency = 0.7 (new goal created)
  → PLAN: LLM decides "acknowledge goal, prepare for first run"
  → ACT: journal entry confirming schedule
  → REFLECT: ingest "new recurring goal accepted" engram
  │
  ▼
[Next day, 8:00 AM]
Cortex PERCEIVE: check_schedules() finds goal due
  → self-inject stimulus("goal.schedule_due", goal_id=...)
  → EVALUATE: serve drive urgency = 0.9 (schedule due)
  → PLAN: LLM plans "fetch deploy logs, summarize, deliver"
  → ACT: dispatch pipeline task via orchestrator
  → REFLECT: ingest outcome engram
  │
  ▼
[Future PERCEIVE cycles]
Cortex queries engrams: "What happened last time I summarized deploy logs?"
  → Memory returns: "Last summary was well-received" or "User asked for less detail"
  → Drive adapts approach based on past outcomes
```

## 6. Configuration

New settings for Cortex (`cortex/app/config.py`):

```python
CORTEX_MAX_IDLE_INTERVAL: int = 1800     # Max seconds between cycles when idle (30 min)
CORTEX_ACTIVE_INTERVAL: int = 30          # Seconds between cycles when active
CORTEX_MODERATE_INTERVAL: int = 60        # Seconds when mild drive interest
CORTEX_MEMORY_ENABLED: bool = True        # Query engrams during PERCEIVE
CORTEX_REFLECT_TO_ENGRAMS: bool = True    # Write reflections as engrams
CORTEX_IDLE_CONSOLIDATION: bool = True    # Trigger consolidation when idle
CORTEX_CONSOLIDATION_COOLDOWN: int = 1800 # Min seconds between consolidations
```

New dependency: `croniter>=1.0` in `cortex/pyproject.toml`.

## 7. Failure Modes

| Failure | Impact | Mitigation |
|---|---|---|
| Memory-service down | Cortex runs without memory context (degraded) | Fallback to empty context, log warning, maintain drive raises urgency |
| Redis down | No stimulus queue, no BRPOP | Cortex falls back to fixed-interval polling via exception handler |
| Stimulus flood | Queue grows unbounded | Drain with limit (max 50 per cycle), oldest stimuli expire (TTL via LTRIM) |
| Budget exhausted | All drives suppressed | Reflect drive still runs (free), stimuli accumulate for next budget period |
| Cron parse error | Goal can't schedule | Validate on create/update, reject invalid expressions |
| Consolidation timeout | Idle cycle blocks | Async fire-and-forget with timeout, don't block cycle |

## 8. Multi-Tenant Considerations

- Stimulus payloads carry `tenant_id` — Cortex filters by tenant in multi-tenant mode
- Goal schedules are per-tenant (goals already have `tenant_id`)
- Engram queries are tenant-scoped (memory-service already supports this)
- Budget tracking is per-tenant (usage_events already scoped)
- Stimulus queue: single queue with tenant filtering, or per-tenant queues (`cortex:stimuli:{tenant_id}`) for isolation

## 9. Dependencies

- `croniter>=1.0` — Cron expression parsing (Cortex)
- No new infrastructure — reuses Redis db5 (already allocated to Cortex)
- No new services — all changes are to existing Cortex, orchestrator, and memory-service
