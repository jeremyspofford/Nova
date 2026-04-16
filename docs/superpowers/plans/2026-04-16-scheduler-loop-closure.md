# Scheduler Loop Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the scheduler loop by (A) making the two default triggers produce useful output via deterministic tool handlers with activity-first / task-on-escalation semantics, and (B) enabling chat-driven creation/management of user-defined triggers with natural-language → cron translation, via an LLM tool-calling upgrade.

**Architecture:** Cron expressions replace intervals (`croniter`). Trigger payloads are a union (`{tool, input}` or `{goal}`). Triage branches on `source=="scheduler"`: tool-type bypasses the classification LLM and invokes the handler directly, reading `{status: ok|action_needed}` to route to activity-only vs. task-creation. The default Ollama model swaps to `qwen2.5-coder:7b` and `supports_tools` flips to `True`. Conversations gain a real tool-calling loop + `pending_tool_call` state for sensitive-op confirmation via a regex allowlist.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, FastAPI, Pydantic v2, httpx, pytest, React/TypeScript (board), Ollama (qwen2.5-coder:7b), croniter, psutil

---

## File Map

**New files:**

| File | Responsibility |
|---|---|
| `services/api/alembic/versions/0005_cron_schedules.py` | Replace `interval_seconds` with `cron_expression`, migrate the 2 seeds |
| `services/api/alembic/versions/0006_conversation_pending_tool_call.py` | Add `pending_tool_call` JSONB column to `conversations` |
| `services/api/app/tools/nova_handlers.py` | `nova.system_health` + `nova.daily_summary` handlers with typed `{status, ...}` return |
| `services/api/app/tools/scheduler_handlers.py` | 4 scheduler-management handlers (create/list/update/delete) that operate in-process via SQLAlchemy session |
| `services/api/tests/test_nova_handlers.py` | Tests for the two default handlers |
| `services/api/tests/test_scheduler_handlers.py` | Tests for the four scheduler-management handlers |
| `services/api/tests/test_tool_calling_loop.py` | Tests for the new conversations tool-calling path |
| `services/board/src/components/Settings/ScheduledTriggersPanel.tsx` | Read-only triggers list in Settings |
| `services/board/src/lib/cron-to-nl.ts` | Cron-expression → human-readable string helper |

**Modified files:**

| File | Change |
|---|---|
| `services/api/requirements.txt` | Add `croniter==2.0.7`, `psutil==6.1.0` |
| `services/api/app/models/scheduled_trigger.py` | Drop `interval_seconds`, add `cron_expression` |
| `services/api/app/schemas/scheduled_trigger.py` | New `ScheduledTriggerCreate`; update `ScheduledTriggerUpdate`; cron validator; payload union validator |
| `services/api/app/routers/system.py` | Add `POST /system/triggers` and `DELETE /system/triggers/{id}`; PATCH validates cron |
| `services/api/app/tools/seed.py` | Migrate `seed_scheduled_triggers` to cron; add 6 new tools to `seed_tools` |
| `services/api/app/tools/handlers.py` | Register `nova.*` and `scheduler.*` in `_REGISTRY`; wire to DB/config where needed |
| `services/api/app/models/conversation.py` | Add `pending_tool_call` column |
| `services/api/app/routers/conversations.py` | Replace intent-classifier with tool-calling loop; add confirmation handling |
| `services/api/app/routers/health.py` | Add `model_ready` boolean to `/health` |
| `services/api/app/config.py` | Default `ollama_model` → `qwen2.5-coder:7b` |
| `services/api/tests/test_system.py` | Add tests for POST/DELETE + cron + payload validation |
| `services/api/tests/test_conversations.py` | Update existing tests for tool-calling path |
| `services/nova-lite/requirements.txt` | Add `croniter==2.0.7` |
| `services/nova-lite/app/logic/scheduler.py` | Rewrite `_is_due` using croniter |
| `services/nova-lite/app/logic/triage.py` | Add scheduler-source branch before `llm_route` |
| `services/nova-lite/tests/test_scheduler.py` | Update fixtures to use cron expressions |
| `services/nova-lite/tests/test_triage.py` | Add scheduler-source routing tests |
| `services/nova-lite/tests/conftest.py` | `FakeClient.invoke_tool` return-shape extension for handler contract |
| `services/board/src/components/Settings/Settings.tsx` | Include `<ScheduledTriggersPanel />` |
| `services/board/src/api/triggers.ts` (new) | `getTriggers()` fetch helper |

---

## Task 1: Cron Schema Migration + Model + Pydantic

**Files:**
- Modify: `services/api/requirements.txt`
- Modify: `services/api/app/models/scheduled_trigger.py`
- Modify: `services/api/app/schemas/scheduled_trigger.py`
- Create: `services/api/alembic/versions/0005_cron_schedules.py`
- Modify: `services/api/app/tools/seed.py`

- [ ] **Step 1: Add croniter dependency**

Append to `services/api/requirements.txt`:

```
croniter==2.0.7
psutil==6.1.0
```

- [ ] **Step 2: Update the `ScheduledTrigger` model**

In `services/api/app/models/scheduled_trigger.py`, replace `interval_seconds` column with `cron_expression`:

```python
from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlalchemy.types import JSON
from app.database import Base


class ScheduledTrigger(Base):
    __tablename__ = "scheduled_triggers"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    cron_expression = Column(String, nullable=False)
    active_hours_start = Column(String, nullable=True)
    active_hours_end = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    payload_template = Column(JSON, nullable=False, default=dict)
    last_fired_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

(Note: `Integer` import removed.)

- [ ] **Step 3: Update Pydantic schemas**

Replace contents of `services/api/app/schemas/scheduled_trigger.py`:

```python
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


def _validate_cron(v: str) -> str:
    from croniter import croniter
    if not croniter.is_valid(v):
        raise ValueError(f"invalid cron expression: {v}")
    return v


def _validate_payload_shape(payload: dict) -> dict:
    has_tool = "tool" in payload
    has_goal = "goal" in payload
    if has_tool and has_goal:
        raise ValueError("payload cannot contain both 'tool' and 'goal'")
    if not (has_tool or has_goal):
        raise ValueError("payload must contain either 'tool' or 'goal'")
    if has_goal:
        goal = payload["goal"]
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
    if has_tool:
        tool = payload["tool"]
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError("tool must be a non-empty string")
    return payload


class ScheduledTriggerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    cron_expression: str
    active_hours_start: str | None
    active_hours_end: str | None
    enabled: bool
    payload_template: dict[str, Any]
    last_fired_at: datetime | None


class ScheduledTriggerCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str
    description: str | None = None
    cron_expression: str
    payload_template: dict[str, Any]
    active_hours_start: str | None = Field(default=None, pattern=HHMM_PATTERN)
    active_hours_end: str | None = Field(default=None, pattern=HHMM_PATTERN)
    enabled: bool = True

    @field_validator("cron_expression")
    @classmethod
    def _cron(cls, v): return _validate_cron(v)

    @model_validator(mode="after")
    def _payload(self):
        _validate_payload_shape(self.payload_template)
        return self


class ScheduledTriggerUpdate(BaseModel):
    enabled: bool | None = None
    cron_expression: str | None = None
    payload_template: dict[str, Any] | None = None
    active_hours_start: str | None = Field(default=None, pattern=HHMM_PATTERN)
    active_hours_end: str | None = Field(default=None, pattern=HHMM_PATTERN)
    last_fired_at: datetime | None = None

    @field_validator("cron_expression")
    @classmethod
    def _cron(cls, v):
        return _validate_cron(v) if v is not None else v

    @model_validator(mode="after")
    def _payload(self):
        if self.payload_template is not None:
            _validate_payload_shape(self.payload_template)
        return self


class ScheduledTriggerListResponse(BaseModel):
    triggers: list[ScheduledTriggerRead]
