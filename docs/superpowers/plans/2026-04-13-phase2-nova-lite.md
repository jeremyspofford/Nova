# Phase 2: Nova-lite Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the nova-lite agent service — a standalone Python container that polls for events, triages them via LLM into tasks, plans and executes tool actions, and summarizes results.

**Architecture:** Single Python service in `services/nova-lite/`. Communicates with the API exclusively over HTTP via a typed `NovaClient`. Cursor-based event deduplication via JSON state file on a Docker volume. Single sequential polling loop with configurable sleep. Logic split into triage/planner/executor/summarizer modules for independent testability. All logic modules receive a client object — no direct HTTP calls outside `client.py`.

**Tech Stack:** Python 3.12, httpx 0.27.2, pydantic-settings 2.6.1, pytest 8.3.4

**Depends on:** Plan A (Phase 2 API additions to `services/api`) must be complete before running `docker compose up nova-lite`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `services/nova-lite/Dockerfile` | Create | Container build |
| `services/nova-lite/requirements.txt` | Create | Dependencies |
| `services/nova-lite/app/__init__.py` | Create | Package marker |
| `services/nova-lite/app/config.py` | Create | Settings via pydantic-settings |
| `services/nova-lite/app/state.py` | Create | Cursor load/save (JSON file) |
| `services/nova-lite/app/client.py` | Create | Typed HTTP client + NovaClientError |
| `services/nova-lite/app/logic/__init__.py` | Create | Package marker |
| `services/nova-lite/app/logic/triage.py` | Create | Event → LLM classify → create Task |
| `services/nova-lite/app/logic/planner.py` | Create | Task → LLM plan → Action list |
| `services/nova-lite/app/logic/executor.py` | Create | Action list → tool invocations |
| `services/nova-lite/app/logic/summarizer.py` | Create | Run results → result_summary string |
| `services/nova-lite/app/main.py` | Create | Entry point: run_loop() + process_task() + signal handling |
| `services/nova-lite/tests/__init__.py` | Create | Package marker |
| `services/nova-lite/tests/conftest.py` | Create | FakeClient fixture + env var setup |
| `services/nova-lite/tests/test_state.py` | Create | Tests for cursor persistence |
| `services/nova-lite/tests/test_client.py` | Create | Tests for NovaClientError + deserialization |
| `services/nova-lite/tests/test_triage.py` | Create | Tests for classify_and_create |
| `services/nova-lite/tests/test_planner.py` | Create | Tests for plan() |
| `services/nova-lite/tests/test_executor.py` | Create | Tests for execute() |
| `services/nova-lite/tests/test_summarizer.py` | Create | Tests for summarize() |
| `services/nova-lite/tests/test_main.py` | Create | Tests for process_task() |
| `infra/docker-compose.yml` | Modify | Add nova-lite service + api healthcheck + nova-lite-state volume |
| `infra/.env.example` | Modify | Add NOVA_API_URL, LOOP_INTERVAL_SECONDS, LOG_LEVEL |

---

### Task 1: Service skeleton

**Files:**
- Create: `services/nova-lite/Dockerfile`
- Create: `services/nova-lite/requirements.txt`
- Create: `services/nova-lite/app/__init__.py`
- Create: `services/nova-lite/app/config.py`
- Create: `services/nova-lite/app/logic/__init__.py`
- Create: `services/nova-lite/tests/__init__.py`
- Create: `services/nova-lite/tests/conftest.py`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["python", "-m", "app.main"]
```

- [ ] **Step 2: Create requirements.txt**

```
httpx==0.27.2
pydantic-settings==2.6.1
pytest==8.3.4
```

- [ ] **Step 3: Create app/__init__.py and app/logic/__init__.py and tests/__init__.py**

Each file is empty (`# intentionally empty`).

- [ ] **Step 4: Create app/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    nova_api_url: str
    loop_interval_seconds: int = 15
    cursor_file: str = "/app/state/cursor.json"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 5: Create tests/conftest.py**

The `FakeClient` here is used by all logic tests. Setting `NOVA_API_URL` before importing `settings` prevents a validation error in tests that don't need real HTTP.

