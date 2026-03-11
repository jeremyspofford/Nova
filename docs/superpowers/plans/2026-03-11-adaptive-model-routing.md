# Adaptive Model Routing Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tier-based model routing to the llm-gateway so every LLM call routes to the cheapest, fastest model capable of producing a good result — based on budget tier, task type, provider availability, and learned outcome quality.

**Architecture:** The gateway gains a tier resolver that sits between request intake and provider dispatch. Callers pass optional `tier` + `task_type` hints; if absent, heuristics infer them. Cortex publishes its budget tier to Redis, and the gateway applies it as a ceiling on cortex requests. An effectiveness matrix (outcome scores aggregated hourly by orchestrator) allows the system to learn which models work best for which tasks.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Redis, Pydantic (nova-contracts)

**Spec:** `docs/superpowers/specs/2026-03-11-adaptive-model-routing-design.md`

---

## Progress Tracker

Use this section to track implementation state if the conversation resets.

| Chunk | Status | Notes |
|-------|--------|-------|
| 1: Contracts & Tier Types | pending | |
| 2: Rate Limiter Read-Only Check | pending | |
| 3: Tier Resolver Core | pending | |
| 4: Gateway Router Integration | pending | |
| 5: Budget Publishing (Cortex) | pending | |
| 6: Budget Ceiling (Gateway) | pending | |
| 7: Cortex Caller Tagging | pending | |
| 8: Pipeline Stage Tagging | pending | |
| 9: Outcome Scoring Schema | pending | |
| 10: Effectiveness Matrix | pending | |

---

## File Structure

### New files
| File | Responsibility |
|------|----------------|
| `nova-contracts/nova_contracts/tier.py` | `TaskType` enum, `Tier` literal type |
| `llm-gateway/app/tier_resolver.py` | Heuristic inference, model resolution, effectiveness matrix reads, budget ceiling |
| `orchestrator/app/effectiveness.py` | Hourly aggregation of outcome scores → Redis |
| `orchestrator/app/migrations/022_adaptive_routing.sql` | Add `metadata` + `outcome_score` columns to `usage_events` |

### Modified files
| File | Change |
|------|--------|
| `nova-contracts/nova_contracts/llm.py` | `model` optional, add `tier` + `task_type` fields |
| `nova-contracts/nova_contracts/__init__.py` | Re-export new types |
| `llm-gateway/app/router.py` | Call tier resolver before `get_provider()` |
| `llm-gateway/app/openai_router.py` | Same tier resolution for `/v1/chat/completions` |
| `llm-gateway/app/registry.py` | Add `resolve_model_for_tier()` |
| `llm-gateway/app/config.py` | Default tier preference lists |
| `llm-gateway/app/rate_limiter.py` | Add `check_remaining_quota()` (read-only) |
| `cortex/app/budget.py` | Publish budget tier to Redis |
| `cortex/app/clients.py` | Add `X-Caller: cortex` header to LLM client |
| `cortex/app/cycle.py` | Tag LLM calls with `tier` + `task_type` |
| `orchestrator/app/db.py` | Extend `insert_usage_event()` with `metadata` + `outcome_score` |
| `orchestrator/app/main.py` | Add hourly effectiveness matrix background task |
| `orchestrator/app/pipeline/agents/base.py` | Add `tier` + `task_type` to BaseAgent and `/complete` payload |
| `orchestrator/app/pipeline/executor.py` | Map pipeline stages to tier + task_type, pass to agents |

---

## Chunk 1: Contracts & Tier Types

### Task 1.1: Create tier types module

**Files:**
- Create: `nova-contracts/nova_contracts/tier.py`

- [ ] **Step 1: Create the tier types file**

```python
"""Tier and task-type enums for adaptive model routing.

Note: Named RoutingTaskType (not TaskType) to avoid collision with
nova_contracts.orchestrator.TaskType which is a different enum.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

Tier = Literal["best", "mid", "cheap"]
TIER_ORDER: list[str] = ["best", "mid", "cheap"]


class RoutingTaskType(str, Enum):
    """Task types for model routing and outcome tracking."""
    planning = "planning"
    task_execution = "task_execution"
    goal_work = "goal_work"
    code_review = "code_review"
    guardrail = "guardrail"
    context_retrieval = "context_retrieval"
    decision = "decision"
    reflection = "reflection"
    narration = "narration"
    extraction = "extraction"
    chat = "chat"
```

