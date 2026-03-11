# Adaptive Model Routing

> Runtime model selection based on budget tier, task type, provider availability, and learned outcome quality. The gateway becomes Nova's intelligent dispatch layer — routing every LLM call to the cheapest, fastest model capable of producing a good result.

---

## Context

Nova's llm-gateway currently routes by **strategy** (local-first, cloud-first, etc.) — which determines Ollama vs cloud fallback ordering. Cortex has a **budget tier** system (best/mid/cheap/none) that affects drive scoring but doesn't influence model selection. The orchestrator pipeline uses one model for all five stages.

The gap: no mechanism translates "this is a cheap reflection task on a tight budget" into "use Groq Llama at 800 tok/s for $0" instead of "use Claude Sonnet at 80 tok/s for $0.01." Every call pays the same price and waits the same latency regardless of task complexity.

---

## 1. Tier System & Model Preference Lists

The gateway gains **model tiers** — ordered preference lists resolved at request time by availability, quota, and context window fit.

### Tiers

| Tier | Use case | Quality threshold | Priority signal |
|------|----------|-------------------|-----------------|
| `best` | User goals, complex code generation, critical decisions | Highest available quality | Quality over cost/speed |
| `mid` | Planning, evaluation, guardrails, structured extraction | Competent but not premium | Balance of quality/speed/cost |
| `cheap` | Reflection, narration, simple classification, formatting | Adequate for straightforward tasks | Speed and cost over quality |
| `none` | Budget exhausted | No LLM calls | N/A — HTTP health checks only |

### Default Preference Lists

Ordered by: quality (best tier), speed×cost (mid/cheap tiers). Each list is a fallback chain — first available model wins.

**best:**
```
claude-sonnet-4-6 → gpt-4o → claude-max/claude-sonnet-4-6 → chatgpt/gpt-4o → gemini/gemini-2.5-pro
```

**mid:**
```
groq/llama-3.3-70b-versatile → gemini/gemini-2.5-flash → cerebras/llama-3.3-70b → claude-haiku
```

**cheap:**
```
cerebras/llama-3.3-70b → groq/llama-3.3-70b-versatile → local ollama → gemini/gemini-2.0-flash-lite
```

Rationale for mid/cheap ordering: Groq (800 tok/s) and Cerebras (2000 tok/s) are free and fast. For tasks where quality isn't the bottleneck, speed matters more — a cortex cycle making 3 cheap calls at Groq speed (0.3s each) vs Claude speed (3-5s each) is the difference between 1s and 15s of latency.

### Resolution Logic

New function `resolve_model_for_tier()` in `registry.py`:

1. Walk the preference list for the requested tier
2. For each candidate model:
   - Is the provider available? (`is_available` property)
   - Does it have remaining quota? (rate limiter check)
   - Does the request fit its context window? (estimate request tokens vs `MODEL_SPECS[model].context_window`)
3. Return the first model passing all checks
4. If no model available in the requested tier, fall back to the next tier down (best → mid → cheap)
5. If nothing available at any tier, return error

### Configuration

Preference lists stored in Redis (`nova:config:llm.tier_preferences`) as JSON, with the defaults above as fallback. Editable at runtime via platform_config — no restart required.

```json
{
  "best": ["claude-sonnet-4-6", "gpt-4o", "claude-max/claude-sonnet-4-6"],
  "mid": ["groq/llama-3.3-70b-versatile", "gemini/gemini-2.5-flash", "cerebras/llama-3.3-70b"],
  "cheap": ["cerebras/llama-3.3-70b", "groq/llama-3.3-70b-versatile", "local-ollama"]
}
```

### Backwards Compatibility

If `model` is explicitly set in the request, the tier system is bypassed entirely. Existing callers continue to work unchanged.

---

## 2. Request-Level Tier Hints & Heuristic Inference

### New Request Field

`CompleteRequest` and `StreamRequest` in `nova-contracts` gain optional fields:

```python
tier: str | None = None       # "best", "mid", "cheap"
task_type: str | None = None  # "planning", "code_review", "reflection", etc.
```

### Three Resolution Paths (in order of precedence)

1. **Explicit `model`** → use it directly, bypass tier system
2. **Explicit `tier`** → resolve via preference lists (Section 1)
3. **Neither set** → infer tier from heuristics, then resolve

### Heuristic Inference

Lightweight, no LLM call — runs in microseconds. Each signal contributes points:

| Signal | Condition | Points toward `cheap` | Points toward `best` |
|--------|-----------|----------------------|---------------------|
| Prompt length | Total tokens across all messages | < 500 tokens: +2 | > 2000 tokens: +2 |
| Max tokens | `max_tokens` field | < 300: +2 | > 2000: +2 |
| Tool use | `tools` field present and non-empty | — | +2 |
| System prompt | Length of system message | < 200 chars: +1 | > 1000 chars: +1 |
| Temperature | `temperature` field | > 0.8: +1 | < 0.2: +1 |
| Code presence | Code fences in messages | — | +2 |

