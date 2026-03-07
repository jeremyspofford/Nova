# Session-End Conversation Summarization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically summarize chat sessions and store them as semantic memories so future conversations can recall what was discussed.

**Architecture:** Two triggers (explicit "New Chat" click + background inactivity sweep) call a shared `summarize_session()` function in the orchestrator. It calls the LLM gateway for a summary, then stores it as a semantic memory via the memory service's `/api/v1/memories/facts` endpoint.

**Tech Stack:** Python/FastAPI (orchestrator), TypeScript/React (dashboard), httpx, asyncio background tasks.

---

### Task 1: Add config setting

**Files:**
- Modify: `orchestrator/app/config.py:44-66`

**Step 1: Add the setting**

Add two new settings to the `Settings` class in `orchestrator/app/config.py`, after the `session_timeout_buffer_seconds` line (line 59):

```python
    # Session summarization
    session_summary_timeout_seconds: int = 7200  # 2h idle before auto-summarize
    session_summary_model: str = "claude-haiku-4-5-20251001"
```

**Step 2: Verify**

Run: `cd /home/jeremy/workspace/nova && python -c "from orchestrator.app.config import settings; print(settings.session_summary_timeout_seconds, settings.session_summary_model)"`

Expected: `7200 claude-haiku-4-5-20251001`

**Step 3: Commit**

```bash
git add orchestrator/app/config.py
git commit -m "feat: add session summarization config settings"
```

---

### Task 2: Create session_summary.py — core summarization function

**Files:**
- Create: `orchestrator/app/session_summary.py`

**Step 1: Create the module**

Create `orchestrator/app/session_summary.py` with the shared summarization function:

```python
"""
Session conversation summarization.

Generates concise summaries of completed chat sessions and stores them
as semantic memories for future retrieval.
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.clients import get_llm_client, get_memory_client
from app.config import settings

log = logging.getLogger(__name__)

SUMMARY_PROMPT = (
    "Summarize this conversation in 2-4 sentences. Capture:\n"
    "- What the user wanted to accomplish\n"
    "- Key decisions made or information exchanged\n"
    "- Any unresolved questions or next steps\n\n"
    "Be factual and specific. Use names, technical terms, and details "
    "from the conversation. Return only the summary text, nothing else."
)


async def summarize_session(
    session_id: str,
    messages: list[dict],
    agent_id: str = "nova",
) -> str | None:
    """
    Summarize a conversation and store it as a semantic memory.

    Returns the summary text on success, None on failure.
    Skips sessions with fewer than 2 messages (nothing meaningful to summarize).
    """
    if len(messages) < 2:
        log.debug("Skipping summary for session %s: too few messages (%d)", session_id, len(messages))
        return None

    # Format conversation for the LLM
    conversation = "\n".join(
        f"{m.get('role', 'user').title()}: {m.get('content', '')}"
        for m in messages
        if m.get("content")
    )

    try:
        # Call LLM gateway for summary
        llm_client = get_llm_client()
        resp = await llm_client.post(
            "/complete",
            json={
                "model": settings.session_summary_model,
                "messages": [
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": conversation},
                ],
                "temperature": 0.2,
                "max_tokens": 300,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract text from response
        content = data.get("content", "")
        if isinstance(content, list):
            content = content[0].get("text", "") if content else ""
        summary = content.strip()

        if not summary:
            log.warning("Empty summary returned for session %s", session_id)
            return None

        # Store as semantic memory via facts endpoint (upserts by session_id key)
        memory_client = get_memory_client()
        await memory_client.post(
            "/api/v1/memories/facts",
            json={
                "agent_id": agent_id,
                "project_id": agent_id,
                "category": "conversation_summary",
                "key": session_id,
                "content": summary,
                "base_confidence": 0.9,
                "metadata": {
                    "source": "session_summary",
                    "message_count": len(messages),
                    "session_id": session_id,
                },
            },
        )

        log.info(
            "Stored session summary for %s (%d messages): %s",
            session_id, len(messages), summary[:80],
        )
        return summary

    except Exception:
        log.exception("Failed to summarize session %s", session_id)
        return None
```

