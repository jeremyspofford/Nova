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

**Seeded defaults** (local-first, cloud opt-in; all cloud starts OFF):

| purpose | preferred | allow_cloud | fallback_chain |
|---|---|---|---|
| `chat` | `ollama-local` (qwen3.5:9b) | `false` | `["ollama-local-fallback"]` |
| `classify` | `ollama-local-fallback` (llama3.2:3b) | `false` | `["ollama-local"]` |
| `triage` | `ollama-local-fallback` | `false` | `["ollama-local"]` |
| `plan` | `ollama-local` | `false` | `["ollama-local-fallback"]` |
| `summarize` | `ollama-local-fallback` | `false` | `["ollama-local"]` |
| `summarize_daily` | `ollama-local` | `false` | `["ollama-local-fallback"]` |
| `code_generate` | `ollama-local` | `false` | `["ollama-local-fallback"]` |

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

`seed_llm_providers` extended to conditionally seed cloud rows when the corresponding API key env var is set:

| id | model_ref | provider_type | rate (input / output per 1M tok) |
|---|---|---|---|
| `anthropic-claude-haiku` | `claude-haiku-4-5` | cloud | $0.25 / $1.25 |
| `anthropic-claude-sonnet` | `claude-sonnet-4-6` | cloud | $3.00 / $15.00 |
| `anthropic-claude-opus` | `claude-opus-4-7` | cloud | $15.00 / $75.00 |
| `openai-gpt-4o` | `gpt-4o` | cloud | $5.00 / $15.00 |
| `openai-gpt-4o-mini` | `gpt-4o-mini` | cloud | $0.15 / $0.60 |
| `openrouter-*` | dynamic | cloud | reported per-call |

Rows are created only when `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` is set in the host env. Missing key → missing provider row → impossible to route to, even if configured in a policy (enforced at policy save).

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

`llm_client.route(db, purpose, messages, privacy_preference=None, _caller=None)`:

1. Fetch policy for `purpose`. If missing, fall back to `privacy_preference=local_preferred` and use `ollama-local` (graceful degradation).
2. Build candidate list: `[preferred_provider_id] + fallback_chain`, deduplicated.
3. **Privacy gate:** if `policy.allow_cloud == false`, filter out any candidate where `provider_type == "cloud"`. If the resulting list is empty, raise `NoMatchingProvidersError`.
4. Try each candidate in order. On exception, try next. Record a failed Run for each attempt that exceptions out.
5. Return `LLMResult(provider_id, model_ref, output, tokens, cost_usd)`.

The `privacy_preference` parameter stays as a **per-call override** — passing `local_required` forces `allow_cloud=false` regardless of policy (for paranoid callers like Nova-lite).

### Cost accounting

Per provider rates stored in `llm_provider_profiles.cost_per_million_*_tokens_usd`. Cost computed at response-time:

```python
def _compute_cost(provider, usage) -> float | None:
    if provider.provider_type != "cloud" or not provider.cost_per_million_input_tokens_usd:
        return None
    return (
        usage.prompt_tokens * provider.cost_per_million_input_tokens_usd / 1_000_000
        + usage.completion_tokens * provider.cost_per_million_output_tokens_usd / 1_000_000
    )
```

OpenRouter returns `usage.cost` directly in the response — use that value when present, ignore the rate table for OpenRouter rows.

Token counts come from the OpenAI `response.usage` field. Anthropic's shim via OpenAI-compat endpoint also populates this.

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

No POST — policies are seeded; users can't add arbitrary new ones (purposes are code-defined).

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

1. Migrations 0007 + 0008 + 0009, model updates, seeds
2. `llm_purpose_policies` API router (GET/PATCH)
3. `llm_client.route_by_policy()` — new entry point that replaces direct `route()` calls; privacy gate; cost computation
4. Update all internal callers (`triage.py`, `planner.py`, `summarizer.py`, `conversations.py`, `nova_handlers.py`) to pass explicit purpose
5. Update `_call_provider_*_real` functions to populate `usage.prompt_tokens`/`usage.completion_tokens`/cost on LLMResult
6. Seed cloud provider rows when env keys present; cost rates in seed
7. `GET /llm/spend` endpoint + Settings widget
8. LLM Policies UI panel (`<LLMPoliciesPanel />`)
9. Set `OLLAMA_KEEP_ALIVE=30m` in Ollama host config + docker-compose env
10. Integration smoke test + push

Each step self-contained; each ends with a green test suite.
