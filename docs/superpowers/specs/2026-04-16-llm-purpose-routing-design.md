# LLM Purpose-Based Routing + Cloud Fallback + Privacy Controls — Design Spec

**Date:** 2026-04-16
**Status:** Draft — pending review

---

## Goal

Make Nova's LLM calls 5-10× faster on average by routing different purposes to appropriately-sized models, while unlocking optional cloud offload for quality-sensitive tasks that benefit from larger models — all under user-configurable privacy controls.

Three things land together:

1. **Per-purpose model routing.** `chat`/`plan` go to qwen3.5:9b, `triage`/`classify` go to llama3.2:3b. Small fast models handle high-frequency cheap work; big models reserved for user-visible quality.
2. **Cloud fallback option.** Anthropic (Haiku/Sonnet/Opus), OpenAI, and OpenRouter available as providers. Per-purpose opt-in — never forced.
3. **Privacy enforcement + cost visibility.** Hard gate preventing cloud routing for purposes marked local-only. Each cloud call's cost logged to the Run; Settings shows monthly spend.

---

## User Stories

### Story 1 — fast chat feels fast
Jeremy types "what's on my task list?" → llama3.2:3b (Phase 1 tool detection) decides it needs `nova.query_activity` → tool runs → qwen3.5:9b (Phase 2) synthesizes reply. The whole thing takes ~4 seconds instead of the current ~15.

### Story 2 — cloud-assisted planning
A complex goal-trigger fires: "design a deployment workflow for a FastAPI app with Postgres." The `plan` purpose is configured with `allow_cloud=true` and a fallback chain `[claude-sonnet, qwen3.5:9b]`. Local 9B is tried first (takes 20s, produces a mediocre plan); if the planner returns a low-confidence result, a follow-up tries Claude Sonnet for ~2s and produces a sharper plan. Run records show both calls; the cloud call shows `$0.042` in activity.

### Story 3 — private-only configuration
Jeremy flips the "Allow cloud?" checkbox off for all purposes in Settings. Every LLM call now strictly uses local providers; the cloud providers are invisible to the routing decisions. Even if his key for Anthropic is still set, nothing sends data there. Settings shows "Cloud spend this month: $0.00" with "privacy mode: local only" badge.

### Story 4 — cost awareness
After a week of goal-trigger runs that occasionally hit Claude, Jeremy opens Settings. The LLM Policies panel shows a "This month" widget: "$1.82 across 43 cloud calls (38 Haiku, 5 Sonnet, 0 Opus)." He spots that his daily-summary is burning Sonnet unnecessarily and switches it to Haiku — same quality for that size of digest.

### Story 5 — provider failure fallback
Claude API is down. A `plan` request fires. Policy chain: `[claude-sonnet, qwen3.5:9b]`. Primary errors → fallback to local 9B → response still arrives, just ~20s slower. Run record flags the failed attempt on Sonnet.

---

## Architecture

### New DB table: `llm_purpose_policies`

One row per purpose. Runtime-editable via Settings UI.

```sql
CREATE TABLE llm_purpose_policies (
    purpose              VARCHAR PRIMARY KEY,        -- e.g. "chat", "triage"
    preferred_provider_id VARCHAR NOT NULL REFERENCES llm_provider_profiles(id),
    allow_cloud          BOOLEAN NOT NULL DEFAULT false,
    fallback_chain       JSON NOT NULL DEFAULT '[]', -- ordered list of provider_ids
    description          VARCHAR,                    -- human-readable hint for Settings UI
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Seeded defaults** (local-first, cloud opt-in; all cloud starts OFF at install):

| purpose | preferred | allow_cloud | fallback_chain |
|---|---|---|---|
| `chat` | `ollama-local` (qwen3.5:9b) | `false` | `["ollama-local-fallback"]` |
| `classify` | `ollama-local-fallback` (llama3.2:3b) | `false` | `["ollama-local"]` |
| `triage` | `ollama-local-fallback` | `false` | `["ollama-local"]` |
| `plan` | `ollama-local` | `false` | `["ollama-local-fallback"]` |
| `summarize` | `ollama-local-fallback` | `false` | `["ollama-local"]` |
| `summarize_daily` | `ollama-local` | `false` | `["ollama-local-fallback"]` |
| `code_generate` | `ollama-local` | `false` | `["ollama-local-fallback"]` |

**All seeded rows have `allow_cloud=false` at install.** User stories 2 and 4 and the Settings UI mockup below describe a *user-edited* state after enabling cloud for specific purposes — they are examples of end-user behavior, not seed values.

**Valid purposes (code-enumerated, enforced at policy PATCH):**

```python
VALID_PURPOSES = frozenset({
    "chat", "classify", "triage", "plan",
    "summarize", "summarize_daily", "code_generate",
})
```

A `PATCH /llm/policies/{purpose}` against an unknown purpose returns 404. This keeps the table bounded and prevents runaway policy fragmentation when modules invent purpose names.

**Prompt/output retention in Run records:** v1 stores prompts and outputs unredacted in `runs.input` / `runs.output` (existing behavior). Data-retention / redaction policy is deferred to a follow-up spec.

Migration `0007_llm_purpose_policies.py`.

### Extensions to `llm_provider_profiles`

Existing columns stay. Add:

```sql
ALTER TABLE llm_provider_profiles
  ADD COLUMN cost_per_million_input_tokens_usd NUMERIC(10, 4),   -- null for local
  ADD COLUMN cost_per_million_output_tokens_usd NUMERIC(10, 4);  -- null for local