**Step 2: Verify import**

Run: `cd /home/jeremy/workspace/nova && python -c "from orchestrator.app.session_summary import summarize_session; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add orchestrator/app/session_summary.py
git commit -m "feat: add session summarization core function"
```

---

### Task 3: Add the background sweep loop

**Files:**
- Modify: `orchestrator/app/session_summary.py` (append to file)

**Step 1: Add the sweep loop**

Append the background sweep function to `orchestrator/app/session_summary.py`:

```python
async def session_summary_sweep() -> None:
    """Background loop: summarize sessions that have gone idle."""
    log.info(
        "Session summary sweep started (timeout=%ds)",
        settings.session_summary_timeout_seconds,
    )

    while True:
        try:
            await asyncio.sleep(600)  # Check every 10 minutes
            await _run_sweep_cycle()
        except asyncio.CancelledError:
            log.info("Session summary sweep shutting down")
            break
        except Exception:
            log.exception("Session summary sweep error — will retry next interval")


async def _run_sweep_cycle() -> None:
    """Single sweep: find idle sessions without summaries, summarize them."""
    memory_client = get_memory_client()

    try:
        # Get recent episodic memories with session_ids
        resp = await memory_client.get(
            "/api/v1/memories/browse",
            params={"tier": "episodic", "limit": 200},
        )
        resp.raise_for_status()
        data = resp.json()

        # Group by session_id, track latest timestamp per session
        from datetime import datetime, timezone
        sessions: dict[str, dict] = {}  # session_id -> {messages, latest, agent_id}
        for item in data.get("items", []):
            sid = (item.get("metadata") or {}).get("session_id")
            if not sid:
                continue

            created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
            if sid not in sessions:
                sessions[sid] = {"messages": [], "latest": created, "agent_id": item.get("agent_id", "nova")}
            else:
                if created > sessions[sid]["latest"]:
                    sessions[sid]["latest"] = created

            # Reconstruct message from episodic content
            content = item.get("content", "")
            role = (item.get("metadata") or {}).get("role", "user")
            # Strip "User: " / "Assistant: " prefix if present
            for prefix in ("User: ", "Assistant: "):
                if content.startswith(prefix):
                    content = content[len(prefix):]
                    break
            sessions[sid]["messages"].append({
                "role": role,
                "content": content,
                "created_at": created,
            })

        if not sessions:
            return

        now = datetime.now(timezone.utc)
        timeout = settings.session_summary_timeout_seconds
        summarized = 0

        for sid, info in sessions.items():
            # Skip sessions that are still active
            age = (now - info["latest"]).total_seconds()
            if age < timeout:
                continue

            # Check if already summarized by searching for existing summary
            check_resp = await memory_client.post(
                "/api/v1/memories/search",
                json={
                    "agent_id": info["agent_id"],
                    "query": f"conversation_summary {sid}",
                    "tiers": ["semantic"],
                    "limit": 1,
                    "metadata_filter": {"category": "conversation_summary", "session_id": sid},
                },
            )
            if check_resp.status_code == 200:
                results = check_resp.json().get("results", [])
                if results:
                    continue  # Already summarized

            # Sort messages by timestamp and summarize
            info["messages"].sort(key=lambda m: m["created_at"])
            msgs = [{"role": m["role"], "content": m["content"]} for m in info["messages"]]
            result = await summarize_session(sid, msgs, agent_id=info["agent_id"])
            if result:
                summarized += 1

        if summarized:
            log.info("Session summary sweep: summarized %d idle session(s)", summarized)

    except Exception:
        log.exception("Session summary sweep cycle failed")
```

**Step 2: Verify import**

Run: `cd /home/jeremy/workspace/nova && python -c "from orchestrator.app.session_summary import session_summary_sweep; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add orchestrator/app/session_summary.py
git commit -m "feat: add background session summary sweep loop"
```