Scoring: sum `best` points minus `cheap` points. Map to tier:

```
score <= -2  → cheap
score <= 2   → mid
score > 2    → best
```

This is the **bootstrap layer** — it exists because the system needs to route before it has outcome data. It gets less important as the learning layer (Section 3) accumulates experience.

### Where This Lives

New module: `llm-gateway/app/tier_resolver.py`

```python
def resolve_tier(request) -> str:
    """Infer tier from request heuristics. Returns 'best'/'mid'/'cheap'."""

def resolve_model(model: str | None, tier: str | None, request) -> str:
    """Full resolution chain: explicit model → explicit tier → heuristic → preference list."""
```

Called from `router.py` before `get_provider()`.

---

## 3. Outcome-Based Learning

Every LLM call already logs to `usage_events` with model, tokens, cost, and metadata. The missing piece is **outcome quality** — did this call produce a good result?

### Outcome Scoring

New nullable column on `usage_events`:

```sql
ALTER TABLE usage_events ADD COLUMN outcome_score REAL;  -- 0.0–1.0, NULL = not yet scored
```

Scoring sources:

| Source | Signal | Score |
|--------|--------|-------|
| Pipeline guardrail | Pass | 0.9 |
| Pipeline guardrail | Fail/rejection | 0.2 |
| Pipeline code review | Accepted | 0.85 |
| Pipeline code review | Requested changes | 0.5 |
| Pipeline task | Completed status | 0.8 for all models in the task |
| Pipeline task | Failed status | 0.3 for the failing stage's model |
| Cortex REFLECT | Outcome evaluation score | Direct (0.0–1.0) |
| User chat | Regeneration | 0.3 (implicit negative) |
| User chat | Continued without correction | 0.7 (implicit positive) |

### Effectiveness Matrix

Aggregated from `usage_events`, cached in Redis, refreshed hourly:

```sql
SELECT model,
       COALESCE(metadata->>'task_type', 'unknown') AS task_type,
       AVG(outcome_score) AS avg_score,
       COUNT(*) AS sample_count
FROM usage_events
WHERE outcome_score IS NOT NULL
  AND created_at > NOW() - INTERVAL '30 days'
GROUP BY 1, 2
```

Redis key: `nova:cache:model_effectiveness` (JSON, TTL 1 hour)

### How It Influences Routing

When resolving a model for a tier + task_type:

1. If the effectiveness matrix has data for this task_type (sample_count >= 10):
   - Filter the tier's preference list to models with `avg_score >= quality_threshold`
   - Quality thresholds: best ≥ 0.80, mid ≥ 0.65, cheap ≥ 0.50
   - Among qualifying models, prefer the cheapest/fastest (preserving preference list order)
2. If insufficient data: fall back to the static preference list (Section 1)

This means the system starts with sensible defaults and gradually learns. A model that consistently fails code review tasks gets filtered out of `mid` and `best` tiers for `code_review` task_type, without anyone manually updating config.

### Self-Improvement Integration

Cortex's **improve** drive can analyze the effectiveness matrix:
- Detect models underperforming for specific task types
- Adjust tier preference lists via platform_config
- Journal the change with reasoning

This is future work (improve drive is currently a stub) but the data infrastructure supports it from day one.

---

## 4. Budget-Aware Tier Capping

Cortex's budget state automatically constrains model selection for autonomous operations.

### Mechanism

Cortex publishes its budget tier to Redis after each budget check:

```
Key:   nova:config:cortex.budget_tier
Value: "best" | "mid" | "cheap" | "none"
TTL:   600s (refreshed every cortex cycle)
```

The gateway reads this (5s cache) and applies it as a **ceiling** on cortex-originated requests:

| Requested tier | budget=best | budget=mid | budget=cheap | budget=none |
|---------------|-------------|------------|-------------|-------------|
| `best` | best | mid | cheap | **reject** |
| `mid` | mid | mid | cheap | **reject** |
| `cheap` | cheap | cheap | cheap | **reject** |

### Caller Identification

The gateway identifies cortex by API key (`sk-nova-cortex-internal`). Budget capping applies **only** to cortex requests. User chat and other callers are uncapped — autonomous background spending shouldn't degrade the human's experience.

### Budget Exhaustion

When tier = `none`, the gateway returns:

```json
{"error": "budget_exhausted", "detail": "Daily budget exceeded", "resets_at": "2026-03-12T00:00:00Z"}
```

HTTP status: 429.

### Future: Per-Tenant Budgets

When Nova becomes multi-tenant, each tenant gets a budget tier in Redis:

```
nova:config:tenant:{tenant_id}.budget_tier
```

The gateway reads by tenant ID from auth context. Same ceiling logic, different key.

---

## 5. Integration Points

### Cortex

Every cortex LLM call includes `tier` and `task_type`:

