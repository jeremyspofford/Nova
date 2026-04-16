# Nova Self-Introspection — Design Spec

**Date:** 2026-04-16
**Status:** Draft — pending review

---

## Goal

When the user asks Nova about itself — "what do my triggers do?", "what tools do you have?", "what model are you running?" — Nova should answer accurately from real state, not hedge or invent. Today, Nova has partial self-knowledge via the chat system prompt, but critical gaps (scheduled trigger descriptions, tool inventory, active policy configuration) force it to guess. This spec closes those gaps with dedicated introspection tools.

## Motivating incident

User asked Nova: *"What model are you running now? How many scheduled tasks do you have?"*

Nova correctly identified the model (qwen3.5:9b) and trigger count (2) — this info comes from the system prompt + `scheduler.list_triggers` tool call. Then user asked: *"Are they useful for anything?"* — Nova had to **speculate** about what each trigger does because `scheduler.list_triggers` returns only `id`, `name`, `cron_expression`, `enabled`, `last_fired_at`, `payload_kind`. No `description`. No `payload_template`. So Nova invented plausible-sounding guesses ("could collect end-of-day metrics…").

User correctly called out: **"You don't know what they do? That's a problem."**

Nova then explained it lacks introspection capability. That's unacceptable — all the information exists in the DB, just isn't exposed to Nova.

## Design principle

**If it's in Nova's DB, Nova should be able to see it when asked.** This is not about ambient awareness (cramming everything into the system prompt, which would blow context windows) — it's about providing introspection *tools* that Nova invokes on demand when the user's question calls for them.

---

## User Stories

### Story 1 — "What do my triggers do?"

Jeremy: *"What scheduled triggers do I have and what do they each do?"*

Nova calls `scheduler.list_triggers` (enhanced to include `description` and `payload_template`). Response per trigger now includes the human-readable description AND the actual payload:

```json
{
  "id": "system-heartbeat",
  "name": "System Heartbeat",
  "description": "Periodic system health check: disk usage, memory, stale tasks, and recent run failures.",
  "cron_expression": "*/30 * * * *",
  "enabled": true,
  "payload": {"tool": "nova.system_health", "input": {}},
  "last_fired_at": "2026-04-16T20:30:13Z"
}
```

Nova's reply quotes the descriptions verbatim and explains what the `nova.system_health` tool does (fetched via the new `nova.describe_tools` tool, or from a cache in the system prompt).

### Story 2 — "What tools do you have?"

Jeremy: *"What can you actually do? What tools are available?"*

Nova calls `nova.describe_tools` → gets the full tool catalog with name + description + risk class + input schema hints. Formats as a grouped list (scheduler, system, shell, fs, nova, http, ha).

### Story 3 — "How are you configured?"

Jeremy: *"What's your current setup? What model, what policies?"*

Nova calls `nova.describe_config` → returns:
- Primary local model + fallback model
- Per-purpose LLM policies (which model handles what)
- Active cloud providers (if any enabled)
- Monthly cloud spend summary
- Nova-lite tick interval + last tick time

Nova synthesizes a concise "here's my current setup" paragraph.

### Story 4 — "Why did the last heartbeat fail?"

Jeremy: *"The last heartbeat seemed off — what happened?"*

Nova calls `nova.query_activity` (already exists) with a filter for `nova.system_health` runs → gets last 5 runs with status, output, error. Explains: "Last three heartbeats ran successfully. The one 3 hours ago found stale tasks (7 pending > 24h) and created escalation task 'Review stalled tasks'."

---

## Architecture

Three new/expanded tools. All are **`risk_class: low`**, read-only, non-sensitive (not in SENSITIVE_TOOLS), auto-execute in chat.

### 1. Expand `scheduler.list_triggers` response

Change in `services/api/app/tools/scheduler_handlers.py`. The existing handler returns a truncated view. Expand to include `description` and raw `payload_template`:

```python
def handle_scheduler_list_triggers(input: dict, db: Session) -> dict:
    triggers = db.query(ScheduledTrigger).order_by(ScheduledTrigger.id).all()
    return {
        "triggers": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,            # NEW
                "cron_expression": t.cron_expression,
                "enabled": t.enabled,
                "payload": t.payload_template,           # NEW (was: payload_kind summary only)
                "active_hours_start": t.active_hours_start,
                "active_hours_end": t.active_hours_end,
                "last_fired_at": t.last_fired_at.isoformat() if t.last_fired_at else None,
            }
            for t in triggers
        ]
    }
```

`payload_kind` removed — Nova's LLM can inspect `payload` directly to tell tool-type from goal-type ("payload has a `tool` key vs a `goal` key").

Update the matching test in `test_scheduler_handlers.py` to assert the new fields.

### 2. New tool: `nova.describe_tools`

New handler in `services/api/app/tools/nova_handlers.py`:

```python
def handle_describe_tools(input: dict, db: Session) -> dict:
    """Return the catalog of available tools with descriptions and categories."""
    from app.models.tool import Tool

    tools = db.query(Tool).filter(Tool.enabled == True).order_by(Tool.name).all()  # noqa: E712
    grouped: dict[str, list[dict]] = {}
    for t in tools:
        category = t.name.split(".", 1)[0] if "." in t.name else "other"
        grouped.setdefault(category, []).append({
            "name": t.name,
            "display_name": t.display_name,
            "description": t.description,
            "risk_class": t.risk_class,
            "input_schema": t.input_schema,
        })
    return {
        "categories": grouped,
        "total_count": sum(len(v) for v in grouped.values()),
    }
```

**Seed entry** (matches the shape of existing entries in `seed_tools`):

```python
dict(
    name="nova.describe_tools",
    display_name="Nova: Describe Tools",
    description=(
        "List all tools Nova can use, grouped by category, with their descriptions. "
        "Use when the user asks 'what tools do you have' or 'what can you do'."
    ),
    adapter_type="internal",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={"type": "object"},
    risk_class="low",
    requires_approval=False,
    timeout_seconds=5,
    enabled=True,
    tags=["nova", "introspection"],
),
```

### 3. New tool: `nova.describe_config`

New handler in `nova_handlers.py`:

```python
def handle_describe_config(input: dict, db: Session) -> dict:
    """Return a snapshot of Nova's current configuration."""
    from datetime import datetime, timezone
    from sqlalchemy import func
    from app.models.llm_provider import LLMProviderProfile
    from app.models.scheduled_trigger import ScheduledTrigger
    from app.models.run import Run

    # Active LLM providers grouped by type
    providers = db.query(LLMProviderProfile).filter(LLMProviderProfile.enabled == True).all()  # noqa: E712
    providers_local = [{"id": p.id, "model_ref": p.model_ref} for p in providers if p.provider_type == "local"]
    providers_cloud = [{"id": p.id, "model_ref": p.model_ref} for p in providers if p.provider_type == "cloud"]

    # Per-purpose policies — defensive for both pre-migration (model import fails)
    # AND pre-seed (module exists, table empty). Keep both guards permanently so
    # describe_config survives operational edge cases (e.g., a fresh clone with no
    # migrations applied yet).
    policy_list: list[dict] = []
    try:
        from app.models.llm_purpose_policy import LLMPurposePolicy  # import inside try — module may not exist yet
        policies = db.query(LLMPurposePolicy).order_by(LLMPurposePolicy.purpose).all()
        policy_list = [
            {
                "purpose": p.purpose,
                "preferred": p.preferred_provider_id,
                "allow_cloud": p.allow_cloud,
                "fallback_chain": p.fallback_chain,
            }
            for p in policies
        ]
    except (ImportError, Exception):
        # ImportError: purpose-routing spec not yet shipped → module absent.
        # Exception (SQLAlchemy OperationalError, etc.): table missing at runtime.
        # Either way, graceful [].
        pass

    # Scheduled trigger count (detail via scheduler.list_triggers — avoid shape duplication)
    trigger_count = (
        db.query(func.count(ScheduledTrigger.id))
        .filter(ScheduledTrigger.enabled == True)  # noqa: E712
        .scalar()
    ) or 0

    # Monthly cloud spend (defensive against pre-migration Run.llm_cost_usd column absence)
    cloud_spend: float | None = None
    try:
        since = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cloud_spend = float(
            db.query(func.coalesce(func.sum(Run.llm_cost_usd), 0))
            .filter(Run.llm_cost_usd.isnot(None))
            .filter(Run.started_at >= since)
            .scalar() or 0
        )
    except Exception:
        pass

    return {
        "providers": {
            "local": providers_local,
            "cloud": providers_cloud,
        },
        "purpose_policies": policy_list,
        "active_trigger_count": trigger_count,
        "cloud_spend_this_month_usd": cloud_spend,
    }
```