```

- [ ] **Step 4: Write the Alembic migration**

Create `services/api/alembic/versions/0005_cron_schedules.py`:

```python
"""replace interval_seconds with cron_expression

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheduled_triggers", sa.Column("cron_expression", sa.String(), nullable=True))

    # Backfill cron_expression for the two seeded triggers.
    op.execute(
        "UPDATE scheduled_triggers SET cron_expression = '*/30 * * * *' WHERE id = 'system-heartbeat'"
    )
    op.execute(
        "UPDATE scheduled_triggers SET cron_expression = '0 0 * * *' WHERE id = 'daily-summary'"
    )

    # Rewrite the two seeded triggers' payload_template to the new {tool, input} shape.
    # seed_scheduled_triggers preserves existing payload_template on restart (user data is
    # sacred), so without this data migration the stale {"check": "system_health"} payload
    # would persist and bypass the triage scheduler-source branch's tool-routing.
    op.execute(
        "UPDATE scheduled_triggers SET payload_template = '{\"tool\": \"nova.system_health\", \"input\": {}}'::json "
        "WHERE id = 'system-heartbeat'"
    )
    op.execute(
        "UPDATE scheduled_triggers SET payload_template = '{\"tool\": \"nova.daily_summary\", \"input\": {\"window_hours\": 24}}'::json "
        "WHERE id = 'daily-summary'"
    )

    op.alter_column("scheduled_triggers", "cron_expression", nullable=False)
    op.drop_column("scheduled_triggers", "interval_seconds")


def downgrade() -> None:
    op.add_column("scheduled_triggers", sa.Column("interval_seconds", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE scheduled_triggers SET interval_seconds = 1800 WHERE id = 'system-heartbeat'"
    )
    op.execute(
        "UPDATE scheduled_triggers SET interval_seconds = 86400 WHERE id = 'daily-summary'"
    )
    # Restore the old payload shape for the two seeded triggers.
    op.execute(
        "UPDATE scheduled_triggers SET payload_template = '{\"check\": \"system_health\"}'::json "
        "WHERE id = 'system-heartbeat'"
    )
    op.execute(
        "UPDATE scheduled_triggers SET payload_template = '{\"check\": \"daily_summary\"}'::json "
        "WHERE id = 'daily-summary'"
    )
    op.alter_column("scheduled_triggers", "interval_seconds", nullable=False)
    op.drop_column("scheduled_triggers", "cron_expression")
```

- [ ] **Step 5: Update `seed_scheduled_triggers`**

In `services/api/app/tools/seed.py`, change the two default definitions so their payloads match the new `{tool, input}` shape and they use cron:

```python
defaults = [
    dict(
        id="system-heartbeat",
        name="System Heartbeat",
        description=(
            "Periodic system health check: disk usage, memory, stale tasks, "
            "and recent run failures."
        ),
        cron_expression="*/30 * * * *",
        enabled=True,
        payload_template={"tool": "nova.system_health", "input": {}},
    ),
    dict(
        id="daily-summary",
        name="Daily Summary",
        description=(
            "Summarise Nova's past 24h of activity — events, runs, and "
            "completed/failed tasks — into a read-once digest."
        ),
        cron_expression="0 0 * * *",
        enabled=True,
        payload_template={"tool": "nova.daily_summary", "input": {"window_hours": 24}},
    ),
]
```

Remove the `interval_seconds=...` lines. Keep the upsert logic as-is (existing rows' `enabled`/`cron_expression`/etc. are preserved; only `name` and `description` refresh).

- [ ] **Step 6: Apply migration against live DB and rebuild API image**

```bash
cd /home/jeremy/workspace/nova-suite
./dev --build
```

Wait for API health to return `status: ok`, then verify:

```bash
docker compose -f infra/docker-compose.yml exec db \
  psql -U nova -d nova -c "\d scheduled_triggers"
```

Expected: `cron_expression | character varying | not null`; no `interval_seconds` column.

- [ ] **Step 7: Verify existing system tests still pass**

```bash
cd services/api
pytest tests/test_system.py -v
```

Expected: all 7 existing system tests pass. One specific test to confirm: `test_seed_preserves_user_modifications` still locks in the preservation guarantee (name/description refresh; enabled/interval_seconds preserved — now interpret as `enabled/cron_expression preserved`). If that test referenced `interval_seconds`, update the assertion to `cron_expression`.

- [ ] **Step 8: Commit**

```bash
git add services/api/requirements.txt \
        services/api/app/models/scheduled_trigger.py \
        services/api/app/schemas/scheduled_trigger.py \
        services/api/alembic/versions/0005_cron_schedules.py \
        services/api/app/tools/seed.py \
        services/api/tests/test_system.py
git commit -m "feat(api): replace interval_seconds with cron_expression on scheduled_triggers"
```

---

## Task 2: POST/DELETE Endpoints + Cron Validation

**Files:**
- Modify: `services/api/app/routers/system.py`
- Modify: `services/api/tests/test_system.py`

- [ ] **Step 1: Write failing tests for POST/DELETE**

Append to `services/api/tests/test_system.py`:

```python
def test_create_trigger_valid_cron(client):
    resp = client.post("/system/triggers", json={
        "id": "test-trigger",
        "name": "Test",
        "cron_expression": "0 9 * * *",
        "payload_template": {"tool": "debug.echo", "input": {}},
    })
    assert resp.status_code == 200
    assert resp.json()["id"] == "test-trigger"


def test_create_trigger_invalid_cron(client):
    resp = client.post("/system/triggers", json={
        "id": "bad",
        "name": "Bad",
        "cron_expression": "not a cron",
        "payload_template": {"tool": "debug.echo"},
    })
    assert resp.status_code == 422


def test_create_trigger_conflicting_payload(client):
    resp = client.post("/system/triggers", json={
        "id": "conflict",
        "name": "Conflict",
        "cron_expression": "0 9 * * *",
        "payload_template": {"tool": "x", "goal": "y"},
    })
    assert resp.status_code == 422


def test_create_trigger_empty_goal(client):
    resp = client.post("/system/triggers", json={
        "id": "empty",
        "name": "Empty",
        "cron_expression": "0 9 * * *",
        "payload_template": {"goal": ""},
    })
    assert resp.status_code == 422


def test_create_trigger_bad_id_pattern(client):
    resp = client.post("/system/triggers", json={
        "id": "NotKebabCase",
        "name": "X",
        "cron_expression": "0 9 * * *",
        "payload_template": {"goal": "x"},
    })
    assert resp.status_code == 422


def test_delete_trigger(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    resp = client.delete("/system/triggers/system-heartbeat")
    assert resp.status_code == 200
    follow = client.get("/system/triggers")
    ids = {t["id"] for t in follow.json()["triggers"]}
    assert "system-heartbeat" not in ids


def test_delete_trigger_not_found(client):
    resp = client.delete("/system/triggers/nonexistent")
    assert resp.status_code == 404


def test_patch_rejects_invalid_cron(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    resp = client.patch("/system/triggers/system-heartbeat",
                        json={"cron_expression": "nope"})
    assert resp.status_code == 422
```

Also update the existing `test_patch_trigger_rejects_nonpositive_interval` — it references a field that no longer exists. Remove it entirely, or replace with `test_patch_rejects_invalid_cron` which is already above.

- [ ] **Step 2: Run tests — confirm failures**

```bash
cd services/api
pytest tests/test_system.py -v
```

Expected: the new tests fail (405 Method Not Allowed for POST/DELETE; 404 for PATCH invalid cron).

- [ ] **Step 3: Implement POST and DELETE**

In `services/api/app/routers/system.py`, add after the existing PATCH handler:

```python
from app.schemas.scheduled_trigger import (
    ScheduledTriggerCreate,
    ScheduledTriggerListResponse,
    ScheduledTriggerRead,
    ScheduledTriggerUpdate,
)


@router.post("/triggers", response_model=ScheduledTriggerRead)
def create_trigger(body: ScheduledTriggerCreate, db: Session = Depends(get_db)):
    existing = db.query(ScheduledTrigger).filter(ScheduledTrigger.id == body.id).first()
    if existing:
        raise HTTPException(409, detail=f"Trigger '{body.id}' already exists")
    trigger = ScheduledTrigger(**body.model_dump())
    db.add(trigger)
    db.commit()
    db.refresh(trigger)
    return ScheduledTriggerRead.model_validate(trigger)


@router.delete("/triggers/{trigger_id}")
def delete_trigger(trigger_id: str, db: Session = Depends(get_db)):
    trigger = db.query(ScheduledTrigger).filter(ScheduledTrigger.id == trigger_id).first()
    if not trigger:
        raise HTTPException(404, detail="Trigger not found")
    db.delete(trigger)
    db.commit()
    return {"status": "deleted", "id": trigger_id}
```

- [ ] **Step 4: Run tests — confirm all pass**

```bash
pytest tests/test_system.py -v
```

Expected: all system tests pass (existing + 7 new).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routers/system.py services/api/tests/test_system.py
git commit -m "feat(api): add POST and DELETE for /system/triggers with cron validation"
```

---

## Task 3: Nova-Lite `_is_due` Cron Rewrite

**Files:**
- Modify: `services/nova-lite/requirements.txt`
- Modify: `services/nova-lite/app/logic/scheduler.py`
- Modify: `services/nova-lite/tests/test_scheduler.py`

- [ ] **Step 1: Add croniter to nova-lite requirements**

Append to `services/nova-lite/requirements.txt`:

```
croniter==2.0.7
```

- [ ] **Step 2: Update scheduler tests to use cron**

Replace the `_is_due`-related tests in `services/nova-lite/tests/test_scheduler.py` (the first 5 tests in that file) with:

```python
def test_is_due_never_fired():
    trigger = {"enabled": True, "cron_expression": "*/30 * * * *", "last_fired_at": None}
    assert _is_due(trigger, datetime.now(timezone.utc)) is True


def test_is_due_recently_fired():
    now = datetime(2026, 4, 16, 10, 5, tzinfo=timezone.utc)
    recent = datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc).isoformat()
    trigger = {"enabled": True, "cron_expression": "*/30 * * * *", "last_fired_at": recent}
    assert _is_due(trigger, now) is False


def test_is_due_cron_occurrence_reached():
    now = datetime(2026, 4, 16, 10, 30, tzinfo=timezone.utc)
    last = datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc).isoformat()
    trigger = {"enabled": True, "cron_expression": "*/30 * * * *", "last_fired_at": last}
    assert _is_due(trigger, now) is True


def test_is_due_catchup_once():
    """If Nova was offline for multiple cron occurrences, fire exactly once on catch-up."""
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    last = datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc).isoformat()
    trigger = {"enabled": True, "cron_expression": "*/30 * * * *", "last_fired_at": last}
    assert _is_due(trigger, now) is True


def test_is_due_disabled_trigger():
    trigger = {"enabled": False, "cron_expression": "* * * * *", "last_fired_at": None}
    assert _is_due(trigger, datetime.now(timezone.utc)) is False
```

Also update the `_make_trigger` helper (lines ~68-80) to emit `cron_expression` instead of `interval_seconds`:

```python
def _make_trigger(trigger_id="system-heartbeat", last_fired_offset_seconds=None):
    now = datetime.now(timezone.utc)
    last_fired = None
    if last_fired_offset_seconds is not None:
        last_fired = (now - timedelta(seconds=last_fired_offset_seconds)).isoformat()
    return {
        "id": trigger_id,
        "name": "System Heartbeat",
        "enabled": True,
        "cron_expression": "* * * * *",  # every minute — always due if last fire is > 60s ago
        "last_fired_at": last_fired,
        "active_hours_start": None,
        "active_hours_end": None,
        "payload_template": {"tool": "nova.system_health", "input": {}},
    }
```

- [ ] **Step 3: Run tests — confirm failures**

```bash
cd services/nova-lite
pytest tests/test_scheduler.py -v
```

Expected: many tests fail because `_is_due` still uses `interval_seconds`.

- [ ] **Step 4: Rewrite `_is_due` in scheduler module**

In `services/nova-lite/app/logic/scheduler.py`:

```python
"""
Check which scheduled triggers are due (cron-based) and emit an event for each.

Each fired trigger claims its interval first (PATCH last_fired_at), then emits
the event. Patch-first ordering means a transient API failure during firing
will cost at most one missed event rather than spam the event stream on every
subsequent tick until the patch eventually lands.
"""
import logging
from datetime import datetime, timezone

from croniter import croniter

from app.client import NovaClientError

log = logging.getLogger(__name__)

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_last_fired(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_due(trigger: dict, now: datetime) -> bool:
    """Return True if the trigger's next cron occurrence has passed since last_fired."""
    if not trigger.get("enabled"):
        return False
    last_fired = _parse_last_fired(trigger.get("last_fired_at"))
    base = last_fired or _EPOCH
    next_fire = croniter(trigger["cron_expression"], base).get_next(datetime)
    return now >= next_fire