- [ ] **Step 2: Commit**

```bash
git add nova-contracts/nova_contracts/tier.py
git commit -m "feat: add tier and task type enums for adaptive routing"
```

### Task 1.2: Update CompleteRequest model

**Files:**
- Modify: `nova-contracts/nova_contracts/llm.py:70-77`

- [ ] **Step 1: Make model optional, add tier and task_type fields**

In `CompleteRequest` class (line 70), change `model: str` to `model: str | None = None` and add:

```python
class CompleteRequest(BaseModel):
    model: str | None = None  # None = tier resolver picks the model
    messages: list[Message]
    tools: list[ToolDefinition] = Field(default_factory=list)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    tier: str | None = None       # "best", "mid", "cheap" — advisory
    task_type: str | None = None  # from TaskType enum — for outcome tracking
```

- [ ] **Step 2: Commit**

```bash
git add nova-contracts/nova_contracts/llm.py
git commit -m "feat: make CompleteRequest.model optional, add tier and task_type fields"
```

---

## Chunk 2: Rate Limiter Read-Only Check

### Task 2.1: Add check_remaining_quota()

**Files:**
- Modify: `llm-gateway/app/rate_limiter.py`

- [ ] **Step 1: Add read-only quota check function**

Add after the existing `check_rate_limit()` function (after line 98):

```python
async def check_remaining_quota(model: str) -> tuple[bool, int | None]:
    """Check if a model has remaining quota WITHOUT incrementing the counter.

    Returns (has_quota, remaining_count). For models without quotas, returns (True, None).
    Used by tier resolver to probe availability before committing.

    Uses the same sliding-window key format as check_rate_limit():
    key = f"nova:ratelimit:{prefix}", entries are sorted set members with
    score = timestamp. We clean expired entries and count remaining.
    """
    prefix = _provider_prefix(model)
    if prefix is None or prefix not in PROVIDER_QUOTAS:
        return True, None  # unlimited (Ollama, paid APIs, subscriptions)

    quota = PROVIDER_QUOTAS[prefix]

    try:
        r = await _get_redis()
        key = f"nova:ratelimit:{prefix}"
        now = time.time()
        window_start = now - _WINDOW

        # Clean + count in a pipeline (read-only: no zadd)
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zcard(key)
        results = await pipe.execute()

        current_count = results[1]
        remaining = max(0, quota - current_count)
        return remaining > 0, remaining
    except Exception:
        return True, None  # fail open
```

Note: Uses the same key format (`nova:ratelimit:{prefix}`), `_WINDOW`, `_provider_prefix()`, and `_get_redis()` as the existing `check_rate_limit()`. The only difference: no `zadd` — we don't increment the counter.

- [ ] **Step 2: Commit**

```bash
git add llm-gateway/app/rate_limiter.py
git commit -m "feat: add read-only check_remaining_quota() for tier resolver probing"
```

---

## Chunk 3: Tier Resolver Core

### Task 3.1: Add tier preference defaults to gateway config

**Files:**
- Modify: `llm-gateway/app/config.py`

- [ ] **Step 1: Add default tier preferences to Settings**

Add these fields to the `Settings` class:

```python
    # Tier-based routing defaults
    tier_preferences_best: str = "claude-sonnet-4-6,gpt-4o,claude-max/claude-sonnet-4-6,chatgpt/gpt-4o,gemini/gemini-2.5-pro"
    tier_preferences_mid: str = "groq/llama-3.3-70b-versatile,gemini/gemini-2.5-flash,cerebras/llama3.1-8b,claude-max/claude-haiku-4-5"
    tier_preferences_cheap: str = "groq/llama-3.3-70b-versatile,cerebras/llama3.1-8b,default-ollama,gemini/gemini-2.5-flash"
```

- [ ] **Step 2: Commit**

```bash
git add llm-gateway/app/config.py
git commit -m "feat: add default tier preference lists to gateway config"
```

### Task 3.2: Create the tier resolver module

**Files:**
- Create: `llm-gateway/app/tier_resolver.py`

- [ ] **Step 1: Create tier_resolver.py with full implementation**

