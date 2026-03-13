# Cortex Proactivity Engine — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Cortex from a fixed-interval polling loop into a stimulus-driven autonomous brain with engram memory integration and goal scheduling.

**Architecture:** Cortex's `asyncio.sleep` loop becomes a `BRPOP`-based hybrid that wakes on stimuli or times out adaptively. Services push typed stimuli to a Redis list (`cortex:stimuli` on db5). Goals gain cron scheduling columns. Cortex reads engrams during PERCEIVE, writes reflections as engrams during REFLECT, and triggers consolidation when idle. All five drives become stimulus-aware.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, redis.asyncio (BRPOP), httpx, croniter

**Spec:** `docs/specs/cortex-proactivity-engine.md`

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `cortex/app/stimulus.py` | Stimulus type constants, `drain_stimuli()` helper, `emit_stimulus()` for self-injection |
| `cortex/app/memory.py` | Engram integration: `perceive_with_memory()`, `reflect_to_engrams()`, `maybe_consolidate()`, `mark_engrams_used()` |
| `cortex/app/scheduler.py` | Schedule checking: `check_schedules()` queries due goals, advances `schedule_next_at` |
| `orchestrator/app/migrations/024_goal_schedules.sql` | Migration: add schedule columns to `goals` table |
| `orchestrator/app/stimulus.py` | Thin `emit_stimulus()` helper for orchestrator (pushes to Redis db5) |
| `memory-service/app/engram/cortex_stimulus.py` | Thin `emit_to_cortex()` helper for memory-service (pushes to Redis db5) |

### Modified Files
| File | What Changes |
|---|---|
| `cortex/app/loop.py` | Replace `asyncio.sleep` with BRPOP hybrid, drain stimuli, adaptive timeout |
| `cortex/app/cycle.py` | Accept `stimuli` param, add memory PERCEIVE, engram REFLECT, idle consolidation |
| `cortex/app/config.py` | Add 7 new settings (intervals, memory flags, consolidation cooldown) |
| `cortex/app/drives/__init__.py` | Add `DriveContext` dataclass, update `evaluate()` signature |
| `cortex/app/drives/serve.py` | Accept `DriveContext`, react to `message.received` and `goal.schedule_due` stimuli |
| `cortex/app/drives/maintain.py` | Accept `DriveContext`, react to `health.degraded` stimulus |
| `cortex/app/drives/improve.py` | Replace stub with real logic: react to `engram.contradiction` |
| `cortex/app/drives/reflect.py` | Replace stub with real logic: cycle-count-based urgency, budget tier change |
| `cortex/app/drives/learn.py` | Accept `DriveContext`, use memory context |
| `cortex/pyproject.toml` | Add `croniter>=1.0` dependency |
| `orchestrator/app/goals_router.py` | Add schedule fields to Create/Update/Response models, validate cron, compute next_at |
| `orchestrator/app/agents/runner.py` | Emit `message.received` stimulus after receiving user messages |
| `memory-service/app/engram/consolidation.py` | Emit `consolidation.complete` stimulus after consolidation |
| `memory-service/app/engram/ingestion.py` | Emit `engram.contradiction` stimulus when contradictions found |

---

## Chunk 1: Stimulus Infrastructure + BRPOP Loop

### Task 1: Add Config Settings

**Files:**
- Modify: `cortex/app/config.py:28-29` (after cycle_interval_seconds)

- [ ] **Step 1: Add new settings to config**

Add these settings after line 29 (`enabled`):

```python
    # Adaptive intervals
    max_idle_interval: int = int(os.getenv("CORTEX_MAX_IDLE_INTERVAL", "1800"))
    active_interval: int = int(os.getenv("CORTEX_ACTIVE_INTERVAL", "30"))
    moderate_interval: int = int(os.getenv("CORTEX_MODERATE_INTERVAL", "60"))

    # Memory integration
    memory_enabled: bool = os.getenv("CORTEX_MEMORY_ENABLED", "true").lower() == "true"
    reflect_to_engrams: bool = os.getenv("CORTEX_REFLECT_TO_ENGRAMS", "true").lower() == "true"
    idle_consolidation: bool = os.getenv("CORTEX_IDLE_CONSOLIDATION", "true").lower() == "true"
    consolidation_cooldown: int = int(os.getenv("CORTEX_CONSOLIDATION_COOLDOWN", "1800"))
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/config.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add cortex/app/config.py
git commit -m "feat(cortex): add proactivity engine config settings"
```

---

### Task 2: Create Stimulus Module

**Files:**
- Create: `cortex/app/stimulus.py`

- [ ] **Step 1: Write the stimulus module**

This module defines stimulus types, draining logic, and self-emission:

```python
"""Stimulus queue — BRPOP-based event system for Cortex.

Services push typed JSON stimuli to Redis list `cortex:stimuli` (db5).
Cortex drains the queue each cycle via BRPOP with adaptive timeout.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from .config import settings

log = logging.getLogger(__name__)

# Redis key for the stimulus queue (on cortex's db5)
STIMULUS_KEY = "cortex:stimuli"

# Maximum stimuli to drain per cycle (prevents runaway)
MAX_DRAIN = 50

# Stimulus type constants
MESSAGE_RECEIVED = "message.received"
GOAL_CREATED = "goal.created"
GOAL_SCHEDULE_DUE = "goal.schedule_due"
GOAL_DEADLINE_APPROACHING = "goal.deadline_approaching"
HEALTH_DEGRADED = "health.degraded"
CONSOLIDATION_COMPLETE = "consolidation.complete"
ENGRAM_CONTRADICTION = "engram.contradiction"
BUDGET_TIER_CHANGE = "budget.tier_change"

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get or create the Redis connection for stimulus queue."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close Redis connection. Call at shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def brpop_stimulus(timeout: int) -> list[dict]:
    """Block until a stimulus arrives or timeout expires, then drain the queue.

    Returns a list of stimulus dicts (may be empty on timeout).
    """
    r = await get_redis()
    stimuli: list[dict] = []

    try:
        result = await r.brpop(STIMULUS_KEY, timeout=timeout)
        if result:
            # result is (key, value) tuple
            stimuli.append(json.loads(result[1]))

            # Drain remaining without blocking (up to MAX_DRAIN)
            while len(stimuli) < MAX_DRAIN:
                extra = await r.rpop(STIMULUS_KEY)
                if extra is None:
                    break
                stimuli.append(json.loads(extra))
    except Exception as e:
        log.warning("BRPOP error (will retry next cycle): %s", e)

    return stimuli


async def emit(type: str, source: str, payload: dict | None = None, priority: int = 0) -> None:
    """Push a stimulus onto the queue. Used by Cortex for self-injection."""
    stimulus = {
        "type": type,
        "source": source,
        "payload": payload or {},
        "priority": priority,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = await get_redis()
        await r.lpush(STIMULUS_KEY, json.dumps(stimulus))
    except Exception as e:
        log.warning("Failed to emit stimulus %s: %s", type, e)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/stimulus.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add cortex/app/stimulus.py
git commit -m "feat(cortex): add stimulus queue module with BRPOP drain"
```

