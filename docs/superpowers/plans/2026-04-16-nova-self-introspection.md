# Nova Self-Introspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap where Nova can't accurately describe its own scheduled triggers, available tools, or current configuration — by enriching `scheduler.list_triggers` and adding two new introspection tools (`nova.describe_tools`, `nova.describe_config`).

**Architecture:** Three tool changes, all read-only, all auto-execute in chat (`risk_class: low`, not in SENSITIVE_TOOLS). `scheduler.list_triggers` response gains `description` + `payload_template` fields (drops `payload_kind` since LLM can infer from payload shape). Two new handlers in `nova_handlers.py` expose tool-catalog and config snapshots. One short nudge in the chat system prompt redirects "what are you / how are you configured" questions to these tools instead of speculating. Zero migrations, zero frontend changes.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, FastAPI, pytest

**Spec reference:** `docs/superpowers/specs/2026-04-16-nova-self-introspection-design.md`

---

## File Map

| File | Change |
|---|---|
| `services/api/app/tools/scheduler_handlers.py` | Modify `handle_scheduler_list_triggers` — add `description`, `payload`, `active_hours_*`; drop `payload_kind` |
| `services/api/app/tools/nova_handlers.py` | Add `handle_describe_tools`, `handle_describe_config` |
| `services/api/app/tools/handlers.py` | Register 2 new handlers in `_REGISTRY` as `(fn, ["db"])` tuples |
| `services/api/app/tools/seed.py` | Add 2 new tool seed entries; update `test_tools.py` expected-set accordingly |
| `services/api/app/routers/conversations.py` | Add one-sentence introspection nudge to `_build_system_prompt` |
| `services/api/tests/test_scheduler_handlers.py` | Update `test_scheduler_list_triggers_handler` assertions for new fields |
| `services/api/tests/test_nova_handlers.py` | Add tests for both new handlers |
| `services/api/tests/test_tools.py` | Extend `test_get_tools_returns_seeded_tools` expected set with 2 new tool names |

No migrations. No frontend changes. No new dependencies.

---

## Task 1: Enrich `scheduler.list_triggers` Response

**Files:**
- Modify: `services/api/app/tools/scheduler_handlers.py`
- Modify: `services/api/tests/test_scheduler_handlers.py`

- [ ] **Step 1: Update the failing test to assert the new shape**

In `services/api/tests/test_scheduler_handlers.py`, find `test_scheduler_list_triggers_handler`. Replace its assertions with:

```python
def test_scheduler_list_triggers_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_list_triggers
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    result = handle_scheduler_list_triggers({}, db_session)
    triggers = result["triggers"]
    ids = {t["id"] for t in triggers}
    assert "system-heartbeat" in ids
    assert "daily-summary" in ids

    # New shape: description + full payload + active_hours_*; no payload_kind
    sh = next(t for t in triggers if t["id"] == "system-heartbeat")
    assert sh["description"] and "Periodic system health check" in sh["description"]
    assert sh["payload"] == {"tool": "nova.system_health", "input": {}}
    assert sh["active_hours_start"] is None
    assert sh["active_hours_end"] is None
    assert "payload_kind" not in sh  # dropped — LLM infers from payload shape
```

- [ ] **Step 2: Run test — confirm it fails**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
pytest tests/test_scheduler_handlers.py::test_scheduler_list_triggers_handler -v
```

Expected: FAIL — current handler returns `payload_kind` and no `description`/`payload` top-level fields.

- [ ] **Step 3: Update handler to return the new shape**

In `services/api/app/tools/scheduler_handlers.py`, replace the body of `handle_scheduler_list_triggers` with:

```python
def handle_scheduler_list_triggers(input: dict, db: Session) -> dict:
    triggers = db.query(ScheduledTrigger).order_by(ScheduledTrigger.id).all()
    return {
        "triggers": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "cron_expression": t.cron_expression,
                "enabled": t.enabled,
                "payload": t.payload_template,
                "active_hours_start": t.active_hours_start,
                "active_hours_end": t.active_hours_end,
                "last_fired_at": t.last_fired_at.isoformat() if t.last_fired_at else None,
            }
            for t in triggers
        ]
    }