def _in_active_hours(trigger: dict, now: datetime) -> bool:
    """Return True if current UTC time is within the trigger's active window.

    If either bound is missing, the trigger is considered always active.
    Midnight-wrapping windows (start > end, e.g. "22:00"–"06:00") are not
    supported: that configuration makes the comparison impossible and the
    trigger will never fire.
    """
    start = trigger.get("active_hours_start")
    end = trigger.get("active_hours_end")
    if not start or not end:
        return True
    current = now.strftime("%H:%M")
    return start <= current <= end


def fire_due_triggers(client) -> int:
    """
    Fetch all triggers, fire those that are due, return the count fired.
    Errors from individual trigger firing are logged and skipped — never raised.
    """
    try:
        triggers = client.get_scheduled_triggers()
    except NovaClientError as exc:
        log.warning("Could not fetch scheduled triggers: %s", exc)
        return 0

    now = datetime.now(timezone.utc)
    fired = 0

    for trigger in triggers:
        if not _is_due(trigger, now) or not _in_active_hours(trigger, now):
            continue
        trigger_id = trigger["id"]
        try:
            client.patch_scheduled_trigger(trigger_id, {"last_fired_at": now.isoformat()})
            client.post_event({
                "type": f"scheduled.{trigger_id}",
                "source": "scheduler",
                "subject": trigger["name"],
                "payload": {**trigger.get("payload_template", {}), "trigger_id": trigger_id},
                "correlation_id": trigger_id,
            })
            log.info("Fired scheduled trigger: %s", trigger_id)
            fired += 1
        except NovaClientError as exc:
            log.warning("Failed to fire trigger %s: %s", trigger_id, exc)

    return fired
```

- [ ] **Step 5: Run tests — confirm all pass**

```bash
pytest tests/test_scheduler.py -v
```

Expected: all 18 scheduler tests pass (the 4 new cron tests + 14 rewritten existing tests).

- [ ] **Step 6: Commit**

```bash
git add services/nova-lite/requirements.txt \
        services/nova-lite/app/logic/scheduler.py \
        services/nova-lite/tests/test_scheduler.py
git commit -m "feat(nova-lite): rewrite scheduler _is_due with croniter"
```

---

## Task 4: Nova Tool Handlers (`system_health`, `daily_summary`)

**Files:**
- Create: `services/api/app/tools/nova_handlers.py`
- Create: `services/api/tests/test_nova_handlers.py`
- Modify: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_nova_handlers.py`:

```python
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone


def test_system_health_all_green(db_session):
    from app.tools.nova_handlers import handle_system_health
    with patch("shutil.disk_usage", return_value=(1000, 500, 500)):  # 50% used
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=40)):
            result = handle_system_health({}, db_session)
    assert result["status"] == "ok"
    assert "disk" in result["message"].lower()


def test_system_health_disk_threshold(db_session):
    from app.tools.nova_handlers import handle_system_health
    with patch("shutil.disk_usage", return_value=(1000, 50, 950)):  # 95% used
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=40)):
            result = handle_system_health({}, db_session)
    assert result["status"] == "action_needed"
    assert "disk" in result["title"].lower()


def test_system_health_memory_threshold(db_session):
    from app.tools.nova_handlers import handle_system_health
    with patch("shutil.disk_usage", return_value=(1000, 500, 500)):
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=95)):
            result = handle_system_health({}, db_session)
    assert result["status"] == "action_needed"
    assert "memory" in result["title"].lower()


def test_system_health_stale_tasks(db_session):
    from app.tools.nova_handlers import handle_system_health
    from app.models.task import Task
    stale = Task(
        id="stale-1",
        title="old",
        status="pending",
        priority="normal",
        risk_class="low",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    db_session.add(stale)
    db_session.commit()
    with patch("shutil.disk_usage", return_value=(1000, 500, 500)):
        with patch("psutil.virtual_memory", return_value=MagicMock(percent=40)):
            result = handle_system_health({}, db_session)
    assert result["status"] == "action_needed"
    assert "stale" in result["title"].lower()


def test_daily_summary_returns_ok_with_message(db_session):
    from app.tools.nova_handlers import handle_daily_summary
    with patch("app.llm_client.route_internal", return_value="Summary text here."):
        result = handle_daily_summary({"window_hours": 24}, db_session)
    assert result["status"] == "ok"
    assert "Summary text here." in result["message"]
    assert "Daily summary" in result["message"]
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd services/api
pytest tests/test_nova_handlers.py -v
```

