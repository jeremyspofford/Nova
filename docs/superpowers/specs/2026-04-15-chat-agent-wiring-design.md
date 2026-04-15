# Chat–Agent Wiring & Activity Log — Design Spec

**Date:** 2026-04-15
**Status:** Approved

---

## Goal

Wire the Chat tab to Nova's tool execution engine so that natural-language messages can trigger real actions (turn on lights, make HTTP requests, etc.). Replace the kanban Board tab with a read-only Activity log showing everything Nova has done.

Scheduling / recurring goals are **out of scope** for this spec — deferred to a follow-up.

---

## Architecture Overview

The chat message path gains one new step before the LLM response call:

1. **Classification call** — a lightweight LLM call classifies the user's message as `"action"` or `"conversation"`, and if `"action"`, extracts the tool name and input parameters.
2. **Tool execution** — if classified as an action with confidence ≥ 0.7, the tool runs synchronously. A streaming acknowledgment (`[Running ha.light.turn_on...]`) is emitted via SSE before the tool starts so the chat doesn't feel frozen.
3. **Response call** — the standard LLM response call, now with the tool result injected into the system prompt context.

Nova-lite continues running unchanged. All tool invocations — whether triggered by chat or by nova-lite — write to the `Run` table, which powers the Activity tab.

The kanban Board is removed from the frontend. Nova-lite's internal tasks become invisible implementation details.

---

## Components

### 1. Intent Classifier (backend — `routers/conversations.py`)

**Classification prompt structure:**

```
System:
You are an intent classifier for Nova.
Classify the user message. Available tools:
  - ha.light.turn_on: {entity_id: string, brightness?: 0-255}
  - ha.light.turn_off: {entity_id: string}
  - http.request: {method: "GET"|"POST", url: string, headers?: object, body?: object, timeout_seconds?: number}
  - debug.echo: {message: string}
  - devops.summarize_ci_failure: {url: string, log_snippet: string}

Respond ONLY with JSON:
{
  "intent": "action" | "conversation",
  "tool_name": string | null,
  "tool_input": object | null,
  "confidence": number
}

If unsure, return intent="conversation". If intent="action", confidence must be >= 0.7 for the action to run.

User: <message>
```

**`_parse_json_safe` helper** (add to `conversations.py`):

```python
import re

def _parse_json_safe(text: str) -> dict | None:
    """Strip markdown fences and parse JSON. Returns None on any failure."""
    try:
        # Strip ```json ... ``` or ``` ... ``` fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        cleaned = match.group(1).strip() if match else text.strip()
        return json.loads(cleaned)
    except Exception:
        return None
```

Note: `_extract_json` exists in `services/nova-lite/app/logic/utils.py` but NOT in `services/api`. Do not import across service boundaries — define the helper inline in `conversations.py` as above.

**Execution ordering — critical constraint:**

FastAPI's `StreamingResponse` consumes the `generate()` generator lazily (after response headers are sent). This means anything that must inform the system prompt — classification result, tool execution, tool output — **must happen synchronously before `generate()` is defined**, captured as closure variables. The generator then reads those variables when it runs.

**Decision logic and tool execution (outside the generator):**

```python
# --- Run BEFORE defining generate() ---

# Step 1: Classify
result: str = llm_client.route_internal(db, "classify", classify_messages)
classification = _parse_json_safe(result)

tool_name = None
tool_context = None  # injected into system prompt inside generator

c = classification or {}
if (
    c.get("intent") == "action"
    and c.get("confidence", 0) >= 0.7
    and c.get("tool_name") in tool_handlers._REGISTRY  # registry check BEFORE Run creation
):
    tool_name = c["tool_name"]
    tool_input = c.get("tool_input") or {}

    # Step 2: Create Run, execute, update Run
    run = Run(
        id=str(uuid4()),
        tool_name=tool_name,
        task_id=None,
        executor_type="chat",
        trigger_type="chat",
        input=tool_input,
        status="running",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()

    try:
        output = tool_handlers.dispatch(tool_name, tool_input, db, cfg)
        run.status = "succeeded"
        run.output = output
        run.summary = f"{tool_name} → succeeded"
        tool_context = f"You just ran `{tool_name}`. Result: {json.dumps(output)}. Status: succeeded."
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        run.summary = f"{tool_name} → failed"
        tool_context = f"You tried to run `{tool_name}` but it failed: {exc}."
    finally:
        run.finished_at = datetime.now(UTC)
        db.commit()

# tool_name and tool_context are now available as closure variables
```

