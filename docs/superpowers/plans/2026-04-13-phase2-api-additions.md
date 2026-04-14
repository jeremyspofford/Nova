# Phase 2: API Additions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 2 API endpoints (events, llm/route, tools/runs, approvals) so Nova-lite has a real backend to call.

**Architecture:** All additions are to the existing `services/api` FastAPI service. New routers replace NotImplementedError stubs. A new `app/llm_client.py` module handles provider selection and LLM calls. A new `app/tools/` package holds tool handlers and startup seeding logic. Main.py gains a lifespan hook that seeds tools and LLM providers on startup.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, openai Python library (OpenAI-compatible, works with Ollama), httpx (already in requirements), pytest + TestClient

**Prerequisite:** Phase 0 implementation complete on `main` branch. All 8 DB tables exist. Run `docker compose up db api` to verify the stack starts cleanly before beginning.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `services/api/requirements.txt` | Modify | Add `openai` |
| `services/api/app/config.py` | Modify | Add `ollama_base_url`, `ollama_model`, `ha_base_url`, `ha_token` |
| `services/api/app/main.py` | Modify | Add lifespan hook for startup seeding |
| `services/api/app/llm_client.py` | Create | Provider selection + LLM call logic |
| `services/api/app/tools/__init__.py` | Create | Package marker |
| `services/api/app/tools/handlers.py` | Create | Tool handler implementations |
| `services/api/app/tools/seed.py` | Create | Upsert tools + LLM providers on startup |
| `services/api/app/schemas/event.py` | Replace stub | EventCreate, EventCreateResponse, EventRead, EventListResponse |
| `services/api/app/schemas/llm_provider.py` | Replace stub | LLMRouteRequest, LLMRouteResponse |
| `services/api/app/schemas/tool.py` | Replace stub | ToolResponse, ToolInvokeRequest, ToolInvokeResponse |
| `services/api/app/schemas/run.py` | Replace stub | RunRead, RunListResponse |
| `services/api/app/schemas/approval.py` | Replace stub | ApprovalCreate, ApprovalRead |
| `services/api/app/routers/events.py` | Replace stub | POST /events, GET /events |
| `services/api/app/routers/llm.py` | Replace stub | POST /llm/route |
| `services/api/app/routers/tools.py` | Replace stub | GET /tools, GET /tools/{name}, POST /tools/{name}/invoke |
| `services/api/app/routers/runs.py` | Replace stub | GET /runs/{id}, GET /tasks/{id}/runs |
| `services/api/app/routers/approvals.py` | Replace stub | POST /tasks/{id}/approvals |
| `services/api/app/routers/tasks.py` | Modify | Add `origin_event_id` query filter |
| `services/api/tests/test_events.py` | Create | Tests for events endpoints |
| `services/api/tests/test_llm.py` | Create | Tests for /llm/route |
| `services/api/tests/test_tools.py` | Create | Tests for tools + invoke |
| `services/api/tests/test_runs.py` | Create | Tests for runs endpoints |
| `services/api/tests/test_approvals.py` | Create | Tests for approvals endpoint |
| `services/api/tests/test_stubs.py` | Modify | Remove now-implemented routes |
| `infra/docker-compose.yml` | Modify | Add healthcheck to `api` service |
| `infra/.env.example` | Modify | Add OLLAMA_BASE_URL, OLLAMA_MODEL |

---

### Task 1: Requirements + stub test cleanup

**Files:**
- Modify: `services/api/requirements.txt`
- Modify: `services/api/tests/test_stubs.py`

- [ ] **Step 1: Add `openai` to requirements.txt**

Open `services/api/requirements.txt`. Add this line:
```
openai==1.75.0
```

- [ ] **Step 2: Update test_stubs.py to remove now-implemented routes**

Replace `services/api/tests/test_stubs.py` entirely:

```python
# These routes remain 501 stubs after Phase 2.
# Routes implemented in Phase 2 (events, /llm/route, tools, runs/{id}, tasks/{id}/runs,
# tasks/{id}/approvals) are removed from this list and tested in their own test files.
STUB_ROUTES = [
    # Board
    ("GET",   "/board",                     None),
    ("PATCH", "/board/tasks/some-id",       {"board_column_id": "col-1"}),
    # Runs — generic list stays 501 (only /runs/{id} and /tasks/{id}/runs are implemented)
    ("GET",   "/runs",                      None),
    # Approvals — respond and get-by-id stay 501 (only POST /tasks/{id}/approvals is implemented)
    ("GET",   "/approvals/some-id",         None),
    ("POST",  "/approvals/some-id/respond", {"decision": "approved", "decided_by": "user"}),
    # Entities
    ("GET",   "/entities",                  None),
    ("GET",   "/entities/some-id",          None),
    ("POST",  "/entities/sync",             {}),
    # LLM providers list — only /llm/route is implemented; provider list/detail stay 501
    ("GET",   "/llm/providers",             None),
    ("GET",   "/llm/providers/some-id",     None),
]


def test_stub_routes_return_501(client):
    for method, path, body in STUB_ROUTES:
        response = client.request(method, path, json=body)
        assert response.status_code == 501, (
            f"{method} {path} returned {response.status_code}, expected 501"
        )
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
cd services/api
python3 -m pytest tests/ -v
```

Expected: 12 passed (stub test now covers 10 routes instead of 19; health + task tests unchanged).

- [ ] **Step 4: Commit**

```bash
git add services/api/requirements.txt services/api/tests/test_stubs.py
git commit -m "chore: add openai dependency; trim test_stubs to Phase 2 remaining 501 routes"
```

---

### Task 2: Event schemas + events router

**Files:**
- Replace: `services/api/app/schemas/event.py`
- Replace: `services/api/app/routers/events.py`
- Create: `services/api/tests/test_events.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_events.py`:

```python
from datetime import datetime, timezone, timedelta


def test_post_event_returns_id_and_timestamp(client):
    response = client.post("/events", json={
        "type": "test.event",
        "source": "test",
        "subject": "Test event",
    })
    assert response.status_code == 201
    data = response.json()
    assert set(data.keys()) == {"id", "timestamp"}
    assert data["id"]
    assert data["timestamp"]


def test_post_event_missing_required_fields(client):
    response = client.post("/events", json={"type": "test.event"})
    assert response.status_code == 422


def test_post_event_optional_fields(client):
    response = client.post("/events", json={
        "type": "ha.state_changed",
        "source": "home_assistant",
        "subject": "light.living_room",
        "payload": {"new_state": "on"},
        "priority": "high",
        "risk_class": "medium",
        "actor_type": "user",
    })
    assert response.status_code == 201


def test_get_events_empty(client):
    response = client.get("/events")
    assert response.status_code == 200
    assert response.json() == {"events": []}


def test_get_events_returns_posted(client):
    client.post("/events", json={"type": "t", "source": "s", "subject": "sub"})
    response = client.get("/events")
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "t"
    assert events[0]["source"] == "s"


def test_get_events_since_filter(client):
    # Post event A
    r_a = client.post("/events", json={"type": "t", "source": "s", "subject": "A"})
    ts_a = r_a.json()["timestamp"]

    # Post event B after A
    client.post("/events", json={"type": "t", "source": "s", "subject": "B"})

    # Query since ts_a — should return only B
    response = client.get(f"/events?since={ts_a}")
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    assert events[0]["subject"] == "B"


def test_get_events_type_filter(client):
    client.post("/events", json={"type": "type.a", "source": "s", "subject": "x"})
    client.post("/events", json={"type": "type.b", "source": "s", "subject": "y"})
    response = client.get("/events?type=type.a")
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "type.a"


def test_get_events_limit(client):
    for i in range(5):
        client.post("/events", json={"type": "t", "source": "s", "subject": str(i)})
    response = client.get("/events?limit=2")
    assert response.status_code == 200
    assert len(response.json()["events"]) == 2
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd services/api
python3 -m pytest tests/test_events.py -v
```

Expected: FAIL — events routes return 501.

- [ ] **Step 3: Replace event schemas**

Replace `services/api/app/schemas/event.py`:

```python
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict


class EventCreate(BaseModel):
    type: str
    source: str
    subject: str
    payload: dict[str, Any] = {}
    priority: str = "normal"
    risk_class: str = "low"
    correlation_id: str | None = None
    actor_type: str = "system"
    actor_id: str | None = None
    entity_refs: list[str] = []
    task_ref: str | None = None


class EventCreateResponse(BaseModel):
    """Minimal POST /events response per 15-16 spec."""
    id: str
    timestamp: datetime


class EventRead(BaseModel):
    """Full event record returned in GET /events."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    source: str
    subject: str
    payload: dict[str, Any]
    timestamp: datetime
    priority: str
    risk_class: str
    actor_type: str
    actor_id: str | None
    entity_refs: list[str]
    task_ref: str | None
    correlation_id: str | None


class EventListResponse(BaseModel):
    events: list[EventRead]
```

- [ ] **Step 4: Replace events router**

Replace `services/api/app/routers/events.py`:

```python
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.event import Event
from app.schemas.event import (
    EventCreate,
    EventCreateResponse,
    EventListResponse,
    EventRead,
)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventCreateResponse, status_code=201)
def create_event(body: EventCreate, db: Session = Depends(get_db)):
    event = Event(
        type=body.type,
        source=body.source,
        subject=body.subject,
        payload=body.payload,
        priority=body.priority,
        risk_class=body.risk_class,
        correlation_id=body.correlation_id,
        actor_type=body.actor_type,
        actor_id=body.actor_id,
        entity_refs=body.entity_refs,
        task_ref=body.task_ref,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return EventCreateResponse(id=event.id, timestamp=event.timestamp)


@router.get("", response_model=EventListResponse)
def list_events(
    since: str | None = Query(None, description="ISO 8601 UTC timestamp; return events after this time"),
    type: str | None = Query(None),
    source: str | None = Query(None),
    priority: str | None = Query(None),
    risk_class: str | None = Query(None),
    correlation_id: str | None = Query(None),
    task_ref: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Event)
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, detail="Invalid 'since' format. Use ISO 8601, e.g. 2026-04-13T10:00:00Z")
        query = query.filter(Event.timestamp > since_dt)
    if type:
        query = query.filter(Event.type == type)
    if source:
        query = query.filter(Event.source == source)
    if priority:
        query = query.filter(Event.priority == priority)
    if risk_class:
        query = query.filter(Event.risk_class == risk_class)
    if correlation_id:
        query = query.filter(Event.correlation_id == correlation_id)
    if task_ref:
        query = query.filter(Event.task_ref == task_ref)
    events = query.order_by(Event.timestamp).offset(offset).limit(limit).all()
    return EventListResponse(events=[EventRead.model_validate(e) for e in events])
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_events.py tests/test_stubs.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/schemas/event.py services/api/app/routers/events.py services/api/tests/test_events.py
git commit -m "feat: implement POST /events and GET /events with since/type/source filters"
```

---

### Task 3: LLM client module + config additions

**Files:**
- Modify: `services/api/app/config.py`
- Create: `services/api/app/llm_client.py`
- Create: `services/api/tests/test_llm_client.py`

- [ ] **Step 1: Write failing unit tests for llm_client**