Expected: ImportError (module doesn't exist yet).

- [ ] **Step 3: Implement the handlers module**

Create `services/api/app/tools/nova_handlers.py`:

```python
"""
Handlers for the two default scheduled triggers: system health + daily summary.

Both return the typed contract:
    {"status": "ok", "message": str}
    {"status": "action_needed", "title": str, "description": str, "details": dict | None}
"""
import logging
import shutil
from datetime import datetime, timedelta, timezone

import psutil
from sqlalchemy.orm import Session

from app import llm_client
from app.models.run import Run
from app.models.task import Task
from app.models.event import Event

log = logging.getLogger(__name__)

DISK_THRESHOLD_PCT = 85
MEMORY_THRESHOLD_PCT = 90
STALE_TASK_HOURS = 24
FAILED_RUN_RATE_THRESHOLD = 0.5


def handle_system_health(input: dict, db: Session) -> dict:
    """Deterministic health check: disk, memory, stale tasks, recent failed runs."""
    total, used, free = shutil.disk_usage("/")
    disk_pct = (used / total) * 100 if total else 0
    if disk_pct > DISK_THRESHOLD_PCT:
        return {
            "status": "action_needed",
            "title": f"Disk at {disk_pct:.0f}% (container `/`)",
            "description": (
                f"Container root disk usage is {disk_pct:.0f}% "
                f"(used {used // (1024**3)}GB of {total // (1024**3)}GB). "
                "Free space or investigate what's filling the volume."
            ),
            "details": {"disk_pct": disk_pct, "used_bytes": used, "total_bytes": total},
        }

    mem_pct = psutil.virtual_memory().percent
    if mem_pct > MEMORY_THRESHOLD_PCT:
        return {
            "status": "action_needed",
            "title": f"Memory at {mem_pct:.0f}%",
            "description": (
                f"System memory at {mem_pct:.0f}% — investigate leaks or resize."
            ),
            "details": {"memory_pct": mem_pct},
        }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_TASK_HOURS)
    stale_count = (
        db.query(Task)
        .filter(Task.status.in_(["pending", "running"]))
        .filter(Task.created_at < cutoff)
        .count()
    )
    if stale_count > 0:
        return {
            "status": "action_needed",
            "title": f"{stale_count} stale task(s)",
            "description": (
                f"{stale_count} task(s) have been pending/running for > "
                f"{STALE_TASK_HOURS}h — review triage pipeline."
            ),
            "details": {"stale_count": stale_count},
        }

    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_runs = db.query(Run).filter(Run.started_at >= hour_ago).all()
    if recent_runs:
        failed = sum(1 for r in recent_runs if r.status == "failed")
        rate = failed / len(recent_runs)
        if rate > FAILED_RUN_RATE_THRESHOLD:
            return {
                "status": "action_needed",
                "title": f"{failed}/{len(recent_runs)} recent runs failed",
                "description": (
                    f"{failed} of {len(recent_runs)} runs in the last hour failed "
                    f"({rate:.0%}). Investigate which tool(s) are breaking."
                ),
                "details": {"failed": failed, "total": len(recent_runs)},
            }

    return {
        "status": "ok",
        "message": (
            f"disk {disk_pct:.0f}%, mem {mem_pct:.0f}%, "
            f"{stale_count} stale, "
            f"{sum(1 for r in recent_runs if r.status == 'failed')}/{len(recent_runs)} runs failed 1h"
        ),
    }


def _build_summary_digest(db: Session, hours: int) -> str:
    """Collect last N hours of events, runs, task transitions into a text digest."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    events = db.query(Event).filter(Event.timestamp >= since).order_by(Event.timestamp).all()
    runs = db.query(Run).filter(Run.started_at >= since).order_by(Run.started_at).all()
    tasks_completed = (
        db.query(Task)
        .filter(Task.status.in_(["done", "failed"]))
        .filter(Task.updated_at >= since)
        .order_by(Task.updated_at)
        .all()
    )

    lines = [f"Activity digest for the last {hours} hours:", ""]
    lines.append(f"Events: {len(events)}")
    for e in events[:20]:
        lines.append(f"  - [{e.type}] {e.subject or ''} (source={e.source})")
    if len(events) > 20:
        lines.append(f"  ... {len(events) - 20} more")

    lines.append("")
    lines.append(f"Tool runs: {len(runs)}")
    by_tool: dict[str, dict] = {}
    for r in runs:
        by_tool.setdefault(r.tool_name, {"ok": 0, "failed": 0})
        by_tool[r.tool_name]["ok" if r.status == "succeeded" else "failed"] += 1
    for tool, counts in by_tool.items():
        lines.append(f"  - {tool}: {counts['ok']} ok, {counts['failed']} failed")

    lines.append("")
    lines.append(f"Tasks completed/failed: {len(tasks_completed)}")
    for t in tasks_completed[:20]:
        lines.append(f"  - [{t.status}] {t.title}")
    if len(tasks_completed) > 20:
        lines.append(f"  ... {len(tasks_completed) - 20} more")

    return "\n".join(lines)


def handle_daily_summary(input: dict, db: Session) -> dict:
    """LLM-summarize the last N hours of activity. Always returns ok — the Run record IS the artifact."""
    hours = int(input.get("window_hours", 24))
    digest = _build_summary_digest(db, hours)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system = (
        "You are Nova's daily-digest summarizer. Given a raw activity digest, "
        "produce a 4-8 sentence human-readable summary. Highlight anything unusual "
        "(high failure rate, repeated errors, stalled tasks). Keep it concise."
    )

    try:
        summary = llm_client.route_internal(
            db,
            purpose="summarize_daily",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": digest},
            ],
        )
    except Exception as exc:
        log.warning("daily_summary LLM failed, falling back to raw digest: %s", exc)
        summary = digest

    return {
        "status": "ok",
        "message": f"Daily summary — {today}\n\n{summary}",
    }
```

- [ ] **Step 4: Register in tool registry**

The existing `_REGISTRY` in `services/api/app/tools/handlers.py` stores tuples of `(handler_fn, deps)` where `deps` is a list of dep names (`"db"` or `"settings"`) that `dispatch()` passes as positional args. Both new handlers need `db`.

In `services/api/app/tools/handlers.py`, import and add to `_REGISTRY`:

```python
from app.tools.nova_handlers import handle_system_health, handle_daily_summary

_REGISTRY = {
    # ... existing entries ...
    "nova.system_health": (handle_system_health, ["db"]),
    "nova.daily_summary": (handle_daily_summary, ["db"]),
}
```

Do NOT change the dispatch function — it already handles the `["db"]` dep pattern correctly.

- [ ] **Step 5: Register in tool seed**

In `services/api/app/tools/seed.py`, add to the `tool_definitions` list in `seed_tools`. The `Tool` model requires `display_name` and `adapter_type` as NOT NULL — the entries MUST include them (and match the style of the existing entries at lines 72-85):

```python
dict(
    name="nova.system_health",
    display_name="Nova: System Health",
    description="Check Nova's own health — disk, memory, stale tasks, recent run failures.",
    adapter_type="internal",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={"type": "object"},
    risk_class="low",
    requires_approval=False,
    timeout_seconds=10,
    enabled=True,
    tags=["nova", "monitoring"],
),
dict(
    name="nova.daily_summary",
    display_name="Nova: Daily Summary",
    description="Summarize the last N hours of activity into a human-readable digest.",
    adapter_type="internal",
    input_schema={
        "type": "object",
        "properties": {"window_hours": {"type": "integer", "minimum": 1, "maximum": 168}},
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
    risk_class="low",
    requires_approval=False,
    timeout_seconds=30,
    enabled=True,
    tags=["nova", "summary"],
),
```

- [ ] **Step 6: Update `test_tools.py::test_get_tools_returns_seeded_tools`**

The test asserts **set equality** on the exact name set (not just a count). In `services/api/tests/test_tools.py` line 11, add `"nova.system_health"` and `"nova.daily_summary"` to the expected set. The assertion currently reads something like:

```python
assert {"debug.echo", "ha.light.turn_on", "devops.summarize_ci_failure", "ha.light.turn_off",
        "http.request", "shell.run", "fs.list", "fs.read", "nova.query_activity"} == names
```

Update to:

```python
assert {"debug.echo", "ha.light.turn_on", "devops.summarize_ci_failure", "ha.light.turn_off",
        "http.request", "shell.run", "fs.list", "fs.read", "nova.query_activity",
        "nova.system_health", "nova.daily_summary"} == names
```

- [ ] **Step 7: Run tests — confirm pass**

```bash
pytest tests/test_nova_handlers.py tests/test_tools.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add services/api/app/tools/nova_handlers.py \
        services/api/app/tools/handlers.py \
        services/api/app/tools/seed.py \
        services/api/tests/test_nova_handlers.py \
        services/api/tests/test_tools.py
git commit -m "feat(api): add nova.system_health and nova.daily_summary tool handlers"
```

---

## Task 5: Triage Scheduler-Source Branching

**Files:**
- Modify: `services/nova-lite/app/logic/triage.py`
- Modify: `services/nova-lite/tests/conftest.py`
- Create: `services/nova-lite/tests/test_triage_scheduler.py`

- [ ] **Step 1: Extend `FakeClient.invoke_tool` return shape**

In `services/nova-lite/tests/conftest.py`, the current `invoke_tool` returns `self._invoke_result`. Tests need to control the response shape per tool.

**Important:** the real `NovaClient.invoke_tool` returns the API's `/tools/{name}/invoke` response envelope:

```python
{"run_id": "r-1", "status": "succeeded", "output": {<handler return>}, "error": None}
```

The handler's `{status: "ok"|"action_needed", ...}` lives in `output`, NOT at the top level. Tests MUST mirror that envelope, or they'll paper over a real bug in the scheduler triage path.

Update `invoke_tool` to:

```python
def invoke_tool(self, tool_name: str, input: dict, task_id: str | None = None) -> dict:
    # Tests can set _invoke_result_by_tool = {"nova.system_health": {<handler output>}}
    # We wrap that output in the real envelope so triage code paths match production.
    by_tool = getattr(self, "_invoke_result_by_tool", {})
    if tool_name in by_tool:
        return {
            "run_id": f"run-{tool_name}",
            "status": "succeeded",
            "output": by_tool[tool_name],
            "error": None,
        }
    return self._invoke_result
```

And add `self._invoke_result_by_tool: dict[str, dict] = {}` to `__init__` after `_invoke_result`.

- [ ] **Step 2: Write failing tests**

Create `services/nova-lite/tests/test_triage_scheduler.py`:

```python
from app.logic import triage


def test_scheduler_tool_event_bypasses_llm(fake_client):
    event = {
        "id": "evt-1",
        "type": "scheduled.system-heartbeat",
        "source": "scheduler",
        "subject": "System Heartbeat",
        "payload": {"tool": "nova.system_health", "input": {}, "trigger_id": "system-heartbeat"},
    }
    fake_client._invoke_result_by_tool = {
        "nova.system_health": {"status": "ok", "message": "all clear"},
    }

    triage.classify_and_create(fake_client, event)

    # No LLM call should have happened (fake_client._llm_response was never consumed)
    # No task should have been created for ok status
    assert len(fake_client.tasks) == 0


def test_scheduler_tool_event_ok_creates_no_task(fake_client):
    event = {
        "id": "evt-1", "type": "scheduled.x", "source": "scheduler",
        "subject": "X", "payload": {"tool": "nova.system_health", "input": {}, "trigger_id": "x"},
    }
    fake_client._invoke_result_by_tool = {
        "nova.system_health": {"status": "ok", "message": "all clear"},
    }
    triage.classify_and_create(fake_client, event)
    assert len(fake_client.tasks) == 0


def test_scheduler_tool_event_action_needed_creates_task(fake_client):
    event = {
        "id": "evt-1", "type": "scheduled.x", "source": "scheduler",
        "subject": "Heartbeat", "payload": {"tool": "nova.system_health", "input": {}, "trigger_id": "x"},
    }
    fake_client._invoke_result_by_tool = {
        "nova.system_health": {
            "status": "action_needed",
            "title": "Disk at 95%",
            "description": "Free space or investigate.",
            "details": {"disk_pct": 95},
        },
    }
    triage.classify_and_create(fake_client, event)
    assert len(fake_client.tasks) == 1
    task = list(fake_client.tasks.values())[0]
    assert task["title"] == "Disk at 95%"
    assert "Free space" in task["description"]
    assert task["origin_event_id"] == "evt-1"


def test_scheduler_goal_event_creates_task_with_goal_description(fake_client):
    event = {
        "id": "evt-2", "type": "scheduled.x", "source": "scheduler",
        "subject": "SideProject daily digest",
        "payload": {"goal": "Check r/SideProject and summarize top 5 posts", "trigger_id": "x"},
    }
    triage.classify_and_create(fake_client, event)
    assert len(fake_client.tasks) == 1
    task = list(fake_client.tasks.values())[0]
    assert "SideProject daily digest" in task["title"]
    assert task["description"] == "Check r/SideProject and summarize top 5 posts"


def test_non_scheduler_event_still_uses_llm(fake_client):
    """Regression: non-scheduler events still go through the LLM classify path."""
    fake_client._llm_response = '{"title": "Classified Title", "description": "d", "priority": "normal", "risk_class": "low", "labels": []}'
    event = {
        "id": "evt-3", "type": "user.request", "source": "human",
        "subject": "x", "payload": {"message": "do the thing"},
    }
    triage.classify_and_create(fake_client, event)
    assert len(fake_client.tasks) == 1
    task = list(fake_client.tasks.values())[0]
    assert task["title"] == "Classified Title"
```

- [ ] **Step 3: Run tests — confirm failures**

```bash
cd services/nova-lite
pytest tests/test_triage_scheduler.py -v
```

Expected: failures — triage still uses LLM for everything.

- [ ] **Step 4: Add scheduler-source branch to triage**

In `services/nova-lite/app/logic/triage.py`, add the branch near the top of `classify_and_create`:

```python
import datetime as _dt


def _handle_scheduler_tool_event(client, event: dict, payload: dict) -> dict | None:
    """Invoke the tool directly; return task-create dict if action_needed, else None.

    `client.invoke_tool` returns the /tools/{name}/invoke envelope:
        {"run_id", "status": "succeeded|failed", "output": {<handler output>}, "error"}
    The handler's escalation status lives in `output.status`.
    """
    tool_name = payload["tool"]
    tool_input = payload.get("input", {})
    envelope = client.invoke_tool(tool_name, tool_input)

    if envelope.get("status") == "failed":
        log.warning("scheduler tool %s failed: %s", tool_name, envelope.get("error"))
        return {
            "title": f"{tool_name} failed",
            "description": envelope.get("error") or "tool invocation failed",
            "priority": "normal",
            "risk_class": "low",
            "origin_event_id": event["id"],
            "labels": ["scheduler", tool_name, "tool-failure"],
        }

    output = envelope.get("output") or {}
    handler_status = output.get("status")
    if handler_status == "ok":
        return None
    if handler_status == "action_needed":
        return {
            "title": output.get("title") or event.get("subject") or tool_name,
            "description": output.get("description"),
            "priority": "normal",
            "risk_class": "low",
            "origin_event_id": event["id"],
            "labels": ["scheduler", tool_name],
        }
    log.warning(
        "scheduler tool %s returned unknown handler status %r; treating as action_needed",
        tool_name, handler_status,
    )
    return {
        "title": event.get("subject") or tool_name,
        "description": str(output),
        "priority": "normal",
        "risk_class": "low",
        "origin_event_id": event["id"],
        "labels": ["scheduler", tool_name, "unexpected-shape"],
    }


def _handle_scheduler_goal_event(event: dict, payload: dict) -> dict:
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    trigger_name = event.get("subject") or payload.get("trigger_id") or "scheduled goal"
    return {
        "title": f"{trigger_name} — {today}",
        "description": payload["goal"],
        "priority": "normal",
        "risk_class": "low",
        "origin_event_id": event["id"],
        "labels": ["scheduler", "goal"],
    }


def classify_and_create(client, event: dict) -> dict | None:
    """Given an event, classify it and create a Task. Deduplicates by origin_event_id."""
    existing = client.get_tasks(origin_event_id=event["id"], limit=1)
    if existing:
        log.debug("Task already exists for event %s, skipping", event["id"])
        return existing[0]

    # ── Scheduler-source fast path ──
    if event.get("source") == "scheduler":
        payload = event.get("payload") or {}
        if "tool" in payload:
            task_fields = _handle_scheduler_tool_event(client, event, payload)
            if task_fields is None:
                return None  # clean — no task, Run record is the activity
            return client.post_task(task_fields)
        if "goal" in payload:
            return client.post_task(_handle_scheduler_goal_event(event, payload))
        log.warning("scheduler event %s has neither tool nor goal in payload; falling through to LLM", event["id"])

    # ── LLM classify path (existing behavior) ──
    prompt = _build_triage_prompt(event)
    try:
        response = client.llm_route(
            purpose="triage",
            messages=[{"role": "user", "content": prompt}],
        )
        fields = _parse_triage_response(response)
    except NovaClientError as exc:
        log.warning("LLM unavailable during triage for event %s: %s", event["id"], exc)
        fields = None

    if fields is None:
        log.warning(
            "Triage LLM response unparseable for event %s, using subject as title",
            event["id"],
        )
        fields = {}

    return client.post_task({
        "title": fields.get("title") or event["subject"],
        "description": fields.get("description"),
        "priority": fields.get("priority", "normal"),
        "risk_class": fields.get("risk_class", "low"),
        "origin_event_id": event["id"],
        "labels": fields.get("labels", []),
    })
```

- [ ] **Step 5: Run tests — confirm all pass**

```bash
pytest tests/test_triage_scheduler.py tests/test_triage.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/nova-lite/app/logic/triage.py \
        services/nova-lite/tests/conftest.py \
        services/nova-lite/tests/test_triage_scheduler.py
git commit -m "feat(nova-lite): route scheduler-source events via direct invoke / goal-task"
```

---

## Task 6: Ollama Model Swap + Health `model_ready`

**Files:**
- Modify: `services/api/app/config.py`
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/app/routers/health.py`
- Modify: `services/api/tests/test_health.py`

- [ ] **Step 1: Write failing test for `model_ready`**

Append to `services/api/tests/test_health.py`:

```python
def test_health_includes_model_ready(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "model_ready" in data
    assert isinstance(data["model_ready"], bool)
```

- [ ] **Step 2: Run test — confirm failure**

```bash
cd services/api
pytest tests/test_health.py::test_health_includes_model_ready -v
```

- [ ] **Step 3: Update config default**

In `services/api/app/config.py` line 11, change:

```python
ollama_model: str = "gemma3:4b"
```

to:

```python
ollama_model: str = "qwen2.5-coder:7b"
```

- [ ] **Step 4: Flip `supports_tools=True` in seed**

In `services/api/app/tools/seed.py`, in `seed_llm_providers`, change the insert branch:

```python
provider = LLMProviderProfile(
    id="ollama-local",
    # ... existing fields ...
    supports_tools=True,  # was False
    # ... rest ...
)
```

Also ensure existing rows flip: add to the update branch right after `provider.enabled = True`:

```python
provider.supports_tools = True
```

This ensures re-seed on restart picks up the flag even for existing installations.

- [ ] **Step 5: Add `model_ready` to health**

In `services/api/app/routers/health.py`, extend the health response:

```python
import httpx
from app.config import settings

def _check_model_ready() -> bool:
    if not settings.ollama_base_url:
        return False
    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
        if not resp.is_success:
            return False
        tags = resp.json().get("models", [])
        return any(m.get("name", "").startswith(settings.ollama_model.split(":")[0]) for m in tags)
    except Exception:
        return False


@router.get("/health")
def health():
    db_ok = check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "model_ready": _check_model_ready(),
    }
```

- [ ] **Step 6: Pull the model**

On the host, ensure the model is available to Ollama:

```bash
ollama pull qwen2.5-coder:7b
```

If this fails (model unavailable, disk full), abort and flag. The model is required.

- [ ] **Step 7: Rebuild, run tests, verify health**

```bash
cd /home/jeremy/workspace/nova-suite
./dev --build
sleep 15
curl -s http://localhost:8000/health | jq
```

Expected: `{"status": "ok", "db": "ok", "model_ready": true}`.

Then:

```bash
cd services/api && pytest tests/test_health.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add services/api/app/config.py \
        services/api/app/tools/seed.py \
        services/api/app/routers/health.py \
        services/api/tests/test_health.py
git commit -m "feat(api): switch default LLM to qwen2.5-coder:7b with tool-calling enabled"
```

---

## Task 7: Conversations — `pending_tool_call` State

**Files:**
- Create: `services/api/alembic/versions/0006_conversation_pending_tool_call.py`
- Modify: `services/api/app/models/conversation.py`

- [ ] **Step 1: Write the migration**

Create `services/api/alembic/versions/0006_conversation_pending_tool_call.py`:

```python
"""add pending_tool_call to conversations

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import JSON

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("pending_tool_call", JSON(), nullable=True))
    op.add_column("conversations", sa.Column("pending_tool_call_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "pending_tool_call_at")
    op.drop_column("conversations", "pending_tool_call")
```

- [ ] **Step 2: Update the `Conversation` model**

In `services/api/app/models/conversation.py`, add the two columns:

```python
# imports if needed:
from sqlalchemy.types import JSON

# in the class:
    pending_tool_call = Column(JSON, nullable=True)
    pending_tool_call_at = Column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Rebuild and verify migration applied**

```bash
cd /home/jeremy/workspace/nova-suite
./dev --build
docker compose -f infra/docker-compose.yml exec db \
  psql -U nova -d nova -c "\d conversations" | grep pending_tool_call
```

Expected: both columns shown.

- [ ] **Step 4: Existing conversation tests still pass**

```bash
cd services/api
pytest tests/test_conversations.py -v --tb=short
```

Expected: no new failures. Pre-existing `test_low_confidence_falls_through_no_run` may still fail — that's unrelated to this task.

- [ ] **Step 5: Commit**

```bash
git add services/api/alembic/versions/0006_conversation_pending_tool_call.py \
        services/api/app/models/conversation.py
git commit -m "feat(api): add pending_tool_call state to conversations"
```

---

## Task 8: Conversations — Tool-Calling Loop

**Files:**
- Modify: `services/api/app/routers/conversations.py`
- Modify: `services/api/app/llm_client.py` (or wherever `route_internal`/`route` lives)
- Create: `services/api/tests/test_tool_calling_loop.py`

This task replaces the one-shot intent classifier with a real tool-calling loop. Read `services/api/app/routers/conversations.py` in full before starting — the changes are significant but localized.

**Pre-read (required before Step 1):**
1. Full `services/api/app/routers/conversations.py` — understand current `send_message` flow, especially the closure trick with `generate()` and the streaming/non-streaming branches
2. `services/api/tests/test_conversations.py` — note which tests exercise the classifier path (listed in Step 5 below)
3. `services/api/app/llm_client.py` — understand how `route_internal` currently works (the new `route_with_tools` follows the same pattern)
4. How `_build_system_prompt(db)` constructs the system message today (lines 38-68) — after this change, the `Available tools:` section should be removed (the tool catalog is passed as a structured `tools` param now, not prose in the prompt)

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_tool_calling_loop.py`:

```python
from unittest.mock import patch


def test_non_sensitive_tool_call_auto_executes(client, db_session):
    """A list_triggers call runs immediately, no confirmation gate."""
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)

    # Mock the LLM to emit a tool call for list_triggers, then a final text response
    with patch("app.llm_client.route_with_tools") as mock_llm:
        mock_llm.side_effect = [
            {"tool_calls": [{"name": "scheduler.list_triggers", "arguments": {}}]},
            {"content": "You have 2 triggers: system-heartbeat and daily-summary."},
        ]

        conv = client.post("/conversations").json()
        resp = client.post(f"/conversations/{conv['id']}/messages", json={"content": "list my triggers"})

        # Final streamed response contains text
        text = resp.text
        assert "2 triggers" in text or "list_triggers" in text


def test_sensitive_tool_call_stores_pending(client, db_session):
    """scheduler.create_trigger is intercepted and prompts for confirmation."""
    with patch("app.llm_client.route_with_tools") as mock_llm:
        mock_llm.return_value = {"tool_calls": [{
            "name": "scheduler.create_trigger",
            "arguments": {
                "id": "sideproject-daily",
                "name": "SideProject daily",
                "cron_expression": "0 9 * * *",
                "payload_template": {"goal": "Check r/SideProject"},
            },
        }]}

        conv = client.post("/conversations").json()
        resp = client.post(f"/conversations/{conv['id']}/messages",
                           json={"content": "create a trigger: every day 9am check reddit"})
        # Response should contain confirmation prompt
        assert "Confirm" in resp.text

        # DB should have pending_tool_call set
        from app.models.conversation import Conversation
        conv_row = db_session.query(Conversation).filter_by(id=conv["id"]).first()
        assert conv_row.pending_tool_call is not None
        assert conv_row.pending_tool_call["name"] == "scheduler.create_trigger"


def test_confirmation_yes_commits_pending(client, db_session):
    """User says 'yes' → pending dispatched, cleared."""
    from app.models.conversation import Conversation
    from datetime import datetime, timezone

    # Seed a conversation with a pending tool call
    conv = Conversation(
        id="c-1",
        title="test",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        pending_tool_call={
            "name": "scheduler.create_trigger",
            "arguments": {
                "id": "test-t",
                "name": "Test",
                "cron_expression": "0 9 * * *",
                "payload_template": {"goal": "test"},
            },
        },
        pending_tool_call_at=datetime.now(timezone.utc),
    )
    db_session.add(conv)
    db_session.commit()

    resp = client.post("/conversations/c-1/messages", json={"content": "yes"})
    # Pending should be cleared
    db_session.expire_all()
    conv = db_session.query(Conversation).filter_by(id="c-1").first()
    assert conv.pending_tool_call is None


def test_confirmation_no_clears_pending(client, db_session):
    """User says 'no' → pending cleared, tool NOT dispatched."""
    # ... similar setup, send "no", assert pending is None and no trigger was created
    pass  # implement parallel to test_confirmation_yes_commits_pending


def test_whole_word_confirm_yesterday_does_not_match(client, db_session):
    """'yesterday' must NOT match the 'yes' confirmation pattern."""
    from app.routers.conversations import CONFIRM_RE
    assert CONFIRM_RE.search("yesterday") is None
    assert CONFIRM_RE.search("yes") is not None
    assert CONFIRM_RE.search("yes please") is not None
```

- [ ] **Step 2: Add `route_with_tools` to `llm_client`**

`services/api/app/llm_client.py` needs a new function that issues an LLM call with tools. The OpenAI-compatible Ollama endpoint supports `tools` param in chat completions. Add:

```python
def route_with_tools(db, purpose: str, messages: list[dict], tools: list[dict]) -> dict:
    """Issue an LLM call with tool catalog. Returns {content: str} or {tool_calls: [...]}."""
    # Look up active provider as in route_internal
    provider = _active_provider(db)
    openai_client = _build_client(provider)
    resp = openai_client.chat.completions.create(
        model=provider.model_ref,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )
    choice = resp.choices[0].message
    if choice.tool_calls:
        return {"tool_calls": [
            {"name": tc.function.name, "arguments": json.loads(tc.function.arguments)}
            for tc in choice.tool_calls
        ]}
    return {"content": choice.content or ""}
```

Adjust to match the existing pattern of `route_internal` in the same file.

- [ ] **Step 3: Rewrite conversations tool path**

In `services/api/app/routers/conversations.py`, replace the intent-classifier block (between the `_parse_json_safe` helper and the `generate()` definition) with a tool-calling loop.

**Structural changes to make, in order:**

1. Delete the `_parse_json_safe` helper (no longer needed — structured `tools` param is authoritative).
2. Delete the classify-messages block, the classify call, and the post-classify Run creation / dispatch block (everything from `tool_list = ...` through `tool_context = ...`).
3. Simplify `_build_system_prompt` — remove the `Available tools:` block (lines in the range of the current prompt that include `tool_lines`). The new system prompt should be focused on: Nova's identity, model, and current pending tasks. The tool catalog is now passed as structured `tools` on the LLM call, not as prose.
4. Add the module-level constants (SENSITIVE_TOOLS, CONFIRM_RE, DENY_RE, MAX_TOOL_TURNS, PENDING_TIMEOUT_MINUTES).
5. Add the helpers below (`_tool_catalog`, `_check_pending_confirmation`, `_render_confirmation`, `_record_run`, `_dispatch_tool_call`).
6. Rewrite the body of `send_message` per the skeleton below.

**Module-level additions:**

```python
import re

CONFIRM_RE = re.compile(r"\b(yes|yep|yeah|confirm|confirmed|do it|go ahead|proceed)\b", re.I)
DENY_RE    = re.compile(r"\b(no|nope|cancel|stop|abort|nvm|never ?mind)\b", re.I)

SENSITIVE_TOOLS = {
    "scheduler.create_trigger",
    "scheduler.update_trigger",
    "scheduler.delete_trigger",
}
MAX_TOOL_TURNS = 3
PENDING_TIMEOUT_MINUTES = 30


def _tool_catalog(db: Session) -> list[dict]:
    """Build OpenAI-format tool list from enabled tools."""
    tools = db.query(Tool).filter(Tool.enabled == True).all()  # noqa: E712
    return [{
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema or {"type": "object"},
        },
    } for t in tools]


def _check_pending_confirmation(conv: Conversation, user_msg: str) -> tuple[str, dict | None]:
    """Returns ("confirm"|"deny"|"none", pending_call_or_None)."""
    if not conv.pending_tool_call:
        return "none", None
    age = datetime.now(timezone.utc) - (conv.pending_tool_call_at or datetime.now(timezone.utc))
    if age.total_seconds() > PENDING_TIMEOUT_MINUTES * 60:
        return "none", None
    if CONFIRM_RE.search(user_msg):
        return "confirm", conv.pending_tool_call
    if DENY_RE.search(user_msg):
        return "deny", conv.pending_tool_call
    return "none", None


def _render_confirmation(tool_name: str, args: dict) -> str:
    verb = {"create": "create", "update": "update", "delete": "delete"}.get(
        tool_name.split(".")[1].split("_")[0], "run"
    )
    lines = [f"I'll {verb} this trigger:"]
    if "name" in args:
        lines.append(f"- **Name:** {args['name']}")
    if "cron_expression" in args:
        lines.append(f"- **Schedule:** `{args['cron_expression']}`")
    if "payload_template" in args:
        p = args["payload_template"]
        if "goal" in p:
            lines.append(f"- **Goal:** {p['goal']}")
        elif "tool" in p:
            lines.append(f"- **Tool:** {p['tool']}")
    lines.append("\nConfirm?")
    return "\n".join(lines)


def _record_run(db: Session, tool_name: str, tool_input: dict, output: dict | None, error: str | None = None) -> None:
    """Persist a Run row for tool-call audit. Matches the existing chat path's Run creation."""
    run = Run(
        id=str(uuid4()),
        tool_name=tool_name,
        task_id=None,
        executor_type="chat",
        trigger_type="chat",
        input=tool_input,
        status="failed" if error else "succeeded",
        output=output,
        error=error,
        summary=f"{tool_name} → {'failed' if error else 'succeeded'}",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()


def _dispatch_tool_call(db: Session, tc: dict) -> dict:
    """Run a non-sensitive tool synchronously; record Run; return the output for LLM context."""
    name = tc["name"]
    args = tc.get("arguments") or {}
    try:
        output = tool_handlers.dispatch(name, args, db, _settings)
        _record_run(db, name, args, output, error=None)
        return output
    except Exception as exc:
        _record_run(db, name, args, output=None, error=str(exc))
        return {"error": str(exc)}
```

**Send-message body skeleton** (replace everything from the current `# --- Phase 1: Intent classification ---` comment down to where `generate()` is defined, keeping the `generate()` + `StreamingResponse` skeleton intact — only the inputs to `generate()` change):

```python
# Resolution order at the top of the synchronous work (before `generate()` is defined):

# --- Step A: Handle pending confirmation if present ---
verdict, pending = _check_pending_confirmation(conv, body.content)
if verdict == "confirm":
    # Dispatch and produce the assistant reply text
    tool_output = _dispatch_tool_call(db, pending)
    conv.pending_tool_call = None
    conv.pending_tool_call_at = None
    db.commit()
    final_text = tool_output.get("summary") or f"Done. {json.dumps(tool_output)}"
elif verdict == "deny":
    conv.pending_tool_call = None
    conv.pending_tool_call_at = None
    db.commit()
    final_text = "Cancelled."
else:
    # --- Step B: Regular tool-calling loop ---
    system_content = _build_system_prompt(db)  # now tool-catalog-free
    messages = [{"role": "system", "content": system_content}]
    for m in history:
        messages.append({"role": m.role, "content": m.content})

    tools = _tool_catalog(db)
    final_text = None
    for turn in range(MAX_TOOL_TURNS):
        result = llm_client.route_with_tools(db, purpose="chat", messages=messages, tools=tools)
        if result.get("content") and not result.get("tool_calls"):
            final_text = result["content"]
            break
        tool_calls = result.get("tool_calls") or []
        # Check for a sensitive call — if any, store pending + break
        sensitive = next((tc for tc in tool_calls if tc["name"] in SENSITIVE_TOOLS), None)
        if sensitive:
            conv.pending_tool_call = sensitive
            conv.pending_tool_call_at = datetime.now(timezone.utc)
            db.commit()
            final_text = _render_confirmation(sensitive["name"], sensitive.get("arguments") or {})
            break
        # Auto-execute all tool_calls and continue the loop
        for tc in tool_calls:
            output = _dispatch_tool_call(db, tc)
            messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
            messages.append({"role": "tool", "name": tc["name"], "content": json.dumps(output)})
    if final_text is None:
        final_text = "I reached the maximum tool-calling turns. Please rephrase."

# --- Step C: define generate() that streams final_text (same pattern as existing code) ---
```

**Streaming contract:** keep the SSE streaming skeleton exactly as today — `generate()` yields chunks of `final_text`, the response sets `media_type="text/event-stream"`. The non-streaming branch (if one exists based on a header) just returns `{"content": final_text}` after persistence.

**Assistant message persistence:** the existing code persists the assistant message after `generate()` drains. Preserve that — `final_text` is what gets persisted, as before.

- [ ] **Step 4: Update pre-existing classifier-era tests in `test_conversations.py`**

The existing test file has a bundle of tests tied to the intent-classifier path. After the rewrite, they MUST be updated or deleted — a subagent that runs the full suite without handling these will see a regression wall. Specifically:

**Delete outright (the mechanism no longer exists):**
- `test_parse_json_safe_parses_plain_json` (line ~186)
- `test_parse_json_safe_strips_markdown_fences` (line ~193)
- `test_parse_json_safe_returns_none_on_invalid` (line ~199)
- `test_low_confidence_falls_through_no_run` (line ~228) — the "confidence threshold" concept doesn't exist in the tool-calling loop

**Rewrite to the new mechanism:**
- `test_action_intent_executes_tool_and_creates_run` (line ~205) — keep the assertion that a tool call produces a Run; change the setup to mock `llm_client.route_with_tools` returning a tool_call dict instead of classifier JSON
- `test_unknown_tool_falls_through_no_run` (line ~246) — keep the assertion that unknown tool names don't create Runs; update setup to have `route_with_tools` return a tool_call with a bogus name → `tool_handlers.dispatch` raises KeyError → `_dispatch_tool_call` records a failed Run (or skips; decide based on the new `_dispatch_tool_call` contract. Spec above records a failed Run; reflect that in the updated assertion.)
- `test_action_sse_emits_running_acknowledgment` (line ~264) — rewrite to assert the new streaming shape. If the new implementation doesn't emit a `[Running tool...]` acknowledgment, either add one (nice UX, keeps the existing contract) OR delete this test and document the UX loss.

**Keep unchanged (should still pass):**
- `test_create_conversation_returns_id_and_title`, `test_list_conversations_*`, `test_get_messages_*`, `test_send_message_non_streaming`, `test_send_message_persists_user_message`, `test_send_message_sse_streams_chunks`, `test_send_message_sse_persists_assistant_message`, `test_send_message_sets_title_*`, `test_send_message_conversation_not_found` — these test the conversation/message plumbing which is unchanged.

- [ ] **Step 5: Run tests — iterate until all pass**

```bash
cd services/api
pytest tests/test_tool_calling_loop.py tests/test_conversations.py -v --tb=short
```

Expected: all new tests pass; the rewrites above pass; the deletions are gone. Run the full api suite to confirm no wider regression:

```bash
pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add services/api/app/routers/conversations.py \
        services/api/app/llm_client.py \
        services/api/tests/test_tool_calling_loop.py \
        services/api/tests/test_conversations.py
git commit -m "feat(api): replace intent classifier with tool-calling loop + pending confirmation"
```

---

## Task 9: Scheduler Management Tools

**Files:**
- Create: `services/api/app/tools/scheduler_handlers.py`
- Modify: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py`
- Create: `services/api/tests/test_scheduler_handlers.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_scheduler_handlers.py`:

```python
def test_scheduler_create_trigger_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_create_trigger
    result = handle_scheduler_create_trigger({
        "id": "my-trigger",
        "name": "My Trigger",
        "cron_expression": "0 9 * * *",
        "payload_template": {"goal": "Check something"},
    }, db_session)
    assert "my-trigger" in result["summary"]

    from app.models.scheduled_trigger import ScheduledTrigger
    assert db_session.query(ScheduledTrigger).filter_by(id="my-trigger").first() is not None


def test_scheduler_list_triggers_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_list_triggers
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    result = handle_scheduler_list_triggers({}, db_session)
    ids = {t["id"] for t in result["triggers"]}
    assert "system-heartbeat" in ids
    assert "daily-summary" in ids


def test_scheduler_update_trigger_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_update_trigger
    from app.tools.seed import seed_scheduled_triggers
    from app.models.scheduled_trigger import ScheduledTrigger
    seed_scheduled_triggers(db_session)
    result = handle_scheduler_update_trigger({
        "id": "system-heartbeat",
        "updates": {"enabled": False},
    }, db_session)
    db_session.expire_all()
    trigger = db_session.query(ScheduledTrigger).filter_by(id="system-heartbeat").first()
    assert trigger.enabled is False


def test_scheduler_delete_trigger_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_delete_trigger
    from app.tools.seed import seed_scheduled_triggers
    from app.models.scheduled_trigger import ScheduledTrigger
    seed_scheduled_triggers(db_session)
    result = handle_scheduler_delete_trigger({"id": "daily-summary"}, db_session)
    assert "daily-summary" in result["summary"]
    assert db_session.query(ScheduledTrigger).filter_by(id="daily-summary").first() is None


def test_scheduler_create_invalid_cron_raises(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_create_trigger
    import pytest
    with pytest.raises(Exception):  # Pydantic ValidationError wrapped
        handle_scheduler_create_trigger({
            "id": "bad",
            "name": "Bad",
            "cron_expression": "not a cron",
            "payload_template": {"goal": "x"},
        }, db_session)
```

- [ ] **Step 2: Run tests — confirm ImportError**

```bash
pytest tests/test_scheduler_handlers.py -v
```

- [ ] **Step 3: Implement the handlers**

Create `services/api/app/tools/scheduler_handlers.py`:

```python
"""
Tool handlers that manage scheduled triggers from chat.
Operate in-process via SQLAlchemy session — no HTTP loop-back.
"""
from sqlalchemy.orm import Session

from app.models.scheduled_trigger import ScheduledTrigger
from app.schemas.scheduled_trigger import ScheduledTriggerCreate, ScheduledTriggerUpdate


def handle_scheduler_create_trigger(input: dict, db: Session) -> dict:
    body = ScheduledTriggerCreate(**input)  # raises ValidationError if invalid
    if db.query(ScheduledTrigger).filter_by(id=body.id).first():
        raise ValueError(f"Trigger '{body.id}' already exists")
    trigger = ScheduledTrigger(**body.model_dump())
    db.add(trigger)
    db.commit()
    return {"id": body.id, "summary": f"Created trigger '{body.name}' ({body.cron_expression})"}


def handle_scheduler_list_triggers(input: dict, db: Session) -> dict:
    triggers = db.query(ScheduledTrigger).order_by(ScheduledTrigger.id).all()
    return {
        "triggers": [
            {
                "id": t.id,
                "name": t.name,
                "cron_expression": t.cron_expression,
                "enabled": t.enabled,
                "payload_kind": "tool" if "tool" in (t.payload_template or {}) else "goal",
                "last_fired_at": t.last_fired_at.isoformat() if t.last_fired_at else None,
            }
            for t in triggers
        ]
    }


def handle_scheduler_update_trigger(input: dict, db: Session) -> dict:
    trigger_id = input["id"]
    updates = input.get("updates") or {}
    trigger = db.query(ScheduledTrigger).filter_by(id=trigger_id).first()
    if not trigger:
        raise ValueError(f"Trigger '{trigger_id}' not found")
    body = ScheduledTriggerUpdate(**updates)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(trigger, field, value)
    db.commit()
    return {"summary": f"Updated trigger '{trigger_id}'", "applied": body.model_dump(exclude_unset=True)}


def handle_scheduler_delete_trigger(input: dict, db: Session) -> dict:
    trigger_id = input["id"]
    trigger = db.query(ScheduledTrigger).filter_by(id=trigger_id).first()
    if not trigger:
        raise ValueError(f"Trigger '{trigger_id}' not found")
    db.delete(trigger)
    db.commit()
    return {"summary": f"Deleted trigger '{trigger_id}'"}
```

- [ ] **Step 4: Register in tool registry**

All four scheduler handlers take `(input, db)`, so register as `(handler, ["db"])` tuples.

In `services/api/app/tools/handlers.py`, extend `_REGISTRY`:

```python
from app.tools.scheduler_handlers import (
    handle_scheduler_create_trigger,
    handle_scheduler_list_triggers,
    handle_scheduler_update_trigger,
    handle_scheduler_delete_trigger,
)

_REGISTRY = {
    # ... existing ...
    "scheduler.create_trigger": (handle_scheduler_create_trigger, ["db"]),
    "scheduler.list_triggers": (handle_scheduler_list_triggers, ["db"]),
    "scheduler.update_trigger": (handle_scheduler_update_trigger, ["db"]),
    "scheduler.delete_trigger": (handle_scheduler_delete_trigger, ["db"]),
}
```

- [ ] **Step 5: Register in tool seed**

In `services/api/app/tools/seed.py`, add to `tool_definitions`. The `Tool` model requires `display_name` and `adapter_type`; each entry MUST include them:

```python
dict(
    name="scheduler.create_trigger",
    display_name="Scheduler: Create Trigger",
    description=(
        "Create a new scheduled trigger. For recurring tasks like 'check reddit daily' "
        "or 'ping this URL every hour'. Use when the user asks to schedule, remind, or "
        "automate something on an interval."
    ),
    adapter_type="internal",
    input_schema={
        "type": "object",
        "required": ["id", "name", "cron_expression", "payload_template"],
        "properties": {
            "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,63}$",
                   "description": "kebab-case identifier"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "cron_expression": {"type": "string",
                                "description": "standard 5-field cron, UTC (e.g. '0 9 * * *')"},
            "payload_template": {
                "type": "object",
                "description": "Either {tool, input} or {goal: string}",
            },
            "active_hours_start": {"type": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]$"},
            "active_hours_end":   {"type": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]$"},
        },
    },
    output_schema={"type": "object"},
    risk_class="low",
    requires_approval=False,
    timeout_seconds=10,
    enabled=True,
    tags=["scheduler"],
),
dict(
    name="scheduler.list_triggers",
    display_name="Scheduler: List Triggers",
    description="List all scheduled triggers and their state. Use when the user asks 'what triggers do I have?'",
    adapter_type="internal",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={"type": "object"},
    risk_class="low",
    requires_approval=False,
    timeout_seconds=5,
    enabled=True,
    tags=["scheduler"],
),
dict(
    name="scheduler.update_trigger",
    display_name="Scheduler: Update Trigger",
    description=(
        "Update an existing trigger (enable/disable, change schedule or payload). "
        "Use when the user asks to pause, resume, or reschedule."
    ),
    adapter_type="internal",
    input_schema={
        "type": "object",
        "required": ["id", "updates"],
        "properties": {
            "id": {"type": "string"},
            "updates": {"type": "object"},
        },
    },
    output_schema={"type": "object"},
    risk_class="low",
    requires_approval=False,
    timeout_seconds=5,
    enabled=True,
    tags=["scheduler"],
),
dict(
    name="scheduler.delete_trigger",
    display_name="Scheduler: Delete Trigger",
    description="Permanently remove a scheduled trigger. Use when the user asks to delete or remove one.",
    adapter_type="internal",
    input_schema={
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "string"}},
    },
    output_schema={"type": "object"},
    risk_class="medium",
    requires_approval=False,
    timeout_seconds=5,
    enabled=True,
    tags=["scheduler"],
),
```

- [ ] **Step 6: Update `test_tools.py::test_get_tools_returns_seeded_tools`**

Extend the expected set (the one already updated in Task 4) with the four new scheduler tool names:

```python
assert {..., "nova.system_health", "nova.daily_summary",
        "scheduler.create_trigger", "scheduler.list_triggers",
        "scheduler.update_trigger", "scheduler.delete_trigger"} == names
```

- [ ] **Step 7: Run tests — confirm all pass**

```bash
pytest tests/test_scheduler_handlers.py tests/test_tools.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add services/api/app/tools/scheduler_handlers.py \
        services/api/app/tools/handlers.py \
        services/api/app/tools/seed.py \
        services/api/tests/test_scheduler_handlers.py \
        services/api/tests/test_tools.py
git commit -m "feat(api): add scheduler.* management tools (create/list/update/delete)"
```

---

## Task 10: Settings — Read-Only Trigger Panel

**Files:**
- Create: `services/board/src/lib/cron-to-nl.ts`
- Create: `services/board/src/api/triggers.ts`
- Create: `services/board/src/components/Settings/ScheduledTriggersPanel.tsx`
- Modify: `services/board/src/components/Settings/Settings.tsx`

- [ ] **Step 1: Cron → human-readable helper**

Create `services/board/src/lib/cron-to-nl.ts`:

```typescript
/**
 * Convert common cron expressions to human-readable English.
 * Covers the 80% case; returns raw expression for anything else.
 */
export function cronToHuman(cron: string): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [minute, hour, dom, month, dow] = parts

  // every minute
  if (cron === "* * * * *") return "every minute"
  // every N minutes
  const everyNMin = minute.match(/^\*\/(\d+)$/)
  if (everyNMin && hour === "*" && dom === "*" && month === "*" && dow === "*") {
    return `every ${everyNMin[1]} minutes`
  }
  // daily at HH:MM
  if (/^\d+$/.test(minute) && /^\d+$/.test(hour) && dom === "*" && month === "*" && dow === "*") {
    const hh = hour.padStart(2, "0")
    const mm = minute.padStart(2, "0")
    return `every day at ${hh}:${mm} UTC`
  }
  // weekdays at HH:MM
  if (/^\d+$/.test(minute) && /^\d+$/.test(hour) && dom === "*" && month === "*" && dow === "1-5") {
    return `every weekday at ${hour.padStart(2, "0")}:${minute.padStart(2, "0")} UTC`
  }
  // hourly at :MM
  if (/^\d+$/.test(minute) && hour === "*" && dom === "*" && month === "*" && dow === "*") {
    return `every hour at :${minute.padStart(2, "0")}`
  }
  return cron
}
```

- [ ] **Step 2: API fetch helper**

Create `services/board/src/api/triggers.ts`:

```typescript
import { apiFetch } from "./base"

