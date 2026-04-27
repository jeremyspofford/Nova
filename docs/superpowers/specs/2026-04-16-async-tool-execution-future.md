> **Origin:** Imported 2026-04-27 from the retired `jeremyspofford/Nova` experiment (`nova-suite`). Authored 2026-04-16. Reference only — future-trigger note, not yet validated against current Nova architecture.

# Async Tool Execution (Option B) — Future Spec

**Date:** 2026-04-16
**Status:** Future work — triggered when chat UX demands instant feel for tool-using messages

---

## Goal

Make chat feel instant even when the user's message triggers tool calls. Today, tool-using chat waits for the full tool-calling loop + synthesis (typical 5-15s); after this change, chat replies within ~1s with "working on that" and the tool result lands asynchronously in the activity feed.

## Trigger for doing this work

- User complains that tool-using chat feels slow even after purpose-routing (Option A) is shipped
- OR Layer D (multi-step orchestration) starts landing, and async execution infrastructure becomes worth building for both
- OR the async UX is needed for multi-tool workflows that would otherwise serialize 5+ tool calls

Don't build this until one of those triggers fires. Purpose-routing may be enough.

---

## Architecture Sketch

### Request flow (after)

```
User message → Nova
  ↓
Phase 1 (fast model): does this need tools?
  ↓
  ├─ No tools needed → stream reply now (current behavior)
  │
  └─ Tools needed →
       ├─ Persist pending_tool_call rows (one per intended call)
       ├─ Stream: "Working on that — I'll post the result to activity when done."
       └─ Return SSE response (chat is unblocked)
  ↓
Background worker (new service or in-process task):
  ↓
  ├─ Poll pending_tool_call rows (maybe every 5s)
  ├─ For each pending call:
  │    ├─ Dispatch tool → Run record populated
  │    ├─ Use Phase 2 model to synthesize user-readable result text
  │    └─ Create activity entry of type "async_tool_result" linked to the Conversation
  └─ Push SSE update to any open chat (or the Conversation WebSocket, see below)
```

### New concepts

- **`pending_tool_calls` table** — tool intents awaiting async execution. Different from the existing `pending_tool_call` confirmation state (that's pre-dispatch). Columns: `id`, `conversation_id`, `tool_name`, `tool_input`, `status (pending|running|done|failed)`, `scheduled_at`, `started_at`, `finished_at`, `result_summary`.
- **Background worker** — either a new service (`async-executor`), a scheduled trigger (`*/5 * * * * *` — every 5s via the new scheduler), or a threadpool inside the API process. Pick based on deployment preference.
- **Activity entries of type `async_tool_result`** — render as cards in the chat log showing tool name, summary, optional expand-to-see-full-output. Link to Run record for full detail.

### Chat UI changes

- Messages that trigger async work show a "spinner" placeholder that resolves into a card when the result arrives.
- Real-time update: either SSE persistent connection on the conversation (preferred) or polling (simpler fallback).
- Nova can still reference the result in a subsequent turn if the user asks follow-up questions — the result is persisted and injected into the system prompt for the next turn.

---

## Design questions to resolve before writing a full spec

1. **Background worker placement:** separate container vs in-process threadpool vs scheduled trigger. Separate container is cleanest for scaling; threadpool is simplest; scheduled trigger reuses existing infrastructure but feels hacky.
2. **Real-time push to chat:** SSE on the conversation (keeps a connection alive) vs WebSocket vs polling. SSE is probably enough and simplest.
3. **Ordering guarantees:** if a user triggers 3 tools in a row, does the async executor run them in parallel or serially? Parallel is faster but may conflict (e.g., two tool calls that both modify the same resource).
4. **Cancellation:** can the user cancel a pending async tool? How does that interact with confirmations from Option A?

## Estimated effort

Medium — 2-3 week delivery. Major pieces:
- Background worker + polling loop (~3 days)
- `pending_tool_calls` table + state machine (~2 days)
- Activity feed async-result rendering (frontend — ~3 days)
- Chat UI spinner → result card (frontend — ~2 days)
- SSE/polling push mechanism (~2 days)
- Integration tests (~2 days)

## Dependencies

- Purpose-routing (Option A) must land first — async execution needs to pick the right model for each tool call
- Activity feed must support rich entry types (currently mostly text)
- Decision on worker placement drives infrastructure changes

---

## Not in scope here

Tool dependencies / DAG orchestration — that's Layer D (workflow engine). Async tool execution is "one user intent → N independent async tool calls." Layer D is "one goal → DAG of tool calls with dependencies + retries + approvals."