```python
"""Adaptive tier-based model resolver.

Resolution chain:
1. Explicit model set → use it directly (bypass tier system)
2. Explicit tier set → resolve via preference lists
3. Neither → infer tier from heuristics, then resolve

Budget ceiling applied for cortex-originated requests.
Effectiveness matrix consulted when sufficient data exists.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .config import settings
from .rate_limiter import check_remaining_quota
from .registry import MODEL_REGISTRY, MODEL_SPECS, _is_ollama_model

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

TIER_ORDER = ["best", "mid", "cheap"]

TIER_CEILING: dict[tuple[str, str], str] = {
    # (requested_tier, budget_tier) → effective_tier
    ("best", "best"): "best",
    ("best", "mid"): "mid",
    ("best", "cheap"): "cheap",
    ("mid", "best"): "mid",
    ("mid", "mid"): "mid",
    ("mid", "cheap"): "cheap",
    ("cheap", "best"): "cheap",
    ("cheap", "mid"): "cheap",
    ("cheap", "cheap"): "cheap",
}

QUALITY_THRESHOLDS = {"best": 0.80, "mid": 0.65, "cheap": 0.50}

# ── In-memory caches ────────────────────────────────────────────────────────

_prefs_cache: dict[str, list[str]] | None = None
_prefs_cache_ts: float = 0.0
_budget_cache: str | None = None
_budget_cache_ts: float = 0.0
_effectiveness_cache: dict | None = None
_effectiveness_cache_ts: float = 0.0
_CACHE_TTL = 5.0  # seconds


# ── Public API ───────────────────────────────────────────────────────────────

async def resolve_model(
    model: str | None,
    tier: str | None,
    task_type: str | None,
    request: Any,
    caller: str | None = None,
) -> str:
    """Full resolution chain — returns a concrete model name.

    Args:
        model: Explicit model from request (bypasses tier system if set).
        tier: Explicit tier hint ("best"/"mid"/"cheap").
        task_type: Task type for effectiveness lookup.
        request: The CompleteRequest (for heuristic signals).
        caller: Value of X-Caller header (e.g. "cortex").

    Returns:
        Resolved model name string.

    Raises:
        ValueError: If no model can be resolved at any tier.
    """
    # Path 1: explicit model — bypass entirely
    if model:
        return model

    # Path 2 or 3: resolve tier
    if not tier:
        tier = infer_tier(request)

    # Budget ceiling for cortex
    if caller == "cortex":
        tier = await _apply_budget_ceiling(tier)
        if tier == "none":
            raise BudgetExhaustedError()

    # Resolve tier → model
    return await _resolve_tier_to_model(tier, task_type, request)


class BudgetExhaustedError(Exception):
    """Raised when cortex budget is exhausted."""
    pass


# ── Heuristic inference ─────────────────────────────────────────────────────

def infer_tier(request: Any) -> str:
    """Infer tier from request signals. Fast, no I/O."""
    best_points = 0
    cheap_points = 0

    # Prompt length (rough token estimate: 4 chars ≈ 1 token)
    total_chars = sum(
        len(m.content) if isinstance(m.content, str) else 100
        for m in (request.messages or [])
    )
    est_tokens = total_chars // 4
    if est_tokens < 500:
        cheap_points += 2
    elif est_tokens > 2000:
        best_points += 2

    # Max tokens
    if request.max_tokens:
        if request.max_tokens < 300:
            cheap_points += 2
        elif request.max_tokens > 2000:
            best_points += 2

    # Tool use
    if request.tools:
        best_points += 2

    # System prompt length
    for m in (request.messages or []):
        if getattr(m, "role", None) == "system":
            content = m.content if isinstance(m.content, str) else ""
            if len(content) < 200:
                cheap_points += 1
            elif len(content) > 1000:
                best_points += 1
            break

    # Temperature
    if request.temperature is not None:
        if request.temperature < 0.2:
            best_points += 1
        elif request.temperature > 0.8:
            cheap_points += 1

    # Code presence
    for m in (request.messages or []):
        content = m.content if isinstance(m.content, str) else ""
        if "```" in content:
            best_points += 2
            break

    score = best_points - cheap_points
    if score <= -2:
        return "cheap"
    if score <= 2:
        return "mid"
    return "best"


# ── Tier → model resolution ─────────────────────────────────────────────────

