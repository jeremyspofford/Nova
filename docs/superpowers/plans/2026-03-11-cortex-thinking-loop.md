# Cortex Thinking Loop + Drives Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Cortex autonomous — a background loop that perceives state, evaluates drives, plans actions via LLM, dispatches work, and journals its thinking.

**Architecture:** The thinking loop runs as an asyncio background task in the Cortex service. Each cycle has 5 phases: PERCEIVE (gather state), EVALUATE (score drives), PLAN (LLM decides action), ACT (dispatch tasks or take action), REFLECT (journal results). Drives are independent modules that each compute an urgency score. The loop uses httpx to call orchestrator (goals, task dispatch), llm-gateway (planning/reflection), and memory-service (context retrieval). All thinking is narrated to a reserved journal conversation.

**Tech Stack:** Python 3.12, asyncio, httpx, asyncpg, FastAPI (existing Cortex service)

**Spec:** `docs/plans/2026-03-10-cortex-design.md`

---

## File Structure

### New files — Cortex service
| File | Responsibility |
|------|----------------|
| `cortex/app/clients.py` | httpx client pool for orchestrator, llm-gateway, memory-service |
| `cortex/app/journal.py` | Write/read entries in the Cortex journal conversation |
| `cortex/app/drives/__init__.py` | Drive base interface, evaluator (score all drives, pick winner) |
| `cortex/app/drives/serve.py` | Urgency from active goals needing work |
| `cortex/app/drives/maintain.py` | Urgency from service health degradation |
| `cortex/app/drives/improve.py` | Stub (urgency 0.0) — future: code quality signals |
| `cortex/app/drives/learn.py` | Stub (urgency 0.0) — future: knowledge gap detection |
| `cortex/app/drives/reflect.py` | Stub (urgency 0.0) — future: experience review |
| `cortex/app/cycle.py` | One thinking cycle — the 5-phase PERCEIVE→EVALUATE→PLAN→ACT→REFLECT |
| `cortex/app/loop.py` | asyncio background task — runs cycles on a timer, respects pause/budget |

### Modified files
| File | Change |
|------|--------|
| `cortex/app/main.py` | Start/stop the thinking loop in lifespan, init/close httpx clients |
| `cortex/app/router.py` | Replace static `/drives` with real urgency scores, add `/journal` endpoint |
| `cortex/app/config.py` | Add `cortex_api_key`, `journal_conversation_id`, `cortex_user_id`, model settings |

---

## Chunk 1: HTTP Clients + Journal + Config

### Task 1: Add config constants and httpx client pool

**Files:**
- Modify: `cortex/app/config.py`
- Create: `cortex/app/clients.py`

- [ ] **Step 1: Add constants to `cortex/app/config.py`**

Add these fields to the `Settings` class after `daily_budget_usd`:

```python
    # Well-known IDs from migration 021
    cortex_user_id: str = "a0000000-0000-0000-0000-000000000001"
    cortex_api_key: str = "sk-nova-cortex-internal"
    journal_conversation_id: str = "c0000000-0000-0000-0000-000000000001"

    # Model selection for Cortex's own LLM calls
    planning_model: str = os.getenv("CORTEX_PLANNING_MODEL", "")  # empty = use DEFAULT_CHAT_MODEL
    reflection_model: str = os.getenv("CORTEX_REFLECTION_MODEL", "")
```

- [ ] **Step 2: Create `cortex/app/clients.py`**

```python
"""HTTP client pool for inter-service communication."""
from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)

_orchestrator: httpx.AsyncClient | None = None
_llm: httpx.AsyncClient | None = None
_memory: httpx.AsyncClient | None = None


def _make_client(base_url: str, timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        limits=httpx.Limits(max_connections=10),
    )


async def init_clients() -> None:
    """Create httpx client pool. Call once at startup."""
    global _orchestrator, _llm, _memory
    _orchestrator = _make_client(settings.orchestrator_url, timeout=60.0)
    _llm = _make_client(settings.llm_gateway_url, timeout=120.0)
    _memory = _make_client(settings.memory_service_url)
    log.info("HTTP clients ready")


async def close_clients() -> None:
    """Close all httpx clients. Call at shutdown."""
    for client in (_orchestrator, _llm, _memory):
        if client:
            await client.aclose()
    log.info("HTTP clients closed")


def get_orchestrator() -> httpx.AsyncClient:
    if _orchestrator is None:
        raise RuntimeError("Orchestrator client not initialized")
    return _orchestrator


def get_llm() -> httpx.AsyncClient:
    if _llm is None:
        raise RuntimeError("LLM client not initialized")
    return _llm


def get_memory() -> httpx.AsyncClient:
    if _memory is None:
        raise RuntimeError("Memory client not initialized")
    return _memory
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile cortex/app/config.py && python3 -m py_compile cortex/app/clients.py && echo "OK"`