---

### Task 3: Rewrite Loop to BRPOP Hybrid

**Files:**
- Modify: `cortex/app/loop.py` (full rewrite)

- [ ] **Step 1: Rewrite loop.py**

Replace the entire file. The key change: `asyncio.sleep(interval)` becomes `brpop_stimulus(timeout)`.

```python
"""Background thinking loop — BRPOP hybrid with adaptive timeout.

Wakes immediately on stimulus, or after timeout for periodic drive evaluation.
Replaces the fixed-interval sleep loop with event-driven reactivity.
"""
from __future__ import annotations

import asyncio
import logging

from .config import settings
from .cycle import run_cycle
from .db import get_pool
from .stimulus import brpop_stimulus, close_redis

log = logging.getLogger(__name__)

_task: asyncio.Task | None = None


async def start() -> None:
    """Start the thinking loop as a background task."""
    global _task
    if _task is not None:
        log.warning("Thinking loop already running")
        return
    _task = asyncio.create_task(_loop(), name="cortex-thinking-loop")
    log.info("Thinking loop started (initial_interval=%ds, enabled=%s)",
             settings.cycle_interval_seconds, settings.enabled)


async def stop() -> None:
    """Stop the thinking loop gracefully."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    await close_redis()
    log.info("Thinking loop stopped")


async def _loop() -> None:
    """Main loop — BRPOP for stimuli, run cycle, adapt timeout."""
    # Initial delay: let other services finish starting
    await asyncio.sleep(15)

    timeout = settings.cycle_interval_seconds  # Start with configured interval

    while True:
        try:
            # Check if enabled
            if not settings.enabled:
                log.debug("Cortex disabled — sleeping %ds", timeout)
                await asyncio.sleep(timeout)
                continue

            # Check if paused
            pool = get_pool()
            async with pool.acquire() as conn:
                status = await conn.fetchval(
                    "SELECT status FROM cortex_state WHERE id = true"
                )

            if status == "paused":
                log.debug("Cortex paused — sleeping %ds", timeout)
                await asyncio.sleep(timeout)
                continue

            # Block until stimulus arrives or timeout expires
            stimuli = await brpop_stimulus(timeout)

            if stimuli:
                log.info("Woke on %d stimulus(i): %s",
                         len(stimuli),
                         ", ".join(s.get("type", "?") for s in stimuli[:5]))
            else:
                log.debug("Woke on timeout (%ds) — periodic check", timeout)

            # Run one cycle with stimuli
            state = await run_cycle(stimuli=stimuli)
            log.info(
                "Cycle %d complete: drive=%s, outcome=%s",
                state.cycle_number,
                state.action_taken,
                (state.outcome[:80] if state.outcome else "none"),
            )

            # Adaptive timeout
            if stimuli or state.action_taken not in ("idle", "none"):
                timeout = settings.active_interval
            elif state.error:
                timeout = min(timeout * 3, settings.max_idle_interval)
            elif any(r.urgency > 0.3 for r in state.drive_results):
                timeout = settings.moderate_interval
            else:
                timeout = min(timeout * 2, settings.max_idle_interval)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Thinking loop error: %s", e, exc_info=True)
            # On unexpected error, fall back to fixed interval to avoid tight loops
            timeout = settings.cycle_interval_seconds
            await asyncio.sleep(60)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/loop.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add cortex/app/loop.py
git commit -m "feat(cortex): replace sleep loop with BRPOP stimulus-driven hybrid"
```

---

### Task 4: Update cycle.py to Accept Stimuli

**Files:**
- Modify: `cortex/app/cycle.py`

This task only wires the `stimuli` parameter through to `run_cycle()` and passes it to drives. Memory integration and idle consolidation come in later tasks.

- [ ] **Step 1: Update CycleState to carry stimuli**

Add `stimuli` field to `CycleState` dataclass (after `user_messages`):

```python
    stimuli: list[dict] = field(default_factory=list)
```

- [ ] **Step 2: Update run_cycle signature and PERCEIVE**

Change `run_cycle()` signature from `async def run_cycle() -> CycleState:` to:

```python
async def run_cycle(stimuli: list[dict] | None = None) -> CycleState:
```

At the start of the function, after `state = CycleState()`, add:

```python
    state.stimuli = stimuli or []
```

- [ ] **Step 3: Pass stimuli to drive assess() calls**

Update the top-level import on line 21 from:
```python
from .drives import DriveResult, DriveWinner, evaluate
```
to:
```python
from .drives import DriveContext, DriveResult, DriveWinner, evaluate
```

Then in the EVALUATE section, change:

```python
            for drive_module in ALL_DRIVES:
                try:
                    result = await drive_module.assess()
                    state.drive_results.append(result)
                except Exception as e:
                    log.warning("Drive %s.assess() failed: %s", drive_module.__name__, e)
```

To:

```python
            drive_ctx = DriveContext(
                stimuli=state.stimuli,
                memory_context="",
                budget_tier=state.budget_tier,
                cycle_count=state.cycle_number,
            )

            for drive_module in ALL_DRIVES:
                try:
                    result = await drive_module.assess(drive_ctx)
                    state.drive_results.append(result)
                except Exception as e:
                    log.warning("Drive %s.assess() failed: %s", drive_module.__name__, e)
```

- [ ] **Step 4: Add memory_context to _plan_action prompt**

In `_plan_action()`, after the `user_msg_summary` block, add:

```python
    stimulus_summary = ""
    if state.stimuli:
        stim_types = ", ".join(s.get("type", "?") for s in state.stimuli[:5])
        stimulus_summary = f"\nStimuli this cycle: {stim_types}"
```

And include `{stimulus_summary}` in the prompt string after `{user_msg_summary}`.

