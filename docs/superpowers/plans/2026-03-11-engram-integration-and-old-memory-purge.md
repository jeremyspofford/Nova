# Engram Integration & Old Memory Purge — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Engram Network into the live conversation loop and delete all old 4-tier memory code, tables, endpoints, and contracts.

**Architecture:** The orchestrator switches from calling old `/api/v1/agents/{id}/context` and `/api/v1/memories/bulk` to calling `/api/v1/engrams/context` (already built) and relying on the Redis ingestion queue (already wired). Old memory-service code (router, retrieval, compaction, cleanup, partitions, reembed, service) is deleted. Old SQL tables are dropped. Dashboard's MemoryInspector is replaced by the existing EngramExplorer page.

**Tech Stack:** Python/FastAPI (orchestrator, memory-service), React/TypeScript (dashboard), PostgreSQL + pgvector, Pydantic (nova-contracts)

**Spec:** `docs/superpowers/specs/2026-03-11-engram-integration-and-old-memory-purge.md`

---

## Chunk 1: Memory Service Internal Cleanup

### Task 1: Move `to_pg_vector()` to `embedding.py`

**Files:**
- Modify: `memory-service/app/embedding.py` — add function at bottom
- Modify: `memory-service/app/engram/activation.py` — update import
- Modify: `memory-service/app/engram/consolidation.py` — update import
- Modify: `memory-service/app/engram/entity_resolution.py` — update import
- Modify: `memory-service/app/engram/ingestion.py` — update import
- Modify: `memory-service/app/engram/retrieval_logger.py` — update import

- [ ] **Step 1: Replace `to_pg_vector` import in `embedding.py` with local definition**

`memory-service/app/embedding.py` line 17 currently has `from app.retrieval import to_pg_vector`. Remove that import line and add the function definition at the bottom of the file:

```python
def to_pg_vector(embedding: list[float]) -> str:
    """Serialize a Python list of floats into a pgvector-compatible string."""
    return "[" + ",".join(str(v) for v in embedding) + "]"
```

- [ ] **Step 2: Update imports in all engram files**

In each of these 5 files, change:
```python
from app.retrieval import to_pg_vector
```
to:
```python
from app.embedding import to_pg_vector
```

Files to update:
- `memory-service/app/engram/activation.py`
- `memory-service/app/engram/consolidation.py`
- `memory-service/app/engram/entity_resolution.py`
- `memory-service/app/engram/ingestion.py`
- `memory-service/app/engram/retrieval_logger.py`

- [ ] **Step 3: Verify syntax**

Run: `cd memory-service && python3 -c "import py_compile; [py_compile.compile(f'app/engram/{f}', doraise=True) for f in ['activation.py','consolidation.py','entity_resolution.py','ingestion.py','retrieval_logger.py']]"`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add memory-service/app/embedding.py memory-service/app/engram/activation.py memory-service/app/engram/consolidation.py memory-service/app/engram/entity_resolution.py memory-service/app/engram/ingestion.py memory-service/app/engram/retrieval_logger.py
git commit -m "refactor: move to_pg_vector() to embedding.py ahead of old memory purge"
```

---

### Task 2: Move `_warmup_embedding()` to `main.py`

**Files:**
- Modify: `memory-service/app/main.py` — add warmup function, remove old router import

- [ ] **Step 1: Add `_warmup_embedding` function to `main.py`**

Add this function before the `app = FastAPI(...)` line:

```python
async def _warmup_embedding():
    """Fire a dummy embedding to force the model into RAM."""
    try:
        from app.db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await get_embedding("warmup", session)
        log.info("Embedding warmup complete")
    except Exception as e:
        log.warning("Embedding warmup failed: %s", e)