```

- [ ] **Step 4: Run test — confirm pass**

```bash
pytest tests/test_scheduler_handlers.py::test_scheduler_list_triggers_handler -v
```

Expected: PASS.

- [ ] **Step 5: Run all scheduler handler tests — no regressions**

```bash
pytest tests/test_scheduler_handlers.py -v
```

Expected: all pass (5 tests).

- [ ] **Step 6: Commit**

```bash
cd /home/jeremy/workspace/nova-suite
git add services/api/app/tools/scheduler_handlers.py \
        services/api/tests/test_scheduler_handlers.py
git commit -m "feat(api): enrich scheduler.list_triggers response with description + payload"
```

---

## Task 2: `nova.describe_tools` Handler

**Files:**
- Modify: `services/api/app/tools/nova_handlers.py`
- Modify: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/tests/test_nova_handlers.py`
- Modify: `services/api/tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `services/api/tests/test_nova_handlers.py`:

```python
def test_describe_tools_groups_by_prefix(db_session):
    from app.tools.nova_handlers import handle_describe_tools
    from app.tools.seed import seed_tools
    seed_tools(db_session)

    result = handle_describe_tools({}, db_session)
    categories = result["categories"]
    assert result["total_count"] >= 11  # at least the currently seeded tools
    # Grouping by first dotted segment
    assert "scheduler" in categories
    assert "nova" in categories
    assert "shell" in categories
    assert "fs" in categories

    # Each entry has the keys the LLM needs
    first_cat = next(iter(categories.values()))
    first_tool = first_cat[0]
    assert "name" in first_tool
    assert "display_name" in first_tool
    assert "description" in first_tool
    assert "risk_class" in first_tool
    assert "input_schema" in first_tool


def test_describe_tools_excludes_disabled(db_session):
    from app.tools.nova_handlers import handle_describe_tools
    from app.tools.seed import seed_tools
    from app.models.tool import Tool
    seed_tools(db_session)

    # Disable one tool and verify it's absent
    tool = db_session.query(Tool).filter_by(name="debug.echo").first()
    tool.enabled = False
    db_session.commit()

    result = handle_describe_tools({}, db_session)
    all_names = [t["name"] for tools_list in result["categories"].values() for t in tools_list]
    assert "debug.echo" not in all_names
```

- [ ] **Step 2: Run tests — confirm ImportError**

```bash
pytest tests/test_nova_handlers.py::test_describe_tools_groups_by_prefix -v
```

Expected: FAIL — `ImportError: cannot import name 'handle_describe_tools'`.

- [ ] **Step 3: Implement the handler**

In `services/api/app/tools/nova_handlers.py`, append:

```python
def handle_describe_tools(input: dict, db: Session) -> dict:
    """Return the catalog of available (enabled) tools, grouped by dotted prefix."""
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

- [ ] **Step 4: Register in `_REGISTRY`**

In `services/api/app/tools/handlers.py`, extend the import line to include `handle_describe_tools` and add the registry entry. The import at the top:

```python
from app.tools.nova_handlers import handle_system_health, handle_daily_summary, handle_describe_tools
```

And inside `_REGISTRY`:

```python
_REGISTRY = {
    # ... existing entries ...
    "nova.describe_tools": (handle_describe_tools, ["db"]),
}
```

- [ ] **Step 5: Add the seed entry**

In `services/api/app/tools/seed.py`, inside the `tool_definitions` list in `seed_tools`, append this dict after the existing `nova.*` entries:

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

- [ ] **Step 6: Update `test_tools.py` expected-set**

In `services/api/tests/test_tools.py`, line 11 (the `test_get_tools_returns_seeded_tools` assertion), add `"nova.describe_tools"` to the expected set. Before:

```python
assert {"debug.echo", "ha.light.turn_on", ..., "scheduler.delete_trigger"} == names
```