Unknown tool names (`tool_name not in tool_handlers._REGISTRY`) fall through silently — no Run is created, no error shown. Only the registry check (not `dispatch()`) gates Run creation.

**Generator (defined after tool execution):**

```python
def generate():
    # Emit acknowledgment if a tool ran
    if tool_name:
        yield f"data: {json.dumps({'delta': f'[Running {tool_name}...]\n'})}\n\n"
        # Note: tool already ran before generate() was entered; this is a UX indicator only

    # Build system prompt with optional tool context
    base_prompt = _build_system_prompt(db)
    system_prompt = (tool_context + "\n\n" + base_prompt) if tool_context else base_prompt

    messages = [{"role": "system", "content": system_prompt}, ...history]

    for chunk in llm_client.route_streaming(db, "chat", messages):
        yield f"data: {json.dumps({'delta': chunk})}\n\n"

    yield f"data: {json.dumps({'complete': True})}\n\n"

return StreamingResponse(generate(), media_type="text/event-stream")
```

**`_build_system_prompt` change:**

Remove the line `"You cannot execute tools directly from chat."` from the existing function. Tool context is prepended separately (see above) rather than modifying `_build_system_prompt` itself.

**Chat-triggered Run record — DB transaction sequence:**

The chat path in `conversations.py` owns Run record creation directly (does not call `dispatch()` from `handlers.py`, which is nova-lite's path). Sequence:

```python
# 1. Create Run before tool executes
run = Run(
    id=str(uuid4()),
    tool_name=tool_name,
    task_id=None,
    executor_type="chat",
    trigger_type="chat",
    input=tool_input,
    status="running",
    started_at=datetime.now(UTC),
)
db.add(run)
db.commit()

# 2. Execute tool
try:
    output = tool_handlers.dispatch(tool_name, tool_input, db, cfg)
    run.status = "succeeded"
    run.output = output
    run.summary = f"{tool_name} → succeeded"
except Exception as exc:
    run.status = "failed"
    run.error = str(exc)
    run.summary = f"{tool_name} → failed"
finally:
    run.finished_at = datetime.now(UTC)
    db.commit()  # second commit updates status/output/summary
```

`tool_handlers.dispatch()` is called here (same as nova-lite's path) — `conversations.py` uses it directly. The difference from nova-lite is that `conversations.py` owns the Run record lifecycle instead of `routers/tools.py`.

---

### 2. Tool Additions (`tools/handlers.py`)

#### `ha.light.turn_off`

```python
def handle_ha_light_turn_off(inp, db, cfg):
    entity_id = inp["entity_id"]
    resp = httpx.post(
        f"{cfg.HA_BASE_URL}/api/services/light/turn_off",
        headers={"Authorization": f"Bearer {cfg.HA_TOKEN}"},
        json={"entity_id": entity_id},
        timeout=10,
    )
    resp.raise_for_status()
    return {"status": "ok", "entity_id": entity_id}
```

Input schema: `{entity_id: string}`
Output schema: `{status: string, entity_id: string}`
Registry entry: `"ha.light.turn_off": (handle_ha_light_turn_off, ["settings"])`

**Seed entry** (add to `tool_definitions` list in `tools/seed.py`):

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
```

#### `http.request`

```python
def handle_http_request(inp, db, cfg):
    method = inp["method"].upper()  # "GET" | "POST"
    url = inp["url"]
    headers = inp.get("headers", {})
    body = inp.get("body")
    timeout = inp.get("timeout_seconds", 30)

    resp = httpx.request(method, url, headers=headers, json=body, timeout=timeout)
    body_text = resp.text[:2048]  # truncate to 2KB
    return {"status_code": resp.status_code, "body": body_text}
```

Input schema: `{method: "GET"|"POST", url: string, headers?: object, body?: object, timeout_seconds?: number}`
Output schema: `{status_code: number, body: string}`
Registry entry: `"http.request": (handle_http_request, [])` — no DB or settings dependency.
Raises on network error (caller marks run as failed).

**Seed entry** (add to `tool_definitions` list in `tools/seed.py`):

```python
dict(
    name="http.request",
    display_name="HTTP Request",
    description="Makes an HTTP GET or POST request to any URL. Returns status code and response body (truncated to 2KB).",
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

---

### 3. Run Model Changes (`models/run.py`)

Two new columns, both additive (non-breaking):

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `trigger_type` | VARCHAR | No | `"agent_loop"` |
| `summary` | TEXT | Yes | null |

**Alembic migration** — create `services/api/alembic/versions/0003_add_run_trigger_type_and_summary.py`:

```python
revision = "0003"
down_revision = "0002"

def upgrade():
    op.add_column("runs", sa.Column("trigger_type", sa.String(), nullable=False, server_default="agent_loop"))
    op.add_column("runs", sa.Column("summary", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("runs", "summary")
    op.drop_column("runs", "trigger_type")
```

`trigger_type` values: `"chat"` | `"agent_loop"`

**Relationship to existing `executor_type` column:**

`executor_type` (existing) records *who* executed the run: `"agent"` (nova-lite) or `"chat"` (chat router) or `"system"`. `trigger_type` (new) records *what triggered* it: `"chat"` (user message) or `"agent_loop"` (nova-lite autonomous loop).

These are different concepts that happen to use overlapping values in this spec. The Activity tab uses `trigger_type` exclusively for its badge display. For chat-triggered runs, set both: `executor_type="chat"`, `trigger_type="chat"`. Nova-lite runs keep `executor_type="agent"` (unchanged) and get `trigger_type="agent_loop"` from the column default.

`summary` population:
- Chat-triggered: written at run completion as `"{tool_name} → {status}"`
- Nova-lite runs: null (frontend falls back to `"{tool_name} ({status})"` display)

---

### 4. Activity API Endpoint (`routers/activity.py`)

New router mounted at `/activity`.

**`GET /activity`**

Query params:
- `limit` (int, default 50, max 200)
- `offset` (int, default 0)

Returns runs where `status IN ('succeeded', 'failed', 'running')` AND `tool_name IS NOT NULL`, ordered by `started_at` DESC. Excludes `queued` and `cancelled`.

`total` is the full filtered count (for pagination), computed as a separate `SELECT COUNT(*)` query with the same filters before applying `limit`/`offset`.

Add to `main.py`: `app.include_router(activity.router, prefix="/activity", tags=["activity"])`

Response schema:

```python
class ActivityEntryRead(BaseModel):
    id: str
    tool_name: str             # non-null (filtered at query level)
    trigger_type: str          # "chat" | "agent_loop"
    status: str                # "succeeded" | "failed" | "running"
    summary: str | None
    input: dict
    output: str | None         # json.dumps(raw_output)[:2000] — API owns truncation
    error: str | None
    started_at: datetime
    finished_at: datetime | None

class ActivityResponse(BaseModel):
    entries: list[ActivityEntryRead]
    total: int
```

`output` is serialized to a JSON string and truncated to 2000 chars server-side before returning. The frontend displays it as a pre-formatted string. If `len(json.dumps(raw_output)) > 2000`, append `" ... [truncated]"` to the truncated string. The frontend shows a "Show full" disclosure only when the response string ends with `" ... [truncated]"`.

---

### 5. Frontend — Activity Tab (`components/Activity/`)

Replaces the Board tab in `AppShell.tsx`.

**Tab label:** "Activity" (was "Board")

**`ActivityFeed` component:**

```
┌──────────────────────────────────────────────────────┐
│  Activity                              [↺ Refresh]   │
├──────────────────────────────────────────────────────┤
│  ● ha.light.turn_on  [chat]  succeeded  2 min ago    │
│    Turned on light.office → succeeded                │
│    ▶ Details                                         │
├──────────────────────────────────────────────────────┤
│  ● http.request  [agent_loop]  running  just now     │
│    http.request → running                            │
├──────────────────────────────────────────────────────┤
│  ● devops.summarize_ci_failure  [agent_loop]  failed │
│    devops.summarize_ci_failure → failed  8 min ago   │
│    ▶ Details                                         │
├──────────────────────────────────────────────────────┤
│                   [Load more]                        │
└──────────────────────────────────────────────────────┘
```

**Expanded "Details" panel** (collapsed by default):

```
Input:  { "entity_id": "light.office" }
Output: { "status": "ok", "entity_id": "light.office" }
Error:  —
```

Output truncated at 2000 chars. "Show full" disclosure if truncated.

**Component local state:**

```typescript
const [entries, setEntries] = useState<ActivityEntry[]>([])
const [offset, setOffset] = useState(0)
const [total, setTotal] = useState(0)
const [loading, setLoading] = useState(false)

// On mount and refresh: reset offset=0, replace entries
// On "Load more": offset += 50, append to entries
// "Load more" button hidden when entries.length >= total
```

**State:** fetched on mount and on manual refresh. No polling — static history view.

**Status indicator:** colored dot (green=succeeded, red=failed, yellow=running).

**Running entries:** show spinner instead of dot, no finished_at.

---

### 6. Frontend — Board Tab Removal

- `AppShell.tsx`: rename "Board" tab to "Activity", render `<ActivityFeed />` instead of `<Board />`
- `uiStore.ts`: change `activeTab` type from `"chat" | "board"` to `"chat" | "activity"`, update default
- `Board` component and related files remain in the codebase but are no longer rendered (full removal is a separate cleanup task)

---

## Data Flow Summary

```
User types: "turn on the office lights"
    │
    ▼
POST /conversations/{id}/messages
    │
    ├─ Phase 1: Classification LLM call
    │     → {"intent": "action", "tool_name": "ha.light.turn_on",
    │         "tool_input": {"entity_id": "light.office"}, "confidence": 0.92}
    │
    ├─ SSE emit: [Running ha.light.turn_on...]
    │
    ├─ Execute tool synchronously
    │     POST to HA API → {"status": "ok"}
    │     Write Run(trigger_type="chat", summary="ha.light.turn_on → succeeded")
    │
    ├─ Phase 2: Response LLM call
    │     System context: "You ran ha.light.turn_on. Result: {status: ok}."
    │     → streams: "Done! I've turned on the office lights."
    │
    └─ SSE emit: {"complete": true}

GET /activity → shows new Run entry at top of feed
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Classification JSON parse fails | Silent fallback to conversation |
| Classification confidence < 0.7 | Silent fallback to conversation |
| Tool name not found in registry | Silent fallback to conversation; **no Run record created** |
| Tool execution fails | Run marked failed; `tool_context` set to error string; LLM response says "I tried X but failed: {error}" |
| Activity API unavailable | Frontend shows error state with retry button |

---

## Testing

### Backend

- Unit tests for `_classify_intent()` — mock LLM, test action vs conversation vs low-confidence paths
- Unit tests for `handle_http_request()` — mock httpx, test GET/POST, truncation, timeout
- Unit tests for `handle_ha_light_turn_off()` — mock httpx, test success and 4xx error
- Integration test: POST message with mocked classifier returning action → tool runs → Run record created with `trigger_type="chat"`
- Integration test: GET `/activity` → returns runs in correct order, correct fields

### Frontend

- `ActivityFeed` renders entries correctly (tool name, badge, status dot, summary)
- Expand/collapse details works
- "Load more" appends next page
- Refresh button re-fetches
- Running entry shows spinner
- `AppShell`: "Activity" tab renders `ActivityFeed`, not `Board`

---

## Out of Scope

- Recurring goals / scheduling (Spec 2)
- Real-time activity updates (websocket/SSE on Activity tab)
- Full Board component removal (cleanup task)
- Additional tools beyond `ha.light.turn_off` and `http.request`
- Tool approval flows from chat
