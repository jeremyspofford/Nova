# Nova-lite End-to-End Wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get nova-lite's agent loop working end-to-end: POST an event → LLM triages it → LLM plans → tool executes → task moves to Done on the board.

**Architecture:** Three targeted fixes unblock the full loop. The API's `POST /llm/route` and `POST /tools/{name}/invoke` are already implemented. Nova-lite's triage/planner/executor/summarizer are already implemented. The blockers are: (1) Ollama is unreachable from Docker containers due to OLLAMA_BASE_URL being `localhost` instead of `host.docker.internal`, (2) LLMs often wrap JSON responses in markdown code fences which silently breaks the JSON parsers in triage and planner, (3) a test file references the wrong task status ("inbox" instead of "pending").

**Tech Stack:** FastAPI, Python 3.12, httpx, openai SDK (for Ollama-compatible calls), pytest, Docker Compose

**Existing code to understand before starting:**
- `services/api/app/llm_client.py` — routes to Ollama via OpenAI-compatible API; reads `endpoint_ref` from seeded `LLMProviderProfile`
- `services/api/app/tools/seed.py` — `seed_llm_providers()` upserts the Ollama provider using `settings.ollama_base_url + "/v1"` as `endpoint_ref`
- `services/nova-lite/app/logic/triage.py` — calls `client.llm_route()`, parses JSON with `json.loads(response)`
- `services/nova-lite/app/logic/planner.py` — same pattern
- `services/nova-lite/tests/conftest.py` — `fake_client` fixture used across all nova-lite tests
- `infra/.env` — OLLAMA_BASE_URL and OLLAMA_MODEL are set here; loaded by docker compose

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `infra/.env` | Modify | Change OLLAMA_BASE_URL to host.docker.internal |
| `docs/llm-setup.md` | Modify | Document Docker vs WSL2 URL distinction |
| `services/nova-lite/app/logic/utils.py` | Create | Shared `_extract_json()` helper |
| `services/nova-lite/app/logic/triage.py` | Modify | Import and use `_extract_json()` |
| `services/nova-lite/app/logic/planner.py` | Modify | Import and use `_extract_json()` |
| `services/nova-lite/tests/test_triage.py` | Modify | Add tests for markdown-wrapped JSON parsing |
| `services/nova-lite/tests/test_planner.py` | Modify | Add tests for markdown-wrapped JSON parsing |
| `services/nova-lite/tests/test_main.py` | Modify | Fix task fixtures using `status="inbox"` → `status="pending"` |
| `services/nova-lite/tests/conftest.py` | Modify | Fix `FakeClient.post_task` default `status="inbox"` → `status="pending"` |

---

## Task 1: Fix Ollama URL for Docker containers

Docker containers cannot use `localhost` to reach the Windows host — `localhost` inside a container refers to the container itself. The API container needs `host.docker.internal:11434`.

**Files:**
- Modify: `infra/.env`
- Modify: `docs/llm-setup.md`

- [ ] **Step 1: Update `.env`**

Change:
```bash
OLLAMA_BASE_URL=http://localhost:11434
```
To:
```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

- [ ] **Step 2: Rebuild and restart the API**

```bash
cd infra && docker compose up --build api
```

Wait for the API to start (watch for "Application startup complete").

- [ ] **Step 3: Smoke test POST /llm/route**

```bash
curl -s -X POST http://localhost:8000/llm/route \
  -H "Content-Type: application/json" \
  -d '{"purpose": "test", "privacy_preference": "local_preferred", "input": {"messages": [{"role": "user", "content": "Say hello in one word."}]}}' | python3 -m json.tool
