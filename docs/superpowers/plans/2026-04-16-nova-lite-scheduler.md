# Nova-Lite Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a proactive scheduled-trigger system to nova-lite so it generates its own work on a configurable interval, and fix the post-approval "ready" task gap.

**Architecture:** A `scheduled_triggers` DB table (seeded from defaults like tools) defines named triggers with intervals. Each nova-lite loop tick checks for due triggers and emits a `POST /events` for each — reusing the existing triage → plan → execute pipeline with zero new code paths. The "ready" task gap is fixed with a one-line addition to the main loop.

**Tech Stack:** Python 3.12, SQLAlchemy (Postgres), Alembic, FastAPI, httpx, pytest

---

## File Map

**New files:**
| File | Responsibility |
|---|---|
| `services/api/app/models/scheduled_trigger.py` | SQLAlchemy model for `scheduled_triggers` table |
| `services/api/app/schemas/scheduled_trigger.py` | Pydantic read/update/list schemas |
| `services/api/app/routers/system.py` | `GET /system/triggers`, `PATCH /system/triggers/{id}` |
| `services/api/tests/test_system.py` | API-level tests for system router |
| `services/nova-lite/app/logic/scheduler.py` | Due-trigger check + event emission logic |
| `services/nova-lite/tests/test_scheduler.py` | Unit tests for scheduler module |

**Modified files:**
| File | Change |
|---|---|
| `services/api/app/models/__init__.py` | Register `ScheduledTrigger` |
| `services/api/app/tools/seed.py` | Add `seed_scheduled_triggers()` |
| `services/api/app/main.py` | Register system router; call seed |
| `services/api/alembic/versions/` | New migration for `scheduled_triggers` table |
| `services/nova-lite/app/client.py` | Add `get_scheduled_triggers()`, `patch_scheduled_trigger()`, `post_event()` |
| `services/nova-lite/tests/conftest.py` | Add scheduler methods to `FakeClient` |
| `services/nova-lite/app/main.py` | Add scheduler branch; fetch `pending + ready` tasks |

---

## Task 1: ScheduledTrigger DB Model

**Files:**
- Create: `services/api/app/models/scheduled_trigger.py`
- Modify: `services/api/app/models/__init__.py`

- [ ] **Step 1: Write the model**

```python
# services/api/app/models/scheduled_trigger.py
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.types import JSON
from app.database import Base


class ScheduledTrigger(Base):
    __tablename__ = "scheduled_triggers"

    id = Column(String, primary_key=True)        # e.g. "system-heartbeat"
    name = Column(String, nullable=False)         # display name
    description = Column(String, nullable=True)
    interval_seconds = Column(Integer, nullable=False)
    active_hours_start = Column(String, nullable=True)  # "09:00" UTC, or None = always
    active_hours_end = Column(String, nullable=True)    # "22:00" UTC, or None = always
    enabled = Column(Boolean, nullable=False, default=True)
    payload_template = Column(JSON, nullable=False, default=dict)
    last_fired_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 2: Register the model**

In `services/api/app/models/__init__.py`, add:

```python
from app.models.scheduled_trigger import ScheduledTrigger
```

And add `"ScheduledTrigger"` to the `__all__` list.

- [ ] **Step 3: Generate the Alembic migration**

With the Docker stack running (`./dev`), execute:

```bash
cd services/api
PYTHONPATH=. DATABASE_URL=postgresql://nova:nova@localhost:5432/nova \
  alembic revision --autogenerate -m "add_scheduled_triggers"
