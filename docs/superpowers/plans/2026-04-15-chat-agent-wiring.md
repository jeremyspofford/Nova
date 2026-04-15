# Chat–Agent Wiring & Activity Log — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire chat messages to Nova's tool execution engine via intent classification, and replace the kanban Board tab with a read-only Activity log.

**Architecture:** The chat path gains a pre-generator classification step: classify intent → execute tool synchronously → capture result as closure variable → stream response with tool context injected. The Activity tab reads from the Run table (augmented with `trigger_type` + `summary` columns) via a new `GET /activity` endpoint.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite + Alembic (backend), React + Zustand + Vitest + Testing Library (frontend), pytest with unittest.mock (backend tests)

---

## File Map

**Backend — Create:**
- `services/api/alembic/versions/0003_add_run_trigger_type_and_summary.py`
- `services/api/app/schemas/activity.py`
- `services/api/app/routers/activity.py`
- `services/api/tests/test_activity.py`

**Backend — Modify:**
- `services/api/app/models/run.py` — add `trigger_type` + `summary` columns
- `services/api/app/tools/handlers.py` — add `ha.light.turn_off` + `http.request` handlers + registry entries
- `services/api/app/tools/seed.py` — add seed entries for 2 new tools
- `services/api/app/routers/conversations.py` — add `_parse_json_safe`, classification logic, generator restructure
- `services/api/app/main.py` — include activity router
- `services/api/tests/test_tool_handlers.py` — add tests for 2 new handlers
- `services/api/tests/test_conversations.py` — add intent classification + tool execution tests

**Frontend — Create:**
- `services/board/src/api/activity.ts`
- `services/board/src/components/Activity/ActivityFeed.tsx`
- `services/board/src/components/Activity/__tests__/ActivityFeed.test.tsx`

**Frontend — Modify:**
- `services/board/src/stores/uiStore.ts` — `"board"` → `"activity"` tab type
- `services/board/src/api/types.ts` — add `ActivityEntry` + `ActivityResponse` types
- `services/board/src/AppShell.tsx` — rename Board tab to Activity, render `ActivityFeed`
- `services/board/src/styles/global.css` — add activity feed CSS
- `services/board/src/components/__tests__/AppShell.test.tsx` — update board → activity

---

### Task 1: DB migration — add trigger_type and summary to Run

**Files:**
- Create: `services/api/alembic/versions/0003_add_run_trigger_type_and_summary.py`
- Modify: `services/api/app/models/run.py`

- [ ] **Step 1: Create the migration file**

Create `services/api/alembic/versions/0003_add_run_trigger_type_and_summary.py`:

```python
"""add trigger_type and summary to runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("trigger_type", sa.String(), nullable=False, server_default="agent_loop"),
    )
    op.add_column(
        "runs",
        sa.Column("summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "summary")
    op.drop_column("runs", "trigger_type")
```

- [ ] **Step 2: Update the Run SQLAlchemy model**

In `services/api/app/models/run.py`:

Change the import line from:
```python
from sqlalchemy import Column, DateTime, String, func
```
to:
```python
from sqlalchemy import Column, DateTime, String, Text, func
```

Add two columns after `executor_id`:
```python
    trigger_type = Column(String, nullable=False, default="agent_loop")
    summary = Column(Text, nullable=True)
```

- [ ] **Step 3: Verify model imports cleanly**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
python -c "from app.models.run import Run; print(Run.trigger_type, Run.summary)"
```
Expected: prints column descriptors without error

- [ ] **Step 4: Commit**

```bash
git add services/api/alembic/versions/0003_add_run_trigger_type_and_summary.py \
        services/api/app/models/run.py
git commit -m "feat(api): add trigger_type and summary columns to Run model"
```

---

### Task 2: New tool handlers — ha.light.turn_off + http.request

**Files:**
- Modify: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/tests/test_tool_handlers.py`

- [ ] **Step 1: Write failing tests for ha.light.turn_off**

Add to `services/api/tests/test_tool_handlers.py`:

```python
def test_ha_light_turn_off_raises_when_not_configured(monkeypatch):
    from app.tools import handlers
    from app.config import settings
    monkeypatch.setattr(settings, "ha_base_url", "")
    with pytest.raises(RuntimeError, match="HA not configured"):
        handlers.handle_ha_light_turn_off({"entity_id": "light.test"}, settings)


def test_ha_light_turn_off_calls_ha_api(monkeypatch):
    from app.tools import handlers
    from app.config import settings
    monkeypatch.setattr(settings, "ha_base_url", "http://fake-ha:8123")
    monkeypatch.setattr(settings, "ha_token", "fake-token")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    with patch("app.tools.handlers.httpx.post", return_value=mock_response):
        result = handlers.handle_ha_light_turn_off({"entity_id": "light.office"}, settings)
    assert result == {"status": "ok", "entity_id": "light.office"}
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
pytest tests/test_tool_handlers.py::test_ha_light_turn_off_raises_when_not_configured \
       tests/test_tool_handlers.py::test_ha_light_turn_off_calls_ha_api -v
```
Expected: FAIL — `handle_ha_light_turn_off` not defined

- [ ] **Step 3: Write failing tests for http.request**

Add to `services/api/tests/test_tool_handlers.py`:

```python
def test_http_request_get_success():
    from app.tools.handlers import handle_http_request
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "Hello World"
    with patch("app.tools.handlers.httpx.request", return_value=mock_resp):
        result = handle_http_request({"method": "GET", "url": "http://example.com"}, None, None)
    assert result == {"status_code": 200, "body": "Hello World"}


def test_http_request_truncates_large_body():
    from app.tools.handlers import handle_http_request
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "x" * 3000
    with patch("app.tools.handlers.httpx.request", return_value=mock_resp):
        result = handle_http_request({"method": "GET", "url": "http://example.com"}, None, None)
    assert len(result["body"]) == 2048


def test_http_request_post_passes_headers_and_body():
    from app.tools.handlers import handle_http_request
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.text = '{"ok": true}'
    with patch("app.tools.handlers.httpx.request", return_value=mock_resp) as mock_req:
        handle_http_request(
            {
                "method": "POST",
                "url": "http://api.example.com/items",
                "headers": {"Authorization": "Bearer tok"},
                "body": {"name": "test"},
                "timeout_seconds": 15,
            },
            None, None,
        )
    call = mock_req.call_args
    assert call.args[0] == "POST"
    assert call.kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert call.kwargs["timeout"] == 15
```

- [ ] **Step 4: Run — expect FAIL**

```bash
pytest tests/test_tool_handlers.py::test_http_request_get_success \
       tests/test_tool_handlers.py::test_http_request_truncates_large_body \
       tests/test_tool_handlers.py::test_http_request_post_passes_headers_and_body -v
```
Expected: FAIL

- [ ] **Step 5: Implement ha.light.turn_off**

Add to `services/api/app/tools/handlers.py` after `handle_ha_light_turn_on`:

```python
def handle_ha_light_turn_off(input: dict, cfg=None) -> dict:
    """Calls the Home Assistant light.turn_off service.

    input: {"entity_id": "light.xyz"}
    Raises RuntimeError if HA_BASE_URL or HA_TOKEN are not configured.
    """
    cfg = cfg or _settings
    if not cfg.ha_base_url or not cfg.ha_token:
        raise RuntimeError(
            "HA not configured: set HA_BASE_URL and HA_TOKEN environment variables"
        )
    resp = httpx.post(
        f"{cfg.ha_base_url}/api/services/light/turn_off",
        headers={"Authorization": f"Bearer {cfg.ha_token}"},
        json={"entity_id": input["entity_id"]},
        timeout=10,
    )
    resp.raise_for_status()
    return {"status": "ok", "entity_id": input["entity_id"]}
```

- [ ] **Step 6: Implement http.request**

Add after `handle_ha_light_turn_off`:

```python
def handle_http_request(input: dict, db=None, cfg=None) -> dict:
    """Makes an HTTP GET or POST request.

    input: {"method": "GET"|"POST", "url": "...", "headers"?: {...},
            "body"?: {...}, "timeout_seconds"?: 30}
    Returns {"status_code": int, "body": str} — body truncated to 2048 chars.
    """
    method = input["method"].upper()
    url = input["url"]
    headers = input.get("headers", {})
    body = input.get("body")
    timeout = input.get("timeout_seconds", 30)
    resp = httpx.request(method, url, headers=headers, json=body, timeout=timeout)
    return {"status_code": resp.status_code, "body": resp.text[:2048]}
```

- [ ] **Step 7: Update _REGISTRY**

Replace the `_REGISTRY` dict in `handlers.py`:

```python
_REGISTRY: dict[str, tuple] = {
    "debug.echo": (handle_debug_echo, []),
    "ha.light.turn_on": (handle_ha_light_turn_on, ["settings"]),
    "ha.light.turn_off": (handle_ha_light_turn_off, ["settings"]),
    "http.request": (handle_http_request, []),
    "devops.summarize_ci_failure": (handle_devops_summarize_ci_failure, ["db"]),
}
```

- [ ] **Step 8: Add seed entries**

In `services/api/app/tools/seed.py`, add to `tool_definitions` after the `ha.light.turn_on` entry:

```python
        dict(
            name="ha.light.turn_off",
            display_name="HA: Turn Off Light",
            description="Turns off a Home Assistant light entity. Requires HA_BASE_URL and HA_TOKEN.",
            adapter_type="home_assistant",
            input_schema={
                "type": "object",
                "properties": {"entity_id": {"type": "string"}},
                "required": ["entity_id"],
            },
            output_schema={"type": "object"},
            risk_class="low",
            requires_approval=False,
            timeout_seconds=10,
            enabled=True,
            tags=["home_assistant", "light"],
        ),
        dict(
            name="http.request",
            display_name="HTTP Request",
            description=(
                "Makes an HTTP GET or POST request to any URL. "
                "Returns status code and response body (truncated to 2KB)."
            ),
            adapter_type="internal",
            input_schema={
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST"]},
                    "url": {"type": "string"},
                    "headers": {"type": "object"},
                    "body": {"type": "object"},
                    "timeout_seconds": {"type": "integer", "default": 30},
                },
                "required": ["method", "url"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "string"},
                },
            },
            risk_class="low",
            requires_approval=False,
            timeout_seconds=35,
            enabled=True,
            tags=["http", "web"],
        ),
```

- [ ] **Step 9: Run all handler tests**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
pytest tests/test_tool_handlers.py -v
```
Expected: All 10 tests pass

- [ ] **Step 10: Commit**

```bash
git add services/api/app/tools/handlers.py \
        services/api/app/tools/seed.py \
        services/api/tests/test_tool_handlers.py
git commit -m "feat(api): add ha.light.turn_off and http.request tool handlers"
```

---

### Task 3: Activity API endpoint

**Files:**
- Create: `services/api/app/schemas/activity.py`
- Create: `services/api/app/routers/activity.py`
- Create: `services/api/tests/test_activity.py`
- Modify: `services/api/app/main.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_activity.py`:

```python
from datetime import datetime, timezone, timedelta
from app.models.run import Run