After: include `"nova.describe_tools"` in the literal set.

- [ ] **Step 7: Run the two new handler tests — confirm pass**

```bash
pytest tests/test_nova_handlers.py::test_describe_tools_groups_by_prefix \
       tests/test_nova_handlers.py::test_describe_tools_excludes_disabled \
       tests/test_tools.py::test_get_tools_returns_seeded_tools -v
```

Expected: all 3 pass.

- [ ] **Step 8: Commit**

```bash
cd /home/jeremy/workspace/nova-suite
git add services/api/app/tools/nova_handlers.py \
        services/api/app/tools/handlers.py \
        services/api/app/tools/seed.py \
        services/api/tests/test_nova_handlers.py \
        services/api/tests/test_tools.py
git commit -m "feat(api): add nova.describe_tools introspection handler"
```

---

## Task 3: `nova.describe_config` Handler

**Files:**
- Modify: `services/api/app/tools/nova_handlers.py`
- Modify: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/tests/test_nova_handlers.py`
- Modify: `services/api/tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `services/api/tests/test_nova_handlers.py`:

```python
def test_describe_config_returns_providers_and_trigger_count(db_session):
    from app.tools.nova_handlers import handle_describe_config
    from app.tools.seed import seed_llm_providers, seed_scheduled_triggers

    # Seed requires OLLAMA_BASE_URL; fake it for the test
    class S:
        ollama_base_url = "http://x"
        ollama_model = "qwen3.5:9b"
        ollama_fallback_model = "llama3.2:3b"
    seed_llm_providers(db_session, S())
    seed_scheduled_triggers(db_session)

    result = handle_describe_config({}, db_session)
    # Providers grouped
    assert "providers" in result
    assert isinstance(result["providers"]["local"], list)
    assert isinstance(result["providers"]["cloud"], list)
    local_ids = {p["id"] for p in result["providers"]["local"]}
    assert "ollama-local" in local_ids
    assert "ollama-local-fallback" in local_ids
    # Trigger count is int, not a list (avoids shape drift with scheduler.list_triggers)
    assert isinstance(result["active_trigger_count"], int)
    assert result["active_trigger_count"] == 2


def test_describe_config_survives_missing_purpose_policy_module(db_session, monkeypatch):
    """If the purpose-routing spec hasn't shipped yet, the model module doesn't
    exist — import MUST be inside the try block so describe_config still works."""
    from app.tools.nova_handlers import handle_describe_config
    import sys

    # Force the import to fail even if the module is present in this process
    monkeypatch.setitem(sys.modules, "app.models.llm_purpose_policy", None)

    result = handle_describe_config({}, db_session)
    assert result["purpose_policies"] == []
    # Other fields still populated (providers list, trigger count)
    assert "providers" in result
    assert "active_trigger_count" in result


def test_describe_config_survives_missing_cost_column(db_session):
    """Pre-migration: Run.llm_cost_usd column doesn't exist. The handler's try
    block must swallow the AttributeError and return cloud_spend=None rather
    than crashing. This test is a regression guard for that behavior.
    """
    from app.tools.nova_handlers import handle_describe_config
    result = handle_describe_config({}, db_session)
    assert "cloud_spend_this_month_usd" in result
    # Pre-migration state: column absent → None. Post-migration with no runs: 0.0.
    # Either is acceptable; the contract is "handler didn't crash."
    assert result["cloud_spend_this_month_usd"] in (None, 0.0)


def test_describe_config_returns_trigger_count_not_list(db_session):
    """Locked contract: prevents drift with scheduler.list_triggers."""
    from app.tools.nova_handlers import handle_describe_config
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    result = handle_describe_config({}, db_session)
    assert isinstance(result["active_trigger_count"], int)
    # Explicitly: result must NOT contain "scheduled_triggers" list
    assert "scheduled_triggers" not in result
```

- [ ] **Step 2: Run tests — confirm ImportError**