Create `services/api/tests/test_llm_client.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from app.llm_client import (
    route,
    route_internal,
    NoProvidersError,
    NoMatchingProvidersError,
    AllProvidersFailed,
    LLMResult,
)
from app.models.llm_provider import LLMProviderProfile


def make_provider(id="p1", provider_type="local", enabled=True):
    p = LLMProviderProfile()
    p.id = id
    p.provider_type = provider_type
    p.endpoint_ref = "http://localhost:11434/v1"
    p.model_ref = "gemma3:4b"
    p.enabled = enabled
    return p


def test_raises_no_providers_when_db_empty(db_session):
    with pytest.raises(NoProvidersError):
        route(db_session, "triage", [{"role": "user", "content": "hi"}])


def test_raises_no_matching_providers_for_local_required_with_cloud_only(db_session):
    db_session.add(make_provider(provider_type="cloud"))
    db_session.commit()
    with pytest.raises(NoMatchingProvidersError):
        route(db_session, "triage", [{"role": "user", "content": "hi"}],
              privacy_preference="local_required")


def test_local_preferred_returns_local_first(db_session):
    local = make_provider(id="local", provider_type="local")
    cloud = make_provider(id="cloud", provider_type="cloud")
    db_session.add_all([local, cloud])
    db_session.commit()

    call_order = []

    def fake_caller(provider, messages):
        call_order.append(provider.id)
        return "ok"

    result = route(db_session, "triage", [{"role": "user", "content": "hi"}],
                   _caller=fake_caller)
    assert isinstance(result, LLMResult)
    assert call_order[0] == "local"


def test_falls_back_to_cloud_when_local_fails(db_session):
    local = make_provider(id="local", provider_type="local")
    cloud = make_provider(id="cloud", provider_type="cloud")
    db_session.add_all([local, cloud])
    db_session.commit()

    def fake_caller(provider, messages):
        if provider.id == "local":
            raise RuntimeError("Ollama down")
        return "cloud response"

    result = route(db_session, "triage", [{"role": "user", "content": "hi"}],
                   privacy_preference="local_preferred", _caller=fake_caller)
    assert result.output == "cloud response"
    assert result.provider_id == "cloud"


def test_raises_all_providers_failed_when_all_fail(db_session):
    db_session.add(make_provider())
    db_session.commit()

    def fake_caller(provider, messages):
        raise RuntimeError("dead")

    with pytest.raises(AllProvidersFailed):
        route(db_session, "triage", [{"role": "user", "content": "hi"}],
              _caller=fake_caller)


def test_route_internal_is_equivalent(db_session):
    db_session.add(make_provider())
    db_session.commit()

    def fake_caller(provider, messages):
        return "internal result"

    result = route_internal(db_session, "summarize",
                            [{"role": "user", "content": "hello"}],
                            _caller=fake_caller)
    assert result == "internal result"
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3 -m pytest tests/test_llm_client.py -v
```

Expected: ImportError — `app.llm_client` does not exist yet.

- [ ] **Step 3: Add config fields**

Open `services/api/app/config.py`. Add four new optional fields inside the `Settings` class, before `model_config`:

```python
    ollama_base_url: str = ""   # e.g. http://ollama:11434; empty = no local provider seeded
    ollama_model: str = "gemma3:4b"
    ha_base_url: str = ""       # e.g. http://homeassistant.local:8123; empty = HA tools return error
    ha_token: str = ""          # HA long-lived access token
```

Full `config.py` after the change:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    deployment_mode: str = "local"
    service_name: str = "nova-api"
    version: str = "0.1.0"
    ollama_base_url: str = ""
    ollama_model: str = "gemma3:4b"
    ha_base_url: str = ""
    ha_token: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 4: Create `app/llm_client.py`**

Create `services/api/app/llm_client.py`:

```python
"""
LLM provider routing.

Public API:
  route(db, purpose, messages, privacy_preference, _caller) -> LLMResult
  route_internal(db, purpose, messages, privacy_preference, _caller) -> str

_caller is injectable for testing; defaults to the real OpenAI-compatible call.
"""
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.llm_provider import LLMProviderProfile


class NoProvidersError(Exception):
    """No enabled LLMProviderProfile records exist in the database."""


class NoMatchingProvidersError(Exception):
    """Enabled providers exist but none match the requested privacy_preference."""


class AllProvidersFailed(Exception):
    """Every candidate provider raised an exception."""
    def __init__(self, last_error: Exception):
        self.last_error = last_error
        super().__init__(str(last_error))


@dataclass
class LLMResult:
    provider_id: str
    model_ref: str
    output: str


def route(
    db: Session,
    purpose: str,
    messages: list[dict],
    privacy_preference: str = "local_preferred",
    _caller=None,
) -> LLMResult:
    """Select a provider and call the LLM. Returns LLMResult.

    _caller(provider, messages) -> str  — injectable for tests; omit in production.
    """
    _caller = _caller or _call_provider_real

    providers = db.query(LLMProviderProfile).filter(
        LLMProviderProfile.enabled == True  # noqa: E712
    ).all()
    if not providers:
        raise NoProvidersError()

    candidates = _select_candidates(providers, privacy_preference)
    if not candidates:
        raise NoMatchingProvidersError()

    last_error: Exception | None = None
    for provider in candidates:
        try:
            output = _caller(provider, messages)
            return LLMResult(
                provider_id=provider.id,
                model_ref=provider.model_ref,
                output=output,
            )
        except Exception as exc:
            last_error = exc

    raise AllProvidersFailed(last_error)


def route_internal(
    db: Session,
    purpose: str,
    messages: list[dict],
    privacy_preference: str = "local_preferred",
    _caller=None,
) -> str:
    """Same as route() but returns just the output string.
    Used by tool handlers that need LLM access without an HTTP round-trip.
    """
    result = route(db, purpose, messages, privacy_preference, _caller)
    return result.output


def _select_candidates(providers: list, privacy_preference: str) -> list:
    local = [p for p in providers if p.provider_type == "local"]
    cloud = [p for p in providers if p.provider_type == "cloud"]
    if privacy_preference == "local_required":
        return local
    elif privacy_preference == "local_preferred":
        return local + cloud
    else:  # cloud_allowed
        return cloud + local


def _call_provider_real(provider, messages: list[dict]) -> str:
    """Call the provider via OpenAI-compatible API. Used in production."""
    import os
    from openai import OpenAI

    if provider.provider_type == "local":
        api_key = "ollama"
    else:
        api_key = (
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or "missing-api-key"
        )

    client = OpenAI(base_url=provider.endpoint_ref, api_key=api_key)
    response = client.chat.completions.create(
        model=provider.model_ref,
        messages=messages,
    )
    return response.choices[0].message.content
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_llm_client.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/config.py services/api/app/llm_client.py services/api/tests/test_llm_client.py
git commit -m "feat: add LLM client with provider selection, fallback, and injectable caller for tests"
```

---

### Task 4: LLM route router + provider seeding + main.py lifespan

**Files:**
- Replace: `services/api/app/schemas/llm_provider.py`
- Replace: `services/api/app/routers/llm.py`
- Create: `services/api/app/tools/__init__.py`
- Create: `services/api/app/tools/seed.py` (LLM provider seeding only — tool seeding added in Task 5)
- Modify: `services/api/app/main.py`
- Create: `services/api/tests/test_llm_route.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_llm_route.py`:

```python
import pytest
from unittest.mock import patch
from app.models.llm_provider import LLMProviderProfile


def make_provider(db, id="p1", provider_type="local"):
    p = LLMProviderProfile(
        id=id,
        name="Test Provider",
        provider_type=provider_type,
        endpoint_ref="http://localhost:11434/v1",
        model_ref="gemma3:4b",
        enabled=True,
        supports_tools=False,
        supports_streaming=False,
        privacy_class="local_only",
        cost_class="low",
        latency_class="medium",
    )
    db.add(p)
    db.commit()
    return p


def test_llm_route_503_when_no_providers(client):
    response = client.post("/llm/route", json={
        "purpose": "triage",
        "input": {"messages": [{"role": "user", "content": "hi"}]},
    })
    assert response.status_code == 503
    assert "No LLM providers" in response.json()["detail"]


def test_llm_route_503_local_required_with_cloud_only(client, db_session):
    make_provider(db_session, provider_type="cloud")
    response = client.post("/llm/route", json={
        "purpose": "triage",
        "input": {"messages": [{"role": "user", "content": "hi"}]},
        "privacy_preference": "local_required",
    })
    assert response.status_code == 503


def test_llm_route_success(client, db_session):
    make_provider(db_session)
    with patch("app.llm_client._call_provider_real", return_value="mocked response"):
        response = client.post("/llm/route", json={
            "purpose": "triage",
            "input": {"messages": [{"role": "user", "content": "hello"}]},
        })
    assert response.status_code == 200
    data = response.json()
    assert data["output"] == "mocked response"
    assert data["provider_id"] == "p1"
    assert data["model_ref"] == "gemma3:4b"


def test_llm_route_502_when_provider_fails(client, db_session):
    make_provider(db_session)
    with patch("app.llm_client._call_provider_real", side_effect=RuntimeError("connection refused")):
        response = client.post("/llm/route", json={
            "purpose": "triage",
            "input": {"messages": [{"role": "user", "content": "hi"}]},
        })
    assert response.status_code == 502
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3 -m pytest tests/test_llm_route.py -v
```

Expected: FAIL — /llm/route returns 501.

- [ ] **Step 3: Replace LLM schemas**

Replace `services/api/app/schemas/llm_provider.py`:

```python
from typing import Literal
from pydantic import BaseModel


class LLMRouteRequest(BaseModel):
    purpose: str
    input: dict  # {"messages": [{"role": "...", "content": "..."}]}
    privacy_preference: Literal["local_preferred", "local_required", "cloud_allowed"] = "local_preferred"
    tool_use_required: bool = False


class LLMRouteResponse(BaseModel):
    provider_id: str
    model_ref: str
    output: str
    # run_id omitted — Phase 5 observability
```

- [ ] **Step 4: Replace LLM router**

Replace `services/api/app/routers/llm.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.llm_provider import LLMRouteRequest, LLMRouteResponse
from app import llm_client

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers")
def list_providers():
    raise NotImplementedError


@router.get("/providers/{provider_id}")
def get_provider(provider_id: str):
    raise NotImplementedError


@router.post("/route", response_model=LLMRouteResponse)
def route_llm(body: LLMRouteRequest, db: Session = Depends(get_db)):
    messages = body.input.get("messages", [])
    try:
        result = llm_client.route(
            db,
            purpose=body.purpose,
            messages=messages,
            privacy_preference=body.privacy_preference,
        )
    except llm_client.NoProvidersError:
        raise HTTPException(
            503,
            detail="No LLM providers configured. Set OLLAMA_BASE_URL and OLLAMA_MODEL to configure a local provider.",
        )
    except llm_client.NoMatchingProvidersError:
        raise HTTPException(
            503,
            detail="No LLM providers available for the requested privacy preference.",
        )
    except llm_client.AllProvidersFailed as exc:
        raise HTTPException(502, detail=f"All LLM providers failed: {exc.last_error}")
    return LLMRouteResponse(
        provider_id=result.provider_id,
        model_ref=result.model_ref,
        output=result.output,
    )
```

- [ ] **Step 5: Create `app/tools/__init__.py`**

Create `services/api/app/tools/__init__.py` as an empty file.

- [ ] **Step 6: Create `app/tools/seed.py`** (LLM provider seeding; tool seeding added in Task 5)

Create `services/api/app/tools/seed.py`:

```python
"""
Startup seeding for tools and LLM providers.
Called from main.py lifespan on every startup (upsert — safe to re-run).
"""
from sqlalchemy.orm import Session
from app.models.llm_provider import LLMProviderProfile


def seed_llm_providers(db: Session, settings) -> None:
    """Upsert the Ollama local provider if OLLAMA_BASE_URL is set."""
    if not settings.ollama_base_url:
        return

    provider = db.query(LLMProviderProfile).filter(
        LLMProviderProfile.id == "ollama-local"
    ).first()

    if provider:
        provider.endpoint_ref = settings.ollama_base_url + "/v1"
        provider.model_ref = settings.ollama_model
        provider.enabled = True
    else:
        provider = LLMProviderProfile(
            id="ollama-local",
            name="Ollama Local",
            provider_type="local",
            endpoint_ref=settings.ollama_base_url + "/v1",
            model_ref=settings.ollama_model,
            enabled=True,
            supports_tools=False,
            supports_streaming=False,
            privacy_class="local_only",
            cost_class="low",
            latency_class="medium",
        )
        db.add(provider)

    db.commit()


def seed_tools(db: Session) -> None:
    """Placeholder — full implementation in Task 5."""
    pass
```

- [ ] **Step 7: Add lifespan to main.py**