def _make_run(db, id="run-1", tool_name="ha.light.turn_on", status="succeeded",
              trigger_type="chat", summary=None, started_at=None, output=None):
    run = Run(
        id=id,
        tool_name=tool_name,
        task_id=None,
        executor_type="chat",
        trigger_type=trigger_type,
        status=status,
        started_at=started_at or datetime.now(timezone.utc),
        output=output or ({"status": "ok"} if status == "succeeded" else None),
        error="timeout" if status == "failed" else None,
        summary=summary or f"{tool_name} → {status}",
    )
    db.add(run)
    db.commit()
    return run


def test_get_activity_empty(client):
    resp = client.get("/activity")
    assert resp.status_code == 200
    assert resp.json() == {"entries": [], "total": 0}


def test_get_activity_returns_succeeded_run(client, db_session):
    _make_run(db_session)
    resp = client.get("/activity")
    data = resp.json()
    assert data["total"] == 1
    entry = data["entries"][0]
    assert entry["tool_name"] == "ha.light.turn_on"
    assert entry["status"] == "succeeded"
    assert entry["trigger_type"] == "chat"
    assert entry["summary"] == "ha.light.turn_on → succeeded"


def test_get_activity_excludes_queued_and_cancelled(client, db_session):
    _make_run(db_session, id="r1", status="succeeded")
    _make_run(db_session, id="r2", tool_name="http.request", status="queued")
    _make_run(db_session, id="r3", tool_name="debug.echo", status="cancelled")
    assert client.get("/activity").json()["total"] == 1


def test_get_activity_excludes_null_tool_name(client, db_session):
    run = Run(id="r-notool", tool_name=None, task_id=None, executor_type="system",
              trigger_type="agent_loop", status="succeeded",
              started_at=datetime.now(timezone.utc))
    db_session.add(run)
    db_session.commit()
    assert client.get("/activity").json()["total"] == 0


def test_get_activity_output_truncated(client, db_session):
    _make_run(db_session, id="r-big", tool_name="http.request",
              output={"body": "x" * 3000})
    entry = client.get("/activity").json()["entries"][0]
    assert entry["output"].endswith("... [truncated]")


def test_get_activity_pagination(client, db_session):
    now = datetime.now(timezone.utc)
    for i in range(5):
        run = Run(id=f"r-{i}", tool_name="debug.echo", status="succeeded",
                  trigger_type="chat", executor_type="chat",
                  started_at=now + timedelta(seconds=i))
        db_session.add(run)
    db_session.commit()
    d1 = client.get("/activity?limit=3&offset=0").json()
    assert d1["total"] == 5
    assert len(d1["entries"]) == 3
    d2 = client.get("/activity?limit=3&offset=3").json()
    assert d2["total"] == 5
    assert len(d2["entries"]) == 2