```bash
pytest tests/test_nova_handlers.py::test_describe_config_returns_providers_and_trigger_count -v
```

Expected: FAIL — `ImportError: cannot import name 'handle_describe_config'`.

- [ ] **Step 3: Implement the handler**

In `services/api/app/tools/nova_handlers.py`, append:

```python
def handle_describe_config(input: dict, db: Session) -> dict:
    """Return a snapshot of Nova's current configuration.

    Defensive: survives both pre-migration (module absent) and pre-seed (table
    empty) states for the LLM purpose-policy system. Guards stay permanent so
    the tool works on fresh clones and after rollbacks.
    """
    from datetime import datetime, timezone
    from sqlalchemy import func
    from app.models.llm_provider import LLMProviderProfile
    from app.models.scheduled_trigger import ScheduledTrigger
    from app.models.run import Run

    providers = db.query(LLMProviderProfile).filter(LLMProviderProfile.enabled == True).all()  # noqa: E712
    providers_local = [
        {"id": p.id, "model_ref": p.model_ref}
        for p in providers if p.provider_type == "local"
    ]
    providers_cloud = [
        {"id": p.id, "model_ref": p.model_ref}
        for p in providers if p.provider_type == "cloud"
    ]

    # Purpose policies — defensive against module-missing AND table-missing.
    policy_list: list[dict] = []
    try:
        from app.models.llm_purpose_policy import LLMPurposePolicy  # import inside try
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
    except Exception:
        # Covers both ImportError (purpose-routing spec not shipped → module absent)
        # and SQLAlchemy OperationalError (table absent pre-migration).
        pass

    # Trigger count (not full list — scheduler.list_triggers owns the detail shape).
    trigger_count = (
        db.query(func.count(ScheduledTrigger.id))
        .filter(ScheduledTrigger.enabled == True)  # noqa: E712
        .scalar()
    ) or 0

    # Monthly cloud spend — defensive against pre-migration column absence.
    cloud_spend: float | None = None
    try:
        since = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        total = (
            db.query(func.coalesce(func.sum(Run.llm_cost_usd), 0))
            .filter(Run.llm_cost_usd.isnot(None))
            .filter(Run.started_at >= since)
            .scalar()
        )
        cloud_spend = float(total or 0)
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

- [ ] **Step 4: Register in `_REGISTRY`**

In `services/api/app/tools/handlers.py`, extend the import and registry:

```python
from app.tools.nova_handlers import (
    handle_system_health,
    handle_daily_summary,
    handle_describe_tools,
    handle_describe_config,
)

_REGISTRY = {
    # ... existing entries ...
    "nova.describe_config": (handle_describe_config, ["db"]),
}
```

- [ ] **Step 5: Add the seed entry**

In `services/api/app/tools/seed.py`, inside `tool_definitions`, add after the `nova.describe_tools` entry:

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

- [ ] **Step 6: Update `test_tools.py` expected-set**

Add `"nova.describe_config"` to the expected set in `test_get_tools_returns_seeded_tools`.

- [ ] **Step 7: Run all new tests — confirm pass**

```bash
pytest tests/test_nova_handlers.py -v
pytest tests/test_tools.py::test_get_tools_returns_seeded_tools -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
cd /home/jeremy/workspace/nova-suite
git add services/api/app/tools/nova_handlers.py \
        services/api/app/tools/handlers.py \
        services/api/app/tools/seed.py \
        services/api/tests/test_nova_handlers.py \
        services/api/tests/test_tools.py
git commit -m "feat(api): add nova.describe_config introspection handler"
```

---

## Task 4: System Prompt Nudge

**Files:**
- Modify: `services/api/app/routers/conversations.py`

This is the key missing piece: Nova needs to *know to call the introspection tools* when the user asks about it. LLMs default to answering from training data ("I'm a large language model…") unless the system prompt redirects them.

- [ ] **Step 1: Read current `_build_system_prompt`**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
grep -n -A 30 "def _build_system_prompt" app/routers/conversations.py
```

