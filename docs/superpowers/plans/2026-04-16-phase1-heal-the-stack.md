# Phase 1.0 Heal the Stack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate five actively-broken P0 items on the running Nova stack — reaper transition loop, health cascade amplification, Redis connection leaks, cloud-only embedding fallback, and default-secret leakage — in one coordinated sprint. Five independent commits, each revertable alone.

**Architecture:** Each of the five fixes lands as its own commit. Mostly mechanical changes in Python service code + one shell-script edit + one Redis config flip. Two fixes get new integration tests (REL-001 reaper recovery; OPS-001 health probe independence) because they're load-bearing regressions. The other three are verified manually — config flips and lifespan plumbing where the observable effect is the test.

**Tech Stack:** Python 3.12 (FastAPI + asyncpg + async Redis), pytest integration suite against a live Docker Compose stack, bash (setup.sh), `redis-cli` for runtime config.

**Spec reference:** `docs/superpowers/specs/2026-04-16-phase1-heal-the-stack-design.md`

---

## Deviation from strict TDD

Per the spec's "Testing Discipline" section: formal tests are written for REL-001 and OPS-001 only. OPS-002, PERF-002, and SEC-005 are verified manually because they are plumbing/config changes where test infrastructure would exceed the change size. This is a deliberate, spec-approved deviation — don't backfill tests.

---

## File structure

| Fix | Files created | Files modified |
|---|---|---|
| OPS-001 | `tests/test_health_cascade.py` | `chat-api/app/main.py`, `orchestrator/app/health.py` |
| OPS-002 | — | `memory-service/app/embedding.py` + `main.py`; `llm-gateway/app/discovery.py` + `registry.py` + `main.py`; `cortex/app/budget.py` + `main.py`; `orchestrator/app/stimulus.py` + `main.py` |
| REL-001 | `tests/test_reaper_stale_fail.py` | `orchestrator/app/pipeline/state_machine.py`, `orchestrator/app/reaper.py`, `orchestrator/app/main.py` |
| PERF-002 | — | None (Redis CLI flips only) |
| SEC-005 | — | `scripts/setup.sh` |

Memory-service calls the LLM gateway's `/embed` endpoint, not Ollama directly (verified via grep in `memory-service/app/embedding.py:173,192,197`). So **no `extra_hosts` compose change is needed** — the gateway is the only container that needs to reach host Ollama, and it already has `extra_hosts: host.docker.internal:host-gateway` per `docker-compose.yml`.

---

## Task 0: Prerequisite sanity check

- [ ] **Step 0.1: Verify the spec commit landed**

Run: `git log --oneline -6`
Expected: Recent commits include `docs: Phase 1.0 heal-the-stack design spec` and `docs: relax Phase 1.0 latency target to <2s with <1s stretch`.

- [ ] **Step 0.2: Verify the stack is running**

Run: `docker compose ps --format "table {{.Name}}\t{{.Status}}" | grep -v editor`
Expected: orchestrator, chat-api, memory-service, llm-gateway, cortex, redis, postgres all "healthy" (or "health: starting" if just booted). If stack is down, bring it up with `make up` before proceeding.

- [ ] **Step 0.3: Capture the "before" signal**

Run: `docker compose logs orchestrator --since 2m 2>&1 | grep -cE "Invalid task status|Reaper: task .* stale"`
Expected: Non-zero (confirms REL-001 is still active).

Run: `docker compose exec -T redis redis-cli -n 1 MGET nova:config:inference.backend nova:config:inference.state nova:config:llm.routing_strategy nova:config:llm.ollama_url`
Expected: `none`, `stopped`, `cloud-only`, `http://172.24.32.1:11434` (or similar unreachable-from-container URL). Confirms PERF-002 state.

---

## Task 1: OPS-001 — Health cascade fix

**Goal:** `chat-api` and `orchestrator` report `ready` even when Ollama (an informational sub-check) is unreachable.

**Files:**
- Create: `tests/test_health_cascade.py`
- Modify: `chat-api/app/main.py:62-78` (the `/health/ready` handler — switch the orchestrator probe URL from `/health/ready` to `/health/live`)
- Modify: `orchestrator/app/health.py:24-34` (switch the memory-service and llm-gateway probe URLs from `/health/ready` to `/health/live`)

### Steps

- [ ] **Step 1.1: Read the two files to confirm line numbers before editing**

Use the `Read` tool on `chat-api/app/main.py` lines 50-90 and `orchestrator/app/health.py` lines 1-60. Confirm the probe URLs currently read `/health/ready`. (Line numbers in this plan were snapshot at spec-write time; they may have drifted.)

- [ ] **Step 1.2: Write the failing integration test**

Create `tests/test_health_cascade.py` with this content:

```python
"""
OPS-001: health-rollup cascade regression test.

If an informational sub-check on llm-gateway (e.g. Ollama probe) is slow,
chat-api's /health/ready should still return "ready". Downstream probes
in rollups must call /health/live (self-only), not /health/ready (cascading).
"""

from __future__ import annotations

import httpx
import pytest


CHAT_API = "http://localhost:8080"
ORCHESTRATOR = "http://localhost:8000"
GATEWAY = "http://localhost:8001"
REDIS_HOST = "localhost"
REDIS_PORT = 6379


@pytest.fixture
def save_restore_ollama_url(redis_db1):
    """Save current Ollama URL, set unreachable URL for test, restore after."""
    original = redis_db1.get("nova:config:llm.ollama_url")
    # Port 1 is conventionally unassigned and refuses connections fast — but
    # we want a slow timeout to prove the cascade doesn't amplify.
    redis_db1.set("nova:config:llm.ollama_url", "http://192.0.2.1:11434")  # TEST-NET-1, blackholes
    yield
    if original is not None:
        redis_db1.set("nova:config:llm.ollama_url", original)
    else:
        redis_db1.delete("nova:config:llm.ollama_url")


def test_chat_api_ready_when_ollama_unreachable(save_restore_ollama_url):
    """chat-api /health/ready must stay 'ready' when Ollama is unreachable."""
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{CHAT_API}/health/ready")
    assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
    body = resp.json()
    assert body.get("status") == "ready", (
        f"Expected status=ready, got {body.get('status')}. "
        f"Full body: {body}"
    )


def test_orchestrator_ready_when_ollama_unreachable(save_restore_ollama_url):
    """orchestrator /health/ready must stay 'ready' when Ollama is unreachable."""
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{ORCHESTRATOR}/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ready", (
        f"Expected status=ready, got {body.get('status')}. "
        f"Full body: {body}"
    )
```

**Note on `redis_db1` fixture:** if `tests/conftest.py` does not already expose a Redis db1 client, add one. Check by grep first: `rg "redis_db1|redis-cli -n 1" tests/conftest.py`. If absent, follow the existing pattern (use `redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)` — the `redis` package is already in `tests/requirements.txt`).

- [ ] **Step 1.3: Run the new test against the current (broken) code — expect FAIL**

Run: `cd tests && pytest test_health_cascade.py -v`
Expected: Both tests FAIL with `status=degraded` (cascade amplifies).

- [ ] **Step 1.4: Edit `chat-api/app/main.py`**

Use the `Edit` tool to change the orchestrator probe URL inside the chat-api `/health/ready` handler. The only substantive change is the path: `/health/ready` → `/health/live`. Leave the timeout, error handling, and queue-depth logic alone.

Example shape (actual surrounding code will differ; match what's there):

```python
# Before:
resp = await client.get(f"{settings.orchestrator_url}/health/ready", timeout=3.0)
# After:
resp = await client.get(f"{settings.orchestrator_url}/health/live", timeout=3.0)
```

- [ ] **Step 1.5: Edit `orchestrator/app/health.py`**

Same pattern. Two probe URLs to update — memory-service and llm-gateway. `/health/ready` → `/health/live` on both.

- [ ] **Step 1.6: Run the test — expect PASS**

Run: `cd tests && pytest test_health_cascade.py -v`
Expected: Both tests PASS.

- [ ] **Step 1.7: Restart the two edited services**

Run: `docker compose restart chat-api orchestrator`
Wait ~10s for health to re-establish (`docker compose ps | grep -E "chat-api|orchestrator"` should show healthy).

- [ ] **Step 1.8: Manual sanity check**

Run: `curl -s http://localhost:8080/health/ready | python3 -m json.tool`
Expected: `status: "ready"` even though Ollama isn't flipped on yet (that's Task 4).

- [ ] **Step 1.9: Commit**

```bash
git add chat-api/app/main.py orchestrator/app/health.py tests/test_health_cascade.py tests/conftest.py
git commit -m "$(cat <<'EOF'
fix(health): stop rollup cascade by probing /health/live downstream

OPS-001 from the Phase 1.0 heal-the-stack spec. chat-api and orchestrator
were calling downstream /health/ready endpoints, which themselves probe
further dependencies with a 3s timeout equal to the outer timeout. Any
slow inner probe (e.g. Ollama unreachable) cascaded to three services
flipping to "degraded". Switch downstream probes to /health/live
(self-only). Cortex already does this correctly — this change aligns
chat-api and orchestrator with that pattern.

Regression test at tests/test_health_cascade.py sets an unreachable
Ollama URL in Redis and asserts chat-api and orchestrator both stay
status=ready.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Only stage `tests/conftest.py` if you actually modified it to add the `redis_db1` fixture.

---

## Task 2: OPS-002 — Redis connection leaks

**Goal:** Every module with a `get_redis()` singleton has a matching `close_redis()` that runs in the service's FastAPI lifespan shutdown. No formal tests — verified by `redis-cli client list` staying stable across a restart cycle.

**Files modified:**
- `memory-service/app/embedding.py` (add `close_redis`)
- `memory-service/app/main.py` (call `close_redis` in lifespan)
- `llm-gateway/app/discovery.py` (add `close_redis`)
- `llm-gateway/app/registry.py` (add `close_strategy_redis`)
- `llm-gateway/app/main.py` (call both in lifespan)
- `cortex/app/budget.py` (add `close_redis`)
- `cortex/app/main.py` (call in lifespan)
- `orchestrator/app/stimulus.py` (add `close_redis`)
- `orchestrator/app/main.py` (call in lifespan)

### Canonical pattern (reference only — match the file you're in)

```python
# In the module with the singleton:
_redis: aioredis.Redis | None = None