async def _resolve_tier_to_model(
    tier: str, task_type: str | None, request: Any,
) -> str:
    """Walk preference list for tier, filtered by availability + effectiveness."""
    prefs = await _get_tier_preferences()
    effectiveness = await _get_effectiveness_matrix()

    # Estimate request token count for context window check
    total_chars = sum(
        len(m.content) if isinstance(m.content, str) else 100
        for m in (request.messages or [])
    )
    est_request_tokens = total_chars // 4

    # Try requested tier, then fall back to lower tiers
    tier_idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else 0
    for try_tier in TIER_ORDER[tier_idx:]:
        candidates = prefs.get(try_tier, [])

        # Filter by effectiveness if we have data for this task_type
        if task_type and effectiveness:
            threshold = QUALITY_THRESHOLDS.get(try_tier, 0.5)
            candidates = _filter_by_effectiveness(
                candidates, task_type, effectiveness, threshold,
            )

        for model_id in candidates:
            # Resolve virtual identifiers
            resolved = _resolve_virtual(model_id)
            if resolved is None:
                continue

            # Check provider availability
            if resolved not in MODEL_REGISTRY:
                continue
            provider = MODEL_REGISTRY[resolved]
            if not provider.is_available:
                continue

            # Check rate limit quota (read-only)
            has_quota, _ = await check_remaining_quota(resolved)
            if not has_quota:
                continue

            # Check context window
            spec = MODEL_SPECS.get(resolved, {})
            ctx_window = spec.get("context_window", 128_000)
            if est_request_tokens > ctx_window * 0.9:  # 90% safety margin
                continue

            log.info(
                "Tier resolved: tier=%s task_type=%s → model=%s",
                try_tier, task_type, resolved,
            )
            return resolved

    raise ValueError(
        f"No model available for tier={tier} task_type={task_type}. "
        "All providers exhausted or unavailable."
    )


def _resolve_virtual(model_id: str) -> str | None:
    """Resolve virtual model identifiers to real model names."""
    if model_id == "default-ollama":
        real = settings.default_ollama_model
        # Check if ollama is available via the registry
        if real in MODEL_REGISTRY:
            return real
        return None
    return model_id


def _filter_by_effectiveness(
    candidates: list[str],
    task_type: str,
    effectiveness: dict,
    threshold: float,
) -> list[str]:
    """Filter candidates by effectiveness score for this task_type.

    Only filters if we have sufficient data (n >= 10). Otherwise returns
    candidates unchanged.
    """
    filtered = []
    for model_id in candidates:
        key = f"{model_id}:{task_type}"
        entry = effectiveness.get(key)
        if entry and entry.get("sample_count", 0) >= 10:
            if entry.get("avg_score", 0) < threshold:
                continue  # Skip — model underperforms for this task type
        filtered.append(model_id)

    # If filtering removed everything, return original list (fail open)
    return filtered if filtered else candidates


# ── Budget ceiling ───────────────────────────────────────────────────────────

async def _apply_budget_ceiling(tier: str) -> str:
    """Cap the requested tier based on cortex budget state from Redis."""
    budget_tier = await _get_budget_tier()
    if budget_tier == "none":
        return "none"
    key = (tier, budget_tier)
    return TIER_CEILING.get(key, tier)


async def _get_budget_tier() -> str:
    """Read cortex budget tier from Redis (5s cache)."""
    global _budget_cache, _budget_cache_ts
    now = time.monotonic()
    if _budget_cache is not None and (now - _budget_cache_ts) < _CACHE_TTL:
        return _budget_cache

    try:
        from .registry import _get_redis_config
        value = await _get_redis_config("cortex.budget_tier", "best")
        _budget_cache = value
    except Exception:
        _budget_cache = "best"
    _budget_cache_ts = now
    return _budget_cache


# ── Tier preferences ─────────────────────────────────────────────────────────

async def _get_tier_preferences() -> dict[str, list[str]]:
    """Read tier preference lists from Redis, fallback to config defaults."""
    global _prefs_cache, _prefs_cache_ts
    now = time.monotonic()
    if _prefs_cache is not None and (now - _prefs_cache_ts) < _CACHE_TTL:
        return _prefs_cache

    prefs = _default_preferences()
    try:
        from .registry import _get_redis_config
        raw = await _get_redis_config("llm.tier_preferences", "")
        if raw:
            override = json.loads(raw)
            for tier_name in TIER_ORDER:
                if tier_name in override:
                    prefs[tier_name] = override[tier_name]
    except Exception:
        pass  # use defaults

    _prefs_cache = prefs
    _prefs_cache_ts = now
    return prefs