Locate the return-string block (lines ~50-75 of `conversations.py`).

- [ ] **Step 2: Add introspection nudge to the system prompt**

The current prompt ends with something like "Respond conversationally. Be concise and helpful." Add one paragraph immediately before that final sentence:

```python
"When the user asks about your configuration, capabilities, scheduled "
"triggers, or what you can do, call the appropriate introspection tool "
"rather than speculating: `nova.describe_config` for your setup, "
"`nova.describe_tools` for your tool catalog, or `scheduler.list_triggers` "
"for what each trigger does. Never invent what a trigger or tool does — "
"read it from the DB.\n\n"
```

Insert this into the `return (...)` expression in `_build_system_prompt`, right before `"Respond conversationally..."`.

- [ ] **Step 3: Rebuild the API container so the new prompt takes effect**

```bash
cd /home/jeremy/workspace/nova-suite
docker compose -f infra/docker-compose.yml up -d --build api
```

Wait for health:

```bash
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do sleep 2; done
echo "API ready"
```

- [ ] **Step 4: Commit**

```bash
cd /home/jeremy/workspace/nova-suite
git add services/api/app/routers/conversations.py
git commit -m "feat(api): nudge LLM to call introspection tools instead of speculating"
```

---

## Task 5: API-Driven Smoke Test + Push

No code changes — validation only. Subagent-executable (no browser required).

- [ ] **Step 1: Full test suite pass**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
pytest tests/ --tb=short
```

Expected: all pass except the 2 known pre-existing unrelated failures (`test_stubs.py::test_stub_routes_return_501`, `test_conversations.py::test_low_confidence_falls_through_no_run`). Document the final counts — should be previous-count + at least 5 new tests from Tasks 1-3.

- [ ] **Step 2: Verify enriched scheduler.list_triggers via direct handler call**

The handler is internally testable — dispatch via the tool endpoint:

```bash
curl -s -X POST http://localhost:8000/tools/scheduler.list_triggers/invoke \
  -H "Content-Type: application/json" -d '{"input": {}}' | python3 -c "
import json, sys
d = json.load(sys.stdin)
triggers = d['output']['triggers']
assert len(triggers) >= 2, 'expected at least 2 seeded triggers'
for t in triggers:
    assert 'description' in t, f'missing description: {t[\"id\"]}'
    assert 'payload' in t, f'missing payload: {t[\"id\"]}'
    assert 'payload_kind' not in t, f'payload_kind should be dropped: {t[\"id\"]}'
    print(f'{t[\"id\"]}: {t[\"description\"][:50]}...')
print('OK')
"
```

Expected: prints each trigger's truncated description and "OK" at the end.

- [ ] **Step 3: Verify nova.describe_tools via direct invoke**

```bash
curl -s -X POST http://localhost:8000/tools/nova.describe_tools/invoke \
  -H "Content-Type: application/json" -d '{"input": {}}' | python3 -c "
import json, sys
d = json.load(sys.stdin)
out = d['output']
cats = out['categories']
assert 'scheduler' in cats, 'scheduler category missing'
assert 'nova' in cats, 'nova category missing'
assert out['total_count'] >= 13, f'expected >= 13 tools, got {out[\"total_count\"]}'
print(f'total={out[\"total_count\"]} categories={list(cats.keys())}')
print('OK')
"
```

Expected: prints the category list and total count (should be 13+: 11 existing + 2 new = 13 minimum).

- [ ] **Step 4: Verify nova.describe_config via direct invoke**

```bash
curl -s -X POST http://localhost:8000/tools/nova.describe_config/invoke \
  -H "Content-Type: application/json" -d '{"input": {}}' | python3 -c "