export interface Trigger {
  id: string
  name: string
  description: string | null
  cron_expression: string
  active_hours_start: string | null
  active_hours_end: string | null
  enabled: boolean
  payload_template: Record<string, unknown>
  last_fired_at: string | null
}

export function getTriggers(): Promise<{ triggers: Trigger[] }> {
  return apiFetch("/system/triggers")
}
```

(Adjust import path of `apiFetch` to match existing `base.ts`/`llm.ts` convention.)

- [ ] **Step 3: Panel component**

Create `services/board/src/components/Settings/ScheduledTriggersPanel.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query"
import { getTriggers } from "../../api/triggers"
import { cronToHuman } from "../../lib/cron-to-nl"

export function ScheduledTriggersPanel() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["triggers"],
    queryFn: getTriggers,
    refetchOnWindowFocus: true,
  })

  if (isLoading) return <div>Loading triggers...</div>
  if (error) return <div>Failed to load triggers.</div>

  const triggers = data?.triggers ?? []

  return (
    <section>
      <h3>Scheduled Triggers</h3>
      {triggers.length === 0 ? (
        <p>No triggers configured.</p>
      ) : (
        <ul>
          {triggers.map(t => {
            const kind = "tool" in (t.payload_template as object) ? "tool" : "goal"
            const payloadLabel = kind === "tool"
              ? `runs: ${(t.payload_template as any).tool}`
              : `goal: ${(t.payload_template as any).goal}`
            return (
              <li key={t.id}>
                <strong>{t.name}</strong>
                <div>{cronToHuman(t.cron_expression)} • {t.enabled ? "enabled" : "disabled"}</div>
                <div>{payloadLabel}</div>
                {t.last_fired_at && <div>last fired: {new Date(t.last_fired_at).toLocaleString()}</div>}
              </li>
            )
          })}
        </ul>
      )}
      <p><em>To add, edit, or remove triggers, ask Nova in chat.</em></p>
    </section>
  )
}
```

- [ ] **Step 4: Wire into Settings**

In `services/board/src/components/Settings/Settings.tsx`, import and render `<ScheduledTriggersPanel />` after the existing LLM provider section. Match the existing section styling.

- [ ] **Step 5: Manual UI smoke check**

```bash
cd /home/jeremy/workspace/nova-suite
./dev --build
```

Open `http://localhost:5173`, navigate to Settings, confirm the Scheduled Triggers section renders both seeded triggers with human-readable schedules ("every 30 minutes" and "every day at 00:00 UTC").