Replace `services/api/app/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.routers import health, tasks, events, board, tools, runs, approvals, entities, llm
from app.database import SessionLocal
from app.tools.seed import seed_tools, seed_llm_providers
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        seed_tools(db)
        seed_llm_providers(db, settings)
    finally:
        db.close()
    yield


app = FastAPI(title="Nova API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(NotImplementedError)
async def not_implemented_handler(request: Request, exc: NotImplementedError):
    return JSONResponse(status_code=501, content={"detail": "Not implemented"})


app.include_router(health.router)
app.include_router(tasks.router)
app.include_router(events.router)
app.include_router(board.router)
app.include_router(tools.router)
app.include_router(runs.router)
app.include_router(approvals.router)
app.include_router(entities.router)
app.include_router(llm.router)
```

- [ ] **Step 8: Run all tests**

```bash
python3 -m pytest tests/ -v
```

Expected: all pass (20+ tests).

- [ ] **Step 9: Commit**

```bash
git add services/api/app/schemas/llm_provider.py services/api/app/routers/llm.py \
        services/api/app/tools/__init__.py services/api/app/tools/seed.py \
        services/api/app/main.py services/api/tests/test_llm_route.py
git commit -m "feat: implement POST /llm/route with provider selection and 503/502 error handling"
```

---

### Task 5: Tool handlers + tool seeding

**Files:**
- Create: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py` (replace placeholder `seed_tools`)
- Create: `services/api/tests/test_tool_handlers.py`

- [ ] **Step 1: Write failing unit tests for handlers**

Create `services/api/tests/test_tool_handlers.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


def test_echo_returns_input():
    from app.tools.handlers import handle_debug_echo
    result = handle_debug_echo({"hello": "world"})
    assert result == {"echo": {"hello": "world"}}


def test_echo_with_empty_input():
    from app.tools.handlers import handle_debug_echo
    result = handle_debug_echo({})
    assert result == {"echo": {}}


def test_ha_light_turn_on_raises_when_not_configured(monkeypatch):
    from app.tools import handlers
    from app.config import settings
    # Ensure HA is not configured
    monkeypatch.setattr(settings, "ha_base_url", "")
    with pytest.raises(RuntimeError, match="HA not configured"):
        handlers.handle_ha_light_turn_on({"entity_id": "light.test"}, settings)


def test_ha_light_turn_on_calls_ha_api(monkeypatch, respx_mock=None):
    """Test HA tool makes the correct HTTP call."""
    from app.tools import handlers
    from app.config import settings
    import httpx

    monkeypatch.setattr(settings, "ha_base_url", "http://fake-ha:8123")
    monkeypatch.setattr(settings, "ha_token", "fake-token")

    # Mock httpx.post
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_response) as mock_post:
        result = handlers.handle_ha_light_turn_on(
            {"entity_id": "light.living_room", "brightness": 200}, settings
        )

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "light.living_room" in str(call_kwargs)
    assert result == {"status": "ok", "entity_id": "light.living_room"}


def test_summarize_ci_failure_calls_llm(db_session):
    from app.tools.handlers import handle_devops_summarize_ci_failure
    from unittest.mock import patch

    with patch("app.llm_client.route_internal", return_value="The build failed due to a timeout."):
        result = handle_devops_summarize_ci_failure(
            {"url": "https://ci.example.com/build/123", "log_snippet": "Error: timeout"},
            db_session,
        )
    assert result == {"summary": "The build failed due to a timeout."}


def test_dispatch_unknown_tool_raises():
    from app.tools.handlers import dispatch
    with pytest.raises(KeyError):
        dispatch("nonexistent.tool", {}, None, None)
```

- [ ] **Step 2: Run to verify they fail**

```bash
python3 -m pytest tests/test_tool_handlers.py -v
```

Expected: ImportError — `app.tools.handlers` does not exist.

- [ ] **Step 3: Create `app/tools/handlers.py`**

Create `services/api/app/tools/handlers.py`:

```python
"""
Tool handler implementations for Phase 2 tools.

Each handler takes (input: dict, *deps) and returns a dict output.
The dispatch() function routes by tool name.
"""
import httpx
from sqlalchemy.orm import Session
from app import llm_client
from app.config import settings as _settings


def handle_debug_echo(input: dict) -> dict:
    """Returns its input unchanged. Used for testing the invocation loop."""
    return {"echo": input}


def handle_ha_light_turn_on(input: dict, cfg=None) -> dict:
    """Calls the Home Assistant light.turn_on service.

    input: {"entity_id": "light.xyz", "brightness": 0-255 (optional)}
    Raises RuntimeError if HA_BASE_URL or HA_TOKEN are not configured.
    """
    cfg = cfg or _settings
    if not cfg.ha_base_url or not cfg.ha_token:
        raise RuntimeError(
            "HA not configured: set HA_BASE_URL and HA_TOKEN environment variables"
        )
    payload: dict = {"entity_id": input["entity_id"]}
    if "brightness" in input:
        payload["brightness"] = input["brightness"]
    resp = httpx.post(
        f"{cfg.ha_base_url}/api/services/light/turn_on",
        headers={"Authorization": f"Bearer {cfg.ha_token}"},
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return {"status": "ok", "entity_id": input["entity_id"]}


def handle_devops_summarize_ci_failure(input: dict, db: Session) -> dict:
    """Uses the LLM (via route_internal) to summarize a CI failure.

    input: {"url": "https://...", "log_snippet": "..."}
    """
    prompt = (
        f"Summarize this CI failure concisely (2-3 sentences):\n"
        f"URL: {input['url']}\n\n"
        f"Log:\n{input['log_snippet']}"
    )
    summary = llm_client.route_internal(
        db,
        purpose="summarize",
        messages=[{"role": "user", "content": prompt}],
    )
    return {"summary": summary}


# Registry: tool name → handler callable
# Each entry is (handler_fn, extra_deps: list["db"|"settings"])
# The dispatch function passes deps in order.
_REGISTRY: dict[str, tuple] = {
    "debug.echo": (handle_debug_echo, []),
    "ha.light.turn_on": (handle_ha_light_turn_on, ["settings"]),
    "devops.summarize_ci_failure": (handle_devops_summarize_ci_failure, ["db"]),
}


def dispatch(tool_name: str, input: dict, db: Session, cfg=None) -> dict:
    """Dispatch to the correct handler by tool name.

    Raises KeyError if tool_name is not in the registry.
    """
    handler_fn, deps = _REGISTRY[tool_name]
    args = []
    for dep in deps:
        if dep == "db":
            args.append(db)
        elif dep == "settings":
            args.append(cfg or _settings)
    return handler_fn(input, *args)
```

- [ ] **Step 4: Replace `seed_tools` in `app/tools/seed.py`**

Open `services/api/app/tools/seed.py` and replace the placeholder `seed_tools` function:

```python
def seed_tools(db: Session) -> None:
    """Upsert the Phase 2 tool definitions. Safe to re-run on every startup."""
    from app.models.tool import Tool

    tool_definitions = [
        dict(
            name="debug.echo",
            display_name="Debug Echo",
            description="Returns its input unchanged. Used for testing the tool invocation loop.",
            adapter_type="internal",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            risk_class="low",
            requires_approval=False,
            timeout_seconds=5,
            enabled=True,
            tags=["debug"],
        ),
        dict(
            name="ha.light.turn_on",
            display_name="HA: Turn On Light",
            description=(
                "Turns on a Home Assistant light entity. "
                "Requires HA_BASE_URL and HA_TOKEN environment variables."
            ),
            adapter_type="home_assistant",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 255},
                },
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
            name="devops.summarize_ci_failure",
            display_name="DevOps: Summarize CI Failure",
            description="Uses the LLM to summarize a CI failure from a URL and log snippet.",
            adapter_type="internal",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "log_snippet": {"type": "string"},
                },
                "required": ["url", "log_snippet"],
            },
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            risk_class="low",
            requires_approval=False,
            timeout_seconds=30,
            enabled=True,
            tags=["devops", "ci"],
        ),
    ]

    for defn in tool_definitions:
        tool = db.query(Tool).filter(Tool.name == defn["name"]).first()
        if tool:
            for k, v in defn.items():
                setattr(tool, k, v)
        else:
            db.add(Tool(**defn))

    db.commit()