async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis

async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
```

```python
# In main.py lifespan:
from app.embedding import close_redis as close_embedding_redis

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... startup ...
    yield
    # shutdown
    await close_embedding_redis()
    # ... other shutdowns ...
```

Canonical example already in repo: `chat-api/app/session.py:30-35`. Use that as the template.

### Steps

- [ ] **Step 2.1: Read each offender and identify the singleton name**

Use `Read` to look at each of the 5 offender files. Note the variable name for the singleton (some use `_redis`, some `_strategy_redis`, some `_get_redis` vs `get_redis`). You'll add a `close_*` function that mirrors the getter name.

- [ ] **Step 2.2: Add `close_redis` to `memory-service/app/embedding.py`**

Use `Edit` to append the close function immediately after the existing getter.

- [ ] **Step 2.3: Wire it into `memory-service/app/main.py` lifespan shutdown**

Import and call `close_redis()` after `yield` in the lifespan context manager. Place it with any other Redis/resource cleanup.

- [ ] **Step 2.4: Repeat for `llm-gateway/app/discovery.py`**

Add close function, import into `llm-gateway/app/main.py`, call in lifespan. The llm-gateway lifespan already has `rate_limiter.aclose()`, `response_cache.aclose()`, `editor_tracker.aclose()` — add yours alongside.

- [ ] **Step 2.5: Repeat for `llm-gateway/app/registry.py`**

Same pattern. The singleton is `_strategy_redis`; name the function `close_strategy_redis`.

- [ ] **Step 2.6: Repeat for `cortex/app/budget.py`**

Add close function, wire into `cortex/app/main.py` lifespan. The cortex lifespan already calls `.stimulus.close_redis()` per the audit — add budget alongside.

- [ ] **Step 2.7: Repeat for `orchestrator/app/stimulus.py`**

Same pattern. Wire into `orchestrator/app/main.py` lifespan.

- [ ] **Step 2.8: Verify imports/syntax by restarting the four services**

Run: `docker compose restart memory-service llm-gateway cortex orchestrator`
Wait: `docker compose ps` shows all four healthy (≤30s typically).

Any startup failure in the logs (`docker compose logs <service> --since 1m`) likely indicates an import typo or a lifespan ordering issue — fix before continuing.

- [ ] **Step 2.9: Verify no connection growth across restart**

Run:
```bash
docker compose exec -T redis redis-cli CLIENT LIST | wc -l
```
Capture the number. Then:
```bash
docker compose restart memory-service llm-gateway cortex orchestrator
```
Wait 30 seconds. Then re-run the `CLIENT LIST | wc -l`. The count should return to roughly the same baseline (± normal churn from the services re-opening their usual pools). Before the fix, it would climb.

- [ ] **Step 2.10: Run the integration suite to confirm nothing regressed**

Run: `make test-quick`
Expected: PASS (fast health-endpoint smoke).

- [ ] **Step 2.11: Commit**

```bash
git add memory-service/app/embedding.py memory-service/app/main.py \
        llm-gateway/app/discovery.py llm-gateway/app/registry.py llm-gateway/app/main.py \
        cortex/app/budget.py cortex/app/main.py \
        orchestrator/app/stimulus.py orchestrator/app/main.py
git commit -m "$(cat <<'EOF'
fix(redis): close pooled clients in 5 services during lifespan shutdown

OPS-002 from the Phase 1.0 heal-the-stack spec. CLAUDE.md codifies the
rule that every module with get_redis() must have a matching close_redis()
called from the FastAPI lifespan shutdown path. Five modules violated it:
memory-service/embedding, llm-gateway/discovery + registry, cortex/budget,
orchestrator/stimulus. Add close functions and wire into each service's
lifespan. Canonical example: chat-api/app/session.py.

Verified: redis-cli CLIENT LIST stable across a full stack restart cycle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: REL-001 — Reaper state transition fix

**Goal:** Stop the 60-second reaper error-spam loop. Transition stuck `*_running` tasks directly to `failed` via a recovery helper that bypasses the regular state machine. Clean up the 9 currently-stuck tasks at startup.

**Files:**
- Create: `tests/test_reaper_stale_fail.py`
- Modify: `orchestrator/app/pipeline/state_machine.py` (add `force_fail_task` helper)
- Modify: `orchestrator/app/reaper.py` (use the helper in `_reap_stale_running_tasks` instead of the `queued` transition)
- Modify: `orchestrator/app/main.py` (add startup cleanup call)