- [ ] **Step 4: Commit**

```bash
git add cortex/app/config.py cortex/app/clients.py
git commit -m "feat: add cortex config constants and httpx client pool"
```

---

### Task 2: Create journal module

**Files:**
- Create: `cortex/app/journal.py`

- [ ] **Step 1: Create `cortex/app/journal.py`**

```python
"""Cortex journal — narrates thinking to a reserved conversation."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from .config import settings
from .db import get_pool

log = logging.getLogger(__name__)

JOURNAL_ID = UUID(settings.journal_conversation_id)
CORTEX_USER_ID = UUID(settings.cortex_user_id)


async def write_entry(
    content: str,
    entry_type: str = "narration",
    metadata: dict | None = None,
) -> UUID:
    """Write a journal entry to the Cortex conversation.

    entry_type: narration | progress | completion | question | escalation | reflection
    """
    meta = {
        "type": entry_type,
        "source": "cortex",
        **(metadata or {}),
    }
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO messages (conversation_id, role, content, metadata)
            VALUES ($1, 'assistant', $2, $3::jsonb)
            RETURNING id
            """,
            JOURNAL_ID,
            content,
            json.dumps(meta),
        )
        await conn.execute(
            "UPDATE conversations SET last_message_at = NOW(), updated_at = NOW() WHERE id = $1",
            JOURNAL_ID,
        )
    msg_id = row["id"]
    log.debug("Journal entry [%s]: %s", entry_type, content[:80])
    return msg_id


async def read_recent(limit: int = 20) -> list[dict]:
    """Read recent journal entries, newest first."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, role, content, metadata, created_at
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            JOURNAL_ID,
            limit,
        )
    return [
        {
            "id": str(r["id"]),
            "role": r["role"],
            "content": r["content"],
            "metadata": r["metadata"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def read_user_replies_since(since: datetime) -> list[dict]:
    """Read user replies to the journal since a given time.

    These are messages from the human directing Cortex behavior.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, metadata, created_at
            FROM messages
            WHERE conversation_id = $1 AND role = 'user' AND created_at > $2
            ORDER BY created_at
            """,
            JOURNAL_ID,
            since,
        )
    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "metadata": r["metadata"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile cortex/app/journal.py && echo "OK"`

- [ ] **Step 3: Commit**

```bash
git add cortex/app/journal.py
git commit -m "feat: add cortex journal module (write/read conversation entries)"
```

---

## Chunk 2: Drive System

### Task 3: Create drive base and evaluator

**Files:**
- Create: `cortex/app/drives/__init__.py`

- [ ] **Step 1: Create `cortex/app/drives/__init__.py`**