```

- [ ] **Step 5: Run handler tests**

```bash
python3 -m pytest tests/test_tool_handlers.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Run all tests**

```bash
python3 -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/tools/handlers.py services/api/app/tools/seed.py \
        services/api/tests/test_tool_handlers.py
git commit -m "feat: add tool handlers (debug.echo, ha.light.turn_on, devops.summarize_ci_failure) and tool seeding"
```

---

### Task 6: Run schemas + Runs router + Tool schemas + Tools router

**Files:**
- Replace: `services/api/app/schemas/run.py`
- Replace: `services/api/app/schemas/tool.py`
- Replace: `services/api/app/routers/runs.py`
- Replace: `services/api/app/routers/tools.py`
- Create: `services/api/tests/test_runs.py`
- Create: `services/api/tests/test_tools.py`

- [ ] **Step 1: Write failing tests for runs**

Create `services/api/tests/test_runs.py`:

```python
def test_get_run_not_found(client):
    response = client.get("/runs/nonexistent-id")
    assert response.status_code == 404


def test_get_task_runs_not_found(client):
    response = client.get("/tasks/nonexistent-id/runs")
    assert response.status_code == 404


def test_get_task_runs_empty(client):
    # Create a task first
    r = client.post("/tasks", json={"title": "test task"})
    task_id = r.json()["id"]
    response = client.get(f"/tasks/{task_id}/runs")
    assert response.status_code == 200
    assert response.json() == {"runs": []}
```

- [ ] **Step 2: Write failing tests for tools**

Create `services/api/tests/test_tools.py`:

```python
import pytest


def test_get_tools_returns_seeded_tools(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    response = client.get("/tools")
    assert response.status_code == 200
    tools = response.json()["tools"]
    names = {t["name"] for t in tools}
    assert {"debug.echo", "ha.light.turn_on", "devops.summarize_ci_failure"} == names


def test_get_tools_default_only_enabled(client, db_session):
    from app.tools.seed import seed_tools
    from app.models.tool import Tool
    seed_tools(db_session)
    # Disable one tool
    tool = db_session.query(Tool).filter(Tool.name == "ha.light.turn_on").first()
    tool.enabled = False
    db_session.commit()
    response = client.get("/tools")
    names = {t["name"] for t in response.json()["tools"]}
    assert "ha.light.turn_on" not in names
    assert "debug.echo" in names


def test_get_tools_enabled_false_shows_all(client, db_session):
    from app.tools.seed import seed_tools
    from app.models.tool import Tool
    seed_tools(db_session)
    tool = db_session.query(Tool).filter(Tool.name == "ha.light.turn_on").first()
    tool.enabled = False
    db_session.commit()
    response = client.get("/tools?enabled=false")
    names = {t["name"] for t in response.json()["tools"]}
    assert "ha.light.turn_on" in names


def test_get_tool_by_name(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    response = client.get("/tools/debug.echo")
    assert response.status_code == 200
    assert response.json()["name"] == "debug.echo"


def test_get_tool_not_found(client):
    response = client.get("/tools/nonexistent.tool")
    assert response.status_code == 404


def test_invoke_debug_echo(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    response = client.post("/tools/debug.echo/invoke", json={"input": {"hello": "world"}})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert "run_id" in data


def test_invoke_creates_run_with_correct_output(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    r = client.post("/tools/debug.echo/invoke", json={"input": {"key": "value"}})
    run_id = r.json()["run_id"]
    run_response = client.get(f"/runs/{run_id}")
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "succeeded"
    assert run["output"] == {"echo": {"key": "value"}}
    assert run["tool_name"] == "debug.echo"


def test_invoke_run_linked_to_task(client, db_session):
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    task = client.post("/tasks", json={"title": "test"}).json()
    r = client.post("/tools/debug.echo/invoke", json={
        "input": {"x": 1},
        "task_id": task["id"],
    })
    run_id = r.json()["run_id"]
    runs = client.get(f"/tasks/{task['id']}/runs").json()["runs"]
    assert any(run["id"] == run_id for run in runs)


def test_invoke_unknown_tool_404(client):
    response = client.post("/tools/unknown.tool/invoke", json={"input": {}})
    assert response.status_code == 404


def test_invoke_disabled_tool_400(client, db_session):
    from app.tools.seed import seed_tools
    from app.models.tool import Tool
    seed_tools(db_session)
    tool = db_session.query(Tool).filter(Tool.name == "debug.echo").first()
    tool.enabled = False
    db_session.commit()
    response = client.post("/tools/debug.echo/invoke", json={"input": {}})
    assert response.status_code == 400
```

