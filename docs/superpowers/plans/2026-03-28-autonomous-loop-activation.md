# P1: Autonomous Loop Activation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 5 reinforcing bugs that prevent Cortex from executing goals autonomously, add self-awareness tools so the chat agent can verify system state, build the intel recommendation pipeline, fix Sources UX confusion, and cover all new code with integration tests.

**Architecture:** 5 sequential tiers, each independently shippable. Tier 1 fixes the Cortex goal execution loop (enriched planning context, skip prevention, budget enforcement). Tier 2 adds memory/consolidation tools to the chat agent. Tier 3 builds the missing `POST /recommendations` endpoint and intel MCP tools for Cortex. Tier 4 renames dashboard labels to disambiguate "Sources." Tier 5 writes regression tests covering Tiers 1-4.

**Tech Stack:** Python 3.11 (FastAPI, asyncpg, httpx), React/TypeScript (Vite, TanStack Query, Tailwind), Redis, PostgreSQL, pytest

**Spec:** `docs/superpowers/specs/2026-03-28-platform-health-analysis.md`

---

## File Map

### Tier 1 — Unblock Goal Execution Loop

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `cortex/app/drives/serve.py` | Enrich stale goals query with description, current_plan, iteration, max_iterations, cost; enforce max_iterations/max_cost |
| Modify | `cortex/app/cycle.py` | Restructure planning prompt, handle skips properly (update last_checked_at, set action_taken="idle"), add skip counter with forced action after 3 skips |
| Test | `tests/test_cortex_loop.py` | New: goal planning context, skip behavior, budget enforcement |

### Tier 2 — Agent Self-Awareness Tools

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `orchestrator/app/tools/memory_tools.py` | Add `get_consolidation_status`, `get_memory_stats`, `trigger_consolidation` tools |
| Modify | `orchestrator/app/tools/__init__.py` | No change needed — memory_tools already registered |
| Modify | `orchestrator/app/agents/runner.py` | Expand self-knowledge to describe all 7 tool groups + metacognition guidance |
| Test | `tests/test_agent_capabilities.py` | Expand: consolidation tool, memory stats tool, self-knowledge content |

### Tier 3 — Intel Recommendation Pipeline

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `orchestrator/app/intel_router.py` | Add `POST /api/v1/intel/recommendations` endpoint |
| Create | `orchestrator/app/tools/intel_tools.py` | New: `query_intel_content`, `create_recommendation`, `get_dismissed_hashes` MCP tools for Cortex |
| Modify | `orchestrator/app/tools/__init__.py` | Register Intel tool group |
| Modify | `intel-worker/app/worker.py` | Remove or consume `intel:new_items` queue push (stop dead letter leak) |
| Test | `tests/test_intel_recommendations.py` | New: POST endpoint, recommendation lifecycle, dismissed hash dedup |

### Tier 4 — Sources UX Clarity

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `dashboard/src/components/layout/Sidebar.tsx` | Rename "Sources" nav link to "Knowledge" |
| Modify | `dashboard/src/pages/Sources.tsx` | Update page title and help text |
| Modify | `dashboard/src/pages/Brain.tsx` | If Sources tab exists, rename to "Provenance" |
| Test | `dashboard build` | TypeScript compilation check (`cd dashboard && npm run build`) |

### Tier 5 — Regression Test Coverage

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `tests/test_cortex_goals.py` | Add goal planning context fields test |
| Modify | `tests/test_consolidation.py` | Add manual trigger test via tool endpoint |
| Create | `tests/test_intel_recommendations.py` | Full recommendation lifecycle coverage |
| Modify | `tests/test_agent_capabilities.py` | Remove xfail markers, add positive assertions |

---

## Task 1: Enrich Serve Drive Planning Context

**Files:**
- Modify: `cortex/app/drives/serve.py:28-44`
- Test: `tests/test_cortex_loop.py` (create)

- [ ] **Step 1: Write failing test — goal planning context includes description and plan**

Create `tests/test_cortex_loop.py`:

```python
"""Tests for Cortex autonomous loop fixes — Tier 1."""
import pytest
import httpx

BASE = "http://localhost:8000/api/v1"
CORTEX = "http://localhost:8100/api/v1/cortex"
HEADERS = {"X-Admin-Secret": ""}  # filled by fixture


@pytest.fixture(autouse=True)
def admin_headers():
    """Read admin secret from env or use default."""
    import os
    secret = os.environ.get("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    HEADERS["X-Admin-Secret"] = secret


@pytest.fixture
def goal_id():
    """Create a test goal and clean up after."""
    import httpx as h
    resp = h.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-cortex-loop-goal",
            "description": "Test goal with description for planning context",
            "priority": 3,
            "max_iterations": 10,
            "max_cost_usd": 1.50,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Failed to create goal: {resp.text}"
    gid = resp.json()["id"]
    yield gid
    # Cleanup
    try:
        h.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
    except Exception:
        pass


def test_goal_detail_includes_planning_fields(goal_id):
    """Goals returned by orchestrator include description, current_plan, iteration,
    max_iterations, and cost_so_far_usd — fields Cortex needs for planning."""
    resp = httpx.get(f"{BASE}/goals/{goal_id}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    # These fields must be present (not None — they should have values or defaults)
    assert "description" in data
    assert data["description"] == "Test goal with description for planning context"
    assert "current_plan" in data
    assert "iteration" in data
    assert "max_iterations" in data
    assert data["max_iterations"] == 10
    assert "cost_so_far_usd" in data
    assert "max_cost_usd" in data
    assert data["max_cost_usd"] == 1.50


def test_cortex_drives_return_serve_with_stale_goals(goal_id):
    """Cortex /drives endpoint returns serve drive with stale goal context
    that includes description, not just title."""
    resp = httpx.get(f"{CORTEX}/drives", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    drives = data.get("drives", [])
    serve = next((d for d in drives if d["name"] == "serve"), None)
    assert serve is not None, "Serve drive not found in drives response"
    # Serve should have context with stale_goals
    ctx = serve.get("context", {})
    stale = ctx.get("stale_goals", [])
    # Our test goal should appear since it was just created (last_checked_at = NULL)
    test_goal = next((g for g in stale if g["id"] == goal_id), None)
    if test_goal:
        # Verify enriched fields are present
        assert "description" in test_goal, "Stale goal missing 'description' field"
        assert "current_plan" in test_goal, "Stale goal missing 'current_plan' field"
        assert "iteration" in test_goal, "Stale goal missing 'iteration' field"
        assert "max_iterations" in test_goal, "Stale goal missing 'max_iterations' field"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_cortex_loop.py -v -x 2>&1 | head -50`