```python
"""Drive system — each drive computes urgency and proposes actions.

Priority × urgency determines which drive wins each cycle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class DriveResult:
    """Output from a drive's assess() method."""
    name: str
    priority: int
    urgency: float  # 0.0–1.0
    description: str
    proposed_action: str | None = None  # Human-readable action description
    context: dict = field(default_factory=dict)  # Data for the PLAN phase


@dataclass
class DriveWinner:
    """The winning drive after evaluation."""
    result: DriveResult
    score: float  # priority_weight * urgency


# Priority weights — lower priority number = higher weight
PRIORITY_WEIGHTS = {1: 5.0, 2: 4.0, 3: 3.0, 4: 2.0, 5: 1.0}


def evaluate(results: list[DriveResult], budget_tier: str) -> DriveWinner | None:
    """Score all drives, apply budget penalty, return the winner.

    Returns None if no drive has urgency > 0 or budget is exhausted.
    """
    if budget_tier == "none":
        # Budget exhausted — only maintain can run (health checks are free)
        results = [r for r in results if r.name == "maintain"]

    scored = []
    for r in results:
        if r.urgency <= 0:
            continue
        weight = PRIORITY_WEIGHTS.get(r.priority, 1.0)
        score = weight * r.urgency

        # Budget penalty: reduce score for expensive drives when budget is tight
        if budget_tier == "cheap" and r.name not in ("maintain", "reflect"):
            score *= 0.3
        elif budget_tier == "mid" and r.name in ("improve", "learn"):
            score *= 0.5

        scored.append(DriveWinner(result=r, score=score))

    if not scored:
        return None

    scored.sort(key=lambda w: w.score, reverse=True)
    winner = scored[0]
    log.info(
        "Drive evaluation: winner=%s score=%.2f (urgency=%.2f, tier=%s) | %s",
        winner.result.name, winner.score, winner.result.urgency,
        budget_tier,
        ", ".join(f"{s.result.name}={s.score:.2f}" for s in scored),
    )
    return winner
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile cortex/app/drives/__init__.py && echo "OK"`

- [ ] **Step 3: Commit**

```bash
git add cortex/app/drives/__init__.py
git commit -m "feat: add drive base interface and evaluator with budget-aware scoring"
```

---

### Task 4: Create serve and maintain drives

**Files:**
- Create: `cortex/app/drives/serve.py`
- Create: `cortex/app/drives/maintain.py`

- [ ] **Step 1: Create `cortex/app/drives/serve.py`**

```python
"""Serve drive — pursue user-set goals.

Urgency is based on:
- Number of active goals
- Whether any goals have pending tasks or need new work
- Time since last check
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..db import get_pool
from . import DriveResult

log = logging.getLogger(__name__)


async def assess() -> DriveResult:
    """Assess serve drive urgency based on active goals."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Count active goals
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM goals WHERE status = 'active'"
        )

        # Find goals needing attention (not checked recently)
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

        # Count in-flight tasks for active goals
        active_tasks = await conn.fetchval(
            """
            SELECT COUNT(*) FROM tasks t
            JOIN goals g ON t.goal_id = g.id
            WHERE g.status = 'active' AND t.status IN ('queued', 'running')
            """
        )

    if active_count == 0:
        return DriveResult(
            name="serve", priority=1, urgency=0.0,
            description="No active goals",
        )

    # Urgency increases with stale goals
    stale_ratio = len(stale_goals) / max(active_count, 1)
    urgency = min(1.0, 0.2 + stale_ratio * 0.6)

    # If tasks are already in-flight, reduce urgency (work is happening)
    if active_tasks > 0:
        urgency *= 0.5

    goal_summaries = [
        {"id": str(g["id"]), "title": g["title"], "priority": g["priority"],
         "progress": g["progress"]}
        for g in stale_goals
    ]

    return DriveResult(
        name="serve",
        priority=1,
        urgency=round(urgency, 2),
        description=f"{active_count} active goals, {len(stale_goals)} need attention",
        proposed_action=f"Work on goal: {stale_goals[0]['title']}" if stale_goals else None,
        context={"stale_goals": goal_summaries, "active_tasks": active_tasks},
    )
```

- [ ] **Step 2: Create `cortex/app/drives/maintain.py`**

```python
"""Maintain drive — keep Nova healthy.

Urgency is based on:
- Service health check results
- Error rates (future)
- Backup freshness (future)
"""
from __future__ import annotations

import logging

from ..clients import get_orchestrator, get_llm, get_memory
from . import DriveResult

log = logging.getLogger(__name__)

SERVICES = [
    ("orchestrator", get_orchestrator),
    ("llm_gateway", get_llm),
    ("memory_service", get_memory),
]


async def assess() -> DriveResult:
    """Assess maintain drive urgency based on service health."""
    checks: dict[str, str] = {}

    for name, get_client in SERVICES:
        try:
            client = get_client()
            resp = await client.get("/health/live", timeout=5.0)
            checks[name] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            checks[name] = f"error: {type(e).__name__}"

    degraded = [name for name, status in checks.items() if status != "ok"]

    if not degraded:
        return DriveResult(
            name="maintain", priority=2, urgency=0.0,
            description="All services healthy",
            context={"checks": checks},
        )

    urgency = min(1.0, len(degraded) / len(SERVICES) + 0.3)

    return DriveResult(
        name="maintain",
        priority=2,
        urgency=round(urgency, 2),
        description=f"Degraded: {', '.join(degraded)}",
        proposed_action=f"Investigate {degraded[0]} health issue",
        context={"checks": checks, "degraded": degraded},
    )
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile cortex/app/drives/serve.py && python3 -m py_compile cortex/app/drives/maintain.py && echo "OK"`