```

Migration `0008_llm_provider_cost_fields.py`.

### New cloud providers (seeded if env keys present)

`seed_llm_providers` extended to conditionally seed cloud rows when the corresponding API key env var is set.

**Precise seed table** (all rows share `provider_type="cloud"`, `supports_tools=true`, `supports_streaming=true`, `privacy_class="cloud"`, `cost_class="medium"` except opus=`high`, `latency_class="low"`):

| id | endpoint_ref | model_ref | input $/1M | output $/1M | env key |
|---|---|---|---|---|---|
| `anthropic-claude-haiku` | `https://api.anthropic.com/v1/` | `claude-haiku-4-5` | 0.2500 | 1.2500 | `ANTHROPIC_API_KEY` |
| `anthropic-claude-sonnet` | `https://api.anthropic.com/v1/` | `claude-sonnet-4-6` | 3.0000 | 15.0000 | `ANTHROPIC_API_KEY` |
| `anthropic-claude-opus` | `https://api.anthropic.com/v1/` | `claude-opus-4-7` | 15.0000 | 75.0000 | `ANTHROPIC_API_KEY` |
| `openai-gpt-4o` | `https://api.openai.com/v1` | `gpt-4o` | 5.0000 | 15.0000 | `OPENAI_API_KEY` |
| `openai-gpt-4o-mini` | `https://api.openai.com/v1` | `gpt-4o-mini` | 0.1500 | 0.6000 | `OPENAI_API_KEY` |
| `openrouter-auto` | `https://openrouter.ai/api/v1` | `openrouter/auto` | null | null | `OPENROUTER_API_KEY` |

OpenRouter has null rate fields — cost is taken from the response's `usage.cost` field per call (always accurate across model choice).

**Lifecycle (insert-only seed, never delete):**