```

Expected: JSON response with an `output` field containing a word. If you get `503`, Ollama isn't reachable — re-check the Windows Firewall inbound rule for port 11434 (TCP, all profiles).

- [ ] **Step 4: Update LLM setup docs**

In `docs/llm-setup.md`, add a note to the Windows + WSL2 section after the `.env` config block:

```markdown
> **Note:** When running services via Docker Compose, containers cannot reach
> `localhost` on the host. Use `http://host.docker.internal:11434` in `infra/.env`.
> For WSL2 commands run directly (e.g., `ollama pull`), `localhost` works with
> mirrored networking enabled.
```

- [ ] **Step 5: Commit**

```bash
git add infra/.env docs/llm-setup.md
git commit -m "fix: use host.docker.internal for Ollama URL in Docker containers"
```

---

## Task 2: Robust JSON parsing for LLM responses

LLMs — especially smaller models like Gemma — sometimes wrap JSON in markdown code fences even when instructed not to. The current parsers call `json.loads(response)` directly. When this fails in triage, nova-lite silently falls back to using the raw event subject as the task title. When it fails in planner, nova-lite silently returns an empty plan and marks the task done immediately. These are silent failures — no errors in logs, just degraded behavior.

Create a shared `_extract_json()` helper in `app/logic/utils.py` and import it into both triage and planner.

**Files:**
- Create: `services/nova-lite/app/logic/utils.py`
- Modify: `services/nova-lite/app/logic/triage.py`
- Modify: `services/nova-lite/app/logic/planner.py`
- Modify: `services/nova-lite/tests/test_triage.py`
- Modify: `services/nova-lite/tests/test_planner.py`

- [ ] **Step 1: Write failing tests for triage**

Add to `services/nova-lite/tests/test_triage.py`:

```python
from app.logic.triage import _parse_triage_response

def test_parse_triage_response_handles_markdown_wrapped_json():
    """LLMs sometimes wrap JSON in code fences — parser must strip them."""
    raw = '```json\n{"title": "Test task", "priority": "normal", "risk_class": "low", "labels": []}\n```'
    result = _parse_triage_response(raw)
    assert result is not None
    assert result["title"] == "Test task"

def test_parse_triage_response_handles_bare_code_fence():
    """Code fence without language tag."""
    raw = '```\n{"title": "Test task", "priority": "low", "risk_class": "low", "labels": []}\n```'
    result = _parse_triage_response(raw)
    assert result is not None
    assert result["title"] == "Test task"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd services/nova-lite && python3 -m pytest tests/test_triage.py::test_parse_triage_response_handles_markdown_wrapped_json tests/test_triage.py::test_parse_triage_response_handles_bare_code_fence -v
```

Expected: FAIL — `_parse_triage_response` does not strip code fences.

- [ ] **Step 3: Create `app/logic/utils.py`**

```python
import re