def test_get_activity_ordered_newest_first(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(Run(id="old", tool_name="debug.echo", status="succeeded",
                       trigger_type="chat", executor_type="chat",
                       started_at=now - timedelta(hours=1)))
    db_session.add(Run(id="new", tool_name="ha.light.turn_on", status="succeeded",
                       trigger_type="chat", executor_type="chat",
                       started_at=now))
    db_session.commit()
    entries = client.get("/activity").json()["entries"]
    assert entries[0]["id"] == "new"
    assert entries[1]["id"] == "old"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
pytest tests/test_activity.py -v
```
Expected: FAIL (404 — route doesn't exist)

- [ ] **Step 3: Create activity schema**

Create `services/api/app/schemas/activity.py`:

```python
from datetime import datetime
from pydantic import BaseModel


class ActivityEntryRead(BaseModel):
    id: str
    tool_name: str
    trigger_type: str
    status: str
    summary: str | None
    input: dict | None
    output: str | None  # JSON string, server-truncated to 2000 chars
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class ActivityResponse(BaseModel):
    entries: list[ActivityEntryRead]
    total: int
```

- [ ] **Step 4: Create activity router**

Create `services/api/app/routers/activity.py`:

```python
import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.run import Run
from app.schemas.activity import ActivityEntryRead, ActivityResponse

router = APIRouter(prefix="/activity", tags=["activity"])


def _serialize_output(output) -> str | None:
    if output is None:
        return None
    s = json.dumps(output)
    if len(s) > 2000:
        return s[:2000] + " ... [truncated]"
    return s


@router.get("", response_model=ActivityResponse)
def get_activity(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    filters = [
        Run.status.in_(["succeeded", "failed", "running"]),
        Run.tool_name.isnot(None),
    ]
    total = db.query(func.count(Run.id)).filter(*filters).scalar() or 0
    runs = (
        db.query(Run)
        .filter(*filters)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return ActivityResponse(
        entries=[
            ActivityEntryRead(
                id=r.id,
                tool_name=r.tool_name,
                trigger_type=r.trigger_type,
                status=r.status,
                summary=r.summary,
                input=r.input,
                output=_serialize_output(r.output),
                error=r.error,
                started_at=r.started_at,
                finished_at=r.finished_at,
            )
            for r in runs
        ],
        total=total,
    )
```

- [ ] **Step 5: Wire into main.py**

In `services/api/app/main.py`, update the import line:
```python
from app.routers import health, tasks, events, board, tools, runs, approvals, entities, llm, conversations, activity
```

Add after `app.include_router(conversations.router)`:
```python
app.include_router(activity.router)
```

- [ ] **Step 6: Run activity tests**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
pytest tests/test_activity.py -v
```
Expected: All 7 tests pass

- [ ] **Step 7: Commit**

```bash
git add services/api/app/schemas/activity.py \
        services/api/app/routers/activity.py \
        services/api/app/main.py \
        services/api/tests/test_activity.py
git commit -m "feat(api): add GET /activity endpoint backed by Run table"
```

---

### Task 4: Intent classifier + tool execution in chat

**Files:**
- Modify: `services/api/app/routers/conversations.py`
- Modify: `services/api/tests/test_conversations.py`

- [ ] **Step 1: Write failing tests for _parse_json_safe**

Add to `services/api/tests/test_conversations.py`:

```python
def test_parse_json_safe_parses_plain_json():
    from app.routers.conversations import _parse_json_safe
    assert _parse_json_safe('{"intent": "action", "confidence": 0.9}') == {
        "intent": "action", "confidence": 0.9
    }


def test_parse_json_safe_strips_markdown_fences():
    from app.routers.conversations import _parse_json_safe
    text = '```json\n{"intent": "conversation"}\n```'
    assert _parse_json_safe(text) == {"intent": "conversation"}


def test_parse_json_safe_returns_none_on_invalid():
    from app.routers.conversations import _parse_json_safe
    assert _parse_json_safe("not json") is None
    assert _parse_json_safe("") is None
```

- [ ] **Step 2: Write failing integration tests for action path**

Add to `services/api/tests/test_conversations.py`:

```python
def test_action_intent_executes_tool_and_creates_run(client, db_session):
    """When classifier returns action intent, tool runs and a Run is created."""
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()

    classify_resp = '{"intent": "action", "tool_name": "debug.echo", "tool_input": {"message": "hi"}, "confidence": 0.95}'

    with patch("app.llm_client._call_provider_real", side_effect=[classify_resp, "Done!"]):
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "echo hi", "stream": False},
        )

    assert resp.status_code == 201
    from app.models.run import Run
    runs = db_session.query(Run).all()
    assert len(runs) == 1
    assert runs[0].tool_name == "debug.echo"
    assert runs[0].trigger_type == "chat"
    assert runs[0].status == "succeeded"
    assert runs[0].summary == "debug.echo → succeeded"


def test_low_confidence_falls_through_no_run(client, db_session):
    """confidence < 0.7 → no Run created, normal reply."""
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()

    classify_resp = '{"intent": "action", "tool_name": "debug.echo", "tool_input": {}, "confidence": 0.5}'

    with patch("app.llm_client._call_provider_real", side_effect=[classify_resp, "Not sure."]):
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "maybe echo?", "stream": False},
        )

    assert resp.status_code == 201
    from app.models.run import Run
    assert db_session.query(Run).count() == 0


def test_unknown_tool_falls_through_no_run(client, db_session):
    """tool_name not in _REGISTRY → no Run created."""
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()

    classify_resp = '{"intent": "action", "tool_name": "nonexistent.tool", "tool_input": {}, "confidence": 0.95}'

    with patch("app.llm_client._call_provider_real", side_effect=[classify_resp, "Nope."]):
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "do the thing", "stream": False},
        )

    assert resp.status_code == 201
    from app.models.run import Run
    assert db_session.query(Run).count() == 0


def test_action_sse_emits_running_acknowledgment(client, db_session):
    """Streaming path emits [Running tool...] as first delta."""
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()

    classify_resp = '{"intent": "action", "tool_name": "debug.echo", "tool_input": {"message": "t"}, "confidence": 0.9}'

    with patch("app.llm_client._call_provider_real", return_value=classify_resp):
        with patch("app.llm_client._call_provider_streaming_real", fake_streaming_caller):
            resp = client.post(
                f"/conversations/{conv['id']}/messages",
                json={"content": "echo t", "stream": True},
            )

    import json as _json
    lines = [l for l in resp.text.split("\n") if l.startswith("data: ")]
    events = [_json.loads(l[6:]) for l in lines]
    deltas = [e["delta"] for e in events if "delta" in e]
    assert deltas[0].startswith("[Running debug.echo")
```

- [ ] **Step 3: Run — expect FAIL**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
pytest tests/test_conversations.py::test_parse_json_safe_parses_plain_json \
       tests/test_conversations.py::test_action_intent_executes_tool_and_creates_run \
       tests/test_conversations.py::test_low_confidence_falls_through_no_run \
       tests/test_conversations.py::test_unknown_tool_falls_through_no_run \
       tests/test_conversations.py::test_action_sse_emits_running_acknowledgment -v
```
Expected: FAIL

- [ ] **Step 4: Add imports to conversations.py**

At the top of `services/api/app/routers/conversations.py`, add:

```python
import re
from app.models.run import Run
from app.tools import handlers as tool_handlers
```

`uuid4` is already imported. `timezone` is already imported as part of `datetime`.

- [ ] **Step 5: Add _parse_json_safe helper**

Add after `_build_system_prompt` in `conversations.py`:

```python
def _parse_json_safe(text: str) -> dict | None:
    """Strip markdown fences and parse JSON. Returns None on any failure."""
    try:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        cleaned = match.group(1).strip() if match else text.strip()
        return json.loads(cleaned)
    except Exception:
        return None
```

- [ ] **Step 6: Update _build_system_prompt**

Remove the sentence `"You cannot execute tools directly from chat — suggest the user post an event or create a task for actions that need execution."` from the return string. Change the tools line from `"Available tools (reference only):\n{tool_lines}"` to `"Available tools:\n{tool_lines}"`.

Updated return value:

```python
    return (
        "You are Nova, an intelligent agent assistant. "
        "Help the user understand their system, answer questions, and take actions.\n\n"
        f"Current pending tasks:\n{task_lines}\n\n"
        f"Available tools:\n{tool_lines}\n\n"
        "Respond conversationally. Be concise and helpful."
    )
```

- [ ] **Step 7: Rewrite send_message with classification + generator restructure**

Replace the entire body of `send_message` in `conversations.py`. The critical constraint: classification and tool execution happen **before** `generate()` is defined, so their results are available as closure variables.

```python
@router.post("/{conversation_id}/messages", status_code=201)
def send_message(
    conversation_id: str,
    body: MessageCreate,
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Persist user message
    user_msg = Message(
        id=str(uuid4()),
        conversation_id=conversation_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    if conv.title == "New Chat":
        conv.title = _make_title(body.content)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Build message history
    history = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )

    # --- Phase 1: Intent classification (MUST run before generator is defined) ---
    tools = db.query(Tool).filter(Tool.enabled == True).all()  # noqa: E712
    tool_list = "\n".join(f"  - {t.name}: {t.description}" for t in tools)
    classify_messages = [
        {
            "role": "system",
            "content": (
                "You are an intent classifier for Nova.\n"
                f"Classify the user message. Available tools:\n{tool_list}\n\n"
                'Respond ONLY with JSON:\n'
                '{"intent": "action" | "conversation", '
                '"tool_name": string | null, '
                '"tool_input": object | null, '
                '"confidence": number}\n\n'
                'If unsure, return intent="conversation".'
            ),
        },
        {"role": "user", "content": body.content},
    ]

    tool_name = None    # captured by generator closure
    tool_context = None  # captured by generator closure

    try:
        classify_result = llm_client.route_internal(db, "classify", classify_messages)
        c = _parse_json_safe(classify_result) or {}
    except Exception:
        c = {}

    if (
        c.get("intent") == "action"
        and c.get("confidence", 0) >= 0.7
        and c.get("tool_name") in tool_handlers._REGISTRY
    ):
        tool_name = c["tool_name"]
        tool_input = c.get("tool_input") or {}

        run = Run(
            id=str(uuid4()),
            tool_name=tool_name,
            task_id=None,
            executor_type="chat",
            trigger_type="chat",
            input=tool_input,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()

        try:
            output = tool_handlers.dispatch(tool_name, tool_input, db)
            run.status = "succeeded"
            run.output = output
            run.summary = f"{tool_name} → succeeded"
            tool_context = (
                f"You just ran `{tool_name}`. "
                f"Result: {json.dumps(output)}. Status: succeeded."
            )
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.summary = f"{tool_name} → failed"
            tool_context = f"You tried to run `{tool_name}` but it failed: {exc}."
        finally:
            run.finished_at = datetime.now(timezone.utc)
            db.commit()

    # --- Phase 2: Build messages for response LLM call ---
    base_prompt = _build_system_prompt(db)
    system_prompt = (tool_context + "\n\n" + base_prompt) if tool_context else base_prompt
    messages = [{"role": "system", "content": system_prompt}] + [
        {"role": m.role, "content": m.content} for m in history
    ]

    if not body.stream:
        try:
            result = llm_client.route(db, "chat", messages)
            output = result.output
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

        assistant_msg = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=output,
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(assistant_msg)
        return MessageRead.model_validate(assistant_msg)

    # Streaming path — generator reads tool_name + tool_context from closure
    def generate():
        if tool_name:
            yield f"data: {json.dumps({'delta': f'[Running {tool_name}...]\n'})}\n\n"

        full_content: list[str] = []
        try:
            for chunk in llm_client.route_streaming(db, "chat", messages):
                full_content.append(chunk)
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            conv.updated_at = datetime.now(timezone.utc)
            db.commit()
            return

        assistant_msg = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content="".join(full_content),
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        yield f"data: {json.dumps({'complete': True})}\n\n"

    return StreamingResponse(
        generate(),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

**Why existing tests still pass:** Existing tests mock `_call_provider_real` to return plain strings like `"Non-streaming reply"`. The classification call receives this, `_parse_json_safe("Non-streaming reply")` returns `None`, `c = {}`, condition fails, falls through. The second mock call returns the expected string for the response. No existing test breaks.

- [ ] **Step 8: Run full conversation test suite**

```bash
cd /home/jeremy/workspace/nova-suite/services/api
pytest tests/test_conversations.py -v
```
Expected: All tests pass (existing 13 + 7 new = 20 total)

- [ ] **Step 9: Run full backend test suite**

```bash
pytest tests/ -v
```
Expected: All tests pass

- [ ] **Step 10: Commit**

```bash
git add services/api/app/routers/conversations.py \
        services/api/tests/test_conversations.py
git commit -m "feat(api): wire intent classification and tool execution into chat message path"
```

---

### Task 5: Frontend — uiStore + AppShell tab rename

**Files:**
- Modify: `services/board/src/stores/uiStore.ts`
- Modify: `services/board/src/AppShell.tsx`
- Modify: `services/board/src/components/__tests__/AppShell.test.tsx`

- [ ] **Step 1: Update AppShell tests first**

Replace the contents of `services/board/src/components/__tests__/AppShell.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react"
import { vi, beforeEach, it, expect } from "vitest"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { AppShell } from "../../AppShell"
import { useUIStore } from "../../stores/uiStore"
import { useChatStore } from "../../stores/chatStore"
import { useSettingsStore } from "../../stores/settingsStore"

vi.mock("../../components/Activity/ActivityFeed", () => ({ ActivityFeed: () => <div data-testid="activity-feed" /> }))
vi.mock("../../components/Chat/ChatPanel", () => ({ ChatPanel: () => <div data-testid="chat-panel" /> }))
vi.mock("../../components/TaskDetail/TaskDetail", () => ({ TaskDetail: () => null }))
vi.mock("../../components/shared/FilterBar", () => ({ FilterBar: () => <div data-testid="filter-bar" /> }))
vi.mock("../../components/shared/Toast", () => ({ Toast: () => null }))
vi.mock("../../api/chat", () => ({
  createConversation: vi.fn().mockResolvedValue({ id: "c1", title: "New Chat", created_at: "", updated_at: "", message_count: 0 }),
}))

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(MemoryRouter, {}, createElement(QueryClientProvider, { client: qc }, children))
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ theme: "system" })
  useUIStore.setState({ selectedTaskId: null, toast: null, activeFilters: {}, activeTab: "chat" })
  useChatStore.setState({ conversationId: null, streamingContent: "", isStreaming: false })
})

it("renders Chat tab and chat panel by default", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByTestId("chat-panel")).toBeInTheDocument()
  expect(screen.queryByTestId("activity-feed")).not.toBeInTheDocument()
})

it("renders Chat and Activity tab buttons", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByRole("button", { name: /chat/i })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: /activity/i })).toBeInTheDocument()
})

it("clicking Activity tab shows activity feed and hides chat panel", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByRole("button", { name: /activity/i }))
  expect(screen.getByTestId("activity-feed")).toBeInTheDocument()
  expect(screen.queryByTestId("chat-panel")).not.toBeInTheDocument()
})

it("settings gear link is present", () => {
  render(<AppShell />, { wrapper: makeWrapper() })
  expect(screen.getByRole("link", { name: /settings/i })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run AppShell tests — expect FAIL**

```bash
cd /home/jeremy/workspace/nova-suite/services/board
npm test -- --reporter=verbose src/components/__tests__/AppShell.test.tsx
```
Expected: FAIL (no "activity" button, ActivityFeed mock import missing)

- [ ] **Step 3: Update uiStore.ts**

In `services/board/src/stores/uiStore.ts`, change:
```typescript
type ActiveTab = "chat" | "board"
```
to:
```typescript
type ActiveTab = "chat" | "activity"
```

- [ ] **Step 4: Update AppShell.tsx**

Replace `services/board/src/AppShell.tsx` with:

```tsx
import { useEffect } from "react"
import { Link } from "react-router-dom"
import { useShallow } from "zustand/react/shallow"
import { useUIStore } from "./stores/uiStore"
import { useChatStore } from "./stores/chatStore"
import { ActivityFeed } from "./components/Activity/ActivityFeed"
import { Toast } from "./components/shared/Toast"
import { ChatPanel } from "./components/Chat/ChatPanel"
import { createConversation } from "./api/chat"

export function AppShell() {
  const { toast, setToast, activeTab, setActiveTab } = useUIStore(
    useShallow(s => ({ toast: s.toast, setToast: s.setToast, activeTab: s.activeTab, setActiveTab: s.setActiveTab }))
  )

  useEffect(() => {
    if (!useChatStore.getState().conversationId) {
      createConversation().then(conv => useChatStore.getState().setConversation(conv.id))
    }
  }, [])

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <span className="app-shell__title">Nova</span>

        <nav className="app-shell__tabs">
          <button
            className={`app-shell__tab${activeTab === "chat" ? " app-shell__tab--active" : ""}`}
            onClick={() => setActiveTab("chat")}
          >
            Chat
          </button>
          <button
            className={`app-shell__tab${activeTab === "activity" ? " app-shell__tab--active" : ""}`}
            onClick={() => setActiveTab("activity")}
          >
            Activity
          </button>
        </nav>

        <Link to="/settings" className="app-shell__settings-link" aria-label="Settings">
          ⚙
        </Link>
      </header>

      <div className="app-shell__body">
        <div className="app-shell__tab-content">
          {activeTab === "chat" ? <ChatPanel /> : <ActivityFeed />}
        </div>
      </div>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  )
}
```

Note: `ActivityFeed` is mocked in tests so TypeScript import error (file doesn't exist yet) won't affect test results — Vitest resolves the mock before the import.

- [ ] **Step 5: Run AppShell tests**

```bash
npm test -- --reporter=verbose src/components/__tests__/AppShell.test.tsx
```
Expected: All 4 tests pass

- [ ] **Step 6: Commit**

```bash
git add services/board/src/stores/uiStore.ts \
        services/board/src/AppShell.tsx \
        services/board/src/components/__tests__/AppShell.test.tsx
git commit -m "feat(board): replace Board tab with Activity tab in AppShell"
```

---

### Task 6: ActivityFeed component + API client

**Files:**
- Modify: `services/board/src/api/types.ts`
- Create: `services/board/src/api/activity.ts`
- Create: `services/board/src/components/Activity/ActivityFeed.tsx`
- Create: `services/board/src/components/Activity/__tests__/ActivityFeed.test.tsx`
- Modify: `services/board/src/styles/global.css`

- [ ] **Step 1: Add types to types.ts**

Add to `services/board/src/api/types.ts`:

```typescript
export interface ActivityEntry {
  id: string
  tool_name: string
  trigger_type: "chat" | "agent_loop"
  status: "succeeded" | "failed" | "running"
  summary: string | null
  input: Record<string, unknown> | null
  output: string | null
  error: string | null
  started_at: string
  finished_at: string | null
}

export interface ActivityResponse {
  entries: ActivityEntry[]
  total: number
}
```

- [ ] **Step 2: Create api/activity.ts**

Create `services/board/src/api/activity.ts`:

```typescript
import { apiFetch } from "./client"
import type { ActivityResponse } from "./types"

export function getActivity(limit = 50, offset = 0): Promise<ActivityResponse> {
  return apiFetch<ActivityResponse>(`/activity?limit=${limit}&offset=${offset}`)
}
```

- [ ] **Step 3: Write failing ActivityFeed tests**

Create `services/board/src/components/Activity/__tests__/ActivityFeed.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { vi, beforeEach, it, expect } from "vitest"
import { ActivityFeed } from "../ActivityFeed"
import type { ActivityEntry } from "../../../api/types"

vi.mock("../../../api/activity", () => ({ getActivity: vi.fn() }))
import { getActivity } from "../../../api/activity"
const mockGet = getActivity as ReturnType<typeof vi.fn>

function entry(overrides: Partial<ActivityEntry> = {}): ActivityEntry {
  return {
    id: "r1",
    tool_name: "ha.light.turn_on",
    trigger_type: "chat",
    status: "succeeded",
    summary: "ha.light.turn_on → succeeded",
    input: { entity_id: "light.office" },
    output: '{"status": "ok"}',
    error: null,
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    ...overrides,
  }
}

beforeEach(() => {
  mockGet.mockResolvedValue({ entries: [], total: 0 })
})

it("shows empty state when no entries", async () => {
  render(<ActivityFeed />)
  await waitFor(() => expect(screen.getByText(/no activity yet/i)).toBeInTheDocument())
})

it("renders tool name, badge, status, and summary", async () => {
  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))
  expect(screen.getByText("ha.light.turn_on → succeeded")).toBeInTheDocument()
  expect(screen.getByText("chat")).toBeInTheDocument()
  expect(screen.getByText("succeeded")).toBeInTheDocument()
})

it("expands details on click", async () => {
  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))
  fireEvent.click(screen.getByRole("button", { name: /details/i }))
  expect(screen.getByText(/light\.office/)).toBeInTheDocument()
})

it("refresh button re-fetches", async () => {
  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))

  mockGet.mockResolvedValue({ entries: [], total: 0 })
  fireEvent.click(screen.getByRole("button", { name: /refresh/i }))
  await waitFor(() => screen.getByText(/no activity yet/i))
})

