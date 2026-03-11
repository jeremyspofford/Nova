# Engram Integration & Old Memory System Purge

> Wire the Engram Network into the live conversation loop and purge all remnants of the old 4-tier memory system. No fallback, no wrapper layer — engrams become the sole memory system.

---

## Context

The Engram Network (Phase 6) is fully built but dormant — the orchestrator still calls the old `/api/v1/agents/{agent_id}/context` endpoint and stores memories via `/api/v1/memories/bulk`. The old system (4-tier tables, hybrid retrieval, compaction loop) is obsolete. No existing data needs preservation.

---

## 1. Orchestrator Changes

### `_get_memory_context()` (`orchestrator/app/agents/runner.py`)

Replace the old call to `/api/v1/agents/{agent_id}/context` with a call to `/api/v1/engrams/context`. The engram endpoint returns a formatted prompt string with sections (self-model, active goal, reconstructed memories, key decisions, open threads). Inject directly into the system prompt.

**Before:**
```python
resp = await memory_client.post(
    f"/api/v1/agents/{agent_id}/context",
    json={"agent_id": agent_id, "query": query, "max_tokens": 4096},
)
```

**After:**
```python
resp = await memory_client.post(
    "/api/v1/engrams/context",
    json={"query": query, "session_id": session_id},
)
# resp.json()["context"] is the formatted prompt string
```

### `_store_exchange()` (`orchestrator/app/agents/runner.py`)

Remove the old `POST /api/v1/memories/bulk` call. The engram ingestion queue (Redis LPUSH → BRPOP) already handles this — data was going through both paths. Delete the redundant old path.

### Session Summarization (`orchestrator/app/session_summary.py`)

**Delete entirely.** The engram consolidation daemon already subsumes session summarization — it replays episodes, extracts patterns into schema engrams, and resolves contradictions. A separate session summary sweep is redundant.

Downstream cleanup required:
- **`orchestrator/app/main.py`** — remove the `session_summary_sweep` background task creation, cancellation, and `asyncio.gather` reference.
- **`orchestrator/app/router.py`** — remove the `POST /api/v1/chat/sessions/{session_id}/summarize` endpoint that imports from `session_summary`.
- **`orchestrator/app/config.py`** — remove `session_summary_timeout_seconds`. **Keep `session_summary_model`** — it is reused by `conversations.py:generate_title()` for conversation title generation (rename to `utility_model` if desired, but not required for this change).

### Pipeline Executor (`orchestrator/app/pipeline/executor.py`)

Remove the `POST /api/v1/memories/bulk` call for exchange log storage. Pipeline conversation turns already flow through `_store_exchange()` → engram ingestion queue. No separate memory storage needed.

---

## 2. Memory Service Cleanup

### Files to Delete

| File | Purpose (obsolete) |
|------|-------------------|
| `memory-service/app/router.py` | Old 11-endpoint memory API |
| `memory-service/app/retrieval.py` | Hybrid vector+keyword search |
| `memory-service/app/compaction.py` | Fact extraction background loop |
| `memory-service/app/cleanup.py` | Working memory TTL cleanup |
| `memory-service/app/service.py` | `save_fact_internal()` |
| `memory-service/app/partitions.py` | Episodic memory monthly partitioning |
| `memory-service/app/reembed.py` | Re-embedding loop |
| `memory-service/app/engram/backfill.py` | Old→engram migration (not needed) |

### Files to Keep

| File | Reason |
|------|--------|
| `memory-service/app/embedding.py` | 3-tier embedding cache, used by engram modules |
| `memory-service/app/engram/*` (except backfill.py) | The new memory system |
| `memory-service/app/db/database.py` | SQLAlchemy engine, session management |
| `memory-service/app/health.py` | Health endpoints |
| `memory-service/app/config.py` | Settings (remove old memory settings) |

### Code Moves

**`to_pg_vector()`** from `retrieval.py` → `embedding.py`. This function is imported by these engram files that need their imports updated:

- `memory-service/app/engram/ingestion.py`
- `memory-service/app/engram/activation.py`
- `memory-service/app/engram/entity_resolution.py`
- `memory-service/app/engram/consolidation.py`
- `memory-service/app/engram/retrieval_logger.py`

**`_warmup_embedding()`** currently lives in old `router.py`. Move to `main.py` directly (or `embedding.py`). It warms the embedding cache that engrams depend on — must be kept.

### `main.py` Updates

Remove imports and background tasks for: `cleanup_loop`, `compaction_loop`, `partition_loop`, `reembed_loop`, old `router`, `context_router`, `warmup_router`.

Remaining background tasks: `ingestion_loop`, `consolidation_loop`, `_warmup_embedding`, `_bootstrap_self_model`.

Remaining routers: `health_router`, `engram_router`.

### `config.py` Updates

Remove old memory-related settings: `redis_working_memory_ttl`, `redis_search_cache_ttl`, `working_memory_cleanup_interval_seconds`, `compaction_enabled`, `compaction_interval_seconds`, `compaction_batch_size`, `compaction_lookback_days`, `compaction_model`, and any other settings whose sole consumers were the deleted files.

### `schema.sql` Updates

Drop old tables:
- `working_memories`
- `episodic_memories`
- `semantic_memories`
- `procedural_memories`

**Keep `embedding_cache`** — actively used by `embedding.py` as L2 cache (Redis → PostgreSQL → LLM Gateway).

Keep all engram tables (`engrams`, `engram_edges`, `engram_archive`, `consolidation_log`, `retrieval_log`, `working_memory_slots`).

---

## 3. Dashboard Changes

### Delete

- `dashboard/src/pages/MemoryInspector.tsx` — old 4-tier memory browser

### Update `api.ts`

Remove: `browseMemoriesV2`, `searchMemories`, `deleteMemory`, `saveFact`, `uploadFile` (memory file upload), and related types (`BrowseMemoryItem`, `MemoryTier`, `FileUploadResponse`, etc.).

### Update `ChatPage.tsx`

Remove the `uploadFile` import and the file attachment upload call (line ~180). File upload stored files as flat memories in the old system — not compatible with engrams. File ingestion can be added as a separate feature later.

### Update `App.tsx`

- Remove `/memory` route and `MemoryInspector` import.
- Remove the `/api/v1/memory/warmup` fetch call (pre-existing dead code — URL doesn't match actual endpoint).

### Update `NavBar.tsx`

Remove old "Memory" nav link. Rename "Engrams" to "Memory" (it is now the sole memory system).

---

## 4. Contracts Cleanup

### `nova-contracts/nova_contracts/memory.py`

Delete entirely — all old memory contract models are obsolete.

### `nova-contracts/nova_contracts/engram.py`

Remove `BackfillRequest` and `BackfillResponse` (no backfill needed).

### `nova-contracts/nova_contracts/__init__.py`

Remove all old memory model exports. Remove backfill exports. Keep engram exports.

---

## 5. Tests

### Delete

- `tests/test_memory.py` — old memory CRUD integration tests against purged endpoints.

New engram integration tests are a separate follow-up task.

---

## Implementation Sequence

1. Move `to_pg_vector()` and `_warmup_embedding()` out of old files into `embedding.py` / `main.py`; update all imports
2. Rewrite orchestrator callers (`runner.py`, delete `session_summary.py`, update `executor.py`, update orchestrator `main.py`)
3. Clean up memory-service (update `main.py`, delete old files, update `schema.sql`, update `config.py`)
4. Remove backfill code and endpoints from engram router and contracts
5. Update dashboard (delete `MemoryInspector`, remove `uploadFile` from `ChatPage`, update nav, clean `api.ts`, clean `App.tsx`)
6. Clean up contracts (delete `memory.py`, update `__init__.py`, update `engram.py`)
7. Delete old integration tests
8. Verify dashboard builds (`npm run build`)
9. Verify Python syntax on all changed files