- [ ] **Step 3: Run to verify they fail**

```bash
python3 -m pytest tests/test_runs.py tests/test_tools.py -v
```

Expected: FAIL — routes return 501 or 404.

- [ ] **Step 4: Replace Run schemas**

Replace `services/api/app/schemas/run.py`:

```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Any


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str | None
    tool_name: str | None
    workflow_ref: str | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: str | None
    executor_type: str
    executor_id: str | None


class RunListResponse(BaseModel):
    runs: list[RunRead]
```

- [ ] **Step 5: Replace Tool schemas**

Replace `services/api/app/schemas/tool.py`:

```python
from typing import Any
from pydantic import BaseModel, ConfigDict


class ToolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    display_name: str
    description: str
    adapter_type: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    risk_class: str
    requires_approval: bool
    timeout_seconds: int
    enabled: bool
    tags: list[str]


class ToolListResponse(BaseModel):
    tools: list[ToolResponse]


class ToolInvokeRequest(BaseModel):
    input: dict[str, Any]
    task_id: str | None = None
    requested_by: str | None = None


class ToolInvokeResponse(BaseModel):
    run_id: str
    status: str
```

- [ ] **Step 6: Replace Runs router**

Replace `services/api/app/routers/runs.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.run import Run
from app.models.task import Task
from app.schemas.run import RunListResponse, RunRead

router = APIRouter(tags=["runs"])


@router.get("/runs", tags=["runs"])
def list_runs():
    raise NotImplementedError


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    return RunRead.model_validate(run)


@router.get("/tasks/{task_id}/runs", response_model=RunListResponse)
def list_task_runs(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    runs = (
        db.query(Run)
        .filter(Run.task_id == task_id)
        .order_by(Run.created_at.desc())
        .all()
    )
    return RunListResponse(runs=[RunRead.model_validate(r) for r in runs])
```

- [ ] **Step 7: Replace Tools router**

Replace `services/api/app/routers/tools.py`:

```python
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.run import Run
from app.models.tool import Tool
from app.schemas.tool import ToolInvokeRequest, ToolInvokeResponse, ToolListResponse, ToolResponse
from app.tools import handlers as tool_handlers

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse)
def list_tools(
    enabled: bool | None = Query(True, description="Filter by enabled status. Default true."),
    db: Session = Depends(get_db),
):
    query = db.query(Tool)
    if enabled is not None:
        query = query.filter(Tool.enabled == enabled)
    tools = query.all()
    return ToolListResponse(tools=[ToolResponse.model_validate(t) for t in tools])


@router.get("/{name}", response_model=ToolResponse)
def get_tool(name: str, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.name == name).first()
    if not tool:
        raise HTTPException(404, "Tool not found")
    return ToolResponse.model_validate(tool)


@router.post("/{name}/invoke", response_model=ToolInvokeResponse)
def invoke_tool(name: str, body: ToolInvokeRequest, db: Session = Depends(get_db)):
    tool = db.query(Tool).filter(Tool.name == name).first()
    if not tool:
        raise HTTPException(404, "Tool not found")
    if not tool.enabled:
        raise HTTPException(400, "Tool is disabled")

    run = Run(
        id=str(uuid4()),
        tool_name=name,
        task_id=body.task_id,
        executor_type="agent",
        input=body.input,
        status="queued",
    )
    db.add(run)
    db.commit()

    # Transition to running
    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        output = tool_handlers.dispatch(name, body.input, db)
        run.status = "succeeded"
        run.output = output
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
    finally:
        run.finished_at = datetime.now(timezone.utc)
        db.commit()

    db.refresh(run)
    return ToolInvokeResponse(run_id=run.id, status=run.status)
```

- [ ] **Step 8: Run all tests**

```bash
python3 -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add services/api/app/schemas/run.py services/api/app/schemas/tool.py \
        services/api/app/routers/runs.py services/api/app/routers/tools.py \
        services/api/tests/test_runs.py services/api/tests/test_tools.py
git commit -m "feat: implement tools router (GET/invoke), runs router (GET by id/task), Run lifecycle"
```

---

### Task 7: Approval schemas + approvals router + GET /tasks origin_event_id filter

**Files:**
- Replace: `services/api/app/schemas/approval.py`
- Replace: `services/api/app/routers/approvals.py`
- Modify: `services/api/app/routers/tasks.py`
- Create: `services/api/tests/test_approvals.py`
- Modify: `services/api/tests/test_tasks.py` (add one test for origin_event_id filter)

- [ ] **Step 1: Write failing tests for approvals**

Create `services/api/tests/test_approvals.py`:

```python
def test_post_approval_creates_record(client):
    task = client.post("/tasks", json={"title": "risky task"}).json()
    response = client.post(f"/tasks/{task['id']}/approvals", json={
        "summary": "Nova-lite wants to turn on all the lights",
        "consequence": "All lights in the house will turn on",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["task_id"] == task["id"]
    assert data["status"] == "pending"
    assert data["summary"] == "Nova-lite wants to turn on all the lights"
    assert data["consequence"] == "All lights in the house will turn on"
    assert data["options"] == ["approve", "deny"]  # default
    assert data["requested_by"] == "nova-lite"
    assert "id" in data
    assert "requested_at" in data


def test_post_approval_moves_task_to_needs_approval(client):
    task = client.post("/tasks", json={"title": "risky task"}).json()
    client.post(f"/tasks/{task['id']}/approvals", json={"summary": "please approve"})
    updated = client.get(f"/tasks/{task['id']}").json()
    assert updated["status"] == "needs_approval"


def test_post_approval_custom_options(client):
    task = client.post("/tasks", json={"title": "task"}).json()
    response = client.post(f"/tasks/{task['id']}/approvals", json={
        "summary": "choose",
        "options": ["yes", "no", "later"],
    })
    assert response.status_code == 201
    assert response.json()["options"] == ["yes", "no", "later"]


def test_post_approval_task_not_found(client):
    response = client.post("/tasks/nonexistent/approvals", json={"summary": "test"})
    assert response.status_code == 404
```