```python
import os
import pytest

# Must set before any app import that references settings
os.environ.setdefault("NOVA_API_URL", "http://test:8000")


class FakeClient:
    """In-memory fake of NovaClient. Tests mutate these attributes to control responses."""

    def __init__(self):
        self.events: list[dict] = []
        self.tasks: dict[str, dict] = {}
        self.tools: list[dict] = []
        self.approvals: dict[str, dict] = {}
        self._llm_response: str = ""
        self._invoke_result: dict = {"run_id": "run-1", "status": "succeeded"}
        self._next_task_id: int = 1

    def get_events(self, since: str, limit: int = 10) -> list[dict]:
        return self.events[:limit]

    def get_tasks(
        self,
        status: str | None = None,
        limit: int = 5,
        origin_event_id: str | None = None,
    ) -> list[dict]:
        result = list(self.tasks.values())
        if status is not None:
            result = [t for t in result if t.get("status") == status]
        if origin_event_id is not None:
            result = [t for t in result if t.get("origin_event_id") == origin_event_id]
        return result[:limit]

    def get_tools(self) -> list[dict]:
        return self.tools

    def post_task(self, payload: dict) -> dict:
        task_id = f"task-{self._next_task_id}"
        self._next_task_id += 1
        task = {"id": task_id, "status": "inbox", **payload}
        self.tasks[task_id] = task
        return task

    def patch_task(self, task_id: str, updates: dict) -> dict:
        self.tasks[task_id].update(updates)
        return self.tasks[task_id]

    def post_approval(self, task_id: str, payload: dict) -> dict:
        approval = {"id": "approval-1", "task_id": task_id, "status": "pending", **payload}
        self.approvals[task_id] = approval
        return approval

    def llm_route(
        self,
        purpose: str,
        messages: list[dict],
        privacy_preference: str = "local_preferred",
    ) -> str:
        return self._llm_response

    def invoke_tool(
        self, tool_name: str, input: dict, task_id: str | None = None
    ) -> dict:
        return self._invoke_result


@pytest.fixture
def fake_client():
    return FakeClient()
```

- [ ] **Step 6: Verify the skeleton imports cleanly**

Run: `cd services/nova-lite && python -c "from app.config import settings; print(settings.nova_api_url)"`