- [ ] **Step 6: Commit**

```bash
git add services/board/src/lib/cron-to-nl.ts \
        services/board/src/api/triggers.ts \
        services/board/src/components/Settings/ScheduledTriggersPanel.tsx \
        services/board/src/components/Settings/Settings.tsx
git commit -m "feat(board): read-only scheduled triggers panel in Settings"
```

---

## Task 11: End-to-End Smoke Test

No code changes — validation only.

- [ ] **Step 1: Fresh rebuild**

```bash
cd /home/jeremy/workspace/nova-suite
./dev --build
sleep 20
```

- [ ] **Step 2: Verify health**

```bash
curl -s http://localhost:8000/health | jq
```

Expected: `{"status": "ok", "db": "ok", "model_ready": true}`.

- [ ] **Step 3: Verify triggers seeded with cron**

```bash
curl -s http://localhost:8000/system/triggers | jq '.triggers[] | {id, cron_expression, payload_template}'
```

Expected: both triggers show `cron_expression` and `{tool: "nova.system_health"|"nova.daily_summary", input: {...}}`.

- [ ] **Step 4: Manually fire heartbeat by clearing last_fired_at**

```bash
curl -s -X PATCH http://localhost:8000/system/triggers/system-heartbeat \
  -H "Content-Type: application/json" \
  -d '{"last_fired_at": null}' | jq
```