```

Add to imports at top:
```python
from app.embedding import get_embedding
```

- [ ] **Step 2: Remove old router imports from `main.py`**

Remove this line:
```python
from app.router import context_router, router, warmup_router, _warmup_embedding
```

The `_warmup_embedding` reference in `asyncio.create_task(_warmup_embedding(), name="warmup")` now resolves to the local function.

- [ ] **Step 3: Remove old background tasks and routers from `main.py`**

In the `lifespan` function, remove these lines:
```python
_cleanup_task = asyncio.create_task(cleanup_loop(), name="cleanup")
_compaction_task = asyncio.create_task(compaction_loop(), name="compaction")
_partition_task = asyncio.create_task(partition_loop(), name="partitions")
_reembed_task = asyncio.create_task(reembed_loop(), name="reembed")
```

And their corresponding cancel and gather lines:
```python
_cleanup_task.cancel()
_compaction_task.cancel()
_partition_task.cancel()
_reembed_task.cancel()
await asyncio.gather(
    _cleanup_task, _compaction_task, _partition_task, _reembed_task,
    _ingestion_task, _consolidation_task,
    return_exceptions=True,
)
```

Replace the gather with:
```python
await asyncio.gather(
    _ingestion_task, _consolidation_task,
    return_exceptions=True,
)
```

Remove these imports:
```python
from app.cleanup import cleanup_loop
from app.compaction import compaction_loop
from app.partitions import partition_loop
from app.reembed import reembed_loop
```

Remove these router registrations:
```python
app.include_router(router)
app.include_router(context_router)
app.include_router(warmup_router)
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/main.py', doraise=True)"`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add memory-service/app/main.py
git commit -m "refactor: remove old memory background tasks and routers from main.py"
```

---

### Task 3: Delete old memory-service files

**Files to delete:**
- `memory-service/app/router.py`
- `memory-service/app/retrieval.py`
- `memory-service/app/compaction.py`
- `memory-service/app/cleanup.py`
- `memory-service/app/service.py`
- `memory-service/app/partitions.py`
- `memory-service/app/reembed.py`
- `memory-service/app/engram/backfill.py`

- [ ] **Step 1: Delete the files**

```bash
rm memory-service/app/router.py memory-service/app/retrieval.py memory-service/app/compaction.py memory-service/app/cleanup.py memory-service/app/service.py memory-service/app/partitions.py memory-service/app/reembed.py memory-service/app/engram/backfill.py
```

- [ ] **Step 2: Verify main.py still parses**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/main.py', doraise=True)"`
Expected: No errors (all old imports were already removed in Task 2)

- [ ] **Step 3: Commit**

```bash
git add -u memory-service/app/
git commit -m "chore: delete old 4-tier memory system files (replaced by engram network)"
```

---

### Task 4: Remove backfill endpoints from engram router

**Files:**
- Modify: `memory-service/app/engram/router.py` — remove backfill endpoints and import

- [ ] **Step 1: Remove backfill imports and endpoints**

In `memory-service/app/engram/router.py`:

Remove from imports:
```python
from .backfill import run_backfill
```

Remove the `_backfill_status` dict:
```python
_backfill_status: dict = {"running": False, "last_result": None}
```

Remove these three endpoint functions entirely:
- `backfill_engrams()` (the `@engram_router.post("/backfill", ...)` handler)
- `backfill_status()` (the `@engram_router.get("/backfill/status")` handler)

Also remove `BackfillRequest` and `BackfillResponse` from the imports:
```python
from nova_contracts.engram import (
    BackfillRequest,
    BackfillResponse,
    IngestRequest,
    IngestResponse,
)
```
Change to:
```python
from nova_contracts.engram import (
    IngestRequest,
    IngestResponse,
)
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/engram/router.py', doraise=True)"`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/engram/router.py
git commit -m "chore: remove backfill endpoints from engram router (no old data to migrate)"
```

---

### Task 5: Clean up `schema.sql` — drop old tables

**Files:**
- Modify: `memory-service/app/db/schema.sql`

- [ ] **Step 1: Replace old table DDL with DROP statements**

Replace everything from line 7 (`-- Working memory: hot path`) through line 136 (`ALTER TABLE procedural_memories ADD COLUMN ...`) with:

```sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Legacy 4-tier memory tables: dropped in favor of engram network.
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS working_memories CASCADE;
DROP TABLE IF EXISTS episodic_memories CASCADE;
DROP TABLE IF EXISTS semantic_memories CASCADE;
DROP TABLE IF EXISTS procedural_memories CASCADE;
```

Keep the `embedding_cache` table (lines 105-110) — move it AFTER the DROP statements since the engram embedding pipeline uses it.

Keep the comment on line 138-141 but update it:
```sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Engram Network: graph-based cognitive memory
-- ─────────────────────────────────────────────────────────────────────────────
```

- [ ] **Step 2: Verify the SQL is syntactically valid**

Run: `python3 -c "print(open('memory-service/app/db/schema.sql').read()[:200])"`
Expected: Should show the extension creation followed by DROP statements

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/db/schema.sql
git commit -m "chore: drop old 4-tier memory tables from schema.sql"
```