def _extract_json(text: str) -> str:
    """Strip markdown code fences if present, return raw JSON string."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    return text.strip()
```

- [ ] **Step 4: Fix triage.py**

Add the import at module level (alongside existing `import json` / `import logging`):

```python
from app.logic.utils import _extract_json
```

Update `_parse_triage_response` to use it:

```python
def _parse_triage_response(response: str) -> dict | None:
    """Parse LLM JSON response. Returns None if response is not valid JSON with a title."""
    try:
        data = json.loads(_extract_json(response))
        if "title" not in data or not data["title"]:
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None
```

- [ ] **Step 5: Run triage tests**

```bash
python3 -m pytest tests/test_triage.py -v
```

Expected: all pass.

- [ ] **Step 6: Write failing tests for planner**

Add to `services/nova-lite/tests/test_planner.py`:

```python
from app.logic.planner import _parse_plan_response

def test_parse_plan_response_handles_markdown_wrapped_json():
    """Planner must handle LLM responses wrapped in code fences."""
    raw = '```json\n{"actions": [{"tool_name": "debug.echo", "input": {}, "reason": "test"}], "reasoning": "ok"}\n```'
    plan = _parse_plan_response(raw)
    assert len(plan.actions) == 1
    assert plan.actions[0].tool_name == "debug.echo"

def test_parse_plan_response_handles_bare_code_fence():
    raw = '```\n{"actions": [], "reasoning": "nothing to do"}\n```'
    plan = _parse_plan_response(raw)
    assert plan.actions == []
    assert plan.reasoning == "nothing to do"
```

- [ ] **Step 7: Run to verify they fail**

```bash
python3 -m pytest tests/test_planner.py::test_parse_plan_response_handles_markdown_wrapped_json tests/test_planner.py::test_parse_plan_response_handles_bare_code_fence -v
```

Expected: FAIL.

- [ ] **Step 8: Fix planner.py**

Add the import at module level:

```python
from app.logic.utils import _extract_json
```

Update `_parse_plan_response` to use it:

```python
def _parse_plan_response(response: str) -> Plan:
    try:
        data = json.loads(_extract_json(response))
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
```

- [ ] **Step 9: Run full nova-lite test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add services/nova-lite/app/logic/utils.py \
        services/nova-lite/app/logic/triage.py \
        services/nova-lite/app/logic/planner.py \
        services/nova-lite/tests/test_triage.py \
        services/nova-lite/tests/test_planner.py
git commit -m "fix: strip markdown code fences from LLM JSON responses in triage and planner"
```

---

## Task 3: Fix stale status references in nova-lite tests

`services/nova-lite/tests/test_main.py` has task fixtures using `"status": "inbox"`. `inbox` is a board column ID, not a task status. The correct status for unprocessed tasks is `"pending"`. These tests still pass because `process_task()` doesn't inspect `status`, but it's misleading and should be corrected.

**Files:**
- Modify: `services/nova-lite/tests/test_main.py`
- Modify: `services/nova-lite/tests/conftest.py`

- [ ] **Step 1: Fix task fixtures in `test_main.py`**

In `test_main.py`, replace every occurrence of `"status": "inbox"` with `"status": "pending"`. There are 6 task fixtures to update (task-1 through task-6).

- [ ] **Step 2: Fix `FakeClient.post_task` in `conftest.py`**

`FakeClient.post_task()` sets `"status": "inbox"` as the default status when creating a task. Find the line that reads:

```python
task = {"id": task_id, "status": "inbox", **payload}
```

Change it to:

```python
task = {"id": task_id, "status": "pending", **payload}
```

This matters because `run_loop` fetches tasks with `status="pending"` — tasks created through `FakeClient.post_task` in any future integration-style tests would otherwise never be found.

- [ ] **Step 3: Run tests**

```bash
cd services/nova-lite && python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/nova-lite/tests/test_main.py \
        services/nova-lite/tests/conftest.py
git commit -m "fix(nova-lite): correct task status in test fixtures and FakeClient from inbox to pending"
```

---

## Task 4: End-to-end smoke test

Verify the full loop works: POST event → nova-lite triages into task → planner plans → executor runs debug.echo → task marked done → board shows it in Done column.

This is a manual verification step, not an automated test. Both docker compose services and nova-lite must be running.

**Prerequisites:** Tasks 1–3 complete. API rebuilt with new OLLAMA_BASE_URL. Nova-lite rebuilt.

- [ ] **Step 1: Rebuild and restart nova-lite**

```bash
cd infra && docker compose up --build api nova-lite
```

- [ ] **Step 2: Verify LLM route works**

```bash
curl -s -X POST http://localhost:8000/llm/route \
  -H "Content-Type: application/json" \
  -d '{"purpose": "test", "privacy_preference": "local_preferred", "input": {"messages": [{"role": "user", "content": "Reply with the single word: hello"}]}}' \
  | python3 -m json.tool
```

Expected: `output` field contains something with "hello". If 503, stop here and fix Ollama connectivity first.

- [ ] **Step 3: POST a test event**

```bash
curl -s -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "type": "test.manual",
    "source": "human",
    "subject": "Test the debug echo tool",
    "payload": {"note": "This is a smoke test event"},
    "priority": "normal",
    "risk_class": "low"
  }' | python3 -m json.tool
```

Expected: response with an `id` and `timestamp`.

- [ ] **Step 4: Watch nova-lite logs**

```bash
docker compose logs nova-lite -f
```

The loop runs in two separate ticks (15 seconds apart):

**Tick 1** — triage:
- `GET /events` returns the new event
- `POST /tasks` creates a task from the event

**Tick 2** — execution (15 seconds later):
- `GET /tasks?status=pending` returns the new task
- `PATCH /tasks/{id}` → running
- `POST /tools/debug.echo/invoke` (if planner chose it)
- `PATCH /tasks/{id}` → done or failed

- [ ] **Step 5: Verify on the board**

Open `http://localhost:5173`. The task should appear in the Done (or Failed) column within one poll interval (5 seconds).

If the task lands in Failed, check nova-lite logs for the error. Common issues:
- LLM returned invalid JSON (Task 2 should prevent this)
- Planner chose `ha.light.turn_on` which will fail without HA — this is fine, task goes to Failed as expected

- [ ] **Step 6: Commit any fixes found during smoke test**

If any issues are found and fixed during the smoke test, commit them:

```bash
git add <changed files>
git commit -m "fix: <description of smoke test fix>"
```