**Permanence:** the try/except guards stay permanently — describe_config is load-bearing for user trust ("Nova tells me what's going on"), so it must never crash due to a missing optional schema. The cost of the guards is trivial (~5 lines) vs the cost of the whole tool failing on a fresh deploy.

**Why trigger count instead of full list:** avoids shape duplication with `scheduler.list_triggers`. If the user wants trigger detail, they say "what triggers do I have" and the LLM calls the dedicated tool. `describe_config` gives a one-paragraph snapshot.

**Seed entry:**

```python
dict(
    name="nova.describe_config",
    display_name="Nova: Describe Config",
    description=(
        "Return Nova's current configuration: active LLM providers, per-purpose "
        "policies, active scheduled trigger count, and month-to-date cloud spend. "
        "Use when the user asks about Nova's setup, model, or configuration."
    ),
    adapter_type="internal",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={"type": "object"},
    risk_class="low",
    requires_approval=False,
    timeout_seconds=5,
    enabled=True,
    tags=["nova", "introspection"],
),
```

### Tool registry additions

In `services/api/app/tools/handlers.py`:

```python
_REGISTRY = {
    # ... existing ...
    "nova.describe_tools": (handle_describe_tools, ["db"]),
    "nova.describe_config": (handle_describe_config, ["db"]),
}
```

### System prompt awareness (nudge, not replacement)

The existing `_build_system_prompt` in `conversations.py` should gain one short paragraph telling Nova these tools exist:

```python
# Added to the system prompt template:
"When asked about your configuration, capabilities, or what your scheduled "
"triggers do, call the `nova.describe_config`, `nova.describe_tools`, or "
"`scheduler.list_triggers` tool — don't speculate from memory."
```

This is the key missing piece: Nova needs to *know to call the tool* when the question is about itself. LLMs default to answering from training data ("I'm Claude, a large language model…") unless the prompt explicitly redirects them to live data.

---

## Frontend changes

None required. These are backend tools Nova invokes; the chat UI already renders tool-calling responses.

---

## Testing Strategy

**Handler tests (in `test_nova_handlers.py` + `test_scheduler_handlers.py`):**

