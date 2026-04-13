# Phase 2: Nova-lite — Design Spec

**Date:** 2026-04-13
**Status:** Approved
**Scope:** `services/nova-lite/` (new) + API additions in `services/api/`

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| LLM access | Nova-lite calls `POST /llm/route` only — no direct model clients | Centralizes provider config; `/llm/route` is the long-term contract |
| Execution model | Single sequential polling loop | YAGNI; two-loop heartbeat pattern is the future shape but not needed to validate Phase 2 |
| API relationship | Nova-lite is a pure HTTP client of the API service | Clean separation; validates contracts in practice |
| Cursor strategy | JSON state file (`state/cursor.json`) persisted to a Docker volume | Survives restarts without schema changes to frozen Event model |
| Tool execution | Synchronous, but maintain queued→running→succeeded/failed Run lifecycle | Keeps model accurate for when async execution lands in later phases |
| Tool seeding | Upsert on API startup | Tools are config, not migrations; makes them easy to update |
| LLM provider seeding | Upsert on API startup from env vars | Same rationale; no migration churn for provider changes |

---

## Phase 2 Scope

### API additions (`services/api/`)

The following currently-stubbed endpoints are implemented in Phase 2:

| Endpoint | Status → Phase 2 |
|---|---|
| `POST /events` | 501 → implemented |
| `GET /events` | 501 → implemented |
| `POST /llm/route` | 501 → implemented |
| `GET /tools` | 501 → implemented |
| `GET /tools/{name}` | 501 → implemented |
| `POST /tools/{name}/invoke` | 501 → implemented |
| `GET /runs/{id}` | 501 → implemented |
| `GET /tasks/{id}/runs` | 501 → implemented |
| `POST /tasks/{id}/approvals` | 501 → implemented |

Additionally:
- `GET /tasks` gains an `origin_event_id` query parameter (additive, non-breaking)
- New `app/llm_client.py` — internal LLM provider routing logic called by `/llm/route`
- New `app/tools/handlers.py` — tool handler implementations
- New `app/tools/seed.py` — tool + LLM provider upsert on startup
- Alembic migration `0002` is **not needed** — all 8 tables already exist; seed data is applied via startup upsert, not DDL

### Nova-lite service (`services/nova-lite/`)

New container. Communicates with the API exclusively over HTTP.

---

## File Layout

```
nova-suite/
├── services/
│   ├── api/
│   │   └── app/
│   │       ├── llm_client.py          # provider selection + model call logic
│   │       ├── tools/
│   │       │   ├── __init__.py
│   │       │   ├── handlers.py        # debug.echo, ha.light.turn_on, devops.summarize_ci_failure
│   │       │   └── seed.py            # upsert tools + LLM providers on startup
│   │       ├── routers/
│   │       │   ├── events.py          # POST /events, GET /events  (was 501)
│   │       │   ├── llm.py             # POST /llm/route             (was 501)
│   │       │   ├── tools.py           # GET /tools, GET /tools/{name}, POST /tools/{name}/invoke (was 501)
│   │       │   ├── runs.py            # GET /runs/{id}, GET /tasks/{id}/runs (was 501)
│   │       │   └── approvals.py       # POST /tasks/{id}/approvals  (was 501)
│   │       └── schemas/
│   │           ├── event.py           # EventCreate, EventResponse (was stub)
│   │           ├── llm_provider.py    # LLMRouteRequest, LLMRouteResponse (was stub)
│   │           ├── tool.py            # ToolResponse, ToolInvokeRequest, ToolInvokeResponse (was stub)
│   │           ├── run.py             # RunResponse (was stub)
│   │           └── approval.py        # ApprovalCreate, ApprovalResponse (was stub)
│   └── nova-lite/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app/
│           ├── main.py                # entry point: loop + signal handling
│           ├── config.py              # pydantic-settings
│           ├── client.py              # typed HTTP client wrapping all API calls
│           ├── state.py               # cursor load/save (JSON file)
│           └── logic/
│               ├── __init__.py
│               ├── triage.py          # event → LLM classify → create Task
│               ├── planner.py         # task → LLM plan → action list
│               ├── executor.py        # action list → tool invocations
│               └── summarizer.py      # run results → result_summary string
└── infra/
    └── docker-compose.yml             # adds nova-lite service
```