### Key insight for the implementer

Looking at the current `orchestrator/app/reaper.py:107-110`, the bug is in the `retry_count < max_retries` branch that tries to transition `task_running → queued`. The `else` branch already transitions to `failed` correctly (line 122-126). So the simplest fix is to **always transition to `failed`** on heartbeat expiry — drop the retry-requeue logic from the reaper. If the task matters, the user re-queues it through the normal submit path.

The spec asks for a dedicated helper that bypasses the state machine. Even though `failed` is a legal successor of `task_running`, the helper approach keeps the intent explicit: this is a recovery path, not a normal state transition.

### Steps

- [ ] **Step 3.1: Read the current reaper + state_machine code**

Use `Read` on `orchestrator/app/reaper.py:56-134` and `orchestrator/app/pipeline/state_machine.py` (especially the `transition_task_status` function). Confirm the current retry-requeue code path.

- [ ] **Step 3.2: Write the failing test**

Create `tests/test_reaper_stale_fail.py`:

```python
"""
REL-001: reaper must fail stuck *_running tasks instead of looping on
a rejected task_running -> queued transition.
"""

from __future__ import annotations

import asyncio
import httpx
import pytest
import pytest_asyncio
import uuid
from datetime import datetime, timedelta, timezone


ORCHESTRATOR = "http://localhost:8000"
PG_DSN = "postgresql://nova:nova_dev_password@localhost:5432/nova"  # adjust per conftest


@pytest_asyncio.fixture
async def stuck_task(pg_pool):
    """Insert a task directly in 'task_running' state with an expired heartbeat."""
    task_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tasks (id, prompt, status, last_heartbeat_at, retry_count, max_retries)
            VALUES ($1, 'nova-test-reaper-stale', 'task_running', $2, 0, 3)
            """,
            task_id,
            datetime.now(timezone.utc) - timedelta(seconds=3600),  # 1h stale
        )
    yield task_id
    # Teardown: delete the test task whatever state it ended up in
    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)


@pytest.mark.asyncio
async def test_reaper_fails_stale_running_task(pg_pool, stuck_task):
    """After one reaper cycle, the stale task should be in 'failed' state."""
    # Trigger a reaper cycle via admin endpoint (if the codebase exposes one),
    # OR wait for the next natural cycle (reaper_interval_seconds, default 60).
    # Prefer the admin endpoint for test speed.
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{ORCHESTRATOR}/api/v1/admin/reaper/tick",
            headers={"X-Admin-Secret": "nova-admin-secret-change-me"},
        )
    if resp.status_code == 404:
        # Admin tick endpoint doesn't exist — fall back to waiting
        await asyncio.sleep(65)

    # Check DB state
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, error FROM tasks WHERE id = $1", stuck_task,
        )
    assert row is not None, "Test task disappeared"
    assert row["status"] == "failed", (
        f"Expected status=failed after reaper, got {row['status']}. "
        f"Error column: {row['error']}"
    )
    assert row["error"] is not None and "reaped" in row["error"].lower(), (
        f"Expected 'reaped' in error column, got: {row['error']}"
    )
```

**If `POST /api/v1/admin/reaper/tick` doesn't exist:** add it in Step 3.3 as part of the implementation (it's useful for testing and for operators). Simple handler: import `_reap_stale_running_tasks` and await it.

**pg_pool fixture:** check `tests/conftest.py`; add one if absent following the existing pattern.

- [ ] **Step 3.3: Run the test — expect FAIL**

Run: `cd tests && pytest test_reaper_stale_fail.py -v -s`
Expected: Task stays in `task_running` (reaper-loop bug reproduces). Test asserts `status=failed` and fails.

- [ ] **Step 3.4: Add `force_fail_task` helper to state_machine.py**

Append to `orchestrator/app/pipeline/state_machine.py`:

```python
async def force_fail_task(task_id: str, reason: str) -> bool:
    """
    Recovery-path helper: transition a stuck task to 'failed' without going
    through the CAS state machine. Used by the reaper and startup cleanup
    when a task has gone silent for longer than task_stale_seconds.

    Writes a clear audit-trail string to tasks.error. Returns True if the
    row was updated, False if the task did not exist or was already in a
    terminal state (failed/complete/cancelled).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE tasks
               SET status = 'failed',
                   error = $2,
                   completed_at = now(),
                   last_heartbeat_at = now()
             WHERE id = $1::uuid
               AND status NOT IN ('failed', 'complete', 'cancelled')
            """,
            task_id, reason,
        )
    # asyncpg returns e.g. "UPDATE 1" on success, "UPDATE 0" if no row matched
    updated = result.endswith(" 1")
    if updated:
        logger.warning(
            "force_fail_task: %s → failed (reason: %s)", task_id, reason,
        )
    return updated
```

- [ ] **Step 3.5: Replace the reaper retry branch with `force_fail_task`**