- [ ] **Step 4: Commit**

```bash
git add cortex/app/drives/serve.py cortex/app/drives/maintain.py
git commit -m "feat: add serve and maintain drives with real urgency scoring"
```

---

### Task 5: Create stub drives (improve, learn, reflect)

**Files:**
- Create: `cortex/app/drives/improve.py`
- Create: `cortex/app/drives/learn.py`
- Create: `cortex/app/drives/reflect.py`

- [ ] **Step 1: Create `cortex/app/drives/improve.py`**

```python
"""Improve drive — make Nova's code better. Stub for now."""
from __future__ import annotations

from . import DriveResult


async def assess() -> DriveResult:
    return DriveResult(
        name="improve", priority=3, urgency=0.0,
        description="No improvement signals (stub)",
    )
```

- [ ] **Step 2: Create `cortex/app/drives/learn.py`**

```python
"""Learn drive — build knowledge. Stub for now."""
from __future__ import annotations

from . import DriveResult


async def assess() -> DriveResult:
    return DriveResult(
        name="learn", priority=4, urgency=0.0,
        description="No learning signals (stub)",
    )
```

- [ ] **Step 3: Create `cortex/app/drives/reflect.py`**

```python
"""Reflect drive — learn from experience. Stub for now."""
from __future__ import annotations

from . import DriveResult


async def assess() -> DriveResult:
    return DriveResult(
        name="reflect", priority=5, urgency=0.0,
        description="No reflection signals (stub)",
    )
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -m py_compile cortex/app/drives/improve.py && python3 -m py_compile cortex/app/drives/learn.py && python3 -m py_compile cortex/app/drives/reflect.py && echo "OK"`

- [ ] **Step 5: Commit**

```bash
git add cortex/app/drives/improve.py cortex/app/drives/learn.py cortex/app/drives/reflect.py
git commit -m "feat: add stub drives (improve, learn, reflect)"
```

---

## Chunk 3: The Thinking Cycle

### Task 6: Create the thinking cycle (5-phase core)

**Files:**
- Create: `cortex/app/cycle.py`

This is the heart of Cortex. One call to `run_cycle()` executes all 5 phases.

- [ ] **Step 1: Create `cortex/app/cycle.py`**