---

## API Additions

### Events

**`POST /events`**

Request body (all from 15-16 spec):
```json
{
  "type": "string",
  "source": "string",
  "subject": "string",
  "payload": {},
  "priority": "normal",
  "risk_class": "low",
  "correlation_id": null,
  "actor_type": "system",
  "actor_id": null,
  "entity_refs": [],
  "task_ref": null
}
```
- `type`, `source`, `subject` are required
- `id` is generated (uuid4), `timestamp` is set server-side to UTC now
- Returns HTTP 201 with full `Event` object

**`GET /events`**

Query parameters:
- `since` (ISO 8601 UTC string, optional) — return only events with `timestamp > since`
- `type` (optional)
- `source` (optional)
- `priority` (optional)
- `risk_class` (optional)
- `correlation_id` (optional)
- `task_ref` (optional)
- `limit` (default 50)
- `offset` (default 0)

Returns `{"events": Event[]}`.

---

### LLM Route

**`POST /llm/route`**

Request body:
```json
{
  "purpose": "triage",
  "input": {"messages": [{"role": "user", "content": "..."}]},
  "privacy_preference": "local_preferred",
  "tool_use_required": false
}
```

`input.messages` follows the OpenAI chat messages format — an array of `{role, content}` objects. This is the only supported input format in Phase 2.

Response:
```json
{
  "provider_id": "ollama-local",
  "model_ref": "gemma3:4b",
  "output": "..."
}
```

`run_id` is omitted from the Phase 2 response (observability is Phase 5).

**Provider selection logic** (in `app/llm_client.py`):

1. Load all `LLMProviderProfile` records where `enabled=true`
2. If none found: raise `503 Service Unavailable` with `{"detail": "No LLM providers configured. Set OLLAMA_BASE_URL and OLLAMA_MODEL to configure a local provider."}`
3. Filter by `privacy_preference`:
   - `local_required` → `provider_type=local` only; 503 if none available
   - `local_preferred` → try `provider_type=local` first; fall back to cloud if no local available
   - `cloud_allowed` → all providers; prefer cloud (`provider_type=cloud`) first
4. Call the selected provider; on failure, try the next candidate
5. If all candidates fail: raise `502 Bad Gateway` with the last error message

**Provider call format:**

For `provider_type=local` (Ollama): use the `openai` Python library with `base_url=provider.endpoint_ref` and `api_key="ollama"` (Ollama ignores this). Call `client.chat.completions.create(model=provider.model_ref, messages=input.messages)`.

For `provider_type=cloud`: use the same `openai` library with the provider's `endpoint_ref` as `base_url` and API key from environment variable `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` depending on provider name. Phase 2 supports OpenAI-compatible cloud endpoints only.

**LLM provider seeding** (in `app/tools/seed.py`, called from `main.py` lifespan):

On startup, upsert a local provider if `OLLAMA_BASE_URL` is set:
```python
LLMProviderProfile(
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
```

New config fields in `app/config.py`:
```
OLLAMA_BASE_URL=http://ollama:11434   (optional; no provider seeded if absent)
OLLAMA_MODEL=gemma3:4b                (optional; default gemma3:4b)
HA_BASE_URL=                          (optional; ha.light.turn_on disabled if absent)
HA_TOKEN=                             (optional)
```

---

### Tools

**`GET /tools`** — returns `{"tools": Tool[]}` for all tools where `enabled=true`.

**`GET /tools/{name}`** — returns single Tool or 404.

**`POST /tools/{name}/invoke`**

Request body:
```json
{
  "task_id": "optional-uuid",
  "input": {},
  "requested_by": "nova-lite"
}
```