---

### Task 4: Start the background sweep in orchestrator lifespan

**Files:**
- Modify: `orchestrator/app/main.py:51-62`

**Step 1: Import and start the task**

In `orchestrator/app/main.py`, add the import at the top with the other imports (after line 20):

```python
from app.session_summary import session_summary_sweep
```

Then in the lifespan function, after the queue worker and reaper are started (after line 53), add:

```python
    _summary_task = asyncio.create_task(session_summary_sweep(), name="session-summary")
```

Update the log line on line 54 to:

```python
    log.info("Queue worker, reaper, and session summary sweep started")
```

In the shutdown section, add cancellation (after line 60):

```python
    _summary_task.cancel()
```

Update the gather call (line 62) to include the new task:

```python
    await asyncio.gather(_queue_task, _reaper_task, _summary_task, return_exceptions=True)
```

**Step 2: Verify syntax**

Run: `cd /home/jeremy/workspace/nova && python -c "import orchestrator.app.main; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add orchestrator/app/main.py
git commit -m "feat: start session summary sweep in orchestrator lifespan"
```

---

### Task 5: Add the summarize endpoint to the router

**Files:**
- Modify: `orchestrator/app/router.py:313-316`

**Step 1: Add the endpoint**

Insert after line 313 (after the `chat_stream` endpoint's closing return statement) and before the key management section comment:

```python


class SummarizeRequest(BaseModel):
    messages: list[dict]


@router.post("/api/v1/chat/sessions/{session_id}/summarize")
async def summarize_chat_session(session_id: str, req: SummarizeRequest, _admin: AdminDep):
    """Summarize a completed chat session and store as semantic memory."""
    from app.session_summary import summarize_session

    summary = await summarize_session(session_id, req.messages)
    if summary is None:
        return {"status": "skipped", "reason": "too few messages or summarization failed"}
    return {"status": "ok", "summary": summary}
```

**Step 2: Verify syntax**

Run: `cd /home/jeremy/workspace/nova && python -c "from orchestrator.app.router import router; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add orchestrator/app/router.py
git commit -m "feat: add POST /api/v1/chat/sessions/{session_id}/summarize endpoint"
```

---

### Task 6: Add dashboard API helper

**Files:**
- Modify: `dashboard/src/api.ts:276-278`

**Step 1: Add the helper function**

Insert after the `uploadFile` function (after line 276) and before the MCP Servers section comment:

```typescript

/** Fire-and-forget: summarize a completed chat session for memory. */
export function summarizeSession(sessionId: string, messages: ChatMessage[]): void {
  // Non-blocking — we don't await this; it's a best-effort background operation
  fetch('/api/v1/chat/sessions/' + encodeURIComponent(sessionId) + '/summarize', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Secret': getAdminSecret(),
    },
    body: JSON.stringify({
      messages: messages.map(m => ({
        role: typeof m.content === 'string' ? m.role : m.role,
        content: typeof m.content === 'string' ? m.content : m.content.map(b => b.text ?? '').join(''),
      })),
    }),
  }).catch(() => {
    // Silently ignore — summarization is best-effort
  })
}
```

**Step 2: Verify types**

Run: `cd /home/jeremy/workspace/nova/dashboard && npx tsc --noEmit`

Expected: No errors

**Step 3: Commit**

```bash
git add dashboard/src/api.ts
git commit -m "feat: add summarizeSession API helper (fire-and-forget)"
```

---

### Task 7: Wire up resetConversation to call summarize

**Files:**
- Modify: `dashboard/src/stores/chat-store.tsx:156-162`

**Step 1: Call summarize before clearing**

Replace the `resetConversation` callback (lines 156-162) with:

```typescript
  const resetConversation = useCallback(() => {
    // Summarize the conversation before clearing (fire-and-forget)
    if (sessionId && messages.length >= 2) {
      const { summarizeSession } = await_import_not_needed
      // We need to import at the top of the file instead
    }
    setMessages([])
    setSessionId(undefined)
    setError(null)
    setPendingFiles([])
    localStorage.removeItem(STORAGE_KEY)
  }, [])
```

Actually — since `resetConversation` uses `useCallback` with `[]` deps, it won't have access to current `sessionId` and `messages` via closure. We need to use refs or restructure slightly.

Better approach: use refs that always point to current values.

Add refs after the state declarations (after line 128):

```typescript
  const messagesRef = useRef(messages)
  const sessionIdRef = useRef(sessionId)
  useEffect(() => { messagesRef.current = messages }, [messages])
  useEffect(() => { sessionIdRef.current = sessionId }, [sessionId])
```

Then update `resetConversation`:

```typescript
  const resetConversation = useCallback(() => {
    // Summarize the completed conversation before clearing (fire-and-forget)
    if (sessionIdRef.current && messagesRef.current.length >= 2) {
      summarizeSession(sessionIdRef.current, messagesRef.current.map(m => ({
        role: m.role,
        content: m.content,
      })))
    }
    setMessages([])
    setSessionId(undefined)
    setError(null)
    setPendingFiles([])
    localStorage.removeItem(STORAGE_KEY)
  }, [])
```

Add the import at the top of the file (after line 7):

```typescript
import { summarizeSession } from '../api'
```

Note: `summarizeSession` expects `ChatMessage[]` but we're passing `{role, content}[]` — the types align since content is a string here.

**Step 2: Verify types and build**

Run: `cd /home/jeremy/workspace/nova/dashboard && npx tsc --noEmit && npm run build`

Expected: No type errors, build succeeds

**Step 3: Commit**

```bash
git add dashboard/src/stores/chat-store.tsx
git commit -m "feat: summarize conversation on New Chat click (fire-and-forget)"
```

---

### Task 8: Integration test

**Files:**
- Modify: `tests/test_orchestrator.py` (append new test)

**Step 1: Write the test**

Add a new test to `tests/test_orchestrator.py`:

```python
    @pytest.mark.asyncio
    async def test_session_summarize(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """POST /api/v1/chat/sessions/{id}/summarize stores a session summary."""
        session_id = f"nova-test-summary-{uuid4().hex[:8]}"
        messages = [
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "The capital of France is Paris."},
            {"role": "user", "content": "What about Germany?"},
            {"role": "assistant", "content": "The capital of Germany is Berlin."},
        ]
        resp = await orchestrator.post(
            f"/api/v1/chat/sessions/{session_id}/summarize",
            json={"messages": messages},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["summary"]) > 10  # Non-trivial summary
```

Note: This test requires an LLM provider to be available. Check if the test file uses `@pytest.mark.requires_llm` and follow the same pattern. If the test file doesn't exist yet or doesn't have a suitable class, create the test in a new class.

**Step 2: Run the test**

Run: `cd /home/jeremy/workspace/nova && python -m pytest tests/test_orchestrator.py::TestOrchestrator::test_session_summarize -v`

Expected: PASS (requires services running + LLM provider configured)

**Step 3: Commit**

```bash
git add tests/test_orchestrator.py
git commit -m "test: add integration test for session summarization endpoint"
```

---

### Task 9: Final verification

**Step 1: TypeScript check**

Run: `cd /home/jeremy/workspace/nova/dashboard && npx tsc --noEmit`

Expected: No errors

**Step 2: Full dashboard build**

Run: `cd /home/jeremy/workspace/nova/dashboard && npm run build`

Expected: Build succeeds

**Step 3: Full test suite (if services running)**

Run: `cd /home/jeremy/workspace/nova && make test`

Expected: All tests pass

**Step 4: Final commit (if any remaining changes)**

```bash
git add -A
git commit -m "feat: session-end conversation summarization

Automatically summarizes chat sessions and stores them as semantic memories.
Two triggers: explicit (New Chat click) and background (2h idle timeout).
Summaries improve future memory retrieval for cross-session context."
```