```python
"""One thinking cycle — PERCEIVE → EVALUATE → PLAN → ACT → REFLECT.

Each cycle:
1. Gathers state (health, goals, budget, user messages)
2. Scores drives and picks the highest-urgency action
3. Uses LLM to plan how to execute the action
4. Dispatches work (pipeline tasks, health checks, etc.)
5. Journals the outcome
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .budget import get_budget_status
from .clients import get_llm, get_orchestrator
from .config import settings
from .db import get_pool
from .drives import DriveResult, DriveWinner, evaluate
from .drives import serve, maintain, improve, learn, reflect
from .journal import read_user_replies_since, write_entry

log = logging.getLogger(__name__)

ALL_DRIVES = [serve, maintain, improve, learn, reflect]


@dataclass
class CycleState:
    """Accumulated state for one cycle."""
    cycle_number: int = 0
    budget_tier: str = "best"
    budget_pct: float = 0.0
    drive_results: list[DriveResult] = field(default_factory=list)
    winner: DriveWinner | None = None
    user_messages: list[dict] = field(default_factory=list)
    action_taken: str = "none"
    outcome: str = ""
    error: str | None = None


async def run_cycle() -> CycleState:
    """Execute one complete thinking cycle. Returns the cycle state for logging."""
    state = CycleState()

    try:
        # ── PERCEIVE ──────────────────────────────────────────────────────
        budget = await get_budget_status()
        state.budget_tier = budget["tier"]
        state.budget_pct = budget["percent_used"]

        # Read cycle count
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT cycle_count, last_cycle_at FROM cortex_state WHERE id = true")
        state.cycle_number = (row["cycle_count"] + 1) if row else 1

        # Check for user replies since last cycle
        last_cycle_at = row["last_cycle_at"] if row and row["last_cycle_at"] else datetime(2020, 1, 1, tzinfo=timezone.utc)
        state.user_messages = await read_user_replies_since(last_cycle_at)

        # ── EVALUATE ──────────────────────────────────────────────────────
        for drive_module in ALL_DRIVES:
            try:
                result = await drive_module.assess()
                state.drive_results.append(result)
            except Exception as e:
                log.warning("Drive %s.assess() failed: %s", drive_module.__name__, e)

        state.winner = evaluate(state.drive_results, state.budget_tier)

        if state.winner is None:
            state.action_taken = "idle"
            state.outcome = "No drives have urgency — nothing to do"
            await _update_state(state)
            await write_entry(
                f"Cycle {state.cycle_number}: idle. Budget {state.budget_pct:.0f}% used ({state.budget_tier}). "
                f"All drives quiet.",
                entry_type="narration",
                metadata={"cycle": state.cycle_number, "action": "idle"},
            )
            return state

        drive = state.winner.result

        # ── PLAN ──────────────────────────────────────────────────────────
        plan = await _plan_action(drive, state)

        # ── ACT ───────────────────────────────────────────────────────────
        state.action_taken = drive.name
        state.outcome = await _execute_action(drive, plan, state)

        # ── REFLECT ──────────────────────────────────────────────────────
        await _reflect(state)
        await _update_state(state)

    except Exception as e:
        state.error = str(e)
        log.error("Cycle %d failed: %s", state.cycle_number, e, exc_info=True)
        try:
            await write_entry(
                f"Cycle {state.cycle_number} FAILED: {e}",
                entry_type="escalation",
                metadata={"cycle": state.cycle_number, "error": str(e)},
            )
        except Exception:
            pass  # Don't let journal failure mask the original error

    return state


async def _plan_action(drive: DriveResult, state: CycleState) -> str:
    """Use LLM to decide what specific action to take for the winning drive."""
    if state.budget_tier == "none":
        return f"Budget exhausted — skip LLM planning. Drive: {drive.name}"

    # Build a compact prompt
    user_msg_summary = ""
    if state.user_messages:
        msgs = "; ".join(m["content"][:100] for m in state.user_messages[:3])
        user_msg_summary = f"\nUser messages since last cycle: {msgs}"

    prompt = f"""You are Nova's autonomous brain (Cortex). You are deciding what to do this cycle.

Winning drive: {drive.name} (urgency {drive.urgency}, score {state.winner.score:.2f})
Drive says: {drive.description}
Proposed action: {drive.proposed_action or 'none specified'}
Context: {json.dumps(drive.context, default=str)}

Budget: {state.budget_pct:.0f}% used today (tier: {state.budget_tier})
Cycle: #{state.cycle_number}{user_msg_summary}

Based on this, decide what SPECIFIC action to take. Be concise (1-3 sentences).
If the drive is "serve" and there are stale goals, pick the highest-priority one and describe what to do next.
If the drive is "maintain" and services are degraded, describe the health issue.
If nothing meaningful can be done, say "skip".

Your response is the action plan (not code, just a description)."""

    try:
        llm = get_llm()
        model = settings.planning_model or ""  # empty string = gateway uses default
        resp = await llm.post("/complete", json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 300,
            "metadata": {"agent_id": "cortex", "task_id": f"cycle-{state.cycle_number}"},
        })
        if resp.status_code == 200:
            data = resp.json()
            return data.get("content", "No plan generated")
        else:
            log.warning("LLM planning call failed: %d %s", resp.status_code, resp.text[:200])
            return f"LLM unavailable ({resp.status_code}) — using drive's proposed action: {drive.proposed_action}"
    except Exception as e:
        log.warning("LLM planning call error: %s", e)
        return f"LLM error — using drive's proposed action: {drive.proposed_action}"


async def _execute_action(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute the planned action. Returns outcome description."""
    if "skip" in plan.lower()[:20]:
        return "Skipped — no meaningful action to take"

    if drive.name == "serve":
        return await _execute_serve(drive, plan, state)
    elif drive.name == "maintain":
        return await _execute_maintain(drive, plan)
    else:
        return f"Drive '{drive.name}' has no executor yet (stub)"


async def _execute_serve(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute a serve action — work on the highest-priority stale goal."""
    stale_goals = drive.context.get("stale_goals", [])
    if not stale_goals:
        return "No stale goals to work on"

    goal = stale_goals[0]
    goal_id = goal["id"]

    # Mark goal as checked
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE goals SET last_checked_at = NOW(), iteration = iteration + 1, updated_at = NOW() WHERE id = $1::uuid",
            goal_id,
        )

    # Dispatch a pipeline task for this goal
    try:
        orch = get_orchestrator()
        resp = await orch.post(
            "/api/v1/pipeline/tasks",
            json={
                "user_input": f"[Cortex goal work] Goal: {goal['title']}. Plan: {plan}",
                "goal_id": goal_id,
                "metadata": {"source": "cortex", "cycle": state.cycle_number, "drive": "serve"},
            },
            headers={"Authorization": f"Bearer {settings.cortex_api_key}"},
        )
        if resp.status_code in (200, 201, 202):
            data = resp.json()
            task_id = data.get("task_id", "unknown")
            return f"Dispatched task {task_id} for goal '{goal['title']}'"
        else:
            return f"Failed to dispatch task: HTTP {resp.status_code} — {resp.text[:200]}"
    except Exception as e:
        return f"Failed to dispatch task: {e}"


async def _execute_maintain(drive: DriveResult, plan: str) -> str:
    """Execute a maintain action — log health issues for now."""
    degraded = drive.context.get("degraded", [])
    if not degraded:
        return "All services healthy — nothing to do"

    # For now, just report. Future: trigger recovery actions.
    return f"Health issues detected: {', '.join(degraded)}. Logged for attention. Plan: {plan}"


async def _reflect(state: CycleState) -> None:
    """Write a journal entry summarizing this cycle."""
    drive_summary = ", ".join(
        f"{r.name}={r.urgency:.2f}" for r in state.drive_results
    )

    if state.winner:
        content = (
            f"**Cycle {state.cycle_number}** — drive: **{state.winner.result.name}** "
            f"(score {state.winner.score:.2f})\n\n"
            f"Drives: {drive_summary}\n"
            f"Budget: {state.budget_pct:.0f}% ({state.budget_tier})\n"
            f"Action: {state.action_taken}\n"
            f"Outcome: {state.outcome}"
        )
    else:
        content = (
            f"**Cycle {state.cycle_number}** — idle\n\n"
            f"Drives: {drive_summary}\n"
            f"Budget: {state.budget_pct:.0f}% ({state.budget_tier})"
        )

    if state.user_messages:
        content += f"\n\nUser messages: {len(state.user_messages)}"

    entry_type = "narration"
    if state.error:
        content += f"\n\nERROR: {state.error}"
        entry_type = "escalation"

    await write_entry(content, entry_type=entry_type, metadata={
        "cycle": state.cycle_number,
        "drive": state.action_taken,
        "budget_tier": state.budget_tier,
    })


async def _update_state(state: CycleState) -> None:
    """Update cortex_state singleton after a cycle."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE cortex_state
            SET cycle_count = $1,
                last_cycle_at = NOW(),
                current_drive = $2,
                last_checkpoint = $3::jsonb,
                updated_at = NOW()
            WHERE id = true
            """,
            state.cycle_number,
            state.action_taken if state.action_taken != "none" else None,
            json.dumps({
                "budget_tier": state.budget_tier,
                "budget_pct": state.budget_pct,
                "outcome": state.outcome[:500] if state.outcome else None,
            }),
        )
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile cortex/app/cycle.py && echo "OK"`