it("load more appends next page", async () => {
  const e1 = entry({ id: "r1", tool_name: "debug.echo" })
  const e2 = entry({ id: "r2", tool_name: "http.request" })
  mockGet.mockResolvedValueOnce({ entries: [e1], total: 2 })
  mockGet.mockResolvedValueOnce({ entries: [e2], total: 2 })

  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("debug.echo"))
  fireEvent.click(screen.getByRole("button", { name: /load more/i }))
  await waitFor(() => screen.getByText("http.request"))
  expect(screen.getByText("debug.echo")).toBeInTheDocument()
})

it("hides load more when all entries loaded", async () => {
  mockGet.mockResolvedValue({ entries: [entry()], total: 1 })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))
  expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument()
})

it("renders running entry with running status", async () => {
  mockGet.mockResolvedValue({
    entries: [entry({ status: "running", finished_at: null })],
    total: 1,
  })
  render(<ActivityFeed />)
  await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument())
})

it("renders failed entry with error", async () => {
  mockGet.mockResolvedValue({
    entries: [entry({ status: "failed", error: "connection refused", output: null })],
    total: 1,
  })
  render(<ActivityFeed />)
  await waitFor(() => screen.getByText("ha.light.turn_on"))
  fireEvent.click(screen.getByRole("button", { name: /details/i }))
  expect(screen.getByText("connection refused")).toBeInTheDocument()
})
```

- [ ] **Step 4: Run tests — expect FAIL**

```bash
cd /home/jeremy/workspace/nova-suite/services/board
npm test -- --reporter=verbose src/components/Activity/__tests__/ActivityFeed.test.tsx
```
Expected: FAIL (ActivityFeed doesn't exist)

- [ ] **Step 5: Create ActivityFeed component**

Create `services/board/src/components/Activity/ActivityFeed.tsx`:

```tsx
import { useState, useEffect } from "react"
import { getActivity } from "../../api/activity"
import type { ActivityEntry } from "../../api/types"