- `test_describe_tools_groups_by_prefix` — seed tools, call handler, assert categories like `scheduler`, `nova`, `shell` are populated with expected names
- `test_describe_tools_excludes_disabled` — disable one tool, confirm it's absent from response
- `test_describe_config_returns_providers_and_policies` — seed one local + one cloud provider + one policy, assert all appear
- `test_describe_config_survives_missing_purpose_policy_module` — patch `sys.modules` so `from app.models.llm_purpose_policy import LLMPurposePolicy` raises `ImportError`; confirm handler still returns 200 with `purpose_policies=[]` and other fields populated
- `test_describe_config_survives_missing_purpose_policy_table` — model imports fine but `db.query(LLMPurposePolicy).all()` raises `OperationalError` (table doesn't exist); confirm graceful `[]`
- `test_describe_config_cloud_spend_computation` — seed Runs with costs, verify month-to-date sum
- `test_describe_config_returns_trigger_count_not_list` — assert `active_trigger_count` is an int, not a list (prevents drift with `scheduler.list_triggers`)
- `test_list_triggers_returns_description_and_payload` — extend existing test to assert new fields appear; assert `payload_kind` field is ABSENT

**Integration test:**
- Chat message *"what tools do you have?"* → mocked LLM calls `nova.describe_tools` → Phase 2 renders grouped list. Assert the tool call happened and the reply mentions at least 3 categories.
- Chat message *"what do my triggers do?"* → mocked LLM calls `scheduler.list_triggers` → Phase 2 reply includes the description text of each trigger.

---

## Migration Plan

No schema migration. Just:

1. Extend `handle_scheduler_list_triggers` to include new fields (backward-compatible addition; existing callers see extra keys).
2. Add the two new nova handlers + register + seed.
3. Update the chat system prompt in `_build_system_prompt`.

Zero DB changes, no migration file.

---

## Error Handling

| Failure | Behavior |
|---|---|
| `nova.describe_config` called before purpose-routing spec ships | `purpose_policies` field is `[]`, cloud-spend is `null`, rest of response populated normally |
| User has 100+ triggers | Response is paginated at 50 per page (add `limit`/`offset` to input schema for v2); v1 returns all (acceptable under realistic trigger counts) |
| `nova.describe_tools` called with no tools seeded | Returns `{"categories": {}, "total_count": 0}` — Nova can say "no tools available" |

---

## Risks & Tradeoffs

**Risk: system prompt bloat.** Adding the "call describe_* when asked about config" nudge is ~2 sentences. Monitor — if we add 5 more nudges over time, prompt length starts biting latency. Mitigation: keep the nudge tight.

**Risk: Nova over-introspects.** Every "how are you?" conversational filler could trigger `describe_config`. Mitigation: the system prompt nudge is scoped ("when asked about your configuration") — trust the LLM to judge. If it misfires, the cost is one cheap tool call (reading 3 tables).

**Risk: describe_config leaks sensitive info.** Output includes provider IDs + model refs + policy shape. No API keys, no secrets. Acceptable — the user is always the one asking. Not exposed via unauth endpoints.

**Risk: backward compat for `scheduler.list_triggers`.** Existing chat history may have Nova remembering an older response shape. New fields are additive; old fields retained (except `payload_kind` which is dropped in favor of full `payload`). LLM adapts naturally.

---

## Not in scope (explicit non-goals)

- **Introspecting handler source code.** Nova doesn't need to read its own Python to answer "what does X do?" — the description column is sufficient.
- **Self-modification through introspection.** Nova can list its tools but shouldn't be able to register new ones via chat (that's a sensitive op and the plan for Layer C tool breadth covers it).
- **Runtime telemetry (CPU, request rates).** That's the domain of `nova.system_health`, not introspection.

---

## Implementation Order (for the follow-on plan)

1. Expand `handle_scheduler_list_triggers` response + test update.
2. `nova.describe_tools` handler + registry + seed + test.
3. `nova.describe_config` handler + registry + seed + test (with graceful-degradation for missing purpose-policy table).
4. Update `_build_system_prompt` with introspection nudge.
5. Integration test: chat message → tool call → assertion.
6. Commit + push. (No migration, no infra change.)

Estimated effort: 2-3 hours of implementation. Small, focused, no new subsystems.

---

## Relationship to other specs

- **`2026-04-16-llm-purpose-routing-design.md`** — `nova.describe_config` surfaces the policies this introduces. The handler is defensive: works with OR without the purpose-routing spec shipped.
- **`2026-04-16-scheduler-loop-closure-design.md`** (already shipped) — `scheduler.list_triggers` was introduced here; this spec patches its response shape.
- **Future: async tool execution** — when that ships, `nova.describe_config` should gain a `pending_async_runs` field to show the queue depth.