---

### Task 6: Clean up `config.py` — remove old settings

**Files:**
- Modify: `memory-service/app/config.py`

- [ ] **Step 1: Remove old memory settings**

Remove these lines from the `Settings` class:

```python
    redis_working_memory_ttl: int = 3600       # 1 hour hot cache
    redis_search_cache_ttl: int = 30           # 30s search result cache
```

```python
    # Cleanup
    working_memory_cleanup_interval_seconds: int = 300

    # Compaction pipeline
    compaction_enabled: bool = True
    compaction_interval_seconds: int = 600
    compaction_batch_size: int = 50
    compaction_lookback_days: int = 7
    compaction_model: str = "claude-haiku-4-5-20251001"
```

Keep `redis_embedding_cache_ttl` — still used by `embedding.py`.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/config.py', doraise=True)"`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/config.py
git commit -m "chore: remove old memory config settings (compaction, cleanup, working memory TTL)"
```

---

## Chunk 2: Orchestrator Cutover

### Task 7: Rewrite `_get_memory_context()` to use engram context

**Files:**
- Modify: `orchestrator/app/agents/runner.py`

- [ ] **Step 1: Rewrite `_get_memory_context()`**

Replace the function at line 282-309 with:

```python
async def _get_memory_context(agent_id: str, query: str, session_id: str = "") -> tuple[str, int]:
    """Fetch engram-powered memory context for prompt assembly.

    Returns (context_string, section_count).
    """
    if not query:
        return "", 0

    memory_client = get_memory_client()
    try:
        resp = await memory_client.post(
            "/api/v1/engrams/context",
            params={"query": query, "session_id": session_id},
        )
        if resp.status_code != 200:
            return "", 0
        data = resp.json()
        context = data.get("context", "")
        if not context:
            return "", 0

        sections = data.get("sections", {})
        section_count = sum(1 for v in sections.values() if v)
        return context, section_count
    except Exception as e:
        log.warning("Engram context retrieval failed: %s", e)
        return "", 0
```

Note: The `/api/v1/engrams/context` endpoint uses query parameters (bare FastAPI function args), not a JSON body. Use `params=` not `json=`.

- [ ] **Step 2: Update callers to pass `session_id`**

The function now takes `session_id`. Update both call sites:

At line ~65 (non-streaming `run_agent_turn`):
```python
_get_memory_context(agent_id, query),
```
Change to:
```python
_get_memory_context(agent_id, query, session_id),
```

At line ~190 (streaming `stream_agent_turn`):
```python
_timed(_get_memory_context(agent_id, query)),
```
Change to:
```python
_timed(_get_memory_context(agent_id, query, session_id)),
```

- [ ] **Step 3: Update status message**

At line ~197 the streaming status says `memor{'y' if memory_count == 1 else 'ies'}`. Update to reflect engram context:

```python
mem_detail = f"{memory_count} section{'s' if memory_count != 1 else ''}" if memory_count else "no context"
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('orchestrator/app/agents/runner.py', doraise=True)"`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/agents/runner.py
git commit -m "feat: switch orchestrator to engram context for memory retrieval"
```

---

### Task 8: Clean up `_store_exchange()` — remove old bulk store

**Files:**
- Modify: `orchestrator/app/agents/runner.py`

- [ ] **Step 1: Remove old memory bulk store from `_store_exchange()`**

Replace the function at line 592-621 with:

```python
async def _store_exchange(
    agent_id: str,
    session_id: str,
    user_message: str,
    assistant_response: str,
) -> None:
    """Emit the conversation exchange to the engram ingestion queue."""
    await _emit_to_engram_queue(agent_id, session_id, user_message, assistant_response)