- [ ] **Step 5: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/cycle.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): wire stimuli through cycle and drive evaluation"
```

---

### Task 5: Update DriveContext and All Drives

**Files:**
- Modify: `cortex/app/drives/__init__.py`
- Modify: `cortex/app/drives/serve.py`
- Modify: `cortex/app/drives/maintain.py`
- Modify: `cortex/app/drives/improve.py`
- Modify: `cortex/app/drives/learn.py`
- Modify: `cortex/app/drives/reflect.py`

- [ ] **Step 1: Add DriveContext to drives/__init__.py**

Add after the `DriveWinner` dataclass:

```python
@dataclass
class DriveContext:
    """Context passed to each drive's assess() method."""
    stimuli: list[dict] = field(default_factory=list)
    memory_context: str = ""
    budget_tier: str = "best"
    cycle_count: int = 0

    def stimuli_of_type(self, *types: str) -> list[dict]:
        """Filter stimuli by type."""
        return [s for s in self.stimuli if s.get("type") in types]
```

Update the `evaluate` function to also export `DriveContext` — no changes needed to evaluate itself, just ensure the import in `__init__.py` includes it.

- [ ] **Step 2: Update serve.py to accept DriveContext and react to stimuli**

Replace the full `assess()` function:

```python
async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Assess serve drive urgency based on active goals and stimuli."""
    pool = get_pool()
    async with pool.acquire() as conn:
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM goals WHERE status = 'active'"
        )

        stale_goals = await conn.fetch(
            """
            SELECT id, title, priority, progress, check_interval_seconds, last_checked_at
            FROM goals
            WHERE status = 'active'
              AND (last_checked_at IS NULL
                   OR last_checked_at < NOW() - (check_interval_seconds || ' seconds')::interval)
            ORDER BY priority DESC
            LIMIT 5
            """,
        )

        active_tasks = await conn.fetchval(
            """
            SELECT COUNT(*) FROM tasks t
            JOIN goals g ON t.goal_id = g.id
            WHERE g.status = 'active' AND t.status IN ('queued', 'running')
            """
        )

    if active_count == 0 and (ctx is None or not ctx.stimuli_of_type(
        "message.received", "goal.created", "goal.schedule_due"
    )):
        return DriveResult(
            name="serve", priority=1, urgency=0.0,
            description="No active goals",
        )

    # Base urgency from stale goals
    stale_ratio = len(stale_goals) / max(active_count, 1) if active_count > 0 else 0
    urgency = min(1.0, 0.2 + stale_ratio * 0.6)

    # If tasks are already in-flight, reduce urgency
    if active_tasks > 0:
        urgency *= 0.5

    # Stimulus boosts
    if ctx:
        schedule_due = ctx.stimuli_of_type("goal.schedule_due")
        if schedule_due:
            urgency = max(urgency, 0.9)  # Near-guaranteed execution

        if ctx.stimuli_of_type("message.received"):
            urgency = min(1.0, urgency + 0.3)

        if ctx.stimuli_of_type("goal.created"):
            urgency = min(1.0, urgency + 0.2)

    goal_summaries = [
        {"id": str(g["id"]), "title": g["title"], "priority": g["priority"],
         "progress": g["progress"]}
        for g in stale_goals
    ]

    # Include scheduled goal info in context if it triggered us
    scheduled_goal_ids = []
    if ctx:
        for s in ctx.stimuli_of_type("goal.schedule_due"):
            gid = s.get("payload", {}).get("goal_id")
            if gid:
                scheduled_goal_ids.append(gid)

    return DriveResult(
        name="serve",
        priority=1,
        urgency=round(urgency, 2),
        description=f"{active_count} active goals, {len(stale_goals)} need attention",
        proposed_action=f"Work on goal: {stale_goals[0]['title']}" if stale_goals else None,
        context={
            "stale_goals": goal_summaries,
            "active_tasks": active_tasks,
            "scheduled_goal_ids": scheduled_goal_ids,
        },
    )
```

- [ ] **Step 3: Update maintain.py to accept DriveContext and handle stimuli**

Replace the full `assess()` function. The key change: `urgency` is initialized to 0.0 at the top, stimulus check happens before the early return so `health.degraded` stimuli work even when local health checks pass.

Add the import: `from . import DriveContext` at the top (after `from . import DriveResult`).

```python
async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Assess maintain drive urgency based on service health and stimuli."""
    checks: dict[str, str] = {}

    for name, get_client in SERVICES:
        try:
            client = get_client()
            resp = await client.get("/health/live", timeout=5.0)
            checks[name] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            checks[name] = f"error: {type(e).__name__}"

    degraded = [name for name, status in checks.items() if status != "ok"]
    urgency = 0.0

    if degraded:
        urgency = min(1.0, len(degraded) / len(SERVICES) + 0.3)

    # Stimulus boost (before early return so external signals aren't missed)
    if ctx and ctx.stimuli_of_type("health.degraded"):
        urgency = max(urgency, 0.7)

    if urgency == 0.0:
        return DriveResult(
            name="maintain", priority=2, urgency=0.0,
            description="All services healthy",
            context={"checks": checks},
        )

    return DriveResult(
        name="maintain",
        priority=2,
        urgency=round(urgency, 2),
        description=f"Degraded: {', '.join(degraded)}" if degraded else "External health alert",
        proposed_action=f"Investigate {degraded[0]} health issue" if degraded else "Check health alert",
        context={"checks": checks, "degraded": degraded},
    )
```

- [ ] **Step 4: Replace improve.py stub with real logic**

```python
"""Improve drive — investigate contradictions and system improvements.

Reacts to engram.contradiction stimuli and neural router readiness.
"""
from __future__ import annotations

import logging

from ..clients import get_memory
from . import DriveContext, DriveResult

log = logging.getLogger(__name__)


async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Assess improve drive urgency based on contradictions and system signals."""
    urgency = 0.0
    description_parts = []
    context = {}

    # React to contradiction stimuli
    if ctx:
        contradictions = ctx.stimuli_of_type("engram.contradiction")
        if contradictions:
            urgency = max(urgency, 0.4)
            description_parts.append(f"{len(contradictions)} contradictions detected")
            context["contradictions"] = [s.get("payload", {}) for s in contradictions]

    # Check neural router status
    try:
        mem = get_memory()
        resp = await mem.get("/api/v1/engrams/router-status", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ready_for_training") and not data.get("model_loaded"):
                urgency = max(urgency, 0.3)
                description_parts.append("Neural router ready for training")
                context["router_status"] = data
    except Exception as e:
        log.debug("Failed to check router status: %s", e)

    if urgency == 0.0:
        return DriveResult(
            name="improve", priority=3, urgency=0.0,
            description="No improvement signals",
        )

    return DriveResult(
        name="improve",
        priority=3,
        urgency=round(urgency, 2),
        description="; ".join(description_parts),
        proposed_action="Investigate and resolve detected issues",
        context=context,
    )
```

- [ ] **Step 5: Replace reflect.py stub with real logic**

```python
"""Reflect drive — learn from experience, review past patterns.