Edit `orchestrator/app/reaper.py` inside `_reap_stale_running_tasks`. Replace the current `if retry_count < max_retries:` + `transition_task_status(..., "queued", ...)` branch with a single call to `force_fail_task`:

```python
# Before: full if/else with retry+queue and exhausted+fail branches
# After:
from .pipeline.state_machine import force_fail_task

for task in stale_tasks:
    task_id = str(task["id"])
    reason = (
        f"reaped: heartbeat expired in state '{task['status']}' "
        f"(retry_count={task['retry_count']}/{task['max_retries']})"
    )
    ok = await force_fail_task(task_id, reason)
    if not ok:
        # Already terminal (complete/failed/cancelled) — nothing to do
        continue
    await move_to_dead_letter(task_id, reason="heartbeat_timeout")
    async with pool.acquire() as conn:
        await _audit(conn, "task_failed", "error", task_id=task_id,
                     data={"reason": "heartbeat_timeout", "was_running_as": task["status"]})
```

Remove the now-unused `load_checkpoint` and `enqueue_task` imports at the top of the file.

- [ ] **Step 3.6: Add startup cleanup to orchestrator/app/main.py lifespan**

In the startup path of the lifespan (before `yield`), call a one-time cleanup. Add a small helper in `orchestrator/app/reaper.py`:

```python
async def cleanup_stale_running_on_startup() -> int:
    """
    One-time at startup: force-fail any task whose heartbeat has expired
    AND is still in a *_running state. Idempotent — subsequent calls find
    nothing to do because earlier runs already cleaned them up.

    Returns the count of tasks cleaned up (for logging).
    """
    from .pipeline.state_machine import force_fail_task

    ACTIVE_STATES = (
        "context_running", "task_running",
        "critique_direction_running", "guardrail_running",
        "code_review_running", "critique_acceptance_running",
        "decision_running", "completing",
    )

    pool = get_pool()
    async with pool.acquire() as conn:
        stale = await conn.fetch(
            """
            SELECT id, status, last_heartbeat_at
              FROM tasks
             WHERE status = ANY($1::text[])
               AND (
                 last_heartbeat_at IS NULL
                 OR last_heartbeat_at < now() - ($2 || ' seconds')::interval
               )
            """,
            list(ACTIVE_STATES),
            str(settings.task_stale_seconds),
        )

    count = 0
    for task in stale:
        reason = (
            f"reaped at startup: previously stuck in '{task['status']}' "
            f"since {task['last_heartbeat_at']}"
        )
        if await force_fail_task(str(task["id"]), reason):
            count += 1

    if count > 0:
        logger.warning("Startup cleanup: force-failed %d stale running tasks", count)
    return count
```

Then in `orchestrator/app/main.py` lifespan startup (before the `yield`), add:

```python
from .reaper import cleanup_stale_running_on_startup
await cleanup_stale_running_on_startup()
```

- [ ] **Step 3.7: Add the admin tick endpoint if needed**

If the test in Step 3.2 expected `POST /api/v1/admin/reaper/tick` and it didn't exist, add it to `orchestrator/app/router.py` or the most appropriate admin router:

```python
@router.post("/admin/reaper/tick", dependencies=[Depends(AdminDep)])
async def reaper_tick():
    """Run a single reaper cycle on demand (admin/test use)."""
    from .reaper import _reap_stale_running_tasks
    await _reap_stale_running_tasks()
    return {"status": "ok"}
```

This is an operator convenience anyway — worth keeping.

- [ ] **Step 3.8: Restart orchestrator and watch the startup logs**

Run:
```bash
docker compose restart orchestrator
docker compose logs orchestrator --since 1m 2>&1 | grep -E "Startup cleanup|force_fail_task|Reaper"
```

Expected: One `Startup cleanup: force-failed N stale running tasks` line with `N=9` (or whatever is currently stuck). Plus `Reaper started` from the normal lifespan. No more `Invalid task status transition` messages on subsequent cycles.

- [ ] **Step 3.9: Run the regression test — expect PASS**

Run: `cd tests && pytest test_reaper_stale_fail.py -v -s`
Expected: PASS.

- [ ] **Step 3.10: Verify log-spam gone**