def _default_preferences() -> dict[str, list[str]]:
    """Parse default preferences from config (comma-separated strings)."""
    return {
        "best": [m.strip() for m in settings.tier_preferences_best.split(",")],
        "mid": [m.strip() for m in settings.tier_preferences_mid.split(",")],
        "cheap": [m.strip() for m in settings.tier_preferences_cheap.split(",")],
    }


# ── Effectiveness matrix ─────────────────────────────────────────────────────

async def _get_effectiveness_matrix() -> dict:
    """Read effectiveness matrix from Redis (5s cache).

    Returns dict of "model:task_type" → {"avg_score": float, "sample_count": int}.
    Empty dict if not available yet (cold start).
    """
    global _effectiveness_cache, _effectiveness_cache_ts
    now = time.monotonic()
    if _effectiveness_cache is not None and (now - _effectiveness_cache_ts) < _CACHE_TTL:
        return _effectiveness_cache

    try:
        from .registry import _get_strategy_redis
        r = await _get_strategy_redis()
        raw = await r.get("nova:cache:model_effectiveness")
        _effectiveness_cache = json.loads(raw) if raw else {}
    except Exception:
        _effectiveness_cache = {}

    _effectiveness_cache_ts = now
    return _effectiveness_cache
```

- [ ] **Step 2: Commit**

```bash
git add llm-gateway/app/tier_resolver.py
git commit -m "feat: add tier resolver with heuristics, preference lists, budget ceiling, effectiveness"
```

### Task 3.3: Add resolve_model_for_tier() to registry

**Files:**
- Modify: `llm-gateway/app/registry.py`

- [ ] **Step 1: Export _is_ollama_model and _get_redis_config**

These are already defined in registry.py. Verify they are not private-only (tier_resolver.py imports them). If `_get_redis_config` is private, either rename it or add a public wrapper. The tier_resolver imports from registry, so these need to be accessible.

Check: `_get_redis_config()` is at ~line 261 and `_is_ollama_model()` is at ~line 307. Both are module-level functions — Python allows cross-module import of underscore-prefixed names. No change needed.

- [ ] **Step 2: Commit** (skip if no changes needed)

---

## Chunk 4: Gateway Router Integration

### Task 4.1: Wire tier resolver into /complete and /stream

**Files:**
- Modify: `llm-gateway/app/router.py`

- [ ] **Step 1: Add tier resolution to complete() handler**

At the top of `router.py`, add import:

```python
from .tier_resolver import resolve_model, BudgetExhaustedError
```

In the `complete()` function (line 39), add tier resolution **before** the `get_provider()` call (before line 52). Also read the `X-Caller` header from the request:

```python
@router.post("/complete", response_model=CompleteResponse)
async def complete(request: CompleteRequest, raw_request: Request) -> CompleteResponse:
    # Resolve model via tier system if not explicitly set
    caller = raw_request.headers.get("x-caller")
    try:
        resolved_model = await resolve_model(
            model=request.model,
            tier=request.tier,
            task_type=request.task_type,
            request=request,
            caller=caller,
        )
        request.model = resolved_model
    except BudgetExhaustedError:
        from datetime import datetime, timezone
        tomorrow = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta
        tomorrow += timedelta(days=1)
        return JSONResponse(
            status_code=429,
            content={
                "error": "budget_exhausted",
                "detail": "Daily budget exceeded",
                "resets_at": tomorrow.isoformat(),
            },
        )
    except ValueError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    # ... rest of existing handler unchanged ...
```

Note: The existing handler signature is `async def complete(request: CompleteRequest)`. Add `raw_request: Request` parameter (FastAPI injects it). Import `from fastapi import Request` and `from fastapi.responses import JSONResponse` at the top.

- [ ] **Step 2: Apply same pattern to stream() handler**

Same changes — add `raw_request: Request`, resolve model before `get_provider()`, handle BudgetExhaustedError.

- [ ] **Step 3: Commit**

```bash
git add llm-gateway/app/router.py
git commit -m "feat: wire tier resolver into /complete and /stream endpoints"
```

### Task 4.2: Wire tier resolver into OpenAI-compat endpoint

**Files:**
- Modify: `llm-gateway/app/openai_router.py`

- [ ] **Step 1: Add tier resolution to chat_completions()**

Same pattern as router.py. The OpenAI-compat request has a `model` field. Before calling `get_provider()` (~line 59), resolve via tier system:

```python
from .tier_resolver import resolve_model, BudgetExhaustedError