Expected: `http://test:8000` (from env var set in shell, or error about missing `NOVA_API_URL` if not set — that's fine, the test env sets it)

- [ ] **Step 7: Commit**

```bash
git add services/nova-lite/
git commit -m "feat(nova-lite): add service skeleton (Dockerfile, config, test fixtures)"
```

---

### Task 2: State module

**Files:**
- Create: `services/nova-lite/app/state.py`
- Create: `services/nova-lite/tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_state.py
import json
from pathlib import Path
import pytest
from app.state import CursorState


def test_load_cursor_returns_utcnow_when_file_absent(tmp_path):
    """First run: no cursor file → use current UTC time as starting point."""
    state = CursorState(cursor_file=str(tmp_path / "cursor.json"))
    cursor = state.load_cursor()
    # Should be a non-empty ISO string
    assert isinstance(cursor, str)
    assert "T" in cursor


def test_save_and_load_cursor_round_trips(tmp_path):
    """Saved cursor is returned on next load."""
    state = CursorState(cursor_file=str(tmp_path / "cursor.json"))
    ts = "2026-04-13T10:00:00Z"
    state.save_cursor(ts)
    assert state.load_cursor() == ts


def test_save_creates_parent_directories(tmp_path):
    """save_cursor creates parent dirs if they don't exist."""
    nested = tmp_path / "deep" / "dir" / "cursor.json"
    state = CursorState(cursor_file=str(nested))
    state.save_cursor("2026-04-13T10:00:00Z")
    assert nested.exists()
    data = json.loads(nested.read_text())
    assert data["last_event_timestamp"] == "2026-04-13T10:00:00Z"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/nova-lite && python -m pytest tests/test_state.py -v
```

Expected: `ImportError: cannot import name 'CursorState' from 'app.state'`

- [ ] **Step 3: Implement app/state.py**

```python
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class CursorState:
    def __init__(self, cursor_file: str):
        self._path = Path(cursor_file)

    def load_cursor(self) -> str:
        """Return the last event timestamp, or UTC now if no cursor file exists."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                return data["last_event_timestamp"]
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("Corrupted cursor file, resetting: %s", e)
        # First run: only process events that arrive after now
        return datetime.now(tz=timezone.utc).isoformat()

    def save_cursor(self, timestamp: str) -> None:
        """Persist the cursor to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"last_event_timestamp": timestamp}))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/nova-lite && python -m pytest tests/test_state.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add services/nova-lite/app/state.py services/nova-lite/tests/test_state.py
git commit -m "feat(nova-lite): add cursor state persistence"
```

---

### Task 3: API client

**Files:**
- Create: `services/nova-lite/app/client.py`
- Create: `services/nova-lite/tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

The tests use httpx's transport injection to avoid real network calls.

```python
# tests/test_client.py
import httpx
import pytest
from app.client import NovaClient, NovaClientError


class _OkTransport(httpx.BaseTransport):
    """Returns a fixed 200 JSON response."""
    def __init__(self, body: dict):
        self._body = body

    def handle_request(self, request):
        return httpx.Response(200, json=self._body)


class _ErrorTransport(httpx.BaseTransport):
    """Returns a fixed error response."""
    def __init__(self, status: int, text: str = "error"):
        self._status = status
        self._text = text

    def handle_request(self, request):
        return httpx.Response(self._status, text=self._text)


def test_raises_nova_client_error_on_non_2xx():
    client = NovaClient("http://test:8000", transport=_ErrorTransport(404, "Not Found"))
    with pytest.raises(NovaClientError) as exc:
        client.get_events(since="2026-01-01T00:00:00Z")
    assert exc.value.status_code == 404
    assert "Not Found" in str(exc.value)


def test_get_events_deserializes_list():
    events = [{"id": "e1", "type": "test", "timestamp": "2026-01-01T00:00:00Z"}]
    client = NovaClient("http://test:8000", transport=_OkTransport({"events": events}))
    result = client.get_events(since="2026-01-01T00:00:00Z")
    assert result == events


def test_get_tasks_deserializes_list():
    tasks = [{"id": "t1", "title": "Do thing", "status": "inbox"}]
    client = NovaClient("http://test:8000", transport=_OkTransport({"tasks": tasks}))
    result = client.get_tasks(status="inbox")
    assert result == tasks


def test_llm_route_returns_output_string():
    body = {"provider_id": "ollama-local", "model_ref": "gemma3:4b", "output": "hello"}
    client = NovaClient("http://test:8000", transport=_OkTransport(body))
    result = client.llm_route(
        purpose="triage", messages=[{"role": "user", "content": "hi"}]
    )
    assert result == "hello"


def test_client_closes_cleanly():
    client = NovaClient("http://test:8000", transport=_OkTransport({"events": []}))
    client.close()  # Should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/nova-lite && python -m pytest tests/test_client.py -v
```

Expected: `ImportError: cannot import name 'NovaClient' from 'app.client'`

- [ ] **Step 3: Implement app/client.py**

```python
import logging

import httpx

log = logging.getLogger(__name__)


class NovaClientError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


class NovaClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        kwargs = {"base_url": base_url.rstrip("/"), "timeout": 30.0}
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.Client(**kwargs)

    def close(self) -> None:
        self._http.close()

    def _check(self, resp: httpx.Response) -> dict:
        if not resp.is_success:
            raise NovaClientError(resp.status_code, resp.text)
        return resp.json()

    # ── Events ────────────────────────────────────────────────

    def get_events(self, since: str, limit: int = 10) -> list[dict]:
        resp = self._http.get("/events", params={"since": since, "limit": limit})
        return self._check(resp)["events"]

    # ── Tasks ─────────────────────────────────────────────────

    def get_tasks(
        self,
        status: str | None = None,
        limit: int = 5,
        origin_event_id: str | None = None,
    ) -> list[dict]:
        params: dict = {"limit": limit}
        if status is not None:
            params["status"] = status
        if origin_event_id is not None:
            params["origin_event_id"] = origin_event_id
        resp = self._http.get("/tasks", params=params)
        return self._check(resp)["tasks"]

    def post_task(self, payload: dict) -> dict:
        resp = self._http.post("/tasks", json=payload)
        return self._check(resp)

    def patch_task(self, task_id: str, updates: dict) -> dict:
        resp = self._http.patch(f"/tasks/{task_id}", json=updates)
        return self._check(resp)

    # ── Tools ─────────────────────────────────────────────────

    def get_tools(self) -> list[dict]:
        resp = self._http.get("/tools")
        return self._check(resp)["tools"]

    def invoke_tool(
        self, tool_name: str, input: dict, task_id: str | None = None
    ) -> dict:
        body: dict = {"input": input}
        if task_id is not None:
            body["task_id"] = task_id
        body["requested_by"] = "nova-lite"
        resp = self._http.post(f"/tools/{tool_name}/invoke", json=body)
        return self._check(resp)

    # ── Approvals ─────────────────────────────────────────────

    def post_approval(self, task_id: str, payload: dict) -> dict:
        resp = self._http.post(f"/tasks/{task_id}/approvals", json=payload)
        return self._check(resp)

    # ── LLM ───────────────────────────────────────────────────

    def llm_route(
        self,
        purpose: str,
        messages: list[dict],
        privacy_preference: str = "local_preferred",
    ) -> str:
        body = {
            "purpose": purpose,
            "input": {"messages": messages},
            "privacy_preference": privacy_preference,
        }
        resp = self._http.post("/llm/route", json=body)
        return self._check(resp)["output"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/nova-lite && python -m pytest tests/test_client.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add services/nova-lite/app/client.py services/nova-lite/tests/test_client.py
git commit -m "feat(nova-lite): add typed HTTP client with NovaClientError"
```

---

### Task 4: Triage logic

**Files:**
- Create: `services/nova-lite/app/logic/triage.py`
- Create: `services/nova-lite/tests/test_triage.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_triage.py
import json
import pytest
from app.logic.triage import classify_and_create


SAMPLE_EVENT = {
    "id": "event-1",
    "type": "ha.state_changed",
    "source": "home_assistant",
    "subject": "light.living_room turned on",
    "payload": {"entity_id": "light.living_room", "new_state": "on"},
    "timestamp": "2026-04-13T10:00:00Z",
}


def test_creates_task_with_llm_fields(fake_client):
    """classify_and_create calls llm_route, parses JSON response, creates task."""
    fake_client._llm_response = json.dumps({
        "title": "Living room light turned on",
        "description": "HA state change detected",
        "priority": "low",
        "risk_class": "low",
        "labels": ["home_assistant"],
    })
    task = classify_and_create(fake_client, SAMPLE_EVENT)
    assert task["title"] == "Living room light turned on"
    assert task["priority"] == "low"
    assert task["origin_event_id"] == "event-1"
    assert "home_assistant" in task["labels"]


def test_falls_back_to_event_subject_on_parse_failure(fake_client):
    """If LLM returns non-JSON, task is created with title=event['subject']."""
    fake_client._llm_response = "I cannot parse this as JSON, sorry."
    task = classify_and_create(fake_client, SAMPLE_EVENT)
    assert task["title"] == SAMPLE_EVENT["subject"]
    assert task["origin_event_id"] == "event-1"


def test_falls_back_on_missing_title_key(fake_client):
    """If JSON parses but has no 'title', fall back to event subject."""
    fake_client._llm_response = json.dumps({"priority": "high"})
    task = classify_and_create(fake_client, SAMPLE_EVENT)
    assert task["title"] == SAMPLE_EVENT["subject"]


def test_dedup_skips_creation_if_task_exists(fake_client):
    """If a task already exists for this origin_event_id, no new task is created."""
    existing = fake_client.post_task({
        "title": "existing", "origin_event_id": "event-1"
    })
    fake_client._llm_response = json.dumps({"title": "new task"})
    result = classify_and_create(fake_client, SAMPLE_EVENT)
    # Should return the existing task, not create a new one
    assert result["id"] == existing["id"]
    assert len(fake_client.tasks) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/nova-lite && python -m pytest tests/test_triage.py -v
```

Expected: `ImportError: cannot import name 'classify_and_create'`

- [ ] **Step 3: Implement app/logic/triage.py**

```python
import json
import logging

log = logging.getLogger(__name__)


def _build_triage_prompt(event: dict) -> str:
    return (
        "You are a task triage assistant. Given this event, create a task.\n\n"
        f"Event type: {event.get('type')}\n"
        f"Source: {event.get('source')}\n"
        f"Subject: {event.get('subject')}\n"
        f"Payload: {json.dumps(event.get('payload', {}))}\n\n"
        "Respond with JSON only (no markdown, no explanation):\n"
        '{"title": "...", "description": "...", "priority": "low|normal|high|urgent", '
        '"risk_class": "low|medium|high", "labels": ["..."]}'
    )


def _parse_triage_response(response: str) -> dict | None:
    """Parse LLM JSON response. Returns None if response is not valid JSON with a title."""
    try:
        data = json.loads(response)
        if "title" not in data or not data["title"]:
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None


def classify_and_create(client, event: dict) -> dict:
    """Given an event, use LLM to classify it and create a Task. Deduplicates by origin_event_id."""
    # Dedup: if a task already exists for this event, return it
    existing = client.get_tasks(origin_event_id=event["id"], limit=1)
    if existing:
        log.debug("Task already exists for event %s, skipping", event["id"])
        return existing[0]

    prompt = _build_triage_prompt(event)
    response = client.llm_route(
        purpose="triage",
        messages=[{"role": "user", "content": prompt}],
    )

    fields = _parse_triage_response(response)
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

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/nova-lite && python -m pytest tests/test_triage.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/nova-lite/app/logic/triage.py services/nova-lite/tests/test_triage.py
git commit -m "feat(nova-lite): add triage logic (event → LLM → task)"
```

---

### Task 5: Planner logic

**Files:**
- Create: `services/nova-lite/app/logic/planner.py`
- Create: `services/nova-lite/tests/test_planner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_planner.py
import json
import pytest
from app.logic.planner import plan, Action, Plan


SAMPLE_TASK = {
    "id": "task-1",
    "title": "Turn on living room light",
    "description": "User requested light on",
    "goal": None,
    "status": "inbox",
    "risk_class": "low",
}

SAMPLE_TOOLS = [
    {
        "name": "ha.light.turn_on",
        "display_name": "HA: Turn On Light",
        "description": "Turns on a Home Assistant light entity.",
        "input_schema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]},
    },
    {
        "name": "debug.echo",
        "display_name": "Debug Echo",
        "description": "Returns its input unchanged.",
        "input_schema": {"type": "object"},
    },
]


def test_plan_returns_actions_from_llm(fake_client):
    """plan() parses LLM JSON and returns an Action list."""
    fake_client.tools = SAMPLE_TOOLS
    fake_client._llm_response = json.dumps({
        "actions": [
            {"tool_name": "ha.light.turn_on", "input": {"entity_id": "light.living_room"}, "reason": "User requested"},
        ],
        "reasoning": "Turning on the light as requested.",
    })
    result = plan(fake_client, SAMPLE_TASK)
    assert isinstance(result, Plan)
    assert len(result.actions) == 1
    assert result.actions[0].tool_name == "ha.light.turn_on"
    assert result.actions[0].input == {"entity_id": "light.living_room"}
    assert "turning on" in result.reasoning.lower()


def test_plan_returns_empty_actions_when_no_action_needed(fake_client):
    """LLM returning empty actions list means no action needed."""
    fake_client.tools = SAMPLE_TOOLS
    fake_client._llm_response = json.dumps({
        "actions": [],
        "reasoning": "Nothing to do.",
    })
    result = plan(fake_client, SAMPLE_TASK)
    assert result.actions == []
    assert result.reasoning == "Nothing to do."


def test_plan_falls_back_to_empty_on_parse_failure(fake_client):
    """If LLM response is not parseable, return empty plan."""
    fake_client.tools = SAMPLE_TOOLS
    fake_client._llm_response = "I don't know what to do here."
    result = plan(fake_client, SAMPLE_TASK)
    assert isinstance(result, Plan)
    assert result.actions == []


def test_plan_caps_at_three_actions(fake_client):
    """plan() truncates action list to at most 3 items."""
    fake_client.tools = SAMPLE_TOOLS
    actions = [
        {"tool_name": "debug.echo", "input": {"n": i}, "reason": f"step {i}"}
        for i in range(5)
    ]
    fake_client._llm_response = json.dumps({"actions": actions, "reasoning": "many steps"})
    result = plan(fake_client, SAMPLE_TASK)
    assert len(result.actions) <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/nova-lite && python -m pytest tests/test_planner.py -v
```

Expected: `ImportError: cannot import name 'plan'`

- [ ] **Step 3: Implement app/logic/planner.py**

```python
import json
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MAX_ACTIONS = 3


@dataclass
class Action:
    tool_name: str
    input: dict
    reason: str


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    reasoning: str = ""


def _build_plan_prompt(task: dict, tools: list[dict]) -> str:
    tool_descriptions = "\n".join(
        f"- {t['name']}: {t['description']} | input_schema: {json.dumps(t.get('input_schema', {}))}"
        for t in tools
    )
    return (
        "You are a task planner. Given this task and available tools, decide what actions to take.\n\n"
        f"Task: {task['title']}\n"
        f"Description: {task.get('description') or 'none'}\n"
        f"Goal: {task.get('goal') or 'none'}\n\n"
        f"Available tools:\n{tool_descriptions}\n\n"
        f"Respond with JSON only (no markdown). Use 0–{MAX_ACTIONS} actions:\n"
        '{"actions": [{"tool_name": "...", "input": {...}, "reason": "..."}], "reasoning": "..."}'
    )


def _parse_plan_response(response: str) -> Plan:
    try:
        data = json.loads(response)
        raw_actions = data.get("actions", [])[:MAX_ACTIONS]
        actions = [
            Action(
                tool_name=a["tool_name"],
                input=a.get("input", {}),
                reason=a.get("reason", ""),
            )
            for a in raw_actions
            if isinstance(a, dict) and "tool_name" in a
        ]
        return Plan(actions=actions, reasoning=data.get("reasoning", ""))
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        log.warning("Failed to parse plan response: %s", e)
        return Plan()


def plan(client, task: dict) -> Plan:
    """Given a task in inbox/ready, ask LLM for 0-3 tool actions."""
    tools = client.get_tools()
    prompt = _build_plan_prompt(task, tools)
    response = client.llm_route(
        purpose="plan",
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_plan_response(response)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/nova-lite && python -m pytest tests/test_planner.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/nova-lite/app/logic/planner.py services/nova-lite/tests/test_planner.py
git commit -m "feat(nova-lite): add planner logic (task → LLM → action list)"
```

---

### Task 6: Executor + Summarizer

**Files:**
- Create: `services/nova-lite/app/logic/executor.py`
- Create: `services/nova-lite/app/logic/summarizer.py`
- Create: `services/nova-lite/tests/test_executor.py`
- Create: `services/nova-lite/tests/test_summarizer.py`

- [ ] **Step 1: Write failing tests for executor**

```python
# tests/test_executor.py
from app.logic.executor import execute
from app.logic.planner import Action, Plan


def test_execute_invokes_each_action(fake_client):
    """execute() calls invoke_tool for each action in the plan."""
    plan = Plan(
        actions=[
            Action(tool_name="debug.echo", input={"x": 1}, reason="test"),
            Action(tool_name="debug.echo", input={"x": 2}, reason="test"),
        ]
    )
    task = {"id": "task-1"}
    fake_client._invoke_result = {"run_id": "r1", "status": "succeeded"}

    results = execute(fake_client, task, plan)
    assert len(results) == 2
    assert all(r["status"] == "succeeded" for r in results)


def test_execute_empty_plan_returns_empty_list(fake_client):
    plan = Plan(actions=[])
    results = execute(fake_client, {"id": "task-1"}, plan)
    assert results == []
```

- [ ] **Step 2: Write failing tests for summarizer**

```python
# tests/test_summarizer.py
from app.logic.summarizer import summarize
from app.logic.planner import Action, Plan


def test_summarize_calls_llm_and_returns_string(fake_client):
    """summarize() calls llm_route and returns its output string."""
    fake_client._llm_response = "Task completed successfully."
    plan = Plan(
        actions=[Action(tool_name="debug.echo", input={}, reason="test")],
        reasoning="just echoing",
    )
    results = [{"run_id": "r1", "status": "succeeded"}]
    result = summarize(fake_client, {"id": "t1", "title": "Test"}, plan, results)
    assert result == "Task completed successfully."


def test_summarize_with_no_actions(fake_client):
    fake_client._llm_response = "Nothing needed."
    result = summarize(fake_client, {"id": "t1", "title": "Test"}, Plan(), [])
    assert result == "Nothing needed."
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd services/nova-lite && python -m pytest tests/test_executor.py tests/test_summarizer.py -v
```

Expected: `ImportError` for both modules

- [ ] **Step 4: Implement app/logic/executor.py**

```python
import logging
from app.logic.planner import Plan

log = logging.getLogger(__name__)


def execute(client, task: dict, plan: Plan) -> list[dict]:
    """Invoke each planned action. Returns list of run result dicts."""
    results = []
    for action in plan.actions:
        run = client.invoke_tool(action.tool_name, action.input, task_id=task["id"])
        log.info(
            "Tool %s invoked for task %s: run %s status=%s",
            action.tool_name, task["id"], run.get("run_id"), run.get("status"),
        )
        results.append(run)
    return results
```

- [ ] **Step 5: Implement app/logic/summarizer.py**

```python
import json
import logging
from app.logic.planner import Plan

log = logging.getLogger(__name__)


def _build_summary_prompt(task: dict, plan: Plan, results: list[dict]) -> str:
    actions_text = "\n".join(
        f"- {a.tool_name}: {json.dumps(a.input)} → {r.get('status', 'unknown')}"
        for a, r in zip(plan.actions, results)
    ) or "No actions were taken."
    return (
        "Write a one-sentence result summary for this completed task.\n\n"
        f"Task: {task.get('title')}\n"
        f"Actions taken:\n{actions_text}\n"
        f"Planner reasoning: {plan.reasoning}\n\n"
        "Respond with a single sentence only."
    )


def summarize(client, task: dict, plan: Plan, results: list[dict]) -> str:
    """Use LLM to produce a result_summary string for the task."""
    prompt = _build_summary_prompt(task, plan, results)
    return client.llm_route(
        purpose="summarize",
        messages=[{"role": "user", "content": prompt}],
    )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd services/nova-lite && python -m pytest tests/test_executor.py tests/test_summarizer.py -v
```

Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add services/nova-lite/app/logic/executor.py services/nova-lite/app/logic/summarizer.py \
        services/nova-lite/tests/test_executor.py services/nova-lite/tests/test_summarizer.py
git commit -m "feat(nova-lite): add executor and summarizer logic"
```

---

### Task 7: Main loop

**Files:**
- Create: `services/nova-lite/app/main.py`
- Create: `services/nova-lite/tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

Tests for `process_task()` — the inner loop body — without running the actual sleep loop.

```python
# tests/test_main.py
import pytest
from app.logic.planner import Plan, Action
from app.main import process_task
import json


def test_process_task_posts_approval_for_high_risk(fake_client):
    """High-risk tasks get posted to /approvals and processing stops there."""
    task = {
        "id": "task-1",
        "title": "Delete all files",
        "description": "risky op",
        "risk_class": "high",
        "approval_required": False,
        "status": "inbox",
    }
    fake_client.tasks["task-1"] = task
    process_task(fake_client, task)
    assert "task-1" in fake_client.approvals
    # Status should NOT have been changed beyond what post_approval does server-side
    # (process_task does NOT call patch_task separately)


def test_process_task_posts_approval_when_approval_required(fake_client):
    """Tasks with approval_required=True also trigger approval."""
    task = {
        "id": "task-2",
        "title": "Send email",
        "risk_class": "low",
        "approval_required": True,
        "status": "inbox",
    }
    fake_client.tasks["task-2"] = task
    process_task(fake_client, task)
    assert "task-2" in fake_client.approvals


def test_process_task_marks_done_when_no_actions(fake_client):
    """If planner returns empty actions, task is marked done with a summary."""
    task = {
        "id": "task-3",
        "title": "Check something",
        "risk_class": "low",
        "approval_required": False,
        "status": "inbox",
    }
    fake_client.tasks["task-3"] = task
    fake_client._llm_response = json.dumps({"actions": [], "reasoning": "Nothing to do."})

    process_task(fake_client, task)
    assert fake_client.tasks["task-3"]["status"] == "done"
    assert "Nothing to do." in fake_client.tasks["task-3"]["result_summary"]


def test_process_task_runs_to_done_on_success(fake_client):
    """Happy path: plan → execute → summarize → done."""
    task = {
        "id": "task-4",
        "title": "Echo something",
        "risk_class": "low",
        "approval_required": False,
        "status": "inbox",
    }
    fake_client.tasks["task-4"] = task
    fake_client.tools = [{"name": "debug.echo", "description": "echo", "input_schema": {}}]

    responses = iter([
        json.dumps({
            "actions": [{"tool_name": "debug.echo", "input": {"x": 1}, "reason": "test"}],
            "reasoning": "Echoing.",
        }),
        "Task completed: echoed successfully.",
    ])
    fake_client.llm_route = lambda purpose, messages, privacy_preference="local_preferred": next(responses)
    fake_client._invoke_result = {"run_id": "r1", "status": "succeeded"}

    process_task(fake_client, task)
    assert fake_client.tasks["task-4"]["status"] == "done"
    assert fake_client.tasks["task-4"]["result_summary"] == "Task completed: echoed successfully."


def test_process_task_marks_failed_when_tool_fails(fake_client):
    """If any run status is not 'succeeded', task ends as failed."""
    task = {
        "id": "task-5",
        "title": "Broken tool",
        "risk_class": "low",
        "approval_required": False,
        "status": "inbox",
    }
    fake_client.tasks["task-5"] = task
    fake_client.tools = [{"name": "debug.echo", "description": "echo", "input_schema": {}}]

    responses = iter([
        json.dumps({
            "actions": [{"tool_name": "debug.echo", "input": {}, "reason": "test"}],
            "reasoning": "Trying.",
        }),
        "Tool failed.",
    ])
    fake_client.llm_route = lambda purpose, messages, privacy_preference="local_preferred": next(responses)
    fake_client._invoke_result = {"run_id": "r2", "status": "failed"}

    process_task(fake_client, task)
    assert fake_client.tasks["task-5"]["status"] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/nova-lite && python -m pytest tests/test_main.py -v
```

Expected: `ImportError: cannot import name 'process_task' from 'app.main'`

- [ ] **Step 3: Implement app/main.py**

```python
import logging
import signal
import time

from app.client import NovaClient, NovaClientError
from app.config import settings
from app.logic import executor, planner, summarizer, triage
from app.state import CursorState

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

_running = True


def _handle_signal(signum, frame):
    global _running
    log.info("Received signal %s, shutting down after current tick", signum)
    _running = False


def process_task(client, task: dict) -> None:
    """Act on a single inbox task: approve, plan, execute, or summarize."""
    task_id = task["id"]

    if task.get("risk_class") == "high" or task.get("approval_required"):
        # POST /tasks/{id}/approvals sets task status=needs_approval server-side;
        # no separate patch_task call needed here.
        client.post_approval(task_id, {
            "summary": f"Nova-lite wants to act on: {task['title']}",
            "consequence": task.get("description"),
        })
        return

    current_plan = planner.plan(client, task)

    if not current_plan.actions:
        client.patch_task(task_id, {
            "status": "done",
            "result_summary": "No action needed. " + current_plan.reasoning,
        })
        return

    client.patch_task(task_id, {"status": "running"})
    results = executor.execute(client, task, current_plan)

    all_succeeded = all(r.get("status") == "succeeded" for r in results)
    summary = summarizer.summarize(client, task, current_plan, results)
    client.patch_task(task_id, {
        "status": "done" if all_succeeded else "failed",
        "result_summary": summary,
    })


def run_loop(client: NovaClient, state: CursorState) -> None:
    """Main polling loop. Runs until SIGTERM/SIGINT."""
    while _running:
        try:
            cursor = state.load_cursor()

            # ── 1. Triage new events ──────────────────────────
            events = client.get_events(since=cursor, limit=10)
            for event in events:
                try:
                    triage.classify_and_create(client, event)
                    cursor = event["timestamp"]
                except NovaClientError as e:
                    log.warning("Triage failed for event %s: %s", event.get("id"), e)
            state.save_cursor(cursor)

            # ── 2. Act on inbox tasks ─────────────────────────
            tasks = client.get_tasks(status="inbox", limit=5)
            for task in tasks:
                try:
                    process_task(client, task)
                except NovaClientError as e:
                    log.warning("Processing failed for task %s: %s", task.get("id"), e)

        except Exception as e:
            log.error("Loop error: %s", e, exc_info=True)

        if _running:
            time.sleep(settings.loop_interval_seconds)


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    client = NovaClient(settings.nova_api_url)
    state = CursorState(settings.cursor_file)

    log.info("Nova-lite starting. API=%s interval=%ds", settings.nova_api_url, settings.loop_interval_seconds)
    try:
        run_loop(client, state)
    finally:
        client.close()
        log.info("Nova-lite stopped.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/nova-lite && python -m pytest tests/test_main.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run the full test suite**

```bash
cd services/nova-lite && python -m pytest -v
```

Expected: All tests pass (no failures)

- [ ] **Step 6: Commit**

```bash
git add services/nova-lite/app/main.py services/nova-lite/tests/test_main.py
git commit -m "feat(nova-lite): add main loop and process_task logic"
```

---

### Task 8: Docker Compose

**Files:**
- Modify: `infra/docker-compose.yml`
- Modify: `infra/.env.example`

- [ ] **Step 1: Read current docker-compose.yml**

Open `infra/docker-compose.yml` and read its current content before editing.

- [ ] **Step 2: Add api healthcheck and nova-lite service**

Add a `healthcheck` block to the `api` service (needed for `condition: service_healthy`):

```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5
```

Add the `nova-lite` service after `api`:

```yaml
  nova-lite:
    build: ../services/nova-lite
    depends_on:
      api:
        condition: service_healthy
    environment:
      NOVA_API_URL: ${NOVA_API_URL:-http://api:8000}
      LOOP_INTERVAL_SECONDS: ${LOOP_INTERVAL_SECONDS:-15}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    volumes:
      - nova-lite-state:/app/state
    restart: unless-stopped
```

Add the `nova-lite-state` named volume to the top-level `volumes:` section.

- [ ] **Step 3: Update infra/.env.example**

If `.env.example` doesn't exist, create it. Add:

```bash
# Nova-lite
NOVA_API_URL=http://api:8000
LOOP_INTERVAL_SECONDS=15
LOG_LEVEL=INFO
```

- [ ] **Step 4: Verify docker-compose.yml is valid**

```bash
cd infra && docker compose config --quiet
```

Expected: No output (valid) or summary of services

- [ ] **Step 5: Commit**

```bash
git add infra/docker-compose.yml infra/.env.example
git commit -m "feat(infra): add nova-lite service and api healthcheck to docker-compose"
```

---

## Phase 2 Integration Check (after both Plan A and Plan B complete)

Run `docker compose up` from `infra/` and verify:

```bash
# 1. Services start cleanly
docker compose up db api nova-lite --wait

# 2. API health
curl http://localhost:8000/health
# Expected: {"status": "ok", "db": "ok"}

# 3. Ingest a test event
curl -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type": "test.manual", "source": "cli", "subject": "manual test event", "payload": {}}'
# Expected: HTTP 201, {"id": "...", "timestamp": "..."}

# 4. Wait 2 loop ticks (30s), then check tasks
curl http://localhost:8000/tasks
# Expected: task with origin_event_id matching the event id above

# 5. Invoke debug.echo directly
curl -X POST http://localhost:8000/tools/debug.echo/invoke \
  -H "Content-Type: application/json" \
  -d '{"input": {"hello": "world"}}'
# Expected: {"run_id": "...", "status": "succeeded"}
```