Run:
```bash
sleep 120  # let 2 reaper cycles pass
docker compose logs orchestrator --since 2m 2>&1 | grep -cE "Invalid task status|Reaper: task .* stale"
```
Expected: 0. (If it's non-zero, something still triggers the old path — investigate before committing.)

- [ ] **Step 3.11: Commit**

```bash
git add orchestrator/app/pipeline/state_machine.py orchestrator/app/reaper.py orchestrator/app/main.py orchestrator/app/router.py tests/test_reaper_stale_fail.py
git commit -m "$(cat <<'EOF'
fix(reaper): force-fail stuck *_running tasks instead of retry-requeue loop

REL-001 from the Phase 1.0 heal-the-stack spec. The reaper attempted
to transition stale task_running rows to 'queued', which the state
machine rejects. Every 60-second reaper cycle re-spammed the rejection
forever; 9 live tasks (4 from 2026-04-04) were looping.

Replace the retry-requeue branch with force_fail_task, a recovery
helper that bypasses the CAS state machine and transitions the row
directly to 'failed' with a clear audit-trail reason in tasks.error.
Add startup cleanup that runs the same helper across any tasks
already stuck when orchestrator boots. If the user wants to retry,
they re-submit through the normal path — the reaper is a terminal
recovery mechanism, not a retry orchestrator.

Adds POST /api/v1/admin/reaper/tick for on-demand cycles (test + ops).

Regression test at tests/test_reaper_stale_fail.py inserts a synthetic
stuck task, triggers a reaper cycle via the admin endpoint, and asserts
the task transitions to 'failed' with a reaped-reason error string.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: PERF-002 — Flip Ollama back on

**Goal:** Chat turn latency drops from 6–14s to <2s (stretch: <1s). Embeddings stop falling back to cloud Gemini. Memory-service `fallback embedding model` log lines go to zero.

**Files:** None. All changes are to runtime Redis state, flipped via `redis-cli` or the dashboard Settings UI.

### Steps

- [ ] **Step 4.1: Set the correct Ollama URL**

Run:
```bash
docker compose exec -T redis redis-cli -n 1 SET nova:config:llm.ollama_url "http://host.docker.internal:11434"
```

Verified during spec-writing: this URL resolves to 14 models from inside the `llm-gateway` container. Host-Docker resolves via the existing `extra_hosts: host.docker.internal:host-gateway` already in compose.

- [ ] **Step 4.2: Flip inference backend state and routing strategy**

Run:
```bash
docker compose exec -T redis redis-cli -n 1 MSET \
  nova:config:inference.backend ollama \
  nova:config:inference.state ready \
  nova:config:llm.routing_strategy local-first
```

- [ ] **Step 4.3: Verify gateway can reach Ollama with the new URL**

Run:
```bash
docker exec nova-llm-gateway-1 python3 -c "
import httpx, os
url = 'http://host.docker.internal:11434/api/tags'
r = httpx.get(url, timeout=3)
print(f'{url}: {len(r.json().get(\"models\",[]))} models')
"
```
Expected: `14 models` (or however many host Ollama has pulled).

- [ ] **Step 4.4: Force gateway + memory-service to re-read config**

Run:
```bash
docker compose restart llm-gateway memory-service
sleep 15
```

(Both services cache the routing strategy for 5 seconds, but a restart is cleaner than waiting.)

- [ ] **Step 4.5: Verify memory-service stops logging cloud fallback**

Run:
```bash
sleep 30  # let a few calls flow through
docker compose logs memory-service --since 1m 2>&1 | grep -c "fallback embedding model"
```
Expected: 0.

- [ ] **Step 4.6: Measure end-to-end chat turn latency**

Use the dashboard at `http://localhost:5173` (dev) or `http://localhost:3000` (prod build), or the chat-api test UI at `http://localhost:8080/`. Send a short message ("hi, tell me about yourself in one sentence"). Use the browser dev tools Network tab to capture the SSE stream duration from first byte to completion.

Expected: <2s warm (commit threshold per spec). If it's between 2s and 6s, still an improvement but investigate: likely some other hot path still hits cloud. If <1s, celebrate.

- [ ] **Step 4.7: Commit the spec-reference record (no code changes)**

Since there are no code changes, create an empty commit to record the runtime-config change as a BACKLOG-traceable event:

```bash
git commit --allow-empty -m "$(cat <<'EOF'
ops(runtime): flip Ollama on, embeddings back to local-first

PERF-002 from the Phase 1.0 heal-the-stack spec. Runtime Redis config
change only (no code): nova:config:llm.ollama_url →
http://host.docker.internal:11434; inference.backend → ollama;
inference.state → ready; llm.routing_strategy → local-first.

Before: every embedding call fell back to cloud Gemini (194 fallback
log lines in a 300-line sample); /engrams/context took 6–14s per chat
turn. After: local Ollama-first routing; memory-service emits zero
fallback log lines; chat turn latency <2s warm.

Host Ollama binding to 0.0.0.0 is a pre-existing configuration on the
developer host (WSL2) and is not part of this repo. See
docs/superpowers/specs/2026-04-16-phase1-heal-the-stack-design.md
Fix 4 for the full reasoning.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Empty commits are unusual — if the team prefers to skip, omit this step and note PERF-002 complete only in the BACKLOG.md update at the very end. The empty commit exists so `git log` tells the whole story of Phase 1.0.

---

## Task 5: SEC-005 — Auto-rotate default secrets in setup.sh

**Goal:** Fresh `./scripts/setup.sh` on a blank `.env` produces randomly-generated `NOVA_ADMIN_SECRET` and `POSTGRES_PASSWORD` instead of leaving the hardcoded defaults.

**Files:**
- Modify: `scripts/setup.sh`

### Steps

- [ ] **Step 5.1: Read the existing rotation pattern**

Use `Read` on `scripts/setup.sh` around lines 33-45 (`CREDENTIAL_MASTER_KEY` and `BRIDGE_SERVICE_SECRET` rotation). Understand the exact bash idiom — `grep`-then-`sed`-in-place, value generated via `openssl rand`.

- [ ] **Step 5.2: Read the `.env.example` defaults you're replacing**

Use `Read` on `.env.example` to confirm the ship-state of each var:
- Line 5: `POSTGRES_PASSWORD=` (**empty** — same shape as existing `CREDENTIAL_MASTER_KEY` and `BRIDGE_SERVICE_SECRET` rotation targets)
- Line 6: `NOVA_ADMIN_SECRET=nova-admin-secret-change-me` (**literal default** — different shape)

The `nova_dev_password` value referenced in the Phase 0 audit is the `docker-compose.yml` fallback (used if the env var is unset at compose-time), not the `.env.example` ship state. Match against what `.env.example` actually has, which is the file `setup.sh` copies.

- [ ] **Step 5.3: Add two new rotation blocks**

After the existing `CREDENTIAL_MASTER_KEY` and `BRIDGE_SERVICE_SECRET` blocks (around setup.sh:45), add two new rotation blocks. Note the two vars need different grep patterns — `POSTGRES_PASSWORD` ships empty (matches existing pattern), `NOVA_ADMIN_SECRET` ships with a literal placeholder (needs a different match).

```bash
# ── Generate Postgres password if not set (matches existing empty-value pattern) ──
if grep -q "^POSTGRES_PASSWORD=$" "${PROJECT_ROOT}/.env" 2>/dev/null; then
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  sed -i "s|^POSTGRES_PASSWORD=$|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" "${PROJECT_ROOT}/.env"
  echo "  Generated POSTGRES_PASSWORD"
fi

# ── Rotate admin secret if still the shipped placeholder ──
if grep -q '^NOVA_ADMIN_SECRET=nova-admin-secret-change-me$' "${PROJECT_ROOT}/.env" 2>/dev/null; then
  NOVA_ADMIN_SECRET=$(openssl rand -hex 32)
  sed -i "s|^NOVA_ADMIN_SECRET=nova-admin-secret-change-me$|NOVA_ADMIN_SECRET=${NOVA_ADMIN_SECRET}|" "${PROJECT_ROOT}/.env"
  echo "  Generated NOVA_ADMIN_SECRET"
fi
```

**Note the idiom match.** The file uses `"${PROJECT_ROOT}/.env"` literally (not a `$ENV_FILE` variable) and capitalizes the new variable name identically to the env key. Match both conventions — easier to review as a cohesive patch.

**Why `openssl rand -hex`:** matches the CREDENTIAL_MASTER_KEY pattern. 32 bytes hex = 64 chars (admin secret). 24 bytes hex = 48 chars (Postgres password — plenty of entropy, fits comfortably in any connection string).

- [ ] **Step 5.4: Dry-run the rotation logic on a throwaway env**

```bash
cp .env.example /tmp/nova-rotation-test.env
grep -E '^(NOVA_ADMIN_SECRET|POSTGRES_PASSWORD)=' /tmp/nova-rotation-test.env
```
Expected: `POSTGRES_PASSWORD=` (empty), `NOVA_ADMIN_SECRET=nova-admin-secret-change-me`.

Run the new rotation logic against it (using the same idiom as setup.sh):
```bash
TMPROOT=/tmp/nova-rotation-test
mkdir -p "$TMPROOT"
cp /tmp/nova-rotation-test.env "$TMPROOT/.env"

if grep -q "^POSTGRES_PASSWORD=$" "$TMPROOT/.env" 2>/dev/null; then
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  sed -i "s|^POSTGRES_PASSWORD=$|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" "$TMPROOT/.env"
fi
if grep -q '^NOVA_ADMIN_SECRET=nova-admin-secret-change-me$' "$TMPROOT/.env" 2>/dev/null; then
  NOVA_ADMIN_SECRET=$(openssl rand -hex 32)
  sed -i "s|^NOVA_ADMIN_SECRET=nova-admin-secret-change-me$|NOVA_ADMIN_SECRET=${NOVA_ADMIN_SECRET}|" "$TMPROOT/.env"
fi

grep -E '^(NOVA_ADMIN_SECRET|POSTGRES_PASSWORD)=' "$TMPROOT/.env"
```
Expected: The two values are now 48-char and 64-char hex strings. Don't paste the values into chat. Shred after: `shred -u "$TMPROOT/.env" /tmp/nova-rotation-test.env && rmdir "$TMPROOT"`.

- [ ] **Step 5.5: Test idempotency**

Run the same logic a second time on the already-rotated `/tmp/test.env`. The `grep -q` guard should prevent re-rotation. Confirm the values didn't change.

- [ ] **Step 5.6: Verify idempotency on real `.env`**

This is the big one: your actual `.env` already has non-default values (set at initial install). Run the updated `scripts/setup.sh` against it. Confirm it does NOT re-rotate. If anything re-rotates, the guard is wrong — fix before committing. (If you're paranoid, take a `diff` of `.env` before and after.)

- [ ] **Step 5.7: Commit**

```bash
git add scripts/setup.sh
git commit -m "$(cat <<'EOF'
fix(setup): auto-rotate admin secret and Postgres password on first run

SEC-005 from the Phase 1.0 heal-the-stack spec. scripts/setup.sh
copied .env.example verbatim but never rotated NOVA_ADMIN_SECRET
or POSTGRES_PASSWORD, so users following the documented non-wizard
install path ended up with the hardcoded defaults
'nova-admin-secret-change-me' and 'nova_dev_password'. Anyone
following CLAUDE.md's quick-start and then enabling Cloudflare
tunnel / Tailscale / REQUIRE_AUTH=false is publishing admin access
with a known credential.

Extend the existing CREDENTIAL_MASTER_KEY / BRIDGE_SERVICE_SECRET
rotation pattern to these two vars: grep-for-default, sed-replace
with openssl rand output. Idempotent by construction — the grep
guard prevents re-rotation on subsequent runs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update BACKLOG.md to Done

- [ ] **Step 6.1: Mark the five rows Done in `docs/audits/2026-04-16-phase0/BACKLOG.md`**

Use `Edit` to change the `Status` column from `Open` to `Done` for: REL-001, OPS-001, OPS-002, PERF-002, SEC-005. Include the commit SHA in a comment column if you want, or just `Done`.

- [ ] **Step 6.2: Commit the backlog update**

```bash
git add docs/audits/2026-04-16-phase0/BACKLOG.md
git commit -m "$(cat <<'EOF'
docs(backlog): mark Phase 1.0 heal-the-stack items Done

REL-001, OPS-001, OPS-002, PERF-002, SEC-005 all shipped. See
commit log for individual SHAs; spec at
docs/superpowers/specs/2026-04-16-phase1-heal-the-stack-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step 7.1: All success criteria from the spec**

Work through the spec's "Success Criteria" section explicitly:

1. **No reaper error spam.** Run:
   ```bash
   docker compose logs orchestrator --since 5m 2>&1 | grep -E "Invalid task status|Reaper: task .* stale" | wc -l
   ```
   Expected: 0.

2. **Health rollups are Ollama-independent.** Run:
   ```bash
   curl -s http://localhost:8000/health/ready | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"
   curl -s http://localhost:8080/health/ready | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"
   ```
   Expected: `ready`, `ready`.

3. **Redis connections stable across restart.** Run a restart cycle and compare `redis-cli CLIENT LIST | wc -l` before/after.

4. **No cloud-embedding fallback.** Run:
   ```bash
   docker compose logs memory-service --since 2m 2>&1 | grep -c "fallback embedding model"
   ```
   Expected: 0.

5. **Chat turn latency <2s warm.** Send a chat message, time it.

6. **Fresh setup.sh rotates secrets.** Covered in Task 5 manual verification.

7. **BACKLOG rows flipped to Done.** Covered in Task 6.

- [ ] **Step 7.2: Full integration test suite passes**

Run: `make test`
Expected: All tests pass (including the new ones from Task 1 and Task 3). Pipeline tests may skip if no LLM provider is configured; that's fine.

- [ ] **Step 7.3: Git log review**

Run: `git log --oneline -7`
Expected: Six new commits (five fixes + one BACKLOG update), each with a conventional-commit prefix.

---

## Definition of done

- [ ] All 6 commits landed on `main`.
- [ ] Two new regression tests (health cascade, reaper stale-fail) pass in `make test`.
- [ ] All seven success criteria from the spec verified.
- [ ] BACKLOG.md shows REL-001, OPS-001, OPS-002, PERF-002, SEC-005 as Done.
- [ ] No leftover log spam (`docker compose logs --since 5m | grep -iE "error|exception" | wc -l` is at baseline).

---

## Rollback

If any of the five fixes causes a regression:

- **OPS-001 revert** — `git revert <sha>` restores the old cascading behavior. No data impact.
- **OPS-002 revert** — `git revert <sha>` re-introduces the leak. No data impact. (Services continue to run.)
- **REL-001 revert** — `git revert <sha>` restores the infinite loop. The force-failed tasks stay failed (that state change is not reverted by the code revert). Acceptable.
- **PERF-002 revert** — flip Redis config back: `inference.backend=none`, `routing_strategy=cloud-only`. No code to revert (empty commit).
- **SEC-005 revert** — `git revert <sha>` restores the non-rotating setup. Already-rotated `.env` files keep their random values (the revert affects future installs only).

Each revert is independent; the five commits are ordered by dependency only incidentally. Any subset can be kept or rolled back.