- On startup, for each row above, if the env key is set AND the row doesn't exist, INSERT it with `enabled=true`.
- On startup, for each row above, if the env key is NOT set AND the row already exists, UPDATE `enabled=false` (disable, don't delete). Existing Runs and policies that reference the provider stay intact.
- On startup, for each row, if the env key IS set and the row exists, UPDATE `enabled=true` (re-enable if previously disabled).
- Never DELETE rows from seed — preserves Run FK integrity and policy references.
- Policy save validates that the referenced provider row exists AND is enabled. Attempt to save a policy pointing at a disabled provider → 422.

**Disabled-provider runtime behavior:** `_select_candidates` only returns enabled providers. A policy pointing at a disabled provider silently falls through to the first enabled fallback. If the entire chain is disabled, `NoMatchingProvidersError`.

### Extensions to `runs` table

```sql
ALTER TABLE runs
  ADD COLUMN llm_provider_id VARCHAR REFERENCES llm_provider_profiles(id),
  ADD COLUMN llm_input_tokens INTEGER,
  ADD COLUMN llm_output_tokens INTEGER,
  ADD COLUMN llm_cost_usd NUMERIC(10, 6);  -- null for local, populated for cloud
```

Migration `0009_run_llm_cost_fields.py`.

Only populated for LLM-driven runs. Tool-only runs (e.g., `debug.echo`) leave these null.

### Routing pipeline

**Key decision: refactor `route()` in place.** The existing `route(db, purpose, messages, privacy_preference, _caller)` signature stays. Internals change to consult policies. The `privacy_preference` parameter becomes a per-call override: when explicit, it takes precedence over the policy's `allow_cloud`; when omitted (new default `None`), the policy decides. No new `route_by_policy` function — that avoids forcing ~8 call sites to change import shape.

New signature:

```python
def route(
    db: Session,
    purpose: str,
    messages: list[dict],
    privacy_preference: str | None = None,  # None → use policy; else override
    _caller=None,
) -> LLMResult:
```

Algorithm:

1. Fetch policy row for `purpose`. If missing, synthesize a default policy: `preferred_provider_id="ollama-local"`, `allow_cloud=False`, `fallback_chain=["ollama-local-fallback"]`. Log a warning (unknown-purpose fallback).
2. Determine `allow_cloud`:
   - If `privacy_preference == "local_required"` → `allow_cloud = False` (override).
   - If `privacy_preference == "cloud_allowed"` → `allow_cloud = True` (override).
   - If `privacy_preference is None` or `"local_preferred"` → `allow_cloud = policy.allow_cloud`.
3. Build candidate list: `[preferred_provider_id] + fallback_chain`, deduplicated, preserving order.
4. Resolve each id to a `LLMProviderProfile` row; drop ids that don't resolve OR resolve to a disabled provider.
5. **Privacy gate:** if `allow_cloud == False`, drop any provider where `provider_type == "cloud"`.
6. If the resulting list is empty, raise `NoMatchingProvidersError("purpose={purpose} privacy_gate=eliminated_all")`.
7. Try each candidate in order. On exception, try next; record a failed Run for each attempt.
8. Return `LLMResult` (see shape below).

Same three changes for `route_with_tools()`. `route_streaming()` follows steps 1-6 identically but uses only the first surviving candidate (no mid-stream fallback), matching today's behavior.

### `LLMResult` shape

```python
@dataclass
class TokenUsage:
    prompt: int | None = None       # None when the engine didn't report usage
    completion: int | None = None

@dataclass
class LLMResult:
    provider_id: str
    model_ref: str
    output: str
    usage: TokenUsage                # empty tokens if local/unreported
    cost_usd: float | None = None    # None for local or when usage is missing
```

`route_with_tools()` returns a `ToolCallResult` that extends the same `provider_id` / `usage` / `cost_usd` fields, with a `content` OR `tool_calls` payload.

### Streaming cost story (v1)

`route_streaming()` does NOT accumulate token usage; cost stays null on the Run for streamed calls. Rationale: the OpenAI streaming protocol doesn't emit `usage` in most delta chunks; only the final chunk of certain providers includes it, and support is inconsistent. v1 accepts null-cost on streamed calls and documents this in the Run audit trail. v2 can add a final-chunk usage extractor when more providers support it reliably.

**Practical impact:** Phase 2 streaming (user-visible chat reply) is uncosted in v1. Phase 1 non-streaming tool-call resolution IS costed. This captures 80%+ of cloud cost already (tool-call Phase 1 is where expensive reasoning usually happens).

### Cost accounting

Per-provider rates stored in `llm_provider_profiles.cost_per_million_*_tokens_usd`. Cost computed at response-time from the OpenAI-compat `response.usage` object — `prompt_tokens` and `completion_tokens` are standard OpenAI field names and all three targets (Anthropic OpenAI-compat, OpenAI, OpenRouter) emit them via the OpenAI client library's `response.usage` attribute.

```python
def _compute_cost(provider, usage_obj, openrouter_cost: float | None = None) -> tuple[TokenUsage, float | None]:
    usage = TokenUsage(
        prompt=getattr(usage_obj, "prompt_tokens", None) if usage_obj else None,
        completion=getattr(usage_obj, "completion_tokens", None) if usage_obj else None,
    )
    # OpenRouter returns its own cost — use verbatim, skip rate-table math.
    if openrouter_cost is not None:
        return usage, openrouter_cost
    # Local provider OR missing rate OR missing usage → null cost.
    if (provider.provider_type != "cloud"
        or provider.cost_per_million_input_tokens_usd is None
        or usage.prompt is None
        or usage.completion is None):
        return usage, None
    cost = (
        usage.prompt * float(provider.cost_per_million_input_tokens_usd) / 1_000_000
        + usage.completion * float(provider.cost_per_million_output_tokens_usd) / 1_000_000
    )
    return usage, cost
```

**Applied to all three `_call_provider_*_real` functions:**

- **`_call_provider_real(provider, messages)`** — synchronous, returns `LLMResult`. After `response = client.chat.completions.create(...)`, compute `usage, cost = _compute_cost(provider, response.usage, openrouter_cost=getattr(response, "cost", None))`. Return `LLMResult(..., usage=usage, cost_usd=cost)`.
- **`_call_provider_with_tools_real(provider, messages, tools)`** — synchronous, returns `ToolCallResult`. Same extraction pattern. Usage and cost attributed regardless of whether the response is text or tool_calls.
- **`_call_provider_streaming_real(provider, messages)`** — yields strings. No cost tracking (see "Streaming cost story" above). The streaming function's caller populates `llm_provider_id` on the Run; `llm_input_tokens`, `llm_output_tokens`, and `llm_cost_usd` stay null.

**Anthropic field-name verification:** Anthropic's OpenAI-compat endpoint (`https://api.anthropic.com/v1/`) emits `usage.prompt_tokens` and `usage.completion_tokens` (OpenAI-shaped) when called via the `openai` Python client. This is documented in Anthropic's OpenAI compatibility announcement and verified by the openai SDK v1.75+ against Claude 4.x models. Test assertion `test_anthropic_usage_fields_match_openai_shape` in the plan pins this contract.

### Write-to-Run attribution

All three `_call_*_real` functions are pure (return data, no DB writes). The calling layer (the Run-creating code in `_dispatch_tool_call`, `llm_handlers.py`, etc.) populates the new Run columns from the returned `LLMResult`:

```python
run.llm_provider_id = result.provider_id
run.llm_input_tokens = result.usage.prompt
run.llm_output_tokens = result.usage.completion
run.llm_cost_usd = result.cost_usd
```

This preserves the current separation between "LLM routing" (stateless) and "Run persistence" (caller's job).

### Settings UI additions

New section: **"LLM Policies"**. Layout:

```
┌ LLM Policies ────────────────────────────────────────────────────┐
│                                                                  │
│ Purpose          Preferred Model       Allow Cloud?  Fallback    │
│ ─────────────── ────────────────────── ─────────── ───────────── │
│ chat            qwen3.5:9b    [drop]   [ ]         qwen2.5-coder │
│ classify        llama3.2:3b   [drop]   [ ]         qwen3.5:9b    │
│ plan            qwen3.5:9b    [drop]   [x]         haiku, 3b     │
│ daily_summary   qwen3.5:9b    [drop]   [x]         haiku, 3b     │
│                                                                  │
│ Cloud spend this month: $1.82 across 43 calls                    │
│   ▸ Claude Haiku:  $0.15 (38 calls)                              │
│   ▸ Claude Sonnet: $1.67 (5 calls)                               │
│                                                                  │
│ [+ Add custom purpose]                                           │
└──────────────────────────────────────────────────────────────────┘
```

Preferred Model: dropdown of all enabled `llm_provider_profiles`, grouped by local/cloud.
Allow Cloud: checkbox. When unchecked, cloud rows disappear from the Preferred dropdown and can't be in the Fallback list.
Fallback: drag-to-reorder list (initially read-only in v1; edit in v2).

Validation on save:
- Preferred provider must exist and be enabled.
- If `allow_cloud == false`, all entries in fallback_chain must be local.
- Preferred can't be in fallback_chain (no loops).

### API endpoints

```
GET    /llm/policies                     → list all purpose policies
PATCH  /llm/policies/{purpose}           → update one policy
GET    /llm/spend?window=month           → { total_usd, by_provider: [...], call_count }
```

No POST — policies are seeded; users can't add arbitrary new ones (purposes are code-defined via `VALID_PURPOSES`).

**`PATCH /llm/policies/{purpose}` request body (all fields optional):**

```json
{
  "preferred_provider_id": "string",
  "allow_cloud": true,
  "fallback_chain": ["string", ...]
}
```

v1 UI sends only `preferred_provider_id` and `allow_cloud`. `fallback_chain` is PATCHable via API (for power users) but not yet editable in the v1 Settings UI (read-only drag-handle shown; editability in v2).

**Response codes:**
- `200` on success
- `404` if `{purpose}` is not in `VALID_PURPOSES`
- `422` on validation errors:
  - `preferred_provider_id` doesn't exist or is disabled
  - `allow_cloud=false` with cloud entries in `fallback_chain` or `preferred_provider_id`
  - `preferred_provider_id` appears in `fallback_chain` (loop)
  - Any `fallback_chain` entry doesn't exist or is disabled

### Cost aggregation query

```python
def current_month_spend(db) -> dict:
    since = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(
            LLMProviderProfile.id,
            LLMProviderProfile.name,
            func.sum(Run.llm_cost_usd).label("total"),
            func.count(Run.id).label("calls"),
        )
        .join(Run, Run.llm_provider_id == LLMProviderProfile.id)
        .filter(Run.llm_cost_usd.isnot(None))
        .filter(Run.started_at >= since)
        .group_by(LLMProviderProfile.id, LLMProviderProfile.name)
        .all()
    )
    return {
        "total_usd": sum(r.total for r in rows),
        "by_provider": [{"id": r.id, "name": r.name, "total": r.total, "calls": r.calls} for r in rows],
        "window_start": since.isoformat(),
    }
```

Indexed on `runs.started_at` (already) and `runs.llm_provider_id` (new).

---

## Cloud Provider Integrations

### Anthropic

Uses Anthropic's OpenAI-compatible endpoint: `https://api.anthropic.com/v1/`. Existing `_call_provider_real` in `llm_client.py` already takes a `base_url` on the provider — no code change needed, just seed the right `endpoint_ref`. API key from `ANTHROPIC_API_KEY`.

Tool-calling: Claude's OpenAI-compat returns structured `tool_calls` (verified in Anthropic docs). `_call_provider_with_tools_real` unchanged.

### OpenAI

`endpoint_ref = "https://api.openai.com/v1"`. API key from `OPENAI_API_KEY`. Standard.

### OpenRouter

`endpoint_ref = "https://openrouter.ai/api/v1"`. API key from `OPENROUTER_API_KEY`. Their response includes `usage.cost` directly — use it instead of our rate table.

Notable: OpenRouter lets users pick *specific* models at request time via `model_ref`. We seed a single `openrouter-*` provider row with `model_ref=openrouter/auto` as a sensible default; power users can duplicate the row and set specific models.

### Provider authentication

All three use bearer tokens in HTTPS headers. `_call_provider_real` reads the right env var based on provider_id prefix. No secrets in DB — env vars only. 1Password or similar stays out of scope for this spec (existing pattern: env vars).

---

## Error Handling

| Failure | Behavior |
|---|---|
| Policy missing for requested purpose | Log warning, fall back to `ollama-local` with `privacy_preference=local_required` |
| Preferred provider disabled | Skip to first fallback |
| `allow_cloud=false` but chain is all-cloud | `NoMatchingProvidersError` with clear message |
| Cloud API 5xx | Fallback to next provider in chain; Run records the attempt with `status=failed` |
| Cloud API 401 (bad key) | Disable provider temporarily (in-memory, for the session); fallback; log to surface the key issue |
| Cost computation fails (missing rate) | Log warning; Run gets null cost; don't fail the request |
| User saves policy with invalid chain | 422 with specific field error |

Policy saves that would break existing Runs (e.g., disabling a provider a Run was already logged against) don't affect history — the FK on `llm_provider_id` is nullable for safety.

---

## Testing Strategy

**API tests:**
- Policy CRUD: GET list, PATCH update, validation (cloud-in-chain when `allow_cloud=false` → 422)
- Seed: missing env keys → cloud providers not seeded
- Spend aggregation: runs with cost → correct totals by provider

**llm_client tests:**
- Route per-purpose picks the preferred provider
- Cloud filtered out when policy disallows
- Fallback on exception
- Cost computed correctly for cloud providers, null for local
- OpenRouter path uses `usage.cost` from response

**Conversations integration test:**
- Phase 1 uses `classify` policy (→ llama3.2:3b)
- Phase 2 uses `chat` policy (→ qwen3.5:9b)
- Mocked LLM responses verify correct provider is called

**E2E smoke:**
- Chat message → verify both Phase 1 (3b) and Phase 2 (9b) hit
- Policy UI edit → saved policy affects next call
- Spend widget returns correct totals after a cloud-routed call (if env key is set; otherwise skip)

---

## Migration Plan

Three migrations in order:

1. `0007_llm_purpose_policies` — new table + seed defaults from `seed_llm_purpose_policies`
2. `0008_llm_provider_cost_fields` — add rate columns; update `seed_llm_providers` to populate rates
3. `0009_run_llm_cost_fields` — add token/cost columns on Run

Backward compat:
- Existing `llm_client.route()` calls without a purpose string still work (fall through to legacy `privacy_preference` path).
- Existing Runs remain valid (new cost columns default null).
- Env-key-absent: no cloud rows seeded; cloud-routed policies simply fail closed.

---

## Risks & Tradeoffs

**Risk: purpose sprawl.** If every module invents its own purpose string, the policy table grows unbounded. Mitigation: enumerate valid purposes in code (`VALID_PURPOSES: set[str]`). Unknown purposes log a warning and use the `chat` policy as default.

**Risk: surprise costs.** A user flips `allow_cloud=true` on `triage` (high-frequency) and blows through $50 in a day. Mitigation: (v2) per-provider monthly budget with hard-stop. v1 relies on the Settings widget for visibility.

**Risk: cloud provider changes rate.** Our rate table goes stale. Mitigation: OpenRouter returns cost per-call (always accurate). Anthropic/OpenAI rates rarely change; document the table's source and review quarterly.

**Risk: cloud-only tests leak keys or make real calls in CI.** Mitigation: `_caller` injection pattern already in place; tests mock `_call_provider_real` and `_call_provider_with_tools_real`. CI never has cloud keys.

**Risk: privacy leak via log.** Run records include prompts/outputs. Mitigation: not addressed in this spec — flag for follow-up (data retention policy + field-level redaction).

---

## Deferred Work (Separate Specs)

- **`2026-04-16-async-tool-execution-future.md` (Option B)** — Tool intents become async jobs; chat replies immediately and results land in activity as they complete. Requires background worker + activity feed support for async results. Major UX win; medium effort.
- **`2026-04-16-speculative-decoding-future.md` (Option C)** — 2-3× throughput via draft+target model pairing. Requires moving off Ollama (llama.cpp direct or vLLM). Engine-level change; no app-level work.

These are tracked as future specs, not bundled. Build when the trigger fires (Option B: when async feel matters; Option C: when you change serving infra anyway).

---

## Implementation Order (for the follow-on plan)

1. Migrations 0007 (policies) + 0008 (provider rates) + 0009 (Run cost fields), model updates, `VALID_PURPOSES` constant, `seed_llm_purpose_policies()` with defaults above.
2. Update `seed_llm_providers` to seed cloud rows conditionally (insert on key-present, disable on key-absent, never delete) with the exact values from the seed table.
3. Refactor `LLMResult` → add `usage: TokenUsage` and `cost_usd` fields. Add `TokenUsage` dataclass. Update the existing `_call_provider_real` to populate both.
4. Update `_call_provider_with_tools_real` to populate `usage` and `cost_usd` on the returned dict (matches the new shape). Leave `_call_provider_streaming_real` unchanged (streaming stays uncosted in v1).
5. Refactor `route()` and `route_with_tools()` to consult policies (Algorithm above). `route_streaming()` adapts steps 1-6 but keeps first-candidate-only.
6. Audit callers (`triage.py`, `planner.py`, `summarizer.py`, `conversations.py`, `nova_handlers.py`). Grep shows they all already pass a `purpose` string — verify each purpose is in `VALID_PURPOSES` and adjust strings if mismatched. This is a ~30-minute audit, not a rewrite.
7. Update Run-creating call sites (`_dispatch_tool_call` in `conversations.py`, `_record_run` for tool runs, `handle_daily_summary` for its LLM call) to populate new Run columns from `LLMResult`.
8. `llm_purpose_policies` API router (GET/PATCH) + validation per the 422 rules above.
9. `GET /llm/spend?window=month` endpoint + tests.
10. Settings UI — new `<LLMPoliciesPanel />` + `<LLMSpendWidget />`. Fetch policies on mount, show table with Preferred/AllowCloud controls, spend summary below.
11. Integration smoke test — mock LLM calls across multiple providers, verify correct routing, privacy gates, and cost attribution end-to-end.
12. Push.

`OLLAMA_KEEP_ALIVE=30m` is **orthogonal** — it's an Ollama host env var change, independent of all the above. Land it separately in a micro-commit (docker-compose env entry) to avoid blocking anything on it.

Each step self-contained; each ends with a green test suite.
