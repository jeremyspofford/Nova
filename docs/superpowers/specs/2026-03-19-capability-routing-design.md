# Capability-Based Model Routing

**Date:** 2026-03-19
**Status:** Approved

## Problem

Nova's chat model is often a cheap local model (e.g., `deepseek-r1:8b`, `llama3.1:8b`) that doesn't support tool calling. When the user asks Nova to search the web or use any tool, the local model either hallucinates tool calls (printing XML tags as text) or claims it can't do it. The user has cloud models configured that handle tools reliably, but Nova doesn't know to escalate.

## Solution

Add a per-turn capability check in the orchestrator. When tools are needed and the current model lacks `function_calling` capability, silently escalate to a tool-capable model for that turn only.

## Design

### Capability Check — `orchestrator/app/model_capabilities.py` (new)

**Data source:** The gateway's `GET /models` endpoint returns `ModelInfo` objects with provider capabilities for statically registered models. The `GET /v1/models/discover` endpoint returns live availability per provider but does NOT carry capability data. The capability module needs both:

1. Call `/models` → build `model_id → set[capability]` map
2. Call `/v1/models/discover` → build `model_id → available` map
3. Intersect: a model is "tool-capable and available" if it has `function_calling` AND is available

Both results cached together with 60s TTL (matches existing `_refresh_available_models` pattern in `model_classifier.py`).

**Public API:**
- `supports_function_calling(model_id: str) -> bool` — checks the capability map
- `resolve_tool_model() -> str | None` — finds the best available tool-capable model
- Unknown models (not in `/models` registry) default to `True` (assume capable, don't block)

**Provider capability status (current):**

| Provider | Declares `function_calling` |
|----------|---------------------------|
| LiteLLM (cloud) | Yes |
| Claude subscription | Yes |
| vLLM | Yes |
| SGLang | Yes |
| Ollama | No |
| ChatGPT subscription | No (text-only scraping) |

### Tool Model Resolution

**Config key:** `llm.tool_model` in `platform_config`

- `"auto"` or unset → auto-resolve using the algorithm below
- Explicit model ID → use that model directly
- If configured model is unavailable → fall back to auto-resolve, then to current model (no crash)

**Auto-resolve algorithm:**
1. Read `llm.cloud_fallback_model` from platform_config — if set, available, and has `function_calling`, use it
2. Otherwise: from the intersection of `/models` capabilities and `/v1/models/discover` availability, collect all models with `function_calling`. Prefer cloud providers over local. Return the first match.
3. If no tool-capable model is available, return `None` (caller proceeds with current model)

**Config default:** Application treats absent key as `"auto"`. No migration needed — the existing `platform_config` upsert pattern handles missing keys gracefully (same as other `llm.*` keys).

### Orchestrator Integration — `orchestrator/app/agents/runner.py`

**Insertion point:** After resolving `effective_tools` (permission filtering) and BEFORE the three-way branch (`guest_mode` / `skip_tool_preresolution` / `_resolve_tool_rounds`). This ensures all code paths — including the `skip_tool_preresolution=True` interactive chat path — get the capability check.

```
# After effective_tools resolution, before prompt building
if effective_tools:
    if not await supports_function_calling(model):
        tool_model = await resolve_tool_model()
        if tool_model:
            model = tool_model  # swap for this turn only
            emit status event (streaming path only)
```

**Streaming path (`run_agent_turn_streaming`):**
- Capability check goes after `effective_tools` resolution (~line 250), before `guest_mode` branch (~line 253)
- Status event: `{"status": {"step": "model_escalation", "state": "done", "detail": "escalated to claude-sonnet-4-6 for tool use"}}`

**Non-streaming path (`run_agent_turn`):**
- Capability check goes after `effective_tools` resolution (~line 70), before prompt building (~line 84)
- No status event needed (non-interactive)

**`_run_tool_loop` fallback path:**
- When called with `tools=None` (pipeline agents via `run_agent_turn_raw`), the loop resolves tools via `get_permitted_tools()`. The capability check also applies here — after resolving `effective_tools`, check the model and swap if needed.

**`_build_nova_context` and model identity:**
- `_build_nova_context` runs inside `asyncio.gather()` BEFORE the capability check, so it receives the original model name in the system prompt (`"Your model: deepseek-r1:8b"`). After escalation, the actual model answering is different (e.g., `claude-sonnet-4-6`).
- This is acceptable: the escalated cloud model won't hallucinate its own identity — it will correctly identify itself regardless of what the system prompt says. Rebuilding context after the swap would cost latency for negligible benefit.

**Logging:** Escalation logged at `INFO` level (it's a state change visible to operators), matching the pattern in `model_classifier.py`.

### Pipeline Agent Scope

Pipeline agents (`ContextAgent`, `TaskAgent`) call `run_agent_turn_raw` with their own model (resolved by `stage_model_resolver.py` from `pipeline.stage_model.*` config). These models are explicitly chosen by the admin for pipeline work.

The capability check in `_run_tool_loop` covers this path: if a pipeline stage model lacks `function_calling` and the stage sends tools, escalation happens. However, pipeline stage model selection is a separate admin decision — the `llm.tool_model` setting applies identically regardless of caller.

### Dashboard UI — `LLMRoutingSection.tsx`

One new field in the LLM Routing section: "Tool Model" picker.

- Same pattern as Cloud Fallback Model picker (dropdown + save/reset)
- Dropdown of available models filtered to those with `function_calling` capability
- "Auto" option (default) — picks best available
- Position: after Cloud Fallback Model

### Edge Cases

- **Tool model set but unavailable:** fall back to auto-resolve, then to current model
- **All models lack function_calling:** proceed with current model (no crash, no regression)
- **User explicitly picks local model in chat:** still escalates for tool turns (system config takes precedence)
- **No cloud provider configured:** no escalation possible, local model used as-is (current behavior)
- **Guest mode:** no tools, no escalation check needed
- **Cache staleness across workers:** per-process 60s cache means capability data may drift across uvicorn workers within the TTL window. Acceptable — matches existing `model_classifier.py` pattern. Redis-backed cache is a future option if needed.

## Files Modified

| File | Change |
|------|--------|
| `orchestrator/app/model_capabilities.py` | New — capability cache, `supports_function_calling()`, `resolve_tool_model()` |
| `orchestrator/app/agents/runner.py` | Capability check + model swap in streaming, non-streaming, and `_run_tool_loop` paths |
| `dashboard/src/pages/settings/LLMRoutingSection.tsx` | Tool model picker field |

## Files NOT Modified

- **LLM gateway** — already exposes capabilities via `/models` and availability via `/v1/models/discover`
- **nova-contracts** — `ModelCapability.function_calling` already exists
- **Database** — uses existing `platform_config` table (absent key treated as `"auto"`)

## Default Behavior

New installs work out of the box. No `llm.tool_model` configured → auto-resolves to best cloud model when tools are needed. If no cloud model is configured, local model handles tools as-is (current behavior, no regression).