```

Expected: a new file appears in `alembic/versions/` named something like `0004_add_scheduled_triggers.py`.

Verify the generated migration contains `op.create_table("scheduled_triggers", ...)`. If autogenerate fails, write the migration manually:

```python
def upgrade() -> None:
    op.create_table(
        "scheduled_triggers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("active_hours_start", sa.String(), nullable=True),
        sa.Column("active_hours_end", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("payload_template", sa.JSON(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

def downgrade() -> None:
    op.drop_table("scheduled_triggers")
```

- [ ] **Step 4: Commit**

```bash
git add services/api/app/models/scheduled_trigger.py \
        services/api/app/models/__init__.py \
        services/api/alembic/versions/
git commit -m "feat(api): add ScheduledTrigger model and migration"
```

---

## Task 2: Schemas + System Router

**Files:**
- Create: `services/api/app/schemas/scheduled_trigger.py`
- Create: `services/api/app/routers/system.py`
- Modify: `services/api/app/main.py`

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_system.py`:

```python
import pytest


def test_list_triggers_empty(client):
    resp = client.get("/system/triggers")
    assert resp.status_code == 200
    assert resp.json()["triggers"] == []


def test_list_triggers_after_seed(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    resp = client.get("/system/triggers")
    assert resp.status_code == 200
    triggers = resp.json()["triggers"]
    assert len(triggers) == 2
    ids = {t["id"] for t in triggers}
    assert "system-heartbeat" in ids
    assert "daily-summary" in ids


def test_patch_trigger_enabled(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    resp = client.patch("/system/triggers/system-heartbeat", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_patch_trigger_last_fired_at(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    ts = "2026-04-16T12:00:00+00:00"
    resp = client.patch("/system/triggers/system-heartbeat", json={"last_fired_at": ts})
    assert resp.status_code == 200
    assert resp.json()["last_fired_at"] is not None


def test_patch_trigger_not_found(client):
    resp = client.patch("/system/triggers/nonexistent", json={"enabled": False})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd services/api
pytest tests/test_system.py -v
```

Expected: ImportError or 404 — router doesn't exist yet.

- [ ] **Step 3: Write the schemas**

Create `services/api/app/schemas/scheduled_trigger.py`:

```python
from datetime import datetime
from pydantic import BaseModel


class ScheduledTriggerRead(BaseModel):
    id: str
    name: str
    description: str | None
    interval_seconds: int
    active_hours_start: str | None
    active_hours_end: str | None
    enabled: bool
    payload_template: dict
    last_fired_at: datetime | None

    model_config = {"from_attributes": True}


class ScheduledTriggerUpdate(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None
    active_hours_start: str | None = None
    active_hours_end: str | None = None
    last_fired_at: datetime | None = None


class ScheduledTriggerListResponse(BaseModel):
    triggers: list[ScheduledTriggerRead]
```

- [ ] **Step 4: Write the system router**

Create `services/api/app/routers/system.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.scheduled_trigger import ScheduledTrigger
from app.schemas.scheduled_trigger import (
    ScheduledTriggerListResponse,
    ScheduledTriggerRead,
    ScheduledTriggerUpdate,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/triggers", response_model=ScheduledTriggerListResponse)
def list_triggers(db: Session = Depends(get_db)):
    triggers = db.query(ScheduledTrigger).order_by(ScheduledTrigger.id).all()
    return ScheduledTriggerListResponse(
        triggers=[ScheduledTriggerRead.model_validate(t) for t in triggers]
    )


@router.patch("/triggers/{trigger_id}", response_model=ScheduledTriggerRead)
def update_trigger(
    trigger_id: str,
    body: ScheduledTriggerUpdate,
    db: Session = Depends(get_db),
):
    trigger = db.query(ScheduledTrigger).filter(ScheduledTrigger.id == trigger_id).first()
    if not trigger:
        raise HTTPException(404, detail="Trigger not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(trigger, field, value)
    db.commit()
    db.refresh(trigger)
    return ScheduledTriggerRead.model_validate(trigger)
```

- [ ] **Step 5: Register the router in main.py**

In `services/api/app/main.py`, update the routers import to include `system`:

```python
from app.routers import health, tasks, events, board, tools, runs, approvals, entities, llm, conversations, activity, system
```

And add after the other `app.include_router(...)` calls:

```python
app.include_router(system.router)
```

- [ ] **Step 6: Run the two non-seed tests — expect pass**

```bash
cd services/api
pytest tests/test_system.py::test_list_triggers_empty \
       tests/test_system.py::test_patch_trigger_not_found -v
```

Expected: both pass. The three seed-dependent tests (`test_list_triggers_after_seed`, `test_patch_trigger_enabled`, `test_patch_trigger_last_fired_at`) will error with `ImportError` until `seed_scheduled_triggers` is added in Task 3 — skip them for now.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/schemas/scheduled_trigger.py \
        services/api/app/routers/system.py \
        services/api/app/main.py \
        services/api/tests/test_system.py
git commit -m "feat(api): add system router with scheduled trigger list + patch endpoints"
```

---

## Task 3: Seed Default Triggers

**Files:**
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/app/main.py`

- [ ] **Step 1: Add `seed_scheduled_triggers` to seed.py**

At the bottom of `services/api/app/tools/seed.py`, add:

```python
def seed_scheduled_triggers(db: Session) -> None:
    """Upsert default scheduled triggers. Preserves user-modified enabled/interval."""
    from app.models.scheduled_trigger import ScheduledTrigger

    defaults = [
        dict(
            id="system-heartbeat",
            name="System Heartbeat",
            description=(
                "Periodic system health check: disk usage, memory, running processes, "
                "and any pending work that needs attention."
            ),
            interval_seconds=1800,  # 30 minutes
            enabled=True,
            payload_template={"check": "system_health"},
        ),
        dict(
            id="daily-summary",
            name="Daily Summary",
            description=(
                "Review today's activity, surface unresolved tasks, "
                "and summarise what Nova has done in the past 24 hours."
            ),
            interval_seconds=86400,  # 24 hours
            enabled=True,
            payload_template={"check": "daily_summary"},
        ),
    ]

    for defn in defaults:
        trigger = (
            db.query(ScheduledTrigger)
            .filter(ScheduledTrigger.id == defn["id"])
            .first()
        )
        if trigger:
            # Refresh display fields only — preserve user's enabled/interval choices
            trigger.name = defn["name"]
            trigger.description = defn["description"]
        else:
            db.add(ScheduledTrigger(**defn))

    db.commit()
```

- [ ] **Step 2: Call it from main.py lifespan**

In `services/api/app/main.py`, update the import:

```python
from app.tools.seed import seed_tools, seed_llm_providers, seed_board_columns, seed_scheduled_triggers
```

And add it to the lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = _db.SessionLocal()
    try:
        seed_tools(db)
        seed_llm_providers(db, settings)
        seed_board_columns(db)
        seed_scheduled_triggers(db)
    finally:
        db.close()
    yield
```

- [ ] **Step 3: Run the seed tests**

```bash
cd services/api
pytest tests/test_system.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 4: Run the full API test suite to check for regressions**

```bash
cd services/api
pytest tests/ -v --tb=short
```

Expected: all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/tools/seed.py services/api/app/main.py
git commit -m "feat(api): seed default scheduled triggers (system-heartbeat, daily-summary)"
```

---

## Task 4: Nova-Lite Client + FakeClient

**Files:**
- Modify: `services/nova-lite/app/client.py`
- Modify: `services/nova-lite/tests/conftest.py`

- [ ] **Step 1: Add three methods to NovaClient**

In `services/nova-lite/app/client.py`, add after `llm_route()`:

```python
def get_scheduled_triggers(self) -> list[dict]:
    return self._request("GET", "/system/triggers")["triggers"]

def patch_scheduled_trigger(self, trigger_id: str, updates: dict) -> dict:
    return self._request("PATCH", f"/system/triggers/{trigger_id}", json=updates)

def post_event(self, payload: dict) -> dict:
    return self._request("POST", "/events", json=payload)
```

- [ ] **Step 2: Extend FakeClient in conftest.py**

In `services/nova-lite/tests/conftest.py`, make three targeted additions — do **not** replace the class:

**In `FakeClient.__init__`, append three new fields after the existing `_next_task_id` line:**

```python
        self.scheduled_triggers: list[dict] = []
        self.posted_events: list[dict] = []
        self.patched_triggers: dict[str, dict] = {}
```

**After the existing `invoke_tool` method, add three new methods:**

```python
    def get_scheduled_triggers(self) -> list[dict]:
        return self.scheduled_triggers

    def patch_scheduled_trigger(self, trigger_id: str, updates: dict) -> dict:
        self.patched_triggers[trigger_id] = updates
        return updates

    def post_event(self, payload: dict) -> dict:
        self.posted_events.append(payload)
        return {"id": f"evt-{len(self.posted_events)}", **payload}
```

- [ ] **Step 3: Run existing nova-lite tests — no regressions**

```bash
cd services/nova-lite
pytest tests/ -v --tb=short
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/nova-lite/app/client.py services/nova-lite/tests/conftest.py
git commit -m "feat(nova-lite): add get_scheduled_triggers, patch_scheduled_trigger, post_event to client"
```

---

## Task 5: Scheduler Module

**Files:**
- Create: `services/nova-lite/app/logic/scheduler.py`
- Create: `services/nova-lite/tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Create `services/nova-lite/tests/test_scheduler.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.logic.scheduler import _in_active_hours, _is_due, fire_due_triggers


# ── _is_due ────────────────────────────────────────────────────────────────

def test_is_due_never_fired():
    trigger = {"enabled": True, "interval_seconds": 1800, "last_fired_at": None}
    assert _is_due(trigger, datetime.now(timezone.utc)) is True


def test_is_due_recently_fired():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=60)).isoformat()
    trigger = {"enabled": True, "interval_seconds": 1800, "last_fired_at": recent}
    assert _is_due(trigger, now) is False


def test_is_due_interval_exactly_elapsed():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=1800)).isoformat()
    trigger = {"enabled": True, "interval_seconds": 1800, "last_fired_at": old}
    assert _is_due(trigger, now) is True


def test_is_due_interval_overdue():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=3600)).isoformat()
    trigger = {"enabled": True, "interval_seconds": 1800, "last_fired_at": old}
    assert _is_due(trigger, now) is True


def test_is_due_disabled_trigger():
    trigger = {"enabled": False, "interval_seconds": 1800, "last_fired_at": None}
    assert _is_due(trigger, datetime.now(timezone.utc)) is False


# ── _in_active_hours ────────────────────────────────────────────────────────

def test_in_active_hours_no_restriction():
    trigger = {"active_hours_start": None, "active_hours_end": None}
    assert _in_active_hours(trigger, datetime.now(timezone.utc)) is True


def test_in_active_hours_within_window():
    now = datetime(2026, 4, 16, 14, 30, tzinfo=timezone.utc)  # 2:30pm UTC
    trigger = {"active_hours_start": "09:00", "active_hours_end": "22:00"}
    assert _in_active_hours(trigger, now) is True


def test_in_active_hours_outside_window():
    now = datetime(2026, 4, 16, 3, 0, tzinfo=timezone.utc)  # 3:00am UTC
    trigger = {"active_hours_start": "09:00", "active_hours_end": "22:00"}
    assert _in_active_hours(trigger, now) is False


def test_in_active_hours_boundary_start():
    now = datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc)  # exactly 09:00
    trigger = {"active_hours_start": "09:00", "active_hours_end": "22:00"}
    assert _in_active_hours(trigger, now) is True


# ── fire_due_triggers ────────────────────────────────────────────────────────

def _make_trigger(trigger_id="system-heartbeat", last_fired_offset_seconds=None):
    now = datetime.now(timezone.utc)
    last_fired = None
    if last_fired_offset_seconds is not None:
        last_fired = (now - timedelta(seconds=last_fired_offset_seconds)).isoformat()
    return {
        "id": trigger_id,
        "name": "System Heartbeat",
        "enabled": True,
        "interval_seconds": 1800,
        "last_fired_at": last_fired,
        "active_hours_start": None,
        "active_hours_end": None,
        "payload_template": {"check": "system_health"},
    }


def test_fire_due_fires_overdue_trigger(fake_client):
    fake_client.scheduled_triggers = [_make_trigger(last_fired_offset_seconds=2000)]
    count = fire_due_triggers(fake_client)
    assert count == 1
    assert len(fake_client.posted_events) == 1
    event = fake_client.posted_events[0]
    assert event["type"] == "scheduled.system-heartbeat"
    assert event["source"] == "scheduler"
    assert "system-heartbeat" in fake_client.patched_triggers
    assert fake_client.patched_triggers["system-heartbeat"]["last_fired_at"] is not None


def test_fire_due_fires_never_fired_trigger(fake_client):
    fake_client.scheduled_triggers = [_make_trigger(last_fired_offset_seconds=None)]
    count = fire_due_triggers(fake_client)
    assert count == 1


def test_fire_due_skips_recent_trigger(fake_client):
    fake_client.scheduled_triggers = [_make_trigger(last_fired_offset_seconds=60)]
    count = fire_due_triggers(fake_client)
    assert count == 0
    assert len(fake_client.posted_events) == 0


def test_fire_due_skips_disabled_trigger(fake_client):
    trigger = _make_trigger()
    trigger["enabled"] = False
    fake_client.scheduled_triggers = [trigger]
    count = fire_due_triggers(fake_client)
    assert count == 0


def test_fire_due_multiple_triggers_mixed(fake_client):
    fake_client.scheduled_triggers = [
        _make_trigger("heartbeat", last_fired_offset_seconds=2000),  # due
        _make_trigger("summary", last_fired_offset_seconds=60),       # not due
    ]
    count = fire_due_triggers(fake_client)
    assert count == 1
    assert fake_client.posted_events[0]["type"] == "scheduled.heartbeat"


def test_fire_due_handles_client_error_gracefully(fake_client):
    from app.client import NovaClientError

    def raise_error():
        raise NovaClientError(503, "unavailable")

    fake_client.get_scheduled_triggers = raise_error
    count = fire_due_triggers(fake_client)
    assert count == 0  # graceful, no exception raised


def test_fire_due_event_contains_trigger_id_in_payload(fake_client):
    fake_client.scheduled_triggers = [_make_trigger(last_fired_offset_seconds=2000)]
    fire_due_triggers(fake_client)
    assert fake_client.posted_events[0]["payload"]["trigger_id"] == "system-heartbeat"
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd services/nova-lite
pytest tests/test_scheduler.py -v
```

Expected: `ImportError: cannot import name '_is_due' from 'app.logic.scheduler'`

- [ ] **Step 3: Implement the scheduler module**

Create `services/nova-lite/app/logic/scheduler.py`:

```python
"""
Check which scheduled triggers are due and emit an event for each.

Each fired trigger:
  1. POSTs to /events with type "scheduled.{trigger_id}"
  2. PATCHes the trigger's last_fired_at so it won't re-fire this interval
"""
import logging
from datetime import datetime, timezone

from app.client import NovaClientError

log = logging.getLogger(__name__)


def _is_due(trigger: dict, now: datetime) -> bool:
    """Return True if the trigger should fire now."""
    if not trigger.get("enabled"):
        return False
    last_fired = trigger.get("last_fired_at")
    if last_fired is None:
        return True
    if isinstance(last_fired, str):
        last_fired_dt = datetime.fromisoformat(last_fired.replace("Z", "+00:00"))
    else:
        last_fired_dt = last_fired
    return (now - last_fired_dt).total_seconds() >= trigger["interval_seconds"]


def _in_active_hours(trigger: dict, now: datetime) -> bool:
    """Return True if current UTC time is within the trigger's active window."""
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
            client.post_event({
                "type": f"scheduled.{trigger_id}",
                "source": "scheduler",
                "subject": trigger["name"],
                "payload": {
                    **trigger.get("payload_template", {}),
                    "trigger_id": trigger_id,
                },
                "correlation_id": trigger_id,
            })
            client.patch_scheduled_trigger(trigger_id, {
                "last_fired_at": now.isoformat(),
            })
            log.info("Fired scheduled trigger: %s", trigger_id)
            fired += 1
        except NovaClientError as exc:
            log.warning("Failed to fire trigger %s: %s", trigger_id, exc)

    return fired
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd services/nova-lite
pytest tests/test_scheduler.py -v
```

Expected: all 16 tests pass.

- [ ] **Step 5: Run the full nova-lite test suite — no regressions**

```bash
cd services/nova-lite
pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/nova-lite/app/logic/scheduler.py \
        services/nova-lite/tests/test_scheduler.py
git commit -m "feat(nova-lite): add scheduler module — fire due scheduled triggers as events"
```

---

## Task 6: Wire Scheduler Into Loop + Fix Ready Tasks

**Files:**
- Modify: `services/nova-lite/app/main.py`

- [ ] **Step 1: Read test_main.py to understand current test structure**

```bash
cat services/nova-lite/tests/test_main.py
```

- [ ] **Step 2: Write one new failing test in test_main.py**

The `run_loop` scheduler integration is already covered by `test_scheduler.py`. The critical gap to test here is that `process_task` accepts "ready" status tasks (the post-approval fix). Add to `services/nova-lite/tests/test_main.py`:

```python
# process_task is already imported at the top of test_main.py — do not re-import it.
def test_process_task_handles_ready_status(fake_client):
    """Tasks with status='ready' (post-approval) are processed the same as pending."""
    fake_client.tools = [{"name": "debug.echo", "description": "echo", "input_schema": {}}]
    fake_client._llm_response = '{"actions": [], "reasoning": "nothing to do"}'
    task = {
        "id": "task-ready-1",
        "title": "Approved task",
        "status": "ready",
        "risk_class": "low",
        "approval_required": False,
        "description": None,
        "goal": None,
    }
    fake_client.tasks["task-ready-1"] = task  # required: FakeClient.patch_task looks up by id
    process_task(fake_client, task)
    assert fake_client.tasks["task-ready-1"]["status"] == "done"
```

- [ ] **Step 3: Run test — expect pass immediately**

```bash
cd services/nova-lite
pytest tests/test_main.py::test_process_task_handles_ready_status -v
```

Expected: PASS — `process_task` has no status check; it processes any task passed to it. This test validates the contract so the loop change in Step 4 is safe. The integration point (run_loop fetching "ready" tasks) is verified at smoke-test time in Task 7.

- [ ] **Step 4: Update main.py**

In `services/nova-lite/app/main.py`:

1. Add `scheduler` to the logic imports:

```python
from app.logic import executor, planner, summarizer, triage, scheduler
```

2. In `run_loop`, replace the task-fetching section and add the scheduler branch:

```python
def run_loop(client: NovaClient, state: CursorState) -> None:
    while _running:
        try:
            cursor = state.load_cursor()

            # ── 0. Fire due scheduled triggers ──────────────────────────
            scheduler.fire_due_triggers(client)

            # ── 1. Triage new events ──────────────────────────────────
            events = client.get_events(since=cursor, limit=10)
            for event in events:
                try:
                    triage.classify_and_create(client, event)
                    cursor = event["timestamp"]
                except NovaClientError as e:
                    log.warning("Triage failed for event %s: %s", event.get("id"), e)
            state.save_cursor(cursor)

            # ── 2. Act on pending + ready tasks ──────────────────────
            pending = client.get_tasks(status="pending", limit=5)
            ready = client.get_tasks(status="ready", limit=5)
            for task in pending + ready:
                try:
                    process_task(client, task)
                except NovaClientError as e:
                    log.warning("Processing failed for task %s: %s", task.get("id"), e)

        except Exception as e:
            log.error("Loop error: %s", e, exc_info=True)

        if _running:
            time.sleep(settings.loop_interval_seconds)
```

- [ ] **Step 5: Run the new test — expect pass**

```bash
cd services/nova-lite
pytest tests/test_main.py -v --tb=short
```

Expected: all tests pass including `test_process_task_handles_ready_status`.

- [ ] **Step 6: Run the full test suite one final time**

```bash
cd services/nova-lite && pytest tests/ -v --tb=short
cd services/api && pytest tests/ -v --tb=short
```

Expected: all tests pass in both services.

- [ ] **Step 7: Commit**

```bash
git add services/nova-lite/app/main.py \
        services/nova-lite/tests/test_main.py
git commit -m "feat(nova-lite): wire scheduler into loop and process ready tasks post-approval"
```

---

## Task 7: Build + Smoke Test

- [ ] **Step 1: Build the Docker stack**

```bash
./dev --build
```

Expected: all images build successfully.

- [ ] **Step 2: Verify migration ran**

```bash
docker compose -f infra/docker-compose.yml exec db \
  psql -U nova -d nova -c "\dt scheduled_triggers"
```

Expected: table exists with columns.

- [ ] **Step 3: Verify triggers seeded**

```bash
curl -s http://localhost:5173/system/triggers | jq .
```

Expected:
```json
{
  "triggers": [
    {"id": "daily-summary", "enabled": true, "interval_seconds": 86400, ...},
    {"id": "system-heartbeat", "enabled": true, "interval_seconds": 1800, ...}
  ]
}
```

- [ ] **Step 4: Manually fire a trigger by clearing last_fired_at**

```bash
curl -s -X PATCH http://localhost:5173/system/triggers/system-heartbeat \
  -H "Content-Type: application/json" \
  -d '{"last_fired_at": null}' | jq .
```

Wait 15–30 seconds (one nova-lite loop tick). Then check the activity feed or events:

```bash
curl -s "http://localhost:5173/events?limit=5" | jq '.events[].type'
```

Expected: `"scheduled.system-heartbeat"` appears.

Check for a task created from triage:

```bash
curl -s "http://localhost:5173/tasks?limit=5" | jq '.tasks[] | {title, status}'
```

Expected: a task with title derived from "System Heartbeat" appears.

- [ ] **Step 5: Final commit and push**

```bash
git push
```

---

## Design Advantages Over OpenClaw Heartbeat

| Concern | OpenClaw | Nova |
|---|---|---|
| LLM cost per tick | Always (even no-ops) | Only when a trigger fires and triage/planner run |
| Suppression mechanism | Fragile HEARTBEAT_OK string at start/end of response | No suppression needed — noop triggers just don't fire |
| Schedule storage | YAML file or HEARTBEAT.md | DB table — runtime-modifiable, auditable |
| Deduplication | None | `last_fired_at` guard + existing `origin_event_id` task dedup |
| Code paths | Separate heartbeat session path | Reuses existing triage → plan → execute pipeline |
| Active hours | Config YAML | Per-trigger DB columns, patchable at runtime |
| Session contamination | Known bug (#56941) | No session concept — each event is stateless |