function relativeTime(iso: string): string {
  const diffMin = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (diffMin < 1) return "just now"
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return `${Math.floor(diffHr / 24)}d ago`
}

function EntryRow({ entry }: { entry: ActivityEntry }) {
  const [expanded, setExpanded] = useState(false)
  const isTruncated = entry.output?.endsWith("... [truncated]") ?? false

  return (
    <div className={`activity-entry activity-entry--${entry.status}`}>
      <div className="activity-entry__row">
        <span className="activity-entry__dot" />
        <span className="activity-entry__name">{entry.tool_name}</span>
        <span className="activity-entry__badge">{entry.trigger_type}</span>
        <span className="activity-entry__status">{entry.status}</span>
        <span className="activity-entry__time">
          {entry.started_at ? relativeTime(entry.started_at) : ""}
        </span>
      </div>

      {entry.summary && (
        <div className="activity-entry__summary">{entry.summary}</div>
      )}

      <button
        className="activity-entry__details-toggle"
        onClick={() => setExpanded(e => !e)}
        aria-label={expanded ? "hide details" : "show details"}
      >
        {expanded ? "▼ Details" : "▶ Details"}
      </button>

      {expanded && (
        <div className="activity-entry__details">
          <div className="activity-entry__detail-row">
            <span className="activity-entry__detail-label">Input</span>
            <pre className="activity-entry__detail-value">
              {entry.input ? JSON.stringify(entry.input, null, 2) : "—"}
            </pre>
          </div>
          <div className="activity-entry__detail-row">
            <span className="activity-entry__detail-label">Output</span>
            <pre className="activity-entry__detail-value">
              {entry.output ?? "—"}
              {isTruncated && <span className="activity-entry__truncated"> (truncated)</span>}
            </pre>
          </div>
          {entry.error && (
            <div className="activity-entry__detail-row">
              <span className="activity-entry__detail-label">Error</span>
              <pre className="activity-entry__detail-value activity-entry__detail-value--error">
                {entry.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ActivityFeed() {
  const [entries, setEntries] = useState<ActivityEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  async function load(offset: number, append: boolean) {
    setLoading(true)
    setFetchError(null)
    try {
      const data = await getActivity(50, offset)
      setTotal(data.total)
      setEntries(prev => append ? [...prev, ...data.entries] : data.entries)
    } catch {
      setFetchError("Failed to load activity.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(0, false) }, [])

  return (
    <div className="activity-feed">
      <div className="activity-feed__header">
        <span className="activity-feed__title">Activity</span>
        <button
          className="activity-feed__refresh"
          onClick={() => load(0, false)}
          disabled={loading}
          aria-label="Refresh"
        >
          ↺ Refresh
        </button>
      </div>

      {fetchError && (
        <div className="activity-feed__error">
          {fetchError}
          <button onClick={() => load(0, false)}>Retry</button>
        </div>
      )}

      {!loading && entries.length === 0 && !fetchError && (
        <div className="activity-feed__empty">No activity yet.</div>
      )}

      <div className="activity-feed__list">
        {entries.map(e => <EntryRow key={e.id} entry={e} />)}
      </div>

      {entries.length < total && (
        <button
          className="activity-feed__load-more"
          onClick={() => load(entries.length, true)}
          disabled={loading}
          aria-label="Load more"
        >
          {loading ? "Loading..." : "Load more"}
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 6: Add CSS to global.css**

Append to `services/board/src/styles/global.css`:

```css
/* ─── Activity Feed ──────────────────────────────────────────── */

.activity-feed {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px;
  overflow-y: auto;
  gap: 8px;
}

.activity-feed__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.activity-feed__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}

.activity-feed__refresh {
  background: none;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 10px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 13px;
}

.activity-feed__refresh:hover:not(:disabled) {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

.activity-feed__empty {
  color: var(--text-muted);
  font-size: 14px;
  text-align: center;
  margin-top: 32px;
}

.activity-feed__error {
  font-size: 13px;
  padding: 8px;
  border: 1px solid #e55;
  border-radius: 6px;
  color: #e55;
  display: flex;
  gap: 8px;
  align-items: center;
}

.activity-feed__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.activity-feed__load-more {
  margin-top: 8px;
  align-self: center;
  padding: 6px 20px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 13px;
}

.activity-feed__load-more:hover:not(:disabled) {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

/* ─── Activity Entry ─────────────────────────────────────────── */

.activity-entry {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.activity-entry--failed { border-color: #e55; }

.activity-entry__row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.activity-entry__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-muted);
}

.activity-entry--succeeded .activity-entry__dot { background: #22c55e; }
.activity-entry--failed    .activity-entry__dot { background: #e55; }
.activity-entry--running   .activity-entry__dot {
  background: #f59e0b;
  animation: activity-pulse 1.2s ease-in-out infinite;
}

@keyframes activity-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.activity-entry__name {
  font-size: 13px;
  font-weight: 600;
  font-family: monospace;
  color: var(--text);
}

.activity-entry__badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-muted);
}

.activity-entry__status {
  font-size: 12px;
  color: var(--text-muted);
}

.activity-entry__time {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: auto;
}

.activity-entry__summary {
  font-size: 12px;
  color: var(--text-muted);
  padding-left: 16px;
}

.activity-entry__details-toggle {
  background: none;
  border: none;
  font-size: 12px;
  color: var(--accent-blue);
  cursor: pointer;
  padding: 0;
  text-align: left;
  margin-top: 2px;
}

.activity-entry__details {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}

.activity-entry__detail-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.activity-entry__detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.activity-entry__detail-value {
  font-size: 12px;
  font-family: monospace;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 8px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.activity-entry__detail-value--error {
  border-color: #e55;
  color: #e55;
}

.activity-entry__truncated {
  color: var(--text-muted);
  font-style: italic;
}
```

- [ ] **Step 7: Run ActivityFeed tests**

```bash
cd /home/jeremy/workspace/nova-suite/services/board
npm test -- --reporter=verbose src/components/Activity/__tests__/ActivityFeed.test.tsx
```
Expected: All 8 tests pass

- [ ] **Step 8: Run full frontend test suite**

```bash
npm test
```
Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add services/board/src/api/types.ts \
        services/board/src/api/activity.ts \
        services/board/src/components/Activity/ActivityFeed.tsx \
        services/board/src/components/Activity/__tests__/ActivityFeed.test.tsx \
        services/board/src/styles/global.css
git commit -m "feat(board): add ActivityFeed component replacing Board tab"
```