# In chat_completions(), before get_provider():
caller = raw_request.headers.get("x-caller")
try:
    resolved_model = await resolve_model(
        model=req.model,
        tier=getattr(req, "tier", None),
        task_type=getattr(req, "task_type", None),
        request=req,
        caller=caller,
    )
    req.model = resolved_model
except BudgetExhaustedError:
    # return 429
except ValueError as e:
    # return 503
```

Note: The OAI request model may not have `tier`/`task_type` fields. Use `getattr` with default `None` — heuristic inference will handle it.

- [ ] **Step 2: Commit**

```bash
git add llm-gateway/app/openai_router.py
git commit -m "feat: wire tier resolver into OpenAI-compat chat completions endpoint"
```

---

## Chunk 5: Budget Publishing (Cortex)

### Task 5.1: Publish budget tier to Redis

**Files:**
- Modify: `cortex/app/budget.py`

- [ ] **Step 1: Add Redis publishing to get_budget_status()**

Add a function that publishes the tier after computing it:

```python
import redis.asyncio as aioredis

from .config import settings

_redis: aioredis.Redis | None = None

async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def publish_budget_tier() -> str:
    """Compute budget tier and publish to Redis for gateway consumption."""
    status = await get_budget_status()
    tier = status["tier"]
    r = await _get_redis()
    await r.set("nova:config:cortex.budget_tier", tier, ex=600)
    return tier
```

Note: Uses `import redis.asyncio as aioredis` — the same pattern as `llm-gateway/app/registry.py` and `llm-gateway/app/rate_limiter.py`.

- [ ] **Step 2: Call publish_budget_tier() in the thinking cycle**

In `cortex/app/cycle.py`, in `run_cycle()` after the budget check (~line 51), add:

```python
from .budget import publish_budget_tier

# After: budget = await get_budget_status()
await publish_budget_tier()
```

- [ ] **Step 3: Commit**

```bash
git add cortex/app/budget.py cortex/app/cycle.py
git commit -m "feat: publish cortex budget tier to Redis for gateway consumption"
```

---

## Chunk 6: Budget Ceiling (Gateway)

Already implemented in `tier_resolver.py` (Chunk 3). The budget ceiling logic is built into `resolve_model()` → `_apply_budget_ceiling()` → `_get_budget_tier()`. No additional work needed.

Mark as: **done when Chunk 3 is complete**.

---

## Chunk 7: Cortex Caller Tagging

### Task 7.1: Add X-Caller header to cortex LLM client

**Files:**
- Modify: `cortex/app/clients.py`

- [ ] **Step 1: Add X-Caller header to the LLM client**

In `init_clients()` (line 25), modify the LLM client creation to include the header:

```python
_llm = httpx.AsyncClient(
    base_url=settings.llm_gateway_url,
    timeout=120.0,
    limits=httpx.Limits(max_connections=10),
    headers={"X-Caller": "cortex"},
)
```

This ensures every request from cortex to llm-gateway carries the identification header.

- [ ] **Step 2: Commit**

```bash
git add cortex/app/clients.py
git commit -m "feat: add X-Caller header to cortex LLM gateway client"
```

### Task 7.2: Tag cortex LLM calls with tier and task_type

**Files:**
- Modify: `cortex/app/cycle.py`

- [ ] **Step 1: Update _plan_action() to include tier and task_type**

In `_plan_action()` (~line 145), update the JSON body:

```python
resp = await llm.post("/complete", json={
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.3,
    "max_tokens": 300,
    "tier": "mid",
    "task_type": "planning",
    "metadata": {"agent_id": "cortex", "task_id": f"cycle-{state.cycle_number}"},
})
```

Note: The tier for `_plan_action` is `"mid"` for routine drive planning. For goal decomposition (user goals), it should be `"best"` — but this distinction can be added later when the serve drive makes its own LLM calls.

- [ ] **Step 2: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat: tag cortex LLM calls with tier and task_type"
```

---

## Chunk 8: Pipeline Stage Tagging

Pipeline agents make LLM calls via `BaseAgent._call_llm_full()` in `orchestrator/app/pipeline/agents/base.py` (line 121). The payload is built at line 136-141 and sent to `/complete`. We need to:
1. Add `tier` and `task_type` fields to the `BaseAgent` constructor
2. Include them in the `/complete` payload
3. Set them per stage when agents are instantiated in the executor

### Task 8.1: Add tier and task_type to BaseAgent

