# Session-End Conversation Summarization — Design

**Date:** 2026-03-07
**Status:** Approved

## Problem

Chat sessions are ephemeral. Within a session, the LLM has full message history. But once a session ends (user clicks "New Chat", closes the tab, or just walks away), there's no consolidated record of what was discussed. Individual episodic memories exist but are raw exchanges — not searchable summaries. If the user asks about a prior conversation later, memory retrieval has to pattern-match against fragmented `User: ...` / `Assistant: ...` pairs.

## Solution

Generate a 2-4 sentence summary of each completed conversation and store it as a semantic memory. Two triggers ensure coverage:

1. **Explicit** — Dashboard calls a summarize endpoint when user clicks "New Chat"
2. **Background sweep** — Periodic job catches sessions that went idle without explicit closure

Both call the same shared summarization function.

## Architecture

```
Dashboard "New Chat" click
    → POST /api/v1/chat/sessions/{session_id}/summarize (messages in body)
    → _summarize_session(session_id, messages)
    → Store as semantic memory via /api/v1/memories/facts

Background inactivity sweep (configurable, default every 10 min)
    → Find sessions with episodic memories but no summary
    → Filter to sessions idle > SESSION_SUMMARY_TIMEOUT_SECONDS (default 7200)
    → Reconstruct conversation from episodic memories
    → _summarize_session(session_id, reconstructed_messages)
    → Store as semantic memory
```

## Files to Modify

| File | Change |
|---|---|
| `orchestrator/app/session_summary.py` | **New** — `summarize_session()`, background sweep loop, LLM prompt |
| `orchestrator/app/router.py` | New endpoint `POST /api/v1/chat/sessions/{session_id}/summarize` |
| `orchestrator/app/config.py` | Add `SESSION_SUMMARY_TIMEOUT_SECONDS` (default 7200) |
| `orchestrator/app/main.py` | Start background sweep task in lifespan |
| `dashboard/src/stores/chat-store.tsx` | Call summarize endpoint in `resetConversation()` |
| `dashboard/src/api.ts` | Add `summarizeSession()` API helper |

## Semantic Memory Schema

```python
{
    "agent_id": agent_id,
    "project_id": agent_id,
    "category": "conversation_summary",
    "key": session_id,
    "content": "<LLM-generated summary>",
    "confidence": 0.9,
    "metadata": {
        "source": "session_summary",
        "message_count": len(messages),
        "session_id": session_id,
    }
}
```

Using `key: session_id` ensures one summary per session (upsert on re-run).

## LLM Prompt

```
Summarize this conversation in 2-4 sentences. Capture:
- What the user wanted to accomplish
- Key decisions made or information exchanged
- Any unresolved questions or next steps

Be factual and specific. Use names, technical terms, and details from the conversation.
```

Model: reuses `COMPACTION_MODEL` setting (default `claude-haiku-4-5-20251001`).

## Background Sweep Details

- Runs every 10 minutes in the orchestrator lifespan
- Queries episodic memories grouped by session_id
- Skips sessions that already have a `conversation_summary` semantic memory
- Skips sessions with activity in the last `SESSION_SUMMARY_TIMEOUT_SECONDS`
- Reconstructs messages from episodic `User: ...` / `Assistant: ...` content
- Fault-tolerant: errors logged, loop continues

## Dashboard Integration

- `resetConversation()` fires a non-blocking fetch to the summarize endpoint before clearing state
- Sends the current messages array directly (no need to reconstruct from episodic)
- Does not block the UI — fire-and-forget

## Scope Boundaries (YAGNI)

- No summarization of ongoing sessions
- No user-facing session history UI
- No sliding-window compression for long conversations (separate feature)
- No special handling for very short sessions (1-2 messages) — the LLM can handle trivial summaries cheaply

## Design Decisions

- **Summarization lives in orchestrator, not memory service** — keeps memory service as a clean storage/retrieval layer, making it swappable
- **Reuses compaction model config** — same class of task, one knob to tune
- **Inactivity timeout configurable via env var** — tune without code changes