- [ ] **Step 3: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat: add cortex thinking cycle (perceive, evaluate, plan, act, reflect)"
```

---

### Task 7: Create the background loop runner

**Files:**
- Create: `cortex/app/loop.py`

- [ ] **Step 1: Create `cortex/app/loop.py`**

```python
"""Background thinking loop — runs cycles on a timer, respects pause and budget."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .config import settings
from .cycle import run_cycle
from .db import get_pool

log = logging.getLogger(__name__)

_task: asyncio.Task | None = None


async def start() -> None:
    """Start the thinking loop as a background task."""
    global _task
    if _task is not None:
        log.warning("Thinking loop already running")
        return
    _task = asyncio.create_task(_loop(), name="cortex-thinking-loop")
    log.info("Thinking loop started (interval=%ds, enabled=%s)",
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
    log.info("Thinking loop stopped")


async def _loop() -> None:
    """Main loop — check state, run cycle, sleep, repeat."""
    # Initial delay: let other services finish starting
    await asyncio.sleep(15)

    while True:
        try:
            interval = settings.cycle_interval_seconds

            # Check if enabled
            if not settings.enabled:
                log.debug("Cortex disabled — sleeping %ds", interval)
                await asyncio.sleep(interval)
                continue

            # Check if paused
            pool = get_pool()
            async with pool.acquire() as conn:
                status = await conn.fetchval(
                    "SELECT status FROM cortex_state WHERE id = true"
                )

            if status == "paused":
                log.debug("Cortex paused — sleeping %ds", interval)
                await asyncio.sleep(interval)
                continue

            # Run one cycle
            log.info("Starting thinking cycle")
            state = await run_cycle()
            log.info(
                "Cycle %d complete: drive=%s, outcome=%s",
                state.cycle_number,
                state.action_taken,
                (state.outcome[:80] if state.outcome else "none"),
            )

            # Adaptive interval: shorter when busy, longer when idle
            if state.action_taken == "idle":
                interval = min(interval * 2, 1800)  # Max 30 min when idle
            elif state.error:
                interval = min(interval * 3, 3600)  # Back off on errors

            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Thinking loop error: %s", e, exc_info=True)
            await asyncio.sleep(60)  # Brief pause on unexpected errors
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile cortex/app/loop.py && echo "OK"`

- [ ] **Step 3: Commit**

```bash
git add cortex/app/loop.py
git commit -m "feat: add cortex background thinking loop with adaptive intervals"
```

---

## Chunk 4: Wiring + API Updates

### Task 8: Wire loop into main.py lifespan

**Files:**
- Modify: `cortex/app/main.py`

- [ ] **Step 1: Update `cortex/app/main.py`**

Replace the entire file with:

```python
"""Nova Cortex — autonomous brain service."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .clients import init_clients, close_clients
from .config import settings
from .db import init_pool, close_pool
from .health import health_router
from .router import cortex_router
from . import loop

logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
log = logging.getLogger("nova.cortex")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await init_clients()
    await loop.start()
    log.info("Cortex service ready — port %s, cycle interval %ds",
             settings.port, settings.cycle_interval_seconds)

    yield

    log.info("Cortex shutting down")
    await loop.stop()
    await close_clients()
    await close_pool()


app = FastAPI(
    title="Nova Cortex",
    version="0.1.0",
    description="Autonomous brain service — thinking loop, goals, drives",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(cortex_router)
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile cortex/app/main.py && echo "OK"`

- [ ] **Step 3: Commit**

```bash
git add cortex/app/main.py
git commit -m "feat: wire thinking loop into cortex lifespan (start on boot, stop on shutdown)"
```

---

### Task 9: Update router with real drives and journal endpoint

**Files:**
- Modify: `cortex/app/router.py`

- [ ] **Step 1: Replace `cortex/app/router.py`**

Replace the entire file with:

```python
"""Cortex control endpoints — status, pause, resume, drives, journal."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from .budget import get_budget_status
from .db import get_pool
from .drives import serve, maintain, improve, learn, reflect
from .journal import read_recent

log = logging.getLogger(__name__)

cortex_router = APIRouter(prefix="/api/v1/cortex", tags=["cortex"])

ALL_DRIVES = [serve, maintain, improve, learn, reflect]


@cortex_router.get("/status")
async def get_status():
    """Current Cortex state — running/paused, cycle count, active drive."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM cortex_state WHERE id = true")
    if not row:
        return {"status": "uninitialized"}
    return {
        "status": row["status"],
        "current_drive": row["current_drive"],
        "cycle_count": row["cycle_count"],
        "last_cycle_at": row["last_cycle_at"].isoformat() if row["last_cycle_at"] else None,
        "last_checkpoint": row["last_checkpoint"],
    }