**Files:**
- Modify: `orchestrator/app/pipeline/agents/base.py:99-117` (constructor)
- Modify: `orchestrator/app/pipeline/agents/base.py:136-141` (payload)

- [ ] **Step 1: Add tier and task_type to BaseAgent.__init__()**

In the constructor (line 99), add two new optional parameters:

```python
def __init__(
    self,
    model: str,
    system_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    fallback_models: list[str] | None = None,
    tier: str | None = None,         # NEW
    task_type: str | None = None,    # NEW
) -> None:
    self.model          = model
    self.system_prompt  = system_prompt or self.DEFAULT_SYSTEM
    self.allowed_tools  = allowed_tools
    self.temperature    = temperature
    self.max_tokens     = max_tokens
    self.fallback_models = fallback_models or []
    self.tier           = tier          # NEW
    self.task_type      = task_type     # NEW
    self._usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "llm_calls": 0}
    self._training_log: list[dict] = []
```

- [ ] **Step 2: Include tier and task_type in the /complete payload**

In `_call_llm_full()` (line 136), update the payload dict:

```python
payload = {
    "model":       model,
    "messages":    messages,
    "temperature": self.temperature,
    "max_tokens":  self.max_tokens,
}
if self.tier:
    payload["tier"] = self.tier
if self.task_type:
    payload["task_type"] = self.task_type
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/pipeline/agents/base.py
git commit -m "feat: add tier and task_type support to BaseAgent LLM calls"
```

### Task 8.2: Set tier and task_type per stage in executor

**Files:**
- Modify: `orchestrator/app/pipeline/executor.py`

- [ ] **Step 1: Add stage tier mapping and pass to agent construction**

Add at module level in `executor.py`:

```python
# Pipeline stage → (tier, task_type) defaults
STAGE_TIER_MAP: dict[str, tuple[str, str]] = {
    "context": ("cheap", "context_retrieval"),
    "task": ("best", "task_execution"),
    "guardrail": ("mid", "guardrail"),
    "code_review": ("mid", "code_review"),
    "decision": ("cheap", "decision"),
}
```

Find where agents are instantiated (in `_run_agent()` or wherever the agent class is constructed). Pass `tier` and `task_type` from the mapping based on `agent.role`:

```python
tier, task_type = STAGE_TIER_MAP.get(agent.role, ("mid", "task_execution"))
# Pass to agent constructor:
agent_instance = AgentClass(model=model, tier=tier, task_type=task_type, ...)
```

The exact injection point depends on how agents are instantiated — follow the code from `_run_agent()` to the agent class constructor. The `agent.role` field maps to keys in `STAGE_TIER_MAP`.

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/pipeline/executor.py
git commit -m "feat: assign tier and task_type per pipeline stage"
```

---

## Chunk 9: Outcome Scoring Schema

### Task 9.1: Add migration for metadata and outcome_score

**Files:**
- Create: `orchestrator/app/migrations/022_adaptive_routing.sql`

- [ ] **Step 1: Create migration file**

```sql
-- 022: Add adaptive routing columns to usage_events
-- metadata: stores task_type, caller identity, pipeline stage context
-- outcome_score: 0.0-1.0 quality score for model effectiveness tracking

ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS outcome_score REAL;

-- Index for effectiveness matrix aggregation query
CREATE INDEX IF NOT EXISTS idx_usage_events_outcome
    ON usage_events (model, outcome_score)
    WHERE outcome_score IS NOT NULL;
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/migrations/022_adaptive_routing.sql
git commit -m "feat: add metadata and outcome_score columns to usage_events"
```

### Task 9.2: Extend insert_usage_event() with new columns

**Files:**
- Modify: `orchestrator/app/db.py:272-299`

- [ ] **Step 1: Add metadata and outcome_score parameters**

Update the function signature and INSERT statement:

```python
async def insert_usage_event(
    api_key_id: UUID | None,
    agent_id: UUID | None,
    session_id: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    duration_ms: int | None,
    metadata: dict | None = None,       # NEW
    outcome_score: float | None = None,  # NEW
) -> None:
```

Update the SQL to include the new columns:

```sql
INSERT INTO usage_events
    (api_key_id, agent_id, session_id, model, input_tokens, output_tokens,
     cost_usd, duration_ms, metadata, outcome_score)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