Urgency rises after many cycles without reflection, or on budget exhaustion.
"""
from __future__ import annotations

import logging

from ..db import get_pool
from . import DriveContext, DriveResult

log = logging.getLogger(__name__)

# Track cycles since last reflection (reset when reflect drive wins)
_cycles_since_reflect: int = 0


def reset_reflect_counter() -> None:
    """Call after reflect drive executes."""
    global _cycles_since_reflect
    _cycles_since_reflect = 0


async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Assess reflect drive urgency based on cycle count and budget state."""
    global _cycles_since_reflect
    _cycles_since_reflect += 1

    urgency = 0.0
    description_parts = []

    # Urgency rises with cycles since last reflection (0.1 per 10 cycles, cap 0.5)
    cycle_urgency = min(0.5, (_cycles_since_reflect // 10) * 0.1)
    if cycle_urgency > 0:
        urgency = max(urgency, cycle_urgency)
        description_parts.append(f"{_cycles_since_reflect} cycles since last reflection")

    # Budget tier change to "none" — good time to reflect on spend
    if ctx and ctx.stimuli_of_type("budget.tier_change"):
        for s in ctx.stimuli_of_type("budget.tier_change"):
            if s.get("payload", {}).get("new_tier") == "none":
                urgency = max(urgency, 0.6)
                description_parts.append("Budget exhausted — time to reflect on spending")

    if urgency == 0.0:
        return DriveResult(
            name="reflect", priority=5, urgency=0.0,
            description="No reflection needed yet",
        )

    return DriveResult(
        name="reflect",
        priority=5,
        urgency=round(urgency, 2),
        description="; ".join(description_parts),
        proposed_action="Review recent drive patterns and outcomes, write reflection engram",
        context={"cycles_since_reflect": _cycles_since_reflect},
    )
```

- [ ] **Step 6: Update learn.py to accept DriveContext**

Change signature to `async def assess(ctx: DriveContext | None = None) -> DriveResult:`.

Add `from . import DriveContext` to the imports (alongside `DriveResult`).

No other changes — the learn drive already works, it just needs the new signature.

- [ ] **Step 7: Verify all drive files compile**

Run:
```bash
cd /home/jeremy/workspace/nova && python -c "
import ast
for f in [
    'cortex/app/drives/__init__.py',
    'cortex/app/drives/serve.py',
    'cortex/app/drives/maintain.py',
    'cortex/app/drives/improve.py',
    'cortex/app/drives/learn.py',
    'cortex/app/drives/reflect.py',
]:
    ast.parse(open(f).read())
    print(f'  {f}: OK')
"
```
Expected: All OK

- [ ] **Step 8: Commit**

```bash
git add cortex/app/drives/
git commit -m "feat(cortex): stimulus-aware drives with DriveContext, activate improve+reflect"
```

---

## Chunk 2: Goal Scheduling

### Task 6: Migration — Add Schedule Columns to Goals

**Files:**
- Create: `orchestrator/app/migrations/024_goal_schedules.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 024: Goal scheduling — cron expressions, next run tracking, completion counting

ALTER TABLE goals ADD COLUMN IF NOT EXISTS schedule_cron TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS schedule_next_at TIMESTAMPTZ;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS schedule_last_ran_at TIMESTAMPTZ;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS max_completions INTEGER;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS completion_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS created_via TEXT NOT NULL DEFAULT 'api';

-- Index for efficient schedule checking (Cortex PERCEIVE phase)
CREATE INDEX IF NOT EXISTS goals_schedule_due_idx
    ON goals (schedule_next_at)
    WHERE status = 'active'
      AND schedule_cron IS NOT NULL
      AND schedule_next_at IS NOT NULL;

COMMENT ON COLUMN goals.schedule_cron IS 'Cron expression (e.g. "0 8 * * 1-5") — NULL means no schedule';
COMMENT ON COLUMN goals.schedule_next_at IS 'Next scheduled execution time — advanced by Cortex after each run';
COMMENT ON COLUMN goals.max_completions IS 'NULL = unlimited recurring, 1 = one-shot reminder';
COMMENT ON COLUMN goals.created_via IS 'api | chat | cortex — how the goal was created';
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/migrations/024_goal_schedules.sql
git commit -m "feat(db): add goal scheduling columns (cron, next_at, completions)"
```

---

### Task 7: Update Goals API for Scheduling

**Files:**
- Modify: `orchestrator/app/goals_router.py`

- [ ] **Step 1: Add schedule fields to request/response models**

Add to `CreateGoalRequest` (after `parent_goal_id`):

```python
    schedule_cron: str | None = None
    max_completions: int | None = None
    created_via: str = "api"
```

Add to `UpdateGoalRequest` (after `check_interval_seconds`):

```python
    schedule_cron: str | None = Field(default=None, description="Cron expression or None to clear")
    max_completions: int | None = None
```

Add to `GoalResponse` (after `parent_goal_id`):

```python
    schedule_cron: str | None
    schedule_next_at: datetime | None
    schedule_last_ran_at: datetime | None
    max_completions: int | None
    completion_count: int
    created_via: str
```

- [ ] **Step 2: Add croniter dependency to orchestrator**

Add `"croniter>=1.0",` to the dependencies list in `orchestrator/pyproject.toml`.

- [ ] **Step 3: Add cron validation helper**

Add after the imports:

```python
def _validate_and_compute_next(cron_expr: str) -> datetime:
    """Validate a cron expression and return the next fire time."""
    from croniter import croniter
    if not croniter.is_valid(cron_expr):
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {cron_expr}")
    return croniter(cron_expr, datetime.now(timezone.utc)).get_next(datetime)
```

Change `from datetime import datetime` to `from datetime import datetime, timezone`.

- [ ] **Step 4: Update create_goal to handle schedule fields**

Replace the INSERT query in `create_goal`:

```python
    pool = get_pool()
    schedule_next_at = None
    if req.schedule_cron:
        schedule_next_at = _validate_and_compute_next(req.schedule_cron)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO goals (title, description, priority, max_iterations,
                               max_cost_usd, check_interval_seconds, parent_goal_id,
                               created_by, schedule_cron, schedule_next_at,
                               max_completions, created_via)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING *
            """,
            req.title, req.description, req.priority, req.max_iterations,
            req.max_cost_usd, req.check_interval_seconds,
            req.parent_goal_id, user.email,
            req.schedule_cron, schedule_next_at,
            req.max_completions, req.created_via,
        )
```

- [ ] **Step 5: Handle schedule_cron in update_goal**

In `update_goal`, after `updates = req.model_dump(exclude_none=True)`, add:

```python
    # If cron is being updated, recompute next_at
    if "schedule_cron" in updates:
        cron_val = updates["schedule_cron"]
        if cron_val:
            updates["schedule_next_at"] = _validate_and_compute_next(cron_val)
        else:
            updates["schedule_next_at"] = None
```

- [ ] **Step 6: Update _row_to_goal to include new fields**

Add to the `GoalResponse` construction in `_row_to_goal`:

```python
        schedule_cron=row["schedule_cron"],
        schedule_next_at=row["schedule_next_at"],
        schedule_last_ran_at=row["schedule_last_ran_at"],
        max_completions=row["max_completions"],
        completion_count=row["completion_count"],
        created_via=row["created_via"],
```

- [ ] **Step 7: Verify syntax**

Run: `python -c "import ast; ast.parse(open('orchestrator/app/goals_router.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 8: Commit**

```bash
git add orchestrator/pyproject.toml orchestrator/app/goals_router.py
git commit -m "feat(orchestrator): add schedule fields to goals API (cron, next_at, completions)"
```

---

### Task 8: Create Scheduler Module in Cortex

**Files:**
- Create: `cortex/app/scheduler.py`
- Modify: `cortex/pyproject.toml` (add croniter)

- [ ] **Step 1: Add croniter dependency**

Add `"croniter>=1.0",` to the dependencies list in `cortex/pyproject.toml`.

- [ ] **Step 2: Write the scheduler module**

```python
"""Goal schedule checker — queries due goals and emits stimuli.

Called during Cortex's PERCEIVE phase each cycle. Finds goals where
schedule_next_at <= now(), emits goal.schedule_due stimuli, and
advances schedule_next_at to the next fire time.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from croniter import croniter

from .db import get_pool
from .stimulus import GOAL_SCHEDULE_DUE

log = logging.getLogger(__name__)


async def check_schedules() -> list[dict]:
    """Find due scheduled goals and return stimuli dicts.

    Also advances schedule_next_at and increments completion_count.
    Returns stimulus dicts (not pushed to Redis — caller merges into cycle).
    """
    pool = get_pool()
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, priority, schedule_cron, max_completions, completion_count
            FROM goals
            WHERE status = 'active'
              AND schedule_cron IS NOT NULL
              AND schedule_next_at IS NOT NULL
              AND schedule_next_at <= $1
              AND (max_completions IS NULL OR completion_count < max_completions)
            ORDER BY priority DESC
            LIMIT 10
            """,
            now,
        )

        stimuli = []
        for row in rows:
            goal_id = str(row["id"])
            cron_expr = row["schedule_cron"]

            # Compute next fire time
            try:
                next_at = croniter(cron_expr, now).get_next(datetime)
            except (ValueError, KeyError):
                log.warning("Invalid cron for goal %s: %s — skipping", goal_id, cron_expr)
                continue

            # Advance schedule and increment count
            new_count = row["completion_count"] + 1
            await conn.execute(
                """
                UPDATE goals
                SET schedule_next_at = $1,
                    schedule_last_ran_at = $2,
                    completion_count = $3,
                    updated_at = NOW()
                WHERE id = $4
                """,
                next_at, now, new_count, row["id"],
            )

            # Auto-complete one-shot goals
            if row["max_completions"] is not None and new_count >= row["max_completions"]:
                await conn.execute(
                    "UPDATE goals SET status = 'completed', updated_at = NOW() WHERE id = $1",
                    row["id"],
                )
                log.info("Goal %s completed (max_completions=%d reached)", goal_id, row["max_completions"])

            stimuli.append({
                "type": GOAL_SCHEDULE_DUE,
                "source": "cortex",
                "payload": {"goal_id": goal_id, "title": row["title"]},
                "priority": row["priority"],
            })
            log.info("Schedule due: goal %s (%s), next at %s", goal_id, row["title"], next_at)

        return stimuli
```

- [ ] **Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/scheduler.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add cortex/pyproject.toml cortex/app/scheduler.py
git commit -m "feat(cortex): add goal scheduler with cron support"
```

---

### Task 9: Wire Scheduler into PERCEIVE Phase

**Files:**
- Modify: `cortex/app/cycle.py`

- [ ] **Step 1: Add scheduler import**

Add to imports at top of cycle.py:

```python
from .scheduler import check_schedules
```

- [ ] **Step 2: Call check_schedules in PERCEIVE**

In `run_cycle()`, after `state.user_messages = ...` and before the EVALUATE section comment, add:

```python
        # Check for due scheduled goals (self-inject stimuli)
        try:
            schedule_stimuli = await check_schedules()
            if schedule_stimuli:
                state.stimuli.extend(schedule_stimuli)
                log.info("Injected %d schedule stimuli", len(schedule_stimuli))
        except Exception as e:
            log.warning("Schedule check failed: %s", e)
```

- [ ] **Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/cycle.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): wire scheduler into PERCEIVE phase"
```

---

## Chunk 3: Engram Memory Integration

### Task 10: Create Memory Integration Module

**Files:**
- Create: `cortex/app/memory.py`

- [ ] **Step 1: Write the memory module**

```python
"""Engram memory integration for Cortex.

Three integration points:
1. PERCEIVE — query engram context for drive-informed decisions
2. REFLECT — write cycle outcomes as engrams for long-term learning
3. IDLE — trigger consolidation when nothing else to do
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .clients import get_memory
from .config import settings

log = logging.getLogger(__name__)


async def perceive_with_memory(stimuli: list[dict], goal_context: str = "") -> dict:
    """Query engram network for context relevant to current cycle.

    Returns dict with memory_context (str), engram_ids (list), retrieval_log_id (str|None).
    """
    if not settings.memory_enabled:
        return {"memory_context": "", "engram_ids": [], "retrieval_log_id": None}

    # Build a query from stimuli + goal context
    query_parts = []
    if goal_context:
        query_parts.append(f"Current goal: {goal_context}")
    for s in stimuli[:5]:
        query_parts.append(f"{s.get('type', 'unknown')}: {json.dumps(s.get('payload', {}))}")

    query = " | ".join(query_parts) or "general system status and pending work"

    try:
        mem = get_memory()
        resp = await mem.post(
            "/api/v1/engrams/context",
            json={"query": query, "session_id": "cortex-perceive", "current_turn": 0},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "memory_context": data.get("context", ""),
                "engram_ids": data.get("engram_ids", []),
                "retrieval_log_id": data.get("retrieval_log_id"),
            }
        log.debug("Memory context request returned %d", resp.status_code)
    except Exception as e:
        log.debug("Failed to get memory context: %s", e)

    return {"memory_context": "", "engram_ids": [], "retrieval_log_id": None}


async def reflect_to_engrams(
    cycle_number: int,
    drive: str,
    urgency: float,
    action_summary: str,
    outcome: str,
    goal_id: str | None = None,
    budget_tier: str = "best",
) -> None:
    """Ingest cycle outcome into engram network for long-term learning.

    Only ingests when an action was actually taken (not idle cycles).
    """
    if not settings.reflect_to_engrams:
        return

    raw_text = (
        f"Cortex cycle #{cycle_number}: "
        f"Drive '{drive}' won (urgency {urgency:.2f}). "
        f"Action: {action_summary}. "
        f"Outcome: {outcome}."
    )

    try:
        mem = get_memory()
        await mem.post(
            "/api/v1/engrams/ingest",
            json={
                "raw_text": raw_text,
                "source_type": "cortex",
                "source_id": "cortex-reflect",
                "metadata": {
                    "drive": drive,
                    "goal_id": goal_id,
                    "budget_tier": budget_tier,
                    "cycle": cycle_number,
                },
            },
            timeout=10.0,
        )
        log.debug("Reflected cycle %d to engrams", cycle_number)
    except Exception as e:
        log.debug("Failed to reflect to engrams: %s", e)


async def maybe_consolidate() -> bool:
    """Trigger consolidation if enough time has passed since last run.

    Returns True if consolidation was triggered.
    """
    if not settings.idle_consolidation:
        return False

    try:
        mem = get_memory()

        # Check last consolidation time
        resp = await mem.get("/api/v1/engrams/consolidation-log?limit=1", timeout=5.0)
        if resp.status_code == 200:
            entries = resp.json().get("entries", [])
            if entries:
                last_at = datetime.fromisoformat(entries[0]["created_at"])
                elapsed = (datetime.now(timezone.utc) - last_at).total_seconds()
                if elapsed < settings.consolidation_cooldown:
                    return False

        # Trigger consolidation (fire and forget with timeout)
        await mem.post("/api/v1/engrams/consolidate", timeout=30.0)
        log.info("Triggered idle consolidation")
        return True
    except Exception as e:
        log.debug("Consolidation trigger failed: %s", e)
        return False


async def mark_engrams_used(retrieval_log_id: str, engram_ids: list[str]) -> None:
    """Report which engrams were used during planning."""
    if not retrieval_log_id or not engram_ids:
        return
    try:
        mem = get_memory()
        await mem.post(
            "/api/v1/engrams/mark-used",
            json={"retrieval_log_id": retrieval_log_id, "engram_ids_used": engram_ids},
            timeout=5.0,
        )
    except Exception as e:
        log.debug("Failed to mark engrams used: %s", e)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/memory.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add cortex/app/memory.py
git commit -m "feat(cortex): add engram memory integration module"
```

---

### Task 11: Wire Memory into Cycle

**Depends on:** Tasks 4 (stimuli param + CycleState.stimuli), 5 (DriveContext), 9 (scheduler in PERCEIVE)

**Files:**
- Modify: `cortex/app/cycle.py`

- [ ] **Step 1: Add memory imports**

Add to imports:

```python
from .memory import perceive_with_memory, reflect_to_engrams, maybe_consolidate, mark_engrams_used
```

- [ ] **Step 2: Add memory_context and retrieval tracking to CycleState**

Add fields to `CycleState`:

```python
    memory_context: str = ""
    engram_ids: list[str] = field(default_factory=list)
    retrieval_log_id: str | None = None
```

- [ ] **Step 3: Add memory PERCEIVE after schedule check, before EVALUATE**

After the schedule check block and before `# ── EVALUATE`, add:

```python
        # Query engram memory for context
        goal_context = ""
        if state.stimuli:
            # Build goal context from schedule_due stimuli
            for s in state.stimuli:
                if s.get("type") == "goal.schedule_due":
                    goal_context = s.get("payload", {}).get("title", "")
                    break

        mem_result = await perceive_with_memory(state.stimuli, goal_context)
        state.memory_context = mem_result["memory_context"]
        state.engram_ids = mem_result["engram_ids"]
        state.retrieval_log_id = mem_result["retrieval_log_id"]
```

- [ ] **Step 4: Pass memory_context to DriveContext**

Update the `DriveContext` construction in EVALUATE to include memory:

```python
            drive_ctx = DriveContext(
                stimuli=state.stimuli,
                memory_context=state.memory_context,
                budget_tier=state.budget_tier,
                cycle_count=state.cycle_number,
            )
```

- [ ] **Step 5: Add memory context to planning prompt**

In `_plan_action()`, add memory context to the prompt. After the `stimulus_summary` block, add:

```python
    if state.memory_context:
        stimulus_summary += f"\n\nRelevant memories:\n{state.memory_context[:1000]}"
```

- [ ] **Step 6: Add idle consolidation when no drive wins**

In the block after `if state.winner is None:` (the idle block), before the journal write, add:

```python
            # Use idle time for memory consolidation
            if state.budget_tier != "none":
                try:
                    consolidated = await maybe_consolidate()
                    if consolidated:
                        state.action_taken = "idle_consolidation"
                        state.outcome = "Triggered memory consolidation during idle"
                except Exception as e:
                    log.debug("Idle consolidation failed: %s", e)
```

- [ ] **Step 7: Add engram reflection after _reflect()**

After `await _reflect(state)` in the main flow (the REFLECT section), add:

```python
        # Write cycle outcome to engram memory
        if state.action_taken not in ("idle", "none", "idle_consolidation"):
            await reflect_to_engrams(
                cycle_number=state.cycle_number,
                drive=state.action_taken,
                urgency=state.winner.result.urgency if state.winner else 0,
                action_summary=state.winner.result.proposed_action or state.action_taken if state.winner else state.action_taken,
                outcome=state.outcome[:500],
                goal_id=state.winner.result.context.get("scheduled_goal_ids", [None])[0] if state.winner else None,
                budget_tier=state.budget_tier,
            )

        # Mark engrams used (all retrieved engrams — coarse heuristic)
        if state.retrieval_log_id and state.engram_ids:
            await mark_engrams_used(state.retrieval_log_id, state.engram_ids)
```

- [ ] **Step 8: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/cycle.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 9: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): wire engram memory into PERCEIVE/REFLECT/idle consolidation"
```

---

## Chunk 4: Stimulus Emitters + Cortex Execute Enhancements

### Task 12: Orchestrator Stimulus Emitter

**Files:**
- Create: `orchestrator/app/stimulus.py`
- Modify: `orchestrator/app/agents/runner.py`
- Modify: `orchestrator/app/goals_router.py`

- [ ] **Step 1: Create the orchestrator stimulus helper**

```python
"""Stimulus emitter — pushes events to Cortex's stimulus queue.

Cortex runs on Redis db5. The orchestrator connects to db5 specifically
for stimulus emission (separate from its own db2 connection).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings

log = logging.getLogger(__name__)

STIMULUS_KEY = "cortex:stimuli"
_CORTEX_REDIS_DB = 5

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    """Get Redis connection pointing at Cortex's db5."""
    global _redis
    if _redis is None:
        import re
        base_url = re.sub(r"/\d+$", "", settings.redis_url)
        _redis = aioredis.from_url(f"{base_url}/{_CORTEX_REDIS_DB}", decode_responses=True)
    return _redis


async def emit_stimulus(type: str, payload: dict | None = None, priority: int = 0) -> None:
    """Push a stimulus to Cortex's queue. Fire-and-forget (never raises)."""
    stimulus = {
        "type": type,
        "source": "orchestrator",
        "payload": payload or {},
        "priority": priority,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = await _get_redis()
        await r.lpush(STIMULUS_KEY, json.dumps(stimulus))
    except Exception as e:
        log.debug("Failed to emit stimulus %s: %s", type, e)
```

- [ ] **Step 2: Emit message.received in agent runner**

In `orchestrator/app/agents/runner.py`, add import at top (after other app imports around line 28):

```python
from app.stimulus import emit_stimulus
```

In `run_agent_turn()`, after the query extraction at line 53 (`query = extract_text_content(...)`) and before the concurrent context fetch, add:

```python
        # Notify Cortex of new user message (fire-and-forget)
        try:
            await emit_stimulus("message.received", {
                "session_id": session_id,
                "preview": query[:100] if query else "",
            })
        except Exception:
            pass
```

Also add the same block in `run_agent_turn_streaming()` (line ~130) at the equivalent point after query extraction.

- [ ] **Step 3: Emit goal.created in goals_router**

In `orchestrator/app/goals_router.py`, add import:

```python
from app.stimulus import emit_stimulus
```

In `create_goal()`, after `log.info("Goal created: ...")`, add:

```python
    await emit_stimulus("goal.created", {
        "goal_id": str(row["id"]),
        "title": req.title,
        "schedule_cron": req.schedule_cron,
    })
```

- [ ] **Step 4: Verify syntax for all modified files**

Run:
```bash
cd /home/jeremy/workspace/nova && python -c "
import ast
for f in ['orchestrator/app/stimulus.py', 'orchestrator/app/goals_router.py']:
    ast.parse(open(f).read())
    print(f'  {f}: OK')
"
```
Expected: All OK

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/stimulus.py orchestrator/app/goals_router.py orchestrator/app/agents/runner.py
git commit -m "feat(orchestrator): emit stimulus events to Cortex on messages and goal creation"
```

---

### Task 13: Memory-Service Stimulus Emitters

**Files:**
- Modify: `memory-service/app/engram/consolidation.py`
- Modify: `memory-service/app/engram/ingestion.py`

These emitters push to Redis db5 (Cortex's DB). The memory-service normally uses db0, so we create a shared helper.

- [ ] **Step 1: Create shared stimulus helper for memory-service**

Create `memory-service/app/engram/cortex_stimulus.py`:

```python
"""Emit stimuli to Cortex's Redis queue (db5) from the memory-service."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings

log = logging.getLogger(__name__)

_cortex_redis: aioredis.Redis | None = None


async def emit_to_cortex(type: str, payload: dict | None = None) -> None:
    """Push a stimulus to Cortex's queue on Redis db5. Fire-and-forget."""
    global _cortex_redis
    if _cortex_redis is None:
        import re
        base_url = re.sub(r"/\d+$", "", str(settings.redis_url))
        _cortex_redis = aioredis.from_url(f"{base_url}/5", decode_responses=True)
    try:
        stimulus = {
            "type": type,
            "source": "memory-service",
            "payload": payload or {},
            "priority": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _cortex_redis.lpush("cortex:stimuli", json.dumps(stimulus))
    except Exception:
        pass  # Fire and forget
```

- [ ] **Step 2: Emit consolidation.complete at end of run_consolidation**

In `consolidation.py`, add import at top:

```python
from .cortex_stimulus import emit_to_cortex
```

At the end of `run_consolidation()`, before the final `return stats`, add:

```python
    await emit_to_cortex("consolidation.complete", {
        "engrams_reviewed": stats.get("engrams_reviewed", 0),
        "schemas_created": stats.get("schemas_created", 0),
        "contradictions_resolved": stats.get("contradictions_resolved", 0),
    })
```

- [ ] **Step 3: Emit engram.contradiction in ingestion.py**

In `ingestion.py`, add import at top:

```python
from .cortex_stimulus import emit_to_cortex
```

In the contradiction handling loop (line ~194), after the `log.info("Contradiction edge: ...")` on line 196, add:

```python
                        await emit_to_cortex("engram.contradiction", {
                            "engram_id": str(new_id),
                            "conflicting_with": str(candidate["id"]),
                        })
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('memory-service/app/engram/consolidation.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add memory-service/app/engram/cortex_stimulus.py memory-service/app/engram/consolidation.py memory-service/app/engram/ingestion.py
git commit -m "feat(memory-service): emit stimulus events to Cortex after consolidation and contradictions"
```

---

### Task 14: Add Reflect and Improve Executors to Cycle

**Depends on:** Task 5, Step 5 (reflect.py rewrite defines `reset_reflect_counter()`)

**Files:**
- Modify: `cortex/app/cycle.py`

Currently `_execute_action` only handles `serve` and `maintain`. We need executors for `improve`, `learn`, and `reflect`.

- [ ] **Step 1: Add executor routing for new drives**

In `_execute_action()`, replace:

```python
    else:
        return f"Drive '{drive.name}' has no executor yet (stub)"
```

With:

```python
    elif drive.name == "improve":
        return await _execute_improve(drive, plan)
    elif drive.name == "reflect":
        return await _execute_reflect(drive, plan, state)
    elif drive.name == "learn":
        return await _execute_learn(drive, plan, state)
    else:
        return f"Drive '{drive.name}' has no executor"
```

- [ ] **Step 2: Add _execute_improve**

```python
async def _execute_improve(drive: DriveResult, plan: str) -> str:
    """Execute an improve action — log improvement opportunity."""
    contradictions = drive.context.get("contradictions", [])
    router_status = drive.context.get("router_status")

    parts = []
    if contradictions:
        parts.append(f"Noted {len(contradictions)} engram contradictions for review")
    if router_status:
        parts.append(f"Neural router status: {router_status.get('mode', 'unknown')}")
    parts.append(f"Plan: {plan[:200]}")

    return "; ".join(parts) if parts else "No specific improvement action taken"
```

- [ ] **Step 3: Add _execute_reflect**

```python
async def _execute_reflect(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute a reflect action — summarize recent patterns."""
    from .drives.reflect import reset_reflect_counter
    reset_reflect_counter()

    # Write a reflection journal entry
    await write_entry(
        f"**Reflection** — {plan[:500]}",
        entry_type="reflection",
        metadata={"cycle": state.cycle_number, "drive": "reflect"},
    )
    return f"Reflection recorded. {plan[:200]}"
```

- [ ] **Step 4: Add _execute_learn**

```python
async def _execute_learn(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute a learn action — log learning opportunity."""
    gaps = drive.context.get("gaps", [])
    if gaps:
        gap_types = ", ".join(g.get("task_type", "unknown") for g in gaps)
        return f"Investigating capability gaps: {gap_types}. Plan: {plan[:200]}"
    return f"Learning action: {plan[:200]}"
```

- [ ] **Step 5: Verify syntax**

Run: `python -c "import ast; ast.parse(open('cortex/app/cycle.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat(cortex): add executors for improve, reflect, and learn drives"
```

---

### Task 15: Update Cortex main.py for Clean Shutdown

**Files:**
- Modify: `cortex/app/main.py`

The stimulus module's Redis connection needs cleanup on shutdown.

- [ ] **Step 1: Import stimulus close in main.py**

No changes needed — `loop.stop()` already calls `close_redis()` from the stimulus module.

Verify that `loop.py`'s `stop()` function calls `await close_redis()` (it should from Task 3).

- [ ] **Step 2: Verify the full import chain compiles**

Run:
```bash
cd /home/jeremy/workspace/nova && python -c "
import ast
for f in [
    'cortex/app/config.py',
    'cortex/app/stimulus.py',
    'cortex/app/memory.py',
    'cortex/app/scheduler.py',
    'cortex/app/loop.py',
    'cortex/app/cycle.py',
    'cortex/app/drives/__init__.py',
    'cortex/app/drives/serve.py',
    'cortex/app/drives/maintain.py',
    'cortex/app/drives/improve.py',
    'cortex/app/drives/reflect.py',
    'cortex/app/drives/learn.py',
    'cortex/app/main.py',
]:
    ast.parse(open(f).read())
    print(f'  {f}: OK')
print('All files compile.')
"
```
Expected: All OK

- [ ] **Step 3: Commit** (only if any changes were made)

```bash
git add cortex/app/main.py
git commit -m "chore(cortex): verify clean shutdown with stimulus redis"
```

---

## Chunk 5: Docker Compose + Integration Smoke Test

### Task 16: Update Docker Compose Environment

**Files:**
- Modify: `docker-compose.yml` (cortex service section)

- [ ] **Step 1: Add new env vars to cortex service**

In the cortex service's `environment` section, add:

```yaml
      CORTEX_MAX_IDLE_INTERVAL: 1800
      CORTEX_ACTIVE_INTERVAL: 30
      CORTEX_MEMORY_ENABLED: "true"
      CORTEX_REFLECT_TO_ENGRAMS: "true"
      CORTEX_IDLE_CONSOLIDATION: "true"
```

These are defaults that match the code defaults, but making them explicit in compose allows easy tuning.

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(compose): add cortex proactivity engine env vars"
```

---

### Task 17: Integration Smoke Test

**Files:**
- Existing test infrastructure at `tests/`

This task validates the end-to-end flow with running services.

- [ ] **Step 1: Verify services start**

Run: `make dev` (or `docker compose up --build -d`)

Check health endpoints:
```bash
curl -s http://localhost:8100/health/live | jq .
curl -s http://localhost:8002/health/live | jq .
curl -s http://localhost:8000/health/live | jq .
```

Expected: All return `{"status": "ok"}` or similar.

- [ ] **Step 2: Test goal creation with schedule**

```bash
curl -s -X POST http://localhost:8000/api/v1/goals \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: $(grep NOVA_ADMIN_SECRET .env | cut -d= -f2)" \
  -d '{
    "title": "Test scheduled goal",
    "description": "Integration test — safe to delete",
    "priority": 1,
    "schedule_cron": "0 8 * * *",
    "max_completions": 1,
    "created_via": "api"
  }' | jq .
```

Expected: Response includes `schedule_cron`, `schedule_next_at` (tomorrow 8am UTC), `completion_count: 0`.

- [ ] **Step 3: Verify Cortex status includes stimulus info**

```bash
curl -s http://localhost:8100/api/v1/cortex/status | jq .
curl -s http://localhost:8100/api/v1/cortex/drives | jq .
```

Expected: Cortex is running. Drives return results (serve may show the new goal).

- [ ] **Step 4: Check Cortex journal for activity**

```bash
curl -s http://localhost:8100/api/v1/cortex/journal?limit=5 | jq .
```

Expected: Recent entries showing cycle activity.

- [ ] **Step 5: Clean up test goal**

```bash
# Get the goal ID from step 2 output, then:
curl -s -X DELETE http://localhost:8000/api/v1/goals/<GOAL_ID> \
  -H "X-Admin-Secret: $(grep NOVA_ADMIN_SECRET .env | cut -d= -f2)"
```

- [ ] **Step 6: Final commit if any fixups were needed**

```bash
git add -p  # Stage only relevant fixes
git commit -m "fix(cortex): integration test fixups for proactivity engine"
```