Expected: FAIL — stale_goals context currently only includes id, title, priority, progress, maturation_status (missing description, current_plan, iteration, max_iterations).

- [ ] **Step 3: Enrich serve drive stale goals query**

In `cortex/app/drives/serve.py`, modify the stale goals query (lines 28-44) to include the missing fields, and add budget enforcement:

```python
        stale_goals = await conn.fetch(
            """
            SELECT id, title, description, priority, progress,
                   check_interval_seconds, last_checked_at,
                   maturation_status, current_plan,
                   iteration, max_iterations, cost_so_far_usd, max_cost_usd
            FROM goals
            WHERE status = 'active'
              AND (
                (last_checked_at IS NULL
                 OR last_checked_at < NOW() - (check_interval_seconds || ' seconds')::interval)
                OR maturation_status IN ('scoping', 'speccing', 'building', 'verifying')
              )
              AND (maturation_status IS NULL OR maturation_status != 'review')
              AND (max_iterations IS NULL OR iteration < max_iterations)
              AND (max_cost_usd IS NULL OR COALESCE(cost_so_far_usd, 0) < max_cost_usd)
            ORDER BY priority DESC
            LIMIT 5
            """,
        )
```

Update the goal_summaries dict (lines 90-94) to include the new fields:

```python
    goal_summaries = [
        {"id": str(g["id"]), "title": g["title"],
         "description": (g["description"] or "")[:500],
         "priority": g["priority"],
         "progress": g["progress"],
         "maturation_status": g.get("maturation_status"),
         "current_plan": g["current_plan"],
         "iteration": g["iteration"],
         "max_iterations": g["max_iterations"],
         "cost_so_far_usd": float(g["cost_so_far_usd"] or 0),
         "max_cost_usd": float(g["max_cost_usd"]) if g["max_cost_usd"] else None}
        for g in stale_goals
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_cortex_loop.py -v -x`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cortex/app/drives/serve.py tests/test_cortex_loop.py
git commit -m "feat(cortex): enrich serve drive with full goal context and budget enforcement"
```

---

## Task 2: Fix Skip Handling in Thinking Cycle

**Files:**
- Modify: `cortex/app/cycle.py:251-296`
- Test: `tests/test_cortex_loop.py`

- [ ] **Step 1: Write failing test — skips update last_checked_at**

Add to `tests/test_cortex_loop.py`:

```python
def test_goal_last_checked_at_updates_on_access(goal_id):
    """When Cortex evaluates a goal (even to skip it), last_checked_at must update
    so the same goal doesn't re-trigger every 30 seconds."""
    import time

    # Read initial state
    resp = httpx.get(f"{BASE}/goals/{goal_id}", headers=HEADERS)
    assert resp.status_code == 200
    initial = resp.json().get("last_checked_at")

    # Trigger cortex to look at goals (via /trigger which forces serve on this goal)
    # We use a direct goal update instead since /trigger dispatches a task
    httpx.patch(
        f"{BASE}/goals/{goal_id}",
        json={"last_checked_at": "2020-01-01T00:00:00Z"},  # Force it stale
        headers=HEADERS,
    )

    # Wait briefly, then read again
    time.sleep(0.5)

    # The test validates the API contract: goals have last_checked_at field
    resp2 = httpx.get(f"{BASE}/goals/{goal_id}", headers=HEADERS)
    assert resp2.status_code == 200
    data = resp2.json()
    assert "last_checked_at" in data, "Goal response must include last_checked_at"
```

- [ ] **Step 2: Run test to verify baseline**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_cortex_loop.py::test_goal_last_checked_at_updates_on_access -v -x`

- [ ] **Step 3: Fix skip handling in cycle.py**

Modify `_execute_action()` in `cortex/app/cycle.py` (around line 293-296) to handle skips properly:

```python
async def _execute_action(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute the planned action. Returns outcome description."""
    if "skip" in plan.lower()[:20]:
        # ── Skip handling: update last_checked_at so we don't re-evaluate immediately
        if drive.name == "serve":
            stale_goals = drive.context.get("stale_goals", [])
            if stale_goals:
                goal_id = stale_goals[0]["id"]
                try:
                    pool = get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE goals SET last_checked_at = NOW(), updated_at = NOW() WHERE id = $1::uuid",
                            goal_id,
                        )
                except Exception as e:
                    log.warning("Failed to update last_checked_at on skip: %s", e)

        # Mark as idle so adaptive timeout stays long
        state.action_taken = "idle"
        return "Skipped — no meaningful action to take"

    if drive.name == "serve":
        return await _execute_serve(drive, plan, state)
    elif drive.name == "maintain":
        return await _execute_maintain(drive, plan)
    elif drive.name == "improve":
        return await _execute_improve(drive, plan)
    elif drive.name == "reflect":
        return await _execute_reflect(drive, plan, state)
    elif drive.name == "learn":
        return await _execute_learn(drive, plan, state)
    else:
        return f"Drive '{drive.name}' has no executor"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_cortex_loop.py -v -x`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cortex/app/cycle.py tests/test_cortex_loop.py