```

Add the new parameters to the argument list, serializing metadata to JSON:

```python
import json as json_mod
# ...
json_mod.dumps(metadata or {}), outcome_score
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/db.py
git commit -m "feat: extend insert_usage_event() with metadata and outcome_score"
```

---

## Chunk 10: Effectiveness Matrix

### Task 10.1: Create effectiveness matrix computation module

**Files:**
- Create: `orchestrator/app/effectiveness.py`

- [ ] **Step 1: Create the module**

```python
"""Effectiveness matrix — hourly aggregation of model outcome scores.

Computes avg outcome_score per (model, task_type) from usage_events
and pushes the result to Redis for the llm-gateway tier resolver.
"""
from __future__ import annotations

import json
import logging

from .db import get_pool
from .redis_client import get_redis

log = logging.getLogger(__name__)

REDIS_KEY = "nova:cache:model_effectiveness"
REDIS_TTL = 3600  # 1 hour


async def compute_and_publish() -> int:
    """Aggregate outcome scores and publish to Redis.

    Returns the number of (model, task_type) entries in the matrix.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT model,
                   COALESCE(metadata->>'task_type', 'unknown') AS task_type,
                   AVG(outcome_score) AS avg_score,
                   COUNT(*) AS sample_count
            FROM usage_events
            WHERE outcome_score IS NOT NULL
              AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY 1, 2
        """)

    matrix = {}
    for row in rows:
        key = f"{row['model']}:{row['task_type']}"
        matrix[key] = {
            "avg_score": round(float(row["avg_score"]), 3),
            "sample_count": int(row["sample_count"]),
        }

    redis = get_redis()
    if redis:
        await redis.set(REDIS_KEY, json.dumps(matrix), ex=REDIS_TTL)
        log.info("Published effectiveness matrix: %d entries", len(matrix))
    else:
        log.warning("Redis unavailable — effectiveness matrix not published")

    return len(matrix)


async def effectiveness_loop() -> None:
    """Background loop — recompute every hour."""
    import asyncio
    while True:
        try:
            await compute_and_publish()
        except Exception:
            log.exception("Effectiveness matrix computation failed")
        await asyncio.sleep(3600)
```

Note: Check how `get_pool()` and `get_redis()` are imported in the orchestrator. Follow the existing patterns from `main.py` and other modules. The `get_redis()` function may be called differently (e.g., `redis_pool` or `get_redis_client()`). Adjust imports accordingly.

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/effectiveness.py
git commit -m "feat: add effectiveness matrix hourly aggregation for adaptive routing"
```

### Task 10.2: Start effectiveness loop in orchestrator lifespan

**Files:**
- Modify: `orchestrator/app/main.py`

- [ ] **Step 1: Add effectiveness loop to lifespan background tasks**

In the lifespan function, after the existing background task starts (~line 113), add:

```python
from .effectiveness import effectiveness_loop

# In lifespan(), after other background tasks:
effectiveness_task = asyncio.create_task(effectiveness_loop())
```

In the shutdown section, cancel it:

```python
effectiveness_task.cancel()
```

Follow the exact same pattern used for `queue_worker()` and `reaper_loop()` background tasks.

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/main.py
git commit -m "feat: start effectiveness matrix background loop in orchestrator"
```

---

## Integration Testing

After all chunks are complete:

- [ ] **Test 1: Tier resolution with explicit model** — Send `POST /complete` with `model=groq/llama-3.3-70b-versatile` → should use that model exactly (bypass tier system)
- [ ] **Test 2: Tier resolution with explicit tier** — Send `POST /complete` with `tier=cheap` (no model) → should resolve to first available model in cheap preference list
- [ ] **Test 3: Heuristic inference** — Send `POST /complete` with neither model nor tier, short prompt, low max_tokens → should infer cheap tier
- [ ] **Test 4: Budget ceiling** — Set `nova:config:cortex.budget_tier` to `cheap` in Redis, send request with `X-Caller: cortex` and `tier=best` → should cap to cheap
- [ ] **Test 5: Budget exhaustion** — Set budget tier to `none`, send cortex request → should get 429
- [ ] **Test 6: Backwards compatibility** — Existing callers that pass `model` should work unchanged
- [ ] **Test 7: Service health** — All services start and pass health checks after changes

Run: `make test-quick` to verify health endpoints, then `make test` for full integration suite.

---

## Post-Implementation

- [ ] Update spec progress tracker (top of this file)
- [ ] Update `docs/superpowers/specs/2026-03-11-adaptive-model-routing-design.md` success criteria checkboxes
- [ ] Commit final state