Lifecycle:
1. Look up Tool by `name` → 404 if not found
2. If `tool.enabled=false` → 400 `{"detail": "Tool is disabled"}`
3. Create `Run` record: `status=queued`, `tool_name=name`, `task_id` if provided, `executor_type=agent`, `input=body.input`, `created_at=now`
4. Update Run: `status=running`, `started_at=now`
5. Call tool handler (synchronous)
6. On success: update Run `status=succeeded`, `finished_at=now`, `output=result`
7. On exception: update Run `status=failed`, `finished_at=now`, `error=str(exc)`
8. Return `{"run_id": run.id, "status": run.status}`

**Tool handlers** (in `app/tools/handlers.py`):

`debug.echo`:
```python
def handle(input: dict) -> dict:
    return {"echo": input}
```

`ha.light.turn_on`:
```python
def handle(input: dict) -> dict:
    # input: {"entity_id": "light.living_room", "brightness": 255 (optional)}
    if not settings.ha_base_url or not settings.ha_token:
        raise RuntimeError("HA not configured: set HA_BASE_URL and HA_TOKEN")
    resp = httpx.post(
        f"{settings.ha_base_url}/api/services/light/turn_on",
        headers={"Authorization": f"Bearer {settings.ha_token}"},
        json={"entity_id": input["entity_id"], **({} if "brightness" not in input else {"brightness": input["brightness"]})},
        timeout=10,
    )
    resp.raise_for_status()
    return {"status": "ok", "entity_id": input["entity_id"]}
```

`devops.summarize_ci_failure`:
```python
def handle(input: dict) -> dict:
    # input: {"url": "https://...", "log_snippet": "..."}
    # Calls internal LLM route logic (not HTTP — direct function call)
    result = llm_client.route_internal(
        purpose="summarize",
        messages=[{"role": "user", "content": f"Summarize this CI failure:\nURL: {input['url']}\n\nLog:\n{input['log_snippet']}"}],
        privacy_preference="local_preferred",
    )
    return {"summary": result}
```

**Tool seeding** (in `app/tools/seed.py`):

On startup, upsert these 3 tools:

```python
tools = [
    Tool(
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
    Tool(
        name="ha.light.turn_on",
        display_name="HA: Turn On Light",
        description="Turns on a Home Assistant light entity. Requires HA_BASE_URL and HA_TOKEN.",
        adapter_type="home_assistant",
        input_schema={"type": "object", "properties": {"entity_id": {"type": "string"}, "brightness": {"type": "integer"}}, "required": ["entity_id"]},
        output_schema={"type": "object"},
        risk_class="low",
        requires_approval=False,
        timeout_seconds=10,
        enabled=True,
        tags=["home_assistant", "light"],
    ),
    Tool(
        name="devops.summarize_ci_failure",
        display_name="DevOps: Summarize CI Failure",
        description="Uses the LLM to summarize a CI failure from a URL and log snippet.",
        adapter_type="internal",
        input_schema={"type": "object", "properties": {"url": {"type": "string"}, "log_snippet": {"type": "string"}}, "required": ["url", "log_snippet"]},
        output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        risk_class="low",
        requires_approval=False,
        timeout_seconds=30,
        enabled=True,
        tags=["devops", "ci"],
    ),
]
```

---

### Runs

**`GET /runs/{id}`** — returns single Run or 404.

**`GET /tasks/{id}/runs`** — returns `{"runs": Run[]}` for runs linked to the given task, ordered by `created_at` desc. 404 if task not found.

---

### Approvals

**`POST /tasks/{id}/approvals`**

Request body:
```json
{
  "summary": "string",
  "consequence": "optional string",
  "options": ["approve", "deny"]
}
```

1. Look up Task → 404 if not found
2. Create `Approval` record: `status=pending`, `task_id`, `requested_by="nova-lite"`, `requested_at=now`, `options` defaulting to `["approve", "deny"]` if not provided
3. PATCH Task: `status=needs_approval`
4. Return HTTP 201 with full `Approval` object

---

### GET /tasks — new filter

Add `origin_event_id` (optional string) query parameter. Returns tasks where `origin_event_id = ?`. Used by Nova-lite for deduplication.

---

## Nova-lite Service