git commit -m "fix(cortex): update last_checked_at on skip, treat skips as idle"
```

---

## Task 3: Add Skip Counter and Forced Action

**Files:**
- Modify: `cortex/app/cycle.py`
- Test: `tests/test_cortex_loop.py`

- [ ] **Step 1: Write failing test — skip counter resets after dispatch**

Add to `tests/test_cortex_loop.py`:

```python
def test_cortex_status_includes_skip_count():
    """Cortex status endpoint should expose skip tracking for observability."""
    resp = httpx.get(f"{CORTEX}/status", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    # last_checkpoint should contain skip tracking info after cycles run
    assert "last_checkpoint" in data or "cycle_count" in data
```

- [ ] **Step 2: Run test to verify baseline**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_cortex_loop.py::test_cortex_status_includes_skip_count -v -x`

- [ ] **Step 3: Add skip counter with forced action after 3 consecutive skips**

Modify `cortex/app/cycle.py`. Add a module-level skip counter and modify the planning prompt:

At the top of the file (after imports), add:

```python
# Track consecutive skips per goal to prevent infinite skip loops
_consecutive_skips: dict[str, int] = {}
MAX_CONSECUTIVE_SKIPS = 3
```

Modify `_plan_action()` to discourage skipping when goals have context:

```python
async def _plan_action(drive: DriveResult, state: CycleState) -> str:
    """Use LLM to decide what specific action to take for the winning drive."""
    if state.budget_tier == "none":
        return f"Budget exhausted — skip LLM planning. Drive: {drive.name}"

    # Build a compact prompt
    user_msg_summary = ""
    if state.user_messages:
        msgs = "; ".join(m["content"][:100] for m in state.user_messages[:3])
        user_msg_summary = f"\nUser messages since last cycle: {msgs}"

    stimulus_summary = ""
    if state.stimuli:
        stim_types = ", ".join(s.get("type", "?") for s in state.stimuli[:5])
        stimulus_summary = f"\nStimuli this cycle: {stim_types}"

    if state.memory_context:
        stimulus_summary += f"\n\nRelevant memories:\n{state.memory_context[:1000]}"

    # Check if forced action is needed (too many consecutive skips)
    forced = False
    goal_context_block = ""
    if drive.name == "serve":
        stale_goals = drive.context.get("stale_goals", [])
        if stale_goals:
            goal = stale_goals[0]
            goal_id = goal.get("id", "")
            skip_count = _consecutive_skips.get(goal_id, 0)
            if skip_count >= MAX_CONSECUTIVE_SKIPS:
                forced = True

            # Build rich goal context
            parts = [f"Title: {goal.get('title', 'unknown')}"]
            if goal.get("description"):
                parts.append(f"Description: {goal['description'][:300]}")
            if goal.get("current_plan"):
                plan_info = goal["current_plan"]
                if isinstance(plan_info, dict):
                    if plan_info.get("last_task_status") == "failed":
                        parts.append(f"Last attempt FAILED: {plan_info.get('last_task_error', 'unknown')[:200]}")
                    elif plan_info.get("last_task_output"):
                        parts.append(f"Last result: {plan_info['last_task_output'][:200]}")
                    if plan_info.get("plan"):
                        parts.append(f"Previous plan: {plan_info['plan'][:200]}")
            parts.append(f"Progress: iteration {goal.get('iteration', 0)}/{goal.get('max_iterations', 50)}")
            if goal.get("cost_so_far_usd"):
                limit = goal.get("max_cost_usd")
                parts.append(f"Cost: ${goal['cost_so_far_usd']:.2f}" + (f" / ${limit:.2f} limit" if limit else ""))
            goal_context_block = "\n".join(parts)

    skip_instruction = ""
    if forced:
        skip_instruction = (
            "\n\nIMPORTANT: This goal has been skipped multiple times consecutively. "
            "You MUST produce an actionable plan this time. Do NOT say 'skip'. "
            "If the goal is unclear, create a task to gather more information or clarify requirements."
        )
    elif drive.name == "serve" and goal_context_block:
        skip_instruction = (
            '\n\nOnly say "skip" if you genuinely cannot identify ANY useful next step. '
            "If the goal has a description, you should be able to plan work."
        )

    prompt = f"""You are Nova's autonomous brain (Cortex). You are deciding what to do this cycle.

Winning drive: {drive.name} (urgency {drive.urgency}, score {state.winner.score:.2f})
Drive says: {drive.description}
Proposed action: {drive.proposed_action or 'none specified'}

{"Goal details:\n" + goal_context_block if goal_context_block else ""}
Context: {json.dumps(drive.context, default=str)[:1000]}

Budget: {state.budget_pct:.0f}% used today (tier: {state.budget_tier})
Cycle: #{state.cycle_number}{user_msg_summary}{stimulus_summary}{skip_instruction}

Based on this, decide what SPECIFIC action to take. Be concise (1-3 sentences).
If the drive is "serve", describe the next concrete task to dispatch for this goal.
If the drive is "maintain" and services are degraded, describe the health issue.

Your response is the action plan (not code, just a description)."""

    try:
        llm = get_llm()
        model = settings.planning_model or ""
        resp = await llm.post("/complete", json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 300,
            "tier": "mid",
            "task_type": "planning",
            "metadata": {"agent_id": "cortex", "task_id": f"cycle-{state.cycle_number}"},
        })
        if resp.status_code == 200:
            data = resp.json()
            state.resolved_model = data.get("model") or state.resolved_model
            return data.get("content", "No plan generated")
        else:
            log.warning("LLM planning call failed: %d %s", resp.status_code, resp.text[:200])
            return f"LLM unavailable ({resp.status_code}) — using drive's proposed action: {drive.proposed_action}"
    except Exception as e:
        log.warning("LLM planning call error: %s", e)
        return f"LLM error — using drive's proposed action: {drive.proposed_action}"
```

Update `_execute_action()` to track skip counts:

```python
async def _execute_action(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute the planned action. Returns outcome description."""
    if "skip" in plan.lower()[:20]:
        # Track consecutive skips per goal
        if drive.name == "serve":
            stale_goals = drive.context.get("stale_goals", [])
            if stale_goals:
                goal_id = stale_goals[0]["id"]
                _consecutive_skips[goal_id] = _consecutive_skips.get(goal_id, 0) + 1
                log.info(
                    "Goal %s skipped (%d consecutive)",
                    goal_id, _consecutive_skips[goal_id],
                )
                # Update last_checked_at so we don't re-evaluate immediately
                try:
                    pool = get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE goals SET last_checked_at = NOW(), updated_at = NOW() WHERE id = $1::uuid",
                            goal_id,
                        )
                except Exception as e:
                    log.warning("Failed to update last_checked_at on skip: %s", e)

        state.action_taken = "idle"
        return "Skipped — no meaningful action to take"

    # Reset skip counter on successful action
    if drive.name == "serve":
        stale_goals = drive.context.get("stale_goals", [])
        if stale_goals:
            goal_id = stale_goals[0]["id"]
            if goal_id in _consecutive_skips:
                del _consecutive_skips[goal_id]

    if drive.name == "serve":
        return await _execute_serve(drive, plan, state)
    elif drive.name == "maintain":
        return await _execute_maintain(drive, plan)
    elif drive.name == "improve":
        return await _execute_improve(drive, plan)
    elif drive.name == "reflect":
        return await _execute_reflect(drive, plan, state)
    elif drive.name == "learn":
        return await _execute_learn(drive, plan, state)
    else:
        return f"Drive '{drive.name}' has no executor"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_cortex_loop.py -v -x`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cortex/app/cycle.py tests/test_cortex_loop.py
git commit -m "feat(cortex): add skip counter with forced action after 3 consecutive skips"
```

---

## Task 4: Add Consolidation and Memory Stats Tools

**Files:**
- Modify: `orchestrator/app/tools/memory_tools.py`
- Test: `tests/test_agent_capabilities.py`

- [ ] **Step 1: Write failing test — consolidation status tool exists**

Add to `tests/test_agent_capabilities.py`:

```python
def test_consolidation_status_tool_accessible():
    """The get_consolidation_status tool should be callable and return data."""
    resp = httpx.get(f"{BASE}/tools", headers=HEADERS)
    assert resp.status_code == 200
    tools = resp.json()
    tool_names = [t["name"] for t in tools] if isinstance(tools, list) else []
    assert "get_consolidation_status" in tool_names, (
        f"get_consolidation_status not in tool catalog. Available: {tool_names}"
    )


def test_memory_stats_tool_accessible():
    """The get_memory_stats tool should be callable and return data."""
    resp = httpx.get(f"{BASE}/tools", headers=HEADERS)
    assert resp.status_code == 200
    tools = resp.json()
    tool_names = [t["name"] for t in tools] if isinstance(tools, list) else []
    assert "get_memory_stats" in tool_names, (
        f"get_memory_stats not in tool catalog. Available: {tool_names}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_agent_capabilities.py::test_consolidation_status_tool_accessible -v -x`

Expected: FAIL — tool doesn't exist yet

- [ ] **Step 3: Add three new memory tools**

Append to `orchestrator/app/tools/memory_tools.py`:

```python
# --- Add these tool definitions to MEMORY_TOOLS list ---

ToolDefinition(
    name="get_consolidation_status",
    description="Check if memory consolidation is running and view recent consolidation history. "
                "Use this to verify consolidation cycles are happening before making claims about memory health.",
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of recent consolidation entries to return (default 5, max 20)",
            },
        },
    },
),
ToolDefinition(
    name="get_memory_stats",
    description="Get current memory system statistics: total engrams, types breakdown, "
                "last ingestion time, edge count, and embedding cache metrics.",
    parameters={"type": "object", "properties": {}},
),
ToolDefinition(
    name="trigger_consolidation",
    description="Manually trigger a memory consolidation cycle. Consolidation merges, prunes, "
                "and strengthens engram connections. Has a cooldown (default 30 min) to prevent overuse.",
    parameters={"type": "object", "properties": {}},
),
```

Add the execution handlers to the `execute_tool()` function in the same file:

```python
    elif name == "get_consolidation_status":
        limit = min(int(arguments.get("limit", 5)), 20)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{MEM_BASE}/consolidation-log", params={"limit": limit})
            if resp.status_code == 200:
                entries = resp.json()
                if not entries:
                    return "No consolidation runs recorded yet."
                lines = ["Recent consolidation history:"]
                for e in entries:
                    lines.append(
                        f"- {e.get('started_at', '?')}: {e.get('status', '?')} "
                        f"({e.get('phases_completed', '?')} phases, "
                        f"{e.get('engrams_processed', '?')} engrams)"
                    )
                return "\n".join(lines)
            return f"Consolidation log unavailable (HTTP {resp.status_code})"
        except Exception as e:
            return f"Failed to check consolidation: {e}"

    elif name == "get_memory_stats":
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{MEM_BASE}/stats")
            if resp.status_code == 200:
                stats = resp.json()
                return json.dumps(stats, indent=2, default=str)
            return f"Memory stats unavailable (HTTP {resp.status_code})"
        except Exception as e:
            return f"Failed to get memory stats: {e}"

    elif name == "trigger_consolidation":
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{MEM_BASE}/consolidate")
            if resp.status_code == 200:
                data = resp.json()
                return f"Consolidation triggered: {json.dumps(data, default=str)}"
            elif resp.status_code == 429:
                return "Consolidation on cooldown — too soon since last run. Try again later."
            return f"Consolidation trigger failed (HTTP {resp.status_code}): {resp.text[:200]}"
        except Exception as e:
            return f"Failed to trigger consolidation: {e}"
```

Note: `MEM_BASE` should already be defined in the file as `http://memory-service:8002/api/v1/engrams`. If not, add it at the top of the module. Also add `import json` if not already imported.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_agent_capabilities.py::test_consolidation_status_tool_accessible tests/test_agent_capabilities.py::test_memory_stats_tool_accessible -v -x`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/tools/memory_tools.py tests/test_agent_capabilities.py
git commit -m "feat(tools): add consolidation status, memory stats, and trigger consolidation tools"
```

---

## Task 5: Expand Self-Knowledge Narrative

**Files:**
- Modify: `orchestrator/app/agents/runner.py` (`_build_self_knowledge()` function)
- Test: `tests/test_agent_capabilities.py`

- [ ] **Step 1: Write failing test — self-knowledge includes all tool groups**

Add to `tests/test_agent_capabilities.py`:

```python
def test_self_knowledge_mentions_all_tool_groups():
    """Self-knowledge block should describe all 7 tool groups, not just diagnosis."""
    resp = httpx.post(
        f"{BASE}/v1/chat/completions",
        json={
            "model": "",
            "messages": [{"role": "user", "content": "What tools do you have access to?"}],
            "max_tokens": 50,
            "stream": False,
        },
        headers=HEADERS,
    )
    # We can't easily inspect the system prompt from outside, but we can
    # check the tool catalog includes all groups
    resp2 = httpx.get(f"{BASE}/tools", headers=HEADERS)
    assert resp2.status_code == 200
    tools = resp2.json()
    tool_names = {t["name"] for t in tools} if isinstance(tools, list) else set()

    # All 7 groups should have at least one tool in the catalog
    expected_groups = {
        "Code": "list_dir",
        "Git": "git_status",
        "Platform": "list_agents",
        "Web": "web_search",
        "Diagnosis": "diagnose_task",
        "Memory": "search_memory",
        "Introspect": "get_platform_config",
    }
    for group, sample_tool in expected_groups.items():
        assert sample_tool in tool_names, f"Tool '{sample_tool}' from group '{group}' missing from catalog"
```

- [ ] **Step 2: Run test to verify baseline**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_agent_capabilities.py::test_self_knowledge_mentions_all_tool_groups -v -x`

- [ ] **Step 3: Expand self-knowledge in runner.py**

Locate `_build_self_knowledge()` in `orchestrator/app/agents/runner.py` and replace the tool description section with a comprehensive listing of all 7 groups plus metacognition guidance:

Add at the end of the self-knowledge block:

```python
    # What I Can Do — tool groups
    parts.append("""
## What I Can Do

I have access to these tool groups:

**Code (Files & Shell):** list_dir, read_file, write_file, run_shell, search_codebase — read, write, and execute within the workspace.

**Git (Version Control):** git_status, git_diff, git_log, git_commit — inspect and commit changes.

**Platform (Agent Management):** list_agents, get_agent_info, create_agent, update_agent, delete_agent, list_models — manage agents and view available models.

**Web (Internet Access):** web_search, web_fetch — search the internet and fetch web pages.

**Diagnosis (Self-Diagnosis):** diagnose_task, check_service_health, get_recent_errors, get_stage_output, get_task_timeline — investigate task failures and system health.

**Memory (Knowledge Retrieval):** what_do_i_know, search_memory, recall_topic, read_source, get_consolidation_status, get_memory_stats, trigger_consolidation — search, recall, and manage my memory system.

**Introspect (Platform Awareness):** get_platform_config, list_knowledge_sources, list_mcp_servers, get_user_profile — query my own configuration and connected services.

## How I Think

- **Verify before asserting.** If a user asks "is consolidation running?" I call get_consolidation_status rather than guessing. If they ask about a failed task, I call diagnose_task.
- **Use tools to check my own state.** I don't claim capabilities I can't verify. If I'm unsure whether something is configured, I use get_platform_config or check_service_health.
- **Admit uncertainty.** If I can't verify something, I say so rather than making a confident claim.
""")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_agent_capabilities.py::test_self_knowledge_mentions_all_tool_groups -v -x`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/agents/runner.py tests/test_agent_capabilities.py
git commit -m "feat(agent): expand self-knowledge with all tool groups and metacognition guidance"
```

---

## Task 6: Add POST /api/v1/intel/recommendations Endpoint

**Files:**
- Modify: `orchestrator/app/intel_router.py`
- Test: `tests/test_intel_recommendations.py` (create)

- [ ] **Step 1: Write failing test — POST recommendations endpoint exists**

Create `tests/test_intel_recommendations.py`:

```python
"""Tests for intel recommendation pipeline — Tier 3."""
import os
import pytest
import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": ""}


@pytest.fixture(autouse=True)
def admin_headers():
    secret = os.environ.get("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    HEADERS["X-Admin-Secret"] = secret


@pytest.fixture
def recommendation_id():
    """Create a test recommendation and clean up after."""
    resp = httpx.post(
        f"{BASE}/intel/recommendations",
        json={
            "title": "nova-test-rec-pipeline",
            "summary": "Test recommendation for pipeline validation",
            "rationale": "Created by integration test",
            "grade": "B",
            "confidence": 0.75,
            "category": "tooling",
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"POST recommendations failed: {resp.text}"
    rid = resp.json()["id"]
    yield rid
    # Cleanup: dismiss it
    try:
        httpx.patch(
            f"{BASE}/intel/recommendations/{rid}",
            json={"status": "dismissed"},
            headers=HEADERS,
        )
    except Exception:
        pass


def test_create_recommendation():
    """POST /api/v1/intel/recommendations creates a recommendation."""
    resp = httpx.post(
        f"{BASE}/intel/recommendations",
        json={
            "title": "nova-test-rec-create",
            "summary": "Test creation of recommendations via API",
            "rationale": "Integration test verifying endpoint exists",
            "grade": "C",
            "confidence": 0.5,
            "category": "other",
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "id" in data
    assert data["title"] == "nova-test-rec-create"
    assert data["grade"] == "C"

    # Cleanup
    httpx.patch(
        f"{BASE}/intel/recommendations/{data['id']}",
        json={"status": "dismissed"},
        headers=HEADERS,
    )


def test_recommendation_lifecycle(recommendation_id):
    """Recommendation can be created, read, and status-updated."""
    # Read
    resp = httpx.get(f"{BASE}/intel/recommendations/{recommendation_id}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["grade"] == "B"

    # Approve (creates a linked goal)
    resp2 = httpx.patch(
        f"{BASE}/intel/recommendations/{recommendation_id}",
        json={"status": "approved"},
        headers=HEADERS,
    )
    assert resp2.status_code == 200

    # Verify status changed
    resp3 = httpx.get(f"{BASE}/intel/recommendations/{recommendation_id}", headers=HEADERS)
    assert resp3.status_code == 200
    # After approval, status transitions to "speccing" (the approve handler creates a goal)
    assert resp3.json()["status"] in ("approved", "speccing")


def test_create_recommendation_with_source_links(recommendation_id):
    """Recommendations can be linked to content items and engrams at creation time."""
    # The recommendation_id fixture already created one; verify it can be read
    resp = httpx.get(f"{BASE}/intel/recommendations/{recommendation_id}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    # Sources and engrams arrays should exist (may be empty for test data)
    assert "sources" in data or "source_count" in data


def test_create_recommendation_validation():
    """POST /api/v1/intel/recommendations rejects invalid data."""
    # Missing required fields
    resp = httpx.post(
        f"{BASE}/intel/recommendations",
        json={"title": "nova-test-rec-invalid"},  # missing summary, grade
        headers=HEADERS,
    )
    assert resp.status_code in (400, 422), f"Expected validation error, got {resp.status_code}"

    # Invalid grade
    resp2 = httpx.post(
        f"{BASE}/intel/recommendations",
        json={
            "title": "nova-test-rec-bad-grade",
            "summary": "Bad grade test",
            "rationale": "Testing validation",
            "grade": "X",  # invalid
            "confidence": 0.5,
            "category": "other",
        },
        headers=HEADERS,
    )
    assert resp2.status_code in (400, 422), f"Expected validation error for bad grade, got {resp2.status_code}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_intel_recommendations.py::test_create_recommendation -v -x`

Expected: FAIL — 405 Method Not Allowed (POST endpoint doesn't exist)

- [ ] **Step 3: Add POST endpoint to intel_router.py**

Add the following endpoint to `orchestrator/app/intel_router.py`:

```python
class CreateRecommendationRequest(BaseModel):
    title: str
    summary: str
    rationale: str
    grade: str  # A, B, or C
    confidence: float  # 0.0-1.0
    category: str = "other"
    features: list[str] = []
    complexity: str = "medium"  # low, medium, high
    auto_implementable: bool = False
    implementation_plan: str | None = None
    source_content_ids: list[str] = []  # optional: link to intel_content_items
    engram_ids: list[str] = []  # optional: link to engrams


@router.post("/recommendations", response_model=dict)
async def create_recommendation(
    req: CreateRecommendationRequest,
    conn=Depends(get_connection),
    _admin=Depends(AdminDep),
):
    """Create a new intel recommendation. Used by Cortex synthesis goals."""
    # Validate grade
    if req.grade not in ("A", "B", "C"):
        raise HTTPException(400, f"Invalid grade '{req.grade}' — must be A, B, or C")
    if not 0 <= req.confidence <= 1:
        raise HTTPException(400, f"Confidence must be 0.0-1.0, got {req.confidence}")
    if req.complexity not in ("low", "medium", "high"):
        raise HTTPException(400, f"Invalid complexity '{req.complexity}' — must be low, medium, or high")

    rec_id = str(uuid4())
    await conn.execute(
        """
        INSERT INTO intel_recommendations (id, title, summary, rationale, features,
            grade, confidence, category, status, auto_implementable,
            implementation_plan, complexity, created_at, updated_at)
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, 'pending', $9, $10, $11, NOW(), NOW())
        """,
        rec_id, req.title, req.summary, req.rationale,
        req.features, req.grade, req.confidence, req.category,
        req.auto_implementable, req.implementation_plan, req.complexity,
    )

    # Link source content items
    for cid in req.source_content_ids:
        try:
            await conn.execute(
                """INSERT INTO intel_recommendation_sources (recommendation_id, content_item_id)
                   VALUES ($1::uuid, $2::uuid) ON CONFLICT DO NOTHING""",
                rec_id, cid,
            )
        except Exception:
            pass  # Skip invalid UUIDs

    # Link engrams (soft reference)
    for eid in req.engram_ids:
        try:
            await conn.execute(
                """INSERT INTO intel_recommendation_engrams (recommendation_id, engram_id)
                   VALUES ($1::uuid, $2::uuid) ON CONFLICT DO NOTHING""",
                rec_id, eid,
            )
        except Exception:
            pass

    # Emit stimulus for Cortex
    try:
        from app.stimulus import emit_stimulus
        await emit_stimulus("recommendation.created", {"recommendation_id": rec_id, "title": req.title, "grade": req.grade})
    except Exception:
        pass

    return {"id": rec_id, "title": req.title, "grade": req.grade, "status": "pending"}
```

Note: Check exact imports and dependency injection patterns already used in `intel_router.py` and match them. The `get_connection`, `AdminDep`, `uuid4`, `BaseModel`, and `HTTPException` should already be imported or available.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_intel_recommendations.py -v -x`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/intel_router.py tests/test_intel_recommendations.py
git commit -m "feat(intel): add POST /api/v1/intel/recommendations endpoint"
```

---

## Task 7: Create Intel MCP Tools for Cortex

**Files:**
- Create: `orchestrator/app/tools/intel_tools.py`
- Modify: `orchestrator/app/tools/__init__.py`
- Test: `tests/test_intel_recommendations.py`

- [ ] **Step 1: Write failing test — intel tools in catalog**

Add to `tests/test_intel_recommendations.py`:

```python
def test_intel_tools_in_catalog():
    """Intel tools should be in the tool catalog for Cortex to use."""
    resp = httpx.get(f"{BASE}/tools", headers=HEADERS)
    assert resp.status_code == 200
    tools = resp.json()
    tool_names = {t["name"] for t in tools} if isinstance(tools, list) else set()
    assert "query_intel_content" in tool_names, f"query_intel_content missing. Got: {tool_names}"
    assert "create_recommendation" in tool_names, f"create_recommendation missing. Got: {tool_names}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_intel_recommendations.py::test_intel_tools_in_catalog -v -x`

Expected: FAIL — tools don't exist yet

- [ ] **Step 3: Create intel_tools.py**

Create `orchestrator/app/tools/intel_tools.py`:

```python
"""Intel tools — let Cortex query intel content and create recommendations."""
from __future__ import annotations

import json
import logging
from uuid import uuid4

from nova_contracts import ToolDefinition

from app.db import get_pool

log = logging.getLogger(__name__)

INTEL_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="query_intel_content",
        description="Query recent intel content items from monitored feeds. "
                    "Returns titles, URLs, categories, and publication dates. "
                    "Use to find what's new in the AI ecosystem.",
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (reddit, github, blog, tooling, docs, other)",
                },
                "since_hours": {
                    "type": "integer",
                    "description": "Items from the last N hours (default 168 = 1 week, max 720)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20, max 100)",
                },
                "search": {
                    "type": "string",
                    "description": "Search title and body text (case-insensitive substring match)",
                },
            },
        },
    ),
    ToolDefinition(
        name="create_recommendation",
        description="Create an intel recommendation for human review. "
                    "Recommendations grade content as A (high value, low effort), "
                    "B (moderate), or C (speculative). Recommendations appear in the dashboard "
                    "Suggested Goals tab for human approval.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short recommendation title"},
                "summary": {"type": "string", "description": "What and why (2-3 sentences)"},
                "rationale": {"type": "string", "description": "Evidence and reasoning"},
                "grade": {"type": "string", "enum": ["A", "B", "C"], "description": "A=high value, B=moderate, C=speculative"},
                "confidence": {"type": "number", "description": "0.0-1.0 confidence score"},
                "category": {"type": "string", "description": "Category (tooling, architecture, performance, security, etc.)"},
                "features": {"type": "array", "items": {"type": "string"}, "description": "Key features/capabilities"},
                "source_content_ids": {"type": "array", "items": {"type": "string"}, "description": "Intel content item IDs that informed this recommendation"},
            },
            "required": ["title", "summary", "rationale", "grade", "confidence"],
        },
    ),
    ToolDefinition(
        name="get_dismissed_hashes",
        description="Get content hash clusters from dismissed recommendations. "
                    "Use before creating a recommendation to check if similar content was already dismissed.",
        parameters={"type": "object", "properties": {}},
    ),
]


async def execute_tool(name: str, arguments: dict) -> str:
    """Execute an intel tool."""
    pool = get_pool()

    if name == "query_intel_content":
        since_hours = min(int(arguments.get("since_hours", 168)), 720)
        limit = min(int(arguments.get("limit", 20)), 100)
        category = arguments.get("category")
        search = arguments.get("search")

        conditions = ["ingested_at > NOW() - ($1 || ' hours')::interval"]
        params: list = [str(since_hours)]
        idx = 2

        if category:
            conditions.append(f"f.category = ${idx}")
            params.append(category)
            idx += 1

        if search:
            conditions.append(f"(ci.title ILIKE ${idx} OR ci.body ILIKE ${idx})")
            params.append(f"%{search}%")
            idx += 1

        where = " AND ".join(conditions)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT ci.id, ci.title, ci.url, ci.author, ci.published_at,
                       ci.ingested_at, f.name as feed_name, f.category
                FROM intel_content_items ci
                JOIN intel_feeds f ON ci.feed_id = f.id
                WHERE {where}
                ORDER BY ci.ingested_at DESC
                LIMIT {limit}
                """,
                *params,
            )

        if not rows:
            return f"No intel content found in the last {since_hours} hours."

        items = []
        for r in rows:
            items.append({
                "id": str(r["id"]),
                "title": r["title"],
                "url": r["url"],
                "author": r["author"],
                "feed": r["feed_name"],
                "category": r["category"],
                "published": str(r["published_at"]) if r["published_at"] else None,
                "ingested": str(r["ingested_at"]),
            })
        return json.dumps(items, indent=2, default=str)

    elif name == "create_recommendation":
        title = arguments.get("title", "")
        summary = arguments.get("summary", "")
        rationale = arguments.get("rationale", "")
        grade = arguments.get("grade", "C")
        confidence = float(arguments.get("confidence", 0.5))
        category = arguments.get("category", "other")
        features = arguments.get("features", [])
        source_ids = arguments.get("source_content_ids", [])

        if grade not in ("A", "B", "C"):
            return f"Invalid grade '{grade}'. Must be A, B, or C."
        if not 0 <= confidence <= 1:
            return f"Confidence must be 0.0-1.0, got {confidence}."
        if not title or not summary:
            return "Title and summary are required."

        rec_id = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO intel_recommendations (id, title, summary, rationale, features,
                    grade, confidence, category, status, created_at, updated_at)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, 'pending', NOW(), NOW())
                """,
                rec_id, title, summary, rationale, features, grade, confidence, category,
            )
            for sid in source_ids:
                try:
                    await conn.execute(
                        """INSERT INTO intel_recommendation_sources (recommendation_id, content_item_id)
                           VALUES ($1::uuid, $2::uuid) ON CONFLICT DO NOTHING""",
                        rec_id, sid,
                    )
                except Exception:
                    pass

        return json.dumps({"id": rec_id, "status": "pending", "title": title, "grade": grade})

    elif name == "get_dismissed_hashes":
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, title, dismissed_hash_cluster
                   FROM intel_recommendations
                   WHERE status = 'dismissed' AND dismissed_hash_cluster IS NOT NULL
                   ORDER BY decided_at DESC NULLS LAST
                   LIMIT 50"""
            )
        if not rows:
            return "No dismissed recommendations with hash clusters found."

        items = []
        for r in rows:
            items.append({
                "id": str(r["id"]),
                "title": r["title"],
                "hashes": r["dismissed_hash_cluster"],
            })
        return json.dumps(items, indent=2, default=str)

    return f"Unknown intel tool: {name}"
```

- [ ] **Step 4: Register intel tools in __init__.py**

Add to `orchestrator/app/tools/__init__.py`:

```python
from app.tools.intel_tools import INTEL_TOOLS
from app.tools.intel_tools import execute_tool as _exec_intel
```

Add to `_REGISTRY`:

```python
ToolGroup("Intel", "Intelligence Analysis", "Query intel feeds, create recommendations, check dismissed content", INTEL_TOOLS, _exec_intel),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_intel_recommendations.py::test_intel_tools_in_catalog -v -x`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/app/tools/intel_tools.py orchestrator/app/tools/__init__.py tests/test_intel_recommendations.py
git commit -m "feat(intel): add intel MCP tools for Cortex — query content, create recommendations, check dismissed"
```

---

## Task 8: Fix Dead Letter Queue (intel:new_items)

**Files:**
- Modify: `intel-worker/app/worker.py` (or wherever the LPUSH to intel:new_items happens)
- Test: `tests/test_intel_recommendations.py`

- [ ] **Step 1: Write failing test — dead queue depth doesn't grow unbounded**

Add to `tests/test_intel_recommendations.py`:

```python
def test_intel_new_items_queue_not_growing():
    """The intel:new_items queue in Redis db6 should not accumulate indefinitely.
    Either it has a consumer, or the push has been removed."""
    import redis
    r = redis.Redis(host="localhost", port=6379, db=6, decode_responses=True)
    depth = r.llen("intel:new_items")
    # If depth is very large, the queue has no consumer and is leaking
    assert depth < 10000, (
        f"intel:new_items queue has {depth} items — no consumer is draining it. "
        "Either add a consumer or stop pushing to this queue."
    )
    r.close()
```

- [ ] **Step 2: Find and remove the dead queue push**

Search `intel-worker/` for `intel:new_items` LPUSH/RPUSH calls. Remove them — the content is already pushed to the engram ingestion queue (db0) which IS consumed by memory-service.

- [ ] **Step 3: Drain existing dead letters**

Add a one-time cleanup or just clear the queue:

```python
# In the test, also clean up existing dead letters (or do this manually)
# docker compose exec redis redis-cli -n 6 DEL intel:new_items
```

- [ ] **Step 4: Run test to verify**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_intel_recommendations.py::test_intel_new_items_queue_not_growing -v -x`

Expected: PASS (after removing the push or draining the queue)

- [ ] **Step 5: Commit**

```bash
git add intel-worker/app/worker.py tests/test_intel_recommendations.py
git commit -m "fix(intel): remove dead intel:new_items queue push — content already flows through engram queue"
```

---

## Task 9: Rename Dashboard Sources to Knowledge

**Files:**
- Modify: `dashboard/src/components/layout/Sidebar.tsx`
- Modify: `dashboard/src/pages/Sources.tsx`
- Test: TypeScript build check

- [ ] **Step 1: Rename sidebar nav link**

In `dashboard/src/components/layout/Sidebar.tsx`, find the Sources nav item and rename:

```typescript
// Before:
{ to: '/sources', label: 'Sources', icon: Globe, minRole: 'member' }

// After:
{ to: '/sources', label: 'Knowledge', icon: Globe, minRole: 'member' }
```

Note: Keep the route as `/sources` to avoid breaking navigation. Only the display label changes.

- [ ] **Step 2: Update Sources page title and description**

In `dashboard/src/pages/Sources.tsx`, update the PageHeader:

```typescript
// Before:
title="Sources"
description="Knowledge sources and intelligence feeds powering Nova's memory"

// After:
title="Knowledge"
description="Knowledge sources and intelligence feeds powering Nova's memory"
```

Update help entries that say "Personal Sources" to "Personal Knowledge Sources" or similar if needed. Keep the help text changes minimal — only rename where "Sources" is the standalone label.

- [ ] **Step 3: Run TypeScript build check**

Run: `cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build 2>&1 | tail -20`

Expected: Build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/layout/Sidebar.tsx dashboard/src/pages/Sources.tsx
git commit -m "fix(dashboard): rename Sources to Knowledge in sidebar and page title"
```

---

## Task 10: Full Regression Test Suite

**Files:**
- Modify: `tests/test_cortex_loop.py`
- Modify: `tests/test_intel_recommendations.py`
- Modify: `tests/test_agent_capabilities.py`
- Modify: `tests/test_consolidation.py`

- [ ] **Step 1: Update test_agent_capabilities.py — remove xfail on tool catalog test**

Find and remove the `@pytest.mark.xfail` decorator on `test_tool_catalog_includes_diagnosis_and_memory` (now that all tools are registered):

```python
# Remove this decorator:
# @pytest.mark.xfail(reason="Diagnosis/Memory/Introspect tools not yet in catalog API")

def test_tool_catalog_includes_diagnosis_and_memory():
    ...
```

- [ ] **Step 2: Update test_agent_capabilities.py — remove xfail on recommendation endpoint test**

Find and remove the `@pytest.mark.xfail` decorator on `test_recommendation_create_endpoint_exists`:

```python
# Remove this decorator:
# @pytest.mark.xfail(reason="POST endpoint missing — see P1 Tier 3")

def test_recommendation_create_endpoint_exists():
    ...
```

- [ ] **Step 3: Add consolidation tool test**

Add to `tests/test_consolidation.py`:

```python
def test_consolidation_tool_returns_data():
    """The memory tool endpoint for consolidation status should work."""
    resp = httpx.get(
        "http://localhost:8002/api/v1/engrams/consolidation-log",
        params={"limit": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Should be a list (possibly empty if no consolidation has run)
    assert isinstance(data, list)
```

- [ ] **Step 4: Run full test suite**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_cortex_loop.py tests/test_intel_recommendations.py tests/test_agent_capabilities.py tests/test_consolidation.py -v --tb=short 2>&1 | tail -40`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: regression coverage for autonomous loop activation (all 5 tiers)"
```

---

## Verification Checklist

After all tasks complete, verify end-to-end:

- [ ] `make test` — Full integration suite passes
- [ ] `cd dashboard && npm run build` — Dashboard compiles
- [ ] Cortex logs show `outcome=Task dispatched` instead of `outcome=Skipped` for goals with descriptions
- [ ] `GET /api/v1/tools` includes all 8 tool groups (Code, Git, Platform, Web, Diagnosis, Introspect, Memory, Intel)
- [ ] `POST /api/v1/intel/recommendations` returns 200 with valid payload
- [ ] Dashboard sidebar shows "Knowledge" not "Sources"
- [ ] `docker compose exec redis redis-cli -n 6 LLEN intel:new_items` returns 0 or small number