| Phase | tier | task_type | Rationale |
|-------|------|-----------|-----------|
| PLAN (goal decomposition) | `best` | `planning` | High-stakes — wrong plan wastes budget |
| PLAN (drive action planning) | `mid` | `planning` | Routine cycle, not user-facing |
| ACT (pipeline dispatch) | `best` | `goal_work` | User goals deserve top models |
| REFLECT (outcome eval) | `cheap` | `reflection` | Summarization, pattern extraction |
| Journal narration | `cheap` | `narration` | Simple text formatting |

Budget ceiling (Section 4) applies on top.

### Orchestrator Pipeline

Default tier per stage (configurable via `platform_config`):

| Stage | tier | task_type |
|-------|------|-----------|
| Context Agent | `cheap` | `context_retrieval` |
| Task Agent | `best` | `task_execution` |
| Guardrail Agent | `mid` | `guardrail` |
| Code Review Agent | `mid` | `code_review` |
| Decision Agent | `cheap` | `decision` |

### Chat API (user conversations)

- No `tier` set — heuristic inference applies
- No budget ceiling
- `task_type`: `"chat"`

### Memory Service (engram decomposition)

Currently hardcoded to `settings.engram_decomposition_model`. Can migrate to `tier: "cheap"`, `task_type: "extraction"`. Low priority.

---

## 6. Data Flow

```
Request arrives at gateway (/complete or /stream)
│
├─ model explicitly set? ──yes──► use that model (existing behavior)
│
├─ tier explicitly set? ──yes──┐
│                              │
├─ neither? ► infer tier ──────┤
│   from heuristics            │
│                              ▼
│                     Is caller cortex?
│                     ├─ yes ► apply budget ceiling (Section 4)
│                     ├─ no  ► use tier as-is
│                     ▼
│              Has outcome data for this task_type?
│              ├─ yes (n≥10) ► filter preference list by effectiveness
│              ├─ no         ► use static preference list
│              ▼
│       Walk filtered preference list:
│         - provider available?
│         - quota remaining?
│         - context window fits?
│         ► return first passing model
│
│       No model at this tier?
│         ► fall back to next tier down
│         ► still nothing? return error
```

---

## 7. New Files & Changes

### New files
| File | Purpose |
|------|---------|
| `llm-gateway/app/tier_resolver.py` | Tier inference, model resolution, effectiveness matrix reads |
| `nova-contracts/nova_contracts/tier.py` | Tier enum, request field additions |

### Modified files
| File | Change |
|------|--------|
| `llm-gateway/app/router.py` | Call `resolve_model()` before `get_provider()` |
| `llm-gateway/app/registry.py` | Add `resolve_model_for_tier()`, context window check |
| `llm-gateway/app/config.py` | Default tier preference lists |
| `nova-contracts/nova_contracts/llm.py` | Add `tier` and `task_type` to request models |
| `cortex/app/cycle.py` | Tag LLM calls with tier + task_type |
| `cortex/app/budget.py` | Publish budget tier to Redis |
| `orchestrator/app/pipeline/executor.py` | Tag pipeline stage calls with tier + task_type |
| `orchestrator/app/migrations/NNN_outcome_score.sql` | Add `outcome_score` column to `usage_events` |

### No changes needed
| File | Why |
|------|-----|
| `llm-gateway/app/providers/*` | Providers don't know about tiers — they receive a resolved model name |
| `llm-gateway/app/rate_limiter.py` | Already queried by tier resolver, no interface change |
| `llm-gateway/app/discovery.py` | Model discovery is orthogonal to tier routing |
| `dashboard/` | No UI changes in this spec (dashboard settings for tier config is future work) |

---

## 8. Future Work (Out of Scope)

- **Adaptive pipeline depth** — use task complexity signal to skip pipeline stages for trivial tasks
- **Dashboard UI for tier configuration** — edit preference lists, view effectiveness matrix, monitor routing decisions
- **Per-tenant budgets** — extend budget ceiling to multi-tenant (mechanism described in Section 4)
- **Cortex improve drive** — automated preference list tuning based on effectiveness matrix analysis
- **Engram decomposition migration** — move from hardcoded model to tier-based routing
- **Cost-per-token dynamic ranking** — replace static preference lists with real-time cost optimization using LiteLLM pricing data

---

## Success Criteria

- [ ] Gateway resolves tier → model using preference lists filtered by availability, quota, and context window
- [ ] Requests with explicit `model` bypass tier system (backwards compatible)
- [ ] Cortex LLM calls include tier + task_type; budget ceiling is enforced
- [ ] Pipeline stages route through tier system with per-stage defaults
- [ ] Heuristic inference produces reasonable tiers for untagged requests
- [ ] `outcome_score` column exists on `usage_events`; pipeline and cortex write scores
- [ ] Effectiveness matrix is computed hourly and cached in Redis
- [ ] When outcome data is sufficient, routing prefers models with higher effectiveness for the task type
- [ ] Budget exhaustion returns 429 with reset time; cortex handles gracefully
- [ ] No latency regression — tier resolution adds < 5ms to request path