@cortex_router.post("/pause")
async def pause():
    """Pause autonomous operation."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cortex_state SET status = 'paused', updated_at = NOW() WHERE id = true"
        )
    log.info("Cortex paused")
    return {"status": "paused"}


@cortex_router.post("/resume")
async def resume():
    """Resume autonomous operation."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cortex_state SET status = 'running', updated_at = NOW() WHERE id = true"
        )
    log.info("Cortex resumed")
    return {"status": "running"}


@cortex_router.get("/drives")
async def get_drives():
    """Live drive urgency scores — calls each drive's assess() method."""
    results = []
    for drive_module in ALL_DRIVES:
        try:
            r = await drive_module.assess()
            results.append({
                "name": r.name,
                "priority": r.priority,
                "urgency": r.urgency,
                "description": r.description,
                "proposed_action": r.proposed_action,
            })
        except Exception as e:
            log.warning("Drive %s.assess() failed: %s", drive_module.__name__, e)
            results.append({
                "name": drive_module.__name__.split(".")[-1],
                "priority": 0,
                "urgency": 0.0,
                "description": f"Error: {e}",
                "proposed_action": None,
            })
    return {"drives": results}


@cortex_router.get("/budget")
async def budget():
    """Current budget state — daily spend, remaining, tier."""
    return await get_budget_status()


@cortex_router.get("/journal")
async def journal(limit: int = Query(default=20, le=100)):
    """Recent journal entries from the Cortex conversation."""
    entries = await read_recent(limit)
    return {"entries": entries}
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -m py_compile cortex/app/router.py && echo "OK"`

- [ ] **Step 3: Commit**

```bash
git add cortex/app/router.py
git commit -m "feat: replace static drives with live urgency scoring, add journal endpoint"
```

---

### Task 10: Add journal API to dashboard

**Files:**
- Modify: `dashboard/src/api.ts`

- [ ] **Step 1: Add journal types and fetch function**

In `dashboard/src/api.ts`, add after the `getCortexBudget` function:

```typescript
export interface JournalEntry {
  id: string
  role: string
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

export const getCortexJournal = (limit = 20) =>
  apiFetch<{ entries: JournalEntry[] }>(`/cortex-api/api/v1/cortex/journal?limit=${limit}`)
```

- [ ] **Step 2: Verify dashboard builds**

Run: `cd /home/jeremy/workspace/nova/dashboard && npx tsc --noEmit && echo "OK"`

- [ ] **Step 3: Commit**

```bash
cd /home/jeremy/workspace/nova && git add dashboard/src/api.ts
git commit -m "feat: add cortex journal API function to dashboard"
```

---

### Task 11: Final verification

- [ ] **Step 1: Verify all Python syntax**

Run: `cd /home/jeremy/workspace/nova && python3 -m py_compile cortex/app/config.py && python3 -m py_compile cortex/app/clients.py && python3 -m py_compile cortex/app/journal.py && python3 -m py_compile cortex/app/drives/__init__.py && python3 -m py_compile cortex/app/drives/serve.py && python3 -m py_compile cortex/app/drives/maintain.py && python3 -m py_compile cortex/app/drives/improve.py && python3 -m py_compile cortex/app/drives/learn.py && python3 -m py_compile cortex/app/drives/reflect.py && python3 -m py_compile cortex/app/cycle.py && python3 -m py_compile cortex/app/loop.py && python3 -m py_compile cortex/app/main.py && python3 -m py_compile cortex/app/router.py && python3 -m py_compile cortex/app/budget.py && echo "All Python OK"`

Expected: `All Python OK`

- [ ] **Step 2: Verify dashboard TypeScript**

Run: `cd /home/jeremy/workspace/nova/dashboard && npx tsc --noEmit && echo "Dashboard OK"`

Expected: `Dashboard OK`

- [ ] **Step 3: Verify Docker builds**

Run: `cd /home/jeremy/workspace/nova && docker compose build cortex 2>&1 | tail -5`

Expected: Successfully built image