```

This removes the old `POST /api/v1/memories/bulk` call. The engram queue is the sole ingestion path.

- [ ] **Step 2: Remove unused import if `get_memory_client` is no longer used in this function**

Check: `get_memory_client` is still used by `_get_memory_context()`, so keep the import.

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('orchestrator/app/agents/runner.py', doraise=True)"`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/agents/runner.py
git commit -m "refactor: remove old memory bulk store from _store_exchange (engram queue is sole path)"
```

---

### Task 9: Delete `session_summary.py` and clean up references

**Files:**
- Delete: `orchestrator/app/session_summary.py`
- Modify: `orchestrator/app/main.py` — remove background task
- Modify: `orchestrator/app/router.py` — remove summarize endpoint

- [ ] **Step 1: Remove session summary sweep from orchestrator `main.py`**

Remove the import:
```python
from app.session_summary import session_summary_sweep
```

Remove the task creation:
```python
_summary_task = asyncio.create_task(session_summary_sweep(),    name="session-summary")
```

Update the log line:
```python
log.info("Queue worker, reaper, and session summary sweep started")
```
to:
```python
log.info("Queue worker and reaper started")
```

Remove the cancel:
```python
_summary_task.cancel()
```

Update the gather:
```python
await asyncio.gather(_queue_task, _reaper_task, _summary_task, return_exceptions=True)
```
to:
```python
await asyncio.gather(_queue_task, _reaper_task, return_exceptions=True)
```

- [ ] **Step 2: Remove summarize endpoint from orchestrator `router.py`**

Delete the endpoint function at line ~395-403:
```python
@router.post("/api/v1/chat/sessions/{session_id}/summarize")
async def summarize_chat_session(session_id: str, req: SummarizeRequest, _user: UserDep):
    ...
```

`SummarizeRequest` is a local class defined just above this endpoint (not an import) — delete it together with the endpoint.

- [ ] **Step 3: Remove `session_summary_timeout_seconds` from orchestrator config**

In `orchestrator/app/config.py`, delete the line:
```python
session_summary_timeout_seconds: int = 1800
```

Keep `session_summary_model` — it's reused by `conversations.py:generate_title()`.

- [ ] **Step 4: Delete the file**

```bash
rm orchestrator/app/session_summary.py
```

- [ ] **Step 5: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('orchestrator/app/main.py', doraise=True)"`
Run: `python3 -c "import py_compile; py_compile.compile('orchestrator/app/router.py', doraise=True)"`
Run: `python3 -c "import py_compile; py_compile.compile('orchestrator/app/config.py', doraise=True)"`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add -u orchestrator/
git commit -m "chore: delete session_summary.py (engram consolidation subsumes this)"
```

---

### Task 10: Clean up pipeline executor memory storage

**Files:**
- Modify: `orchestrator/app/pipeline/executor.py`

- [ ] **Step 1: Replace old memory bulk store with engram ingestion**

Find the `_extract_task_memory` function (around line 875-953). Replace the entire function body to ingest through the engram queue instead of old `/memories/bulk`:

```python
async def _extract_task_memory(
    state: "PipelineState",
    task_id: str,
    user_input: str,
    final_output: str,
) -> None:
    """Post-pipeline: emit structured memories to the engram ingestion queue."""
    try:
        import json as _json
        from datetime import datetime, timezone
        # Build a summary of the pipeline run for engram decomposition
        flags = sorted(state.flags)
        summary_lines = [
            f"Pipeline task completed.",
            f"Task: {user_input[:300]}",
            f"Output: {final_output[:400]}",
        ]
        if flags:
            summary_lines.append(f"Flags: {', '.join(flags)}")

        guardrail = state.completed.get("guardrail", {})
        if guardrail.get("blocked"):
            findings = guardrail.get("findings", [])
            if findings:
                top = findings[0]
                summary_lines.append(
                    f"Guardrail blocked: {top.get('type', 'unknown')} — {top.get('description', '')}"
                )

        review = state.completed.get("code_review", {})
        issues = review.get("issues", [])
        if issues:
            issue_lines = [
                f"[{iss.get('severity', 'info').upper()}] {iss.get('description', '')}"
                for iss in issues[:5]
            ]
            summary_lines.append("Code review findings:\n" + "\n".join(issue_lines))

        raw_text = "\n".join(summary_lines)

        # Use the same engram queue as _store_exchange
        from app.agents.runner import _get_engram_redis
        redis = _get_engram_redis()
        payload = _json.dumps({
            "raw_text": raw_text,
            "source_type": "pipeline",
            "source_id": None,
            "session_id": task_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"task_id": task_id, "source": "pipeline_completion"},
        })
        await redis.lpush("engram:ingestion:queue", payload)
        logger.debug("Emitted pipeline memories for task %s to engram queue", task_id)
    except Exception as exc:
        logger.warning("Pipeline memory extraction failed for task %s: %s", task_id, exc)