import json, sys
d = json.load(sys.stdin)
out = d['output']
assert 'providers' in out
assert 'local' in out['providers']
assert isinstance(out['active_trigger_count'], int)
assert out['active_trigger_count'] >= 2
# purpose_policies may be [] pre-routing-spec — that's OK
assert 'purpose_policies' in out
print(f'local={len(out[\"providers\"][\"local\"])} cloud={len(out[\"providers\"][\"cloud\"])} triggers={out[\"active_trigger_count\"]}')
print('OK')
"
```

Expected: prints provider counts + trigger count + "OK".

- [ ] **Step 5: End-to-end chat test (API only, no browser)**

Create a conversation and send the motivating question via the API. Streaming response is accumulated on-the-fly:

```bash
CONV_ID=$(curl -s -X POST http://localhost:8000/conversations | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "Conversation: $CONV_ID"

# Send non-streaming request for easy parsing
curl -s -X POST "http://localhost:8000/conversations/$CONV_ID/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "what scheduled triggers do I have and what do they actually do?", "stream": false}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
content = d.get('content', '')
print('REPLY:', content[:400])
# Soft assertion: reply should mention real descriptions, not invented text
# (we can't fully automate the quality check, but we can flag obvious bad patterns)
assert 'crontab' not in content.lower(), 'Nova fell back to crontab speculation — prompt nudge not working'
print('OK')
"
```

Expected: Nova's reply contains the actual descriptions from the DB (e.g., "Periodic system health check" or "Summarise Nova's past 24h"). The test fails loud if Nova falls back to `crontab -l` speculation (the regression we're fixing).

Also verify the tool was actually invoked via Runs:

```bash
curl -s "http://localhost:8000/runs?limit=5" | python3 -c "
import json, sys
d = json.load(sys.stdin)
recent_tools = [r['tool_name'] for r in d.get('runs', [])]
# scheduler.list_triggers should be in the last 5 runs
assert any('scheduler.list_triggers' in t or 'nova.describe' in t for t in recent_tools), \
    f'No introspection tool in recent runs: {recent_tools}'
print('Tools called recently:', recent_tools)
print('OK')
"
```

- [ ] **Step 6: Push**

```bash
cd /home/jeremy/workspace/nova-suite
git push origin main
```

---

### Optional: human browser validation (skip in subagent mode)

If a human is running this plan interactively, also open `http://localhost:5173/` and send:
- *"what scheduled triggers do I have and what do they actually do?"* — expect Nova to quote the DB descriptions
- *"what tools do you have?"* — expect a grouped list
- *"what's your current configuration?"* — expect provider info + trigger count

If Nova still speculates, re-check Task 4's system-prompt change landed and the API container was rebuilt.

---

## Rollback Plan

If any of the three tool/prompt changes misbehaves in chat:

- Task 1 (scheduler.list_triggers): revert the handler commit; the response shape was backward-compatible additive (new fields) plus one removal (`payload_kind`). The only consumer is Nova's LLM itself; no frontend reads `payload_kind`.
- Task 2-3 (new tools): disable via Settings or `UPDATE tools SET enabled = false WHERE name IN ('nova.describe_tools', 'nova.describe_config')`. Nova's LLM won't see them in the tool catalog.
- Task 4 (system prompt): revert the one commit; Nova reverts to pre-nudge prompt.

Zero schema changes means rollback is always `git revert` — no migration juggling.

---

## Dependencies Between Tasks

- Tasks 1, 2, 3 are mutually independent (different files/scope).
- Task 4 depends on Tasks 2 + 3 (nudge references tools that must exist).
- Task 5 depends on all prior tasks and the stack rebuild.

Suggested execution order: 1 → 2 → 3 → 4 → 5 (matches plan order; keeps each commit focused and the test suite green throughout).

---

## Post-implementation Notes

- Nova's conversation history from before this ships will still contain the "I can only speculate" response. That's fine — new turns use the new prompt. No retroactive fix.
- `scheduler.list_triggers` dropped `payload_kind` in favor of the full `payload`. Anyone reading this tool's output elsewhere (there are no other consumers today) should infer kind from `payload` keys (`"tool" in payload` vs `"goal" in payload`).
- After the purpose-routing spec ships, `nova.describe_config` will start returning non-empty `purpose_policies` automatically — no code change needed (the try block will just succeed).