- [ ] **Step 5: Wait one scheduler tick (≤15s) and observe**

```bash
sleep 20
curl -s "http://localhost:8000/events?limit=5" | jq '.events[] | {type, source}'
curl -s "http://localhost:8000/runs?limit=5" | jq '.runs[] | {tool_name, status, output}'
curl -s "http://localhost:8000/tasks?limit=5" | jq '.tasks[] | {title, status}'
```

Expected:
- Events shows `scheduled.system-heartbeat` with `source=scheduler`.
- Runs shows a `nova.system_health` run with status `succeeded` and an output dict containing `status: "ok"` + a message.
- Tasks: no new task created for the clean heartbeat.

- [ ] **Step 6: Force an escalation and confirm task creation**

Run the API container with a patched high-disk value temporarily, or just insert a stale task to trip the stale-task check:

```bash
docker compose -f infra/docker-compose.yml exec db psql -U nova -d nova <<'SQL'
INSERT INTO tasks (id, title, status, priority, risk_class, created_at, updated_at)
VALUES ('stale-smoke-test', 'stale seed', 'pending', 'normal', 'low',
        now() - interval '48 hours', now() - interval '48 hours');
SQL
```

Clear last_fired_at again (Step 4 command) and wait:

```bash
sleep 20
curl -s "http://localhost:8000/tasks?limit=5" | jq '.tasks[] | {title, status, origin_event_id}'
```