- [ ] **Step 2: Write failing test for origin_event_id filter**

Add to `services/api/tests/test_tasks.py`:

```python
def test_list_tasks_filter_by_origin_event_id(client):
    client.post("/tasks", json={"title": "from event", "origin_event_id": "evt-abc"})
    client.post("/tasks", json={"title": "no event"})
    response = client.get("/tasks?origin_event_id=evt-abc")
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["origin_event_id"] == "evt-abc"
```

- [ ] **Step 3: Run to verify they fail**

```bash
python3 -m pytest tests/test_approvals.py tests/test_tasks.py -v
```

Expected: approval tests fail (501), origin_event_id test fails (filter not implemented).

- [ ] **Step 4: Replace approval schemas**

Replace `services/api/app/schemas/approval.py`:

```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ApprovalCreate(BaseModel):
    summary: str
    consequence: str | None = None
    options: list[str] = ["approve", "deny"]


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    requested_by: str
    requested_at: datetime
    summary: str
    consequence: str | None
    options: list[str]
    status: str
    decided_by: str | None
    decided_at: datetime | None
    decision: str | None
    reason: str | None
```

- [ ] **Step 5: Replace approvals router**

Replace `services/api/app/routers/approvals.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.approval import Approval
from app.models.task import Task
from app.schemas.approval import ApprovalCreate, ApprovalRead

router = APIRouter(tags=["approvals"])


@router.post("/tasks/{task_id}/approvals", response_model=ApprovalRead, status_code=201)
def request_approval(task_id: str, body: ApprovalCreate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    approval = Approval(
        task_id=task_id,
        requested_by="nova-lite",
        summary=body.summary,
        consequence=body.consequence,
        options=body.options,
        status="pending",
    )
    db.add(approval)

    # Server-side: set task status to needs_approval
    task.status = "needs_approval"
    db.commit()
    db.refresh(approval)
    return ApprovalRead.model_validate(approval)


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str):
    raise NotImplementedError


@router.post("/approvals/{approval_id}/respond")
def respond_to_approval(approval_id: str):
    raise NotImplementedError
```

- [ ] **Step 6: Add `origin_event_id` filter to GET /tasks**

Open `services/api/app/routers/tasks.py`. In the `list_tasks` function, add `origin_event_id` as a parameter and apply the filter:

Add to the function signature (after `approval_required` param):
```python
    origin_event_id: str | None = Query(None),
```

Add to the filter block (after the `approval_required` filter):
```python
    if origin_event_id:
        query = query.filter(Task.origin_event_id == origin_event_id)
```

- [ ] **Step 7: Run all tests**

```bash
python3 -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add services/api/app/schemas/approval.py services/api/app/routers/approvals.py \
        services/api/app/routers/tasks.py services/api/tests/test_approvals.py \
        services/api/tests/test_tasks.py
git commit -m "feat: implement POST /tasks/{id}/approvals; add origin_event_id filter to GET /tasks"
```

---

### Task 8: Docker Compose api healthcheck + .env.example + smoke test

**Files:**
- Modify: `infra/docker-compose.yml`
- Modify: `infra/.env.example`

- [ ] **Step 1: Add healthcheck to api service in docker-compose.yml**

Open `infra/docker-compose.yml`. The `api` service currently has no healthcheck. Add one so the `nova-lite` container (Phase 2B plan) can use `depends_on: condition: service_healthy`.

Locate the `api:` service block and add:

```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
```

The `start_period` gives the Alembic migration time to run before health checks begin.

- [ ] **Step 2: Add new env vars to .env.example**

Open `infra/.env.example`. Add:

```
# LLM Provider (optional — no local provider seeded if absent)
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=gemma3:4b

# Home Assistant (optional — ha.light.turn_on returns error if absent)
HA_BASE_URL=http://homeassistant.local:8123
HA_TOKEN=your-long-lived-access-token
```

- [ ] **Step 3: Run full test suite one final time**

```bash
cd services/api
python3 -m pytest tests/ -v
```

Expected: all tests pass (health × 2, tasks × 10+, events × 7, llm_client × 6, llm_route × 4, tool_handlers × 5, tools × 9, runs × 3, approvals × 4, stubs × 10).

- [ ] **Step 4: Start the stack and run manual smoke tests**

```bash
cd infra
docker compose up --build -d
sleep 20  # wait for migrations

# Health check
curl -s http://localhost:8000/health | python3 -m json.tool

# Post an event
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type":"ci.build_failed","source":"github","subject":"main branch","payload":{"repo":"nova-suite"}}' \
  | python3 -m json.tool

# List events
curl -s http://localhost:8000/events | python3 -m json.tool

# LLM route — expect 503 (no Ollama running in CI)
curl -s -X POST http://localhost:8000/llm/route \
  -H "Content-Type: application/json" \
  -d '{"purpose":"test","input":{"messages":[{"role":"user","content":"hi"}]}}' \
  | python3 -m json.tool

# Invoke debug.echo tool
curl -s -X POST http://localhost:8000/tools/debug.echo/invoke \
  -H "Content-Type: application/json" \
  -d '{"input":{"hello":"world"}}' \
  | python3 -m json.tool

# Get the run
RUN_ID=$(curl -s -X POST http://localhost:8000/tools/debug.echo/invoke \
  -H "Content-Type: application/json" \
  -d '{"input":{"test":1}}' | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")
curl -s http://localhost:8000/runs/$RUN_ID | python3 -m json.tool

docker compose down
```

Expected:
- `/health` → `{"status": "ok", "db": "ok"}`
- POST `/events` → `{"id": "...", "timestamp": "..."}`
- GET `/events` → `{"events": [...]}`
- POST `/llm/route` → 503 (no Ollama)
- POST `/tools/debug.echo/invoke` → `{"run_id": "...", "status": "succeeded"}`
- GET `/runs/{id}` → full Run with `output: {"echo": {"hello": "world"}}`

- [ ] **Step 5: Commit**

```bash
git add infra/docker-compose.yml infra/.env.example
git commit -m "feat: add api service healthcheck to docker-compose; document new env vars in .env.example"
```