### Config (`app/config.py`)

```
NOVA_API_URL=http://api:8000          (required)
LOOP_INTERVAL_SECONDS=15              (default 15)
CURSOR_FILE=/app/state/cursor.json    (default)
LOG_LEVEL=INFO                        (default)
```

### Cursor (`app/state.py`)

Persists `{"last_event_timestamp": "2026-04-13T10:00:00Z"}` to `CURSOR_FILE`. On first run (file absent), uses `datetime.utcnow().isoformat()` — processes only events that arrive after Nova-lite starts.

The cursor file path should be on a Docker volume so it survives container restarts.

### API Client (`app/client.py`)

Typed methods wrapping `httpx.Client`:
```python
class NovaClient:
    def get_events(self, since: str, limit: int = 10) -> list[dict]: ...
    def get_tasks(self, status: str, limit: int = 5, origin_event_id: str | None = None) -> list[dict]: ...
    def post_task(self, payload: dict) -> dict: ...
    def patch_task(self, task_id: str, updates: dict) -> dict: ...
    def post_approval(self, task_id: str, payload: dict) -> dict: ...
    def llm_route(self, purpose: str, messages: list[dict], privacy_preference: str = "local_preferred") -> str: ...
    def invoke_tool(self, tool_name: str, input: dict, task_id: str | None = None) -> dict: ...
```

All methods raise `NovaClientError` (a custom exception) on non-2xx responses, with the status code and body preserved. The loop catches `NovaClientError` per operation and logs + skips rather than crashing.

### Triage (`app/logic/triage.py`)

```python
def classify_and_create(client, event: dict) -> dict:
    """Given an unprocessed event, use LLM to classify it and create a Task."""
    prompt = build_triage_prompt(event)
    response = client.llm_route(
        purpose="triage",
        messages=[{"role": "user", "content": prompt}],
    )
    task_fields = parse_triage_response(response)
    # task_fields: {title, description, priority, risk_class, labels}
    return client.post_task({
        "title": task_fields["title"],
        "description": task_fields.get("description"),
        "priority": task_fields.get("priority", "normal"),
        "risk_class": task_fields.get("risk_class", "low"),
        "origin_event_id": event["id"],
        "labels": task_fields.get("labels", []),
    })
```

Triage prompt instructs the LLM to return JSON with `title`, `description`, `priority` (`low`/`normal`/`high`/`urgent`), `risk_class` (`low`/`medium`/`high`), and `labels`. Response is parsed with `json.loads`; on parse failure the task is created with `title=event["subject"]` and defaults.

### Planner (`app/logic/planner.py`)

```python
@dataclass
class Action:
    tool_name: str
    input: dict
    reason: str

@dataclass
class Plan:
    actions: list[Action]   # 0–3 actions
    reasoning: str
```

```python
def plan(client, task: dict) -> Plan:
    """Given a task in inbox/ready, ask LLM for 0-3 tool actions."""
    tools = client.get_tools()  # cached per loop tick
    prompt = build_plan_prompt(task, tools)
    response = client.llm_route(
        purpose="plan",
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_plan_response(response)
```

Plan prompt includes the task title/description/goal and the list of available enabled tools (name, description, input_schema). LLM returns JSON: `{"actions": [{"tool_name": "...", "input": {...}, "reason": "..."}], "reasoning": "..."}`. Empty actions list = no action needed.

### Executor (`app/logic/executor.py`)

```python
def execute(client, task: dict, plan: Plan) -> list[dict]:
    """Invoke each planned action, return list of run results."""
    results = []
    for action in plan.actions:
        run = client.invoke_tool(action.tool_name, action.input, task_id=task["id"])
        results.append(run)
    return results
```

### Summarizer (`app/logic/summarizer.py`)

```python
def summarize(client, task: dict, plan: Plan, results: list[dict]) -> str:
    """Use LLM to write a result_summary for the completed task."""
    prompt = build_summary_prompt(task, plan, results)
    return client.llm_route(
        purpose="summarize",
        messages=[{"role": "user", "content": prompt}],
    )
```