```

- [ ] **Step 2: Remove unused import of `get_memory_client` if no other usage in this file**

Search the file for other uses of `get_memory_client`. If `_extract_task_memory` was the only caller, the import can be removed. If used elsewhere, keep it.

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('orchestrator/app/pipeline/executor.py', doraise=True)"`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/pipeline/executor.py
git commit -m "refactor: route pipeline memory extraction through engram queue"
```

---

## Chunk 3: Dashboard & Contracts Cleanup

### Task 11: Update dashboard — delete MemoryInspector, clean nav and routes

**Files:**
- Delete: `dashboard/src/pages/MemoryInspector.tsx`
- Modify: `dashboard/src/App.tsx` — remove old route and import, remove warmup call
- Modify: `dashboard/src/components/NavBar.tsx` — rename Engrams to Memory

- [ ] **Step 1: Delete MemoryInspector**

```bash
rm dashboard/src/pages/MemoryInspector.tsx
```

- [ ] **Step 2: Update `App.tsx`**

Remove the import:
```typescript
import { MemoryInspector } from './pages/MemoryInspector'
```

Remove the route:
```typescript
<Route path="/memory"  element={<PageShell><MemoryInspector /></PageShell>} />
```

Remove the broken warmup call (line ~98):
```typescript
else fetch('/api/v1/memory/warmup', { method: 'POST' }).catch(() => {})
```
Replace with just:
```typescript
else {}
```
Or simplify the whole `useEffect` to just the `checkBackendReady` call without the warmup.

- [ ] **Step 3: Update `NavBar.tsx`**

Change the Engrams nav link:
```typescript
{ to: '/engrams',  label: 'Engrams',  icon: GitMerge         },
```
to:
```typescript
{ to: '/engrams',  label: 'Memory',   icon: Brain            },
```

Remove the now-unused `GitMerge` import from lucide-react (only if not used elsewhere).

Remove the old Memory link:
```typescript
{ to: '/memory',   label: 'Memory',   icon: Brain            },
```

- [ ] **Step 4: Verify build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 5: Commit**

```bash
git add -u dashboard/src/
git commit -m "chore: delete MemoryInspector, rename Engrams nav to Memory"
```

---

### Task 12: Clean up `api.ts` — remove old memory functions

**Files:**
- Modify: `dashboard/src/api.ts`
- Modify: `dashboard/src/pages/chat/ChatPage.tsx` — remove uploadFile usage

- [ ] **Step 1: Remove old memory types and functions from `api.ts`**

Remove these types:
- `FileUploadResponse` interface
- `MemoryTier` type
- `SaveFactRequest` interface
- `BrowseMemoryItem` interface
- `BrowseMemoryResponse` interface

Remove these functions:
- `uploadFile()`
- `browseMemoriesV2()`
- `searchMemories()`
- `deleteMemory()`
- `saveFact()`

- [ ] **Step 2: Update `ChatPage.tsx`**

Remove `uploadFile` from the import:
```typescript
import { streamChat, uploadFile, discoverModels, ... } from '../../api'
```
becomes:
```typescript
import { streamChat, discoverModels, ... } from '../../api'
```

Remove the file upload call (around line 178-181):
```typescript
if (attachments) {
  for (const att of attachments) {
    uploadFile(att.file, currentSessionId).catch(() => {})
  }
}
```

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds. If there are other files importing removed functions, fix those too.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/api.ts dashboard/src/pages/chat/ChatPage.tsx
git commit -m "chore: remove old memory API functions from dashboard"
```

---

### Task 13: Clean up nova-contracts

**Files:**
- Delete: `nova-contracts/nova_contracts/memory.py`
- Modify: `nova-contracts/nova_contracts/engram.py` — remove BackfillRequest/BackfillResponse
- Modify: `nova-contracts/nova_contracts/__init__.py` — remove all old memory exports

- [ ] **Step 1: Delete `memory.py`**

```bash
rm nova-contracts/nova_contracts/memory.py
```

- [ ] **Step 2: Remove backfill models from `engram.py`**

Delete the `BackfillRequest` and `BackfillResponse` classes from `nova-contracts/nova_contracts/engram.py`.

- [ ] **Step 3: Rewrite `__init__.py`**

Replace entirely with:

```python
from .llm import (
    ModelCapability,
    ContentBlock,
    Message,
    extract_text_content,
    ToolCallRef,
    ToolDefinition,
    CompleteRequest,
    CompleteResponse,
    StreamChunk,
    EmbedRequest,
    EmbedResponse,
    ModelInfo,
    ToolCall,
)
from .orchestrator import (
    AgentStatus,
    AgentConfig,
    CreateAgentRequest,
    AgentInfo,
    TaskType,
    SubmitTaskRequest,
    TaskStatus,
    TaskResult,
)
from .chat import (
    ChatMessageType,
    ChatMessage,
    StreamChunkMessage,
    SessionInfo,
)
from .engram import (
    EngramType,
    EdgeRelation,
    IngestionSourceType,
    IngestionEvent,
    DecomposedEngram,
    DecomposedRelationship,
    DecomposedContradiction,
    DecompositionResult,
    IngestRequest,
    IngestResponse,
    EngramDetail,
)

__all__ = [
    "ModelCapability", "ContentBlock", "Message", "extract_text_content",
    "ToolCallRef", "ToolDefinition",
    "CompleteRequest", "CompleteResponse", "StreamChunk",
    "EmbedRequest", "EmbedResponse", "ModelInfo", "ToolCall",
    "AgentStatus", "AgentConfig", "CreateAgentRequest", "AgentInfo",
    "TaskType", "SubmitTaskRequest", "TaskStatus", "TaskResult",
    "ChatMessageType", "ChatMessage", "StreamChunkMessage", "SessionInfo",
    "EngramType", "EdgeRelation", "IngestionSourceType", "IngestionEvent",
    "DecomposedEngram", "DecomposedRelationship", "DecomposedContradiction",
    "DecompositionResult", "IngestRequest", "IngestResponse", "EngramDetail",
]
```

- [ ] **Step 4: Check for remaining importers of old memory models**

Run: `grep -r "from nova_contracts.memory" orchestrator/ memory-service/ chat-api/ dashboard/ tests/ --include="*.py" -l`

If any files still import from `nova_contracts.memory`, fix them.

- [ ] **Step 5: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('nova-contracts/nova_contracts/__init__.py', doraise=True)"`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add -u nova-contracts/ && git add nova-contracts/
git commit -m "chore: delete old memory contracts, remove backfill models"
```

---

### Task 14: Delete old integration tests

**Files:**
- Delete: `tests/test_memory.py`

- [ ] **Step 1: Delete the test file**

```bash
rm tests/test_memory.py
```

- [ ] **Step 2: Verify remaining tests still pass syntax check**

Run: `python3 -c "import py_compile; [py_compile.compile(f, doraise=True) for f in __import__('glob').glob('tests/*.py')]"`
Expected: No errors from remaining test files

- [ ] **Step 3: Commit**

```bash
git add -u tests/
git commit -m "chore: delete old memory integration tests (replaced by engram system)"
```

---

## Chunk 4: Final Verification

### Task 15: Full verification pass

- [ ] **Step 1: Verify all Python syntax**

```bash
find memory-service/app -name "*.py" -exec python3 -c "import py_compile; py_compile.compile('{}', doraise=True)" \;
find orchestrator/app -name "*.py" -exec python3 -c "import py_compile; py_compile.compile('{}', doraise=True)" \;
find nova-contracts -name "*.py" -exec python3 -c "import py_compile; py_compile.compile('{}', doraise=True)" \;
```
Expected: No errors

- [ ] **Step 2: Verify dashboard builds**

```bash
cd dashboard && npm run build
```
Expected: Build succeeds

- [ ] **Step 3: Verify no dangling imports to deleted files**

```bash
grep -r "from app.router import\|from app.retrieval import\|from app.compaction import\|from app.cleanup import\|from app.service import\|from app.partitions import\|from app.reembed import\|from app.session_summary import\|from nova_contracts.memory import" memory-service/ orchestrator/ nova-contracts/ --include="*.py"
```
Expected: No matches

- [ ] **Step 4: Remove dead orchestrator warmup proxy endpoint**

In `orchestrator/app/router.py`, find and delete the `POST /api/v1/memory/warmup` endpoint that proxied to the old memory-service warmup router. It will 404 now that the old warmup router is gone.

- [ ] **Step 5: Verify no references to old API endpoints**

```bash
grep -r "memories/bulk\|memories/search\|memories/browse\|memories/facts\|memories/files\|agents.*context" orchestrator/ memory-service/ --include="*.py" | grep -v engram | grep -v "\.pyc"
```
Expected: No matches (all memory references should be engram-based now)

- [ ] **Step 6: Final commit if any fixes were needed**

```bash
git add -A && git commit -m "fix: resolve any remaining dangling references from old memory purge"
```
(Only if step 3 or 4 found issues that needed fixing)