Expected: a new task with title like "1 stale task(s)" linked to a scheduled event.

Clean up the stale seed:

```bash
docker compose -f infra/docker-compose.yml exec db psql -U nova -d nova -c "DELETE FROM tasks WHERE id = 'stale-smoke-test'"
```

- [ ] **Step 7: Chat-driven trigger creation (manual)**

Open http://localhost:5173 → Chat tab. Type:

> every day at 9am UTC, run debug.echo with a hello message

Nova's LLM should:
- Recognize scheduling intent
- Call `scheduler.create_trigger` with `cron="0 9 * * *"`, payload `{"tool": "debug.echo", "input": {"message": "hello"}}`
- Reply with confirmation prompt
- On "yes" → commit

Verify via:

```bash
curl -s http://localhost:8000/system/triggers | jq '.triggers[] | select(.id | contains("debug") or contains("echo") or contains("hello"))'
```

Expected: the new trigger appears.

Open Settings panel in the board, confirm the new trigger shows.

Delete via chat ("remove the debug echo trigger"). Confirm it's gone.

- [ ] **Step 8: Full test suite pass**

```bash
cd /home/jeremy/workspace/nova-suite/services/api && pytest tests/ --tb=short
cd /home/jeremy/workspace/nova-suite/services/nova-lite && pytest tests/ --tb=short
```

Expected:
- API: all pass except previously-known unrelated failures (document final counts).
- Nova-lite: all pass (should be 54+ now).

- [ ] **Step 9: Push**

```bash
cd /home/jeremy/workspace/nova-suite
git push origin main
```

No commit for Task 11 itself (no code changes).

---

## Rollback Plan

If anything in Task 7 or 8 goes wrong in production:

- Revert Task 7's conversations rewrite by pointing HEAD at the pre-Task-7 SHA; the intent-classifier path still lives in git history and restores cleanly.
- Migrations `0005` and `0006` have working `downgrade()` functions. Run `alembic downgrade -2` in the API container to roll back both if needed.
- The Ollama model swap (Task 6) is settings-only — Settings panel lets the user switch back to the previous default (`gemma3:4b`) without touching code.

## Dependencies Between Tasks

- Tasks 1-2 are API foundation, no dependencies.
- Task 3 (nova-lite cron) depends on Task 1's seed format.
- Task 4 (handlers) is independent but must land before Task 5 (triage uses them via invoke_tool contract).
- Task 5 (triage) depends on Tasks 1, 3, 4.
- Task 6 (model swap) is independent; must land before Task 8 uses tool-calling.
- Task 7 (pending_tool_call migration) is independent.
- Task 8 (tool-calling loop) depends on Tasks 6 + 7.
- Task 9 (scheduler.* tools) depends on Task 8 (wrapped in tool-calling) but handlers can be written + unit-tested before Task 8 ships.
- Task 10 (Settings UI) depends on Tasks 1-2 for the API shape.
- Task 11 integration test depends on all prior tasks.