### Main Loop (`app/main.py`)

```python
def run_loop(client, state):
    tools_cache = None

    while True:
        try:
            cursor = state.load_cursor()

            # ── 1. Triage new events ──────────────────────────
            events = client.get_events(since=cursor, limit=10)
            for event in events:
                try:
                    existing = client.get_tasks(origin_event_id=event["id"], limit=1)
                    if not existing:
                        triage.classify_and_create(client, event)
                    cursor = event["timestamp"]
                except NovaClientError as e:
                    log.warning("Triage failed for event %s: %s", event["id"], e)
            state.save_cursor(cursor)

            # ── 2. Act on inbox tasks ─────────────────────────
            tasks = client.get_tasks(status="inbox", limit=5)
            for task in tasks:
                try:
                    process_task(client, task)
                except NovaClientError as e:
                    log.warning("Processing failed for task %s: %s", task["id"], e)

        except Exception as e:
            log.error("Loop error: %s", e)

        time.sleep(settings.loop_interval_seconds)


def process_task(client, task):
    # Check approval requirement
    if task["risk_class"] == "high" or task["approval_required"]:
        client.post_approval(task["id"], {
            "summary": f"Nova-lite wants to act on: {task['title']}",
            "consequence": task.get("description"),
        })
        client.patch_task(task["id"], {"status": "needs_approval"})
        return

    plan = planner.plan(client, task)

    if not plan.actions:
        client.patch_task(task["id"], {
            "status": "done",
            "result_summary": "No action needed. " + plan.reasoning,
        })
        return

    client.patch_task(task["id"], {"status": "running"})
    results = executor.execute(client, task, plan)

    all_succeeded = all(r["status"] == "succeeded" for r in results)
    summary = summarizer.summarize(client, task, plan, results)
    client.patch_task(task["id"], {
        "status": "done" if all_succeeded else "failed",
        "result_summary": summary,
    })
```

---

## Docker Compose Additions

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

volumes:
  nova-lite-state:
```

The `api` service needs a healthcheck added to docker-compose.yml so `depends_on: condition: service_healthy` works:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 10s
  timeout: 5s
  retries: 5
```

---

## Phase 2 Success Criteria

- [ ] `docker compose up` starts `db`, `api`, and `nova-lite` without errors
- [ ] `POST /events` with a test event returns HTTP 201 with an id
- [ ] `GET /events?since=<timestamp>` returns only events after that timestamp
- [ ] `POST /llm/route` with `privacy_preference=local_preferred` returns a model response (requires Ollama running; returns 503 if not configured)
- [ ] `POST /llm/route` with no providers configured returns HTTP 503 with a helpful message
- [ ] `POST /tools/debug.echo/invoke` with `{"input": {"hello": "world"}}` returns `{"run_id": "...", "status": "succeeded"}`
- [ ] `GET /runs/{run_id}` returns the Run with `output={"echo": {"hello": "world"}}`
- [ ] After `POST /events`, Nova-lite creates a corresponding Task within two loop ticks
- [ ] Nova-lite moves a low-risk task from `inbox` → `running` → `done` end-to-end
- [ ] A high-risk task (`risk_class=high`) is moved to `needs_approval` with an Approval record created
- [ ] Swagger UI at `http://localhost:8000/docs` shows all newly-implemented endpoints (not 501)

---

## Out of Scope (Phase 2)

- `GET /approvals/{id}`, `POST /approvals/{id}/respond` — remain 501 (approval response UI is Phase 1)
- `GET /board`, `PATCH /board/tasks/{id}` — remain 501 (Nova Board is Phase 1)
- `GET /entities`, `GET /entities/{id}`, `POST /entities/sync` — remain 501 (HA integration is Phase 3)
- WebSocket / real-time push
- Concurrent or async tool execution
- Nova-lite processing `needs_approval` tasks after approval (requires the approvals response endpoint)
- Tool `ha.light.turn_on` actually connecting to HA (HA is Phase 3; tool returns error if `HA_BASE_URL` not set)
- Authentication / API keys
