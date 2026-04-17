# Reliability Audit — 2026-04-16

## Scope

Reviewed the surfaces called out in the audit brief:

- Engram/source corruption surfaces (ingestion race conditions, partial writes, orphan potential)
- DB migration safety: orchestrator's versioned SQL runner and memory-service's single `schema.sql`
- Stale Redis state (heartbeats, dedup set, `nova:config:*` overrides)
- Backup/restore correctness (`make backup`/`make restore` and recovery-service `backup.py`)
- Heartbeat / stale-reaper logic (30s heartbeat, 120s TTL, 150s stale, 60s reaper cycle)
- Ingestion idempotency (Redis BRPOP worker at `memory-service/app/engram/ingestion.py`)
- Consolidation cycle mutex (`_consolidation_lock`) and crash-mid-phase behavior
- Partial startup failure handling and `close_redis()` coverage per CLAUDE.md
- Data integrity in live DB and Redis (snapshot taken at audit time)

**Out of scope (as instructed):** distributed deployment (pre-implementation), multi-node consensus.

Findings are anchored in code paths and in live-system evidence captured at audit time. A running compose stack was observed; stuck tasks and reaper misbehaviour are real, not hypothetical.

---

## Findings

### [P0] Reaper infinite-loops on stuck `task_running` rows because `task_running → queued` is rejected by the state machine

- **Evidence:**
  - `orchestrator/app/reaper.py:107-110` calls `transition_task_status(task_id, "queued", ...)` for any task whose heartbeat expired.
  - `orchestrator/app/pipeline/state_machine.py:49-53` defines the allowed successors for `task_running`: `{"critique_direction_running", "guardrail_running", "code_review_running", "critique_acceptance_running", "completing", "failed", "cancelled"}` — `queued` is **not** among them.
  - Live DB (audit time): 9 tasks in `task_running` / `context_running`. Four of them (`b6a9c3fe…`, `395d596b…`, `802a22e1…`, `1797b46a…`) date from **2026-04-04**. They have been stuck for 13 days.
  - Live logs (audit time): orchestrator is emitting, every reaper cycle (60 s), per-task:
    ```
    ERROR app.pipeline.state_machine: Invalid task status transition: task=… task_running -> queued (rejected by state machine)
    WARNING app.reaper: Reaper: task … stale in state 'task_running' (attempt 1/2) — re-queuing
    INFO app.reaper: Reaper: task … transition to queued rejected — skipping
    ```
  - Note: the "(attempt 1/2)" counter never advances because `retry_count` is only incremented by the CAS update, which the state machine short-circuits. The reaper will spam these log lines forever.
- **Impact:** Permanent garbage in the task table, constant error-log noise (drowns real errors), wasted reaper cycles, and — crucially — these tasks never reach `failed` so they never hit the dead-letter queue, never surface in the "failed tasks" UI, and never return a clean terminal signal to their parent goal in cortex. This is the exact "stale `task_running` surviving restart" class called out in the audit brief, and it is active on Jeremy's box right now.
- **Recommendation:** Add `queued` as a legal successor from every `*_running` state in `VALID_TRANSITIONS`, **or** change the reaper to (a) call a dedicated "force-requeue" helper that bypasses the state machine for recovery purposes, and (b) escalate to `failed` after the first transition rejection so the task exits the running set instead of being retried every cycle. Whichever path is chosen, add a one-time startup cleanup that converts any pre-existing stuck `*_running` rows with expired heartbeats into `failed` with a clear error message. Tests should cover: (i) `task_running → queued` retry path succeeds, (ii) transition rejection never loops.
- **Effort:** S

### [P0] `make backup` / recovery `backup.py` silently exclude `/data/sources/` filesystem content

- **Evidence:**
  - `scripts/backup.sh:29-30` runs `pg_dump` and then `tar -czf` only the `database.sql`. No filesystem content is included.
  - `recovery-service/app/backup.py:47-72` and `178-210` (manual + checkpoint backups) do the same — `pg_dump` only.
  - `memory-service/app/engram/sources.py:42` hard-codes `SOURCES_DIR = Path("/data/sources")` and `:99, :138-140` writes large (> ~100 KB) source bodies to the filesystem and stores only `content_path` in the DB.
  - `docker-compose.yml:266` binds `./data/sources:/data/sources`, confirming the volume is real and persisted on the host.
- **Impact:** After a restore from any of the three backup code paths, every large source ends up with a `content_path` row whose file is missing. `/api/v1/engrams/sources/{id}/content` returns 404/empty for those rows, and `redecompose` fails because it tries to reread source text. The DB → backup → restore loop is advertised as the canonical crash-recovery mechanism (dashboard "Recovery" surface), so the UX promise is broken; a user restoring from yesterday can end up with a degraded memory that silently has gaps. Same issue applies to any tool that re-embeds from stored source content.
- **Recommendation:** Either (a) add `/data/sources/` (and `data/postgres/` is already live, so skip that; but do include any other bind-mounted state) to the `tar` step in both code paths, or (b) short-term: enforce a DB-only content rule in `sources.py._store_to_filesystem()` by either inlining everything in `content TEXT` until a proper filesystem-backup story ships, or refusing to accept sources > N KB. Long-term: a proper backup manifest format that lists what the archive contains; restore verifies all pieces are present before touching the DB.
- **Effort:** S (include `/data/sources/` in the tar) to M (proper manifest + verification).

### [P0] Engram ingestion worker loses payloads on crash between BRPOP and async task spawn

- **Evidence:**
  - `memory-service/app/engram/ingestion.py:63-89` reads an item from Redis with `BRPOP` (which **removes** it from the list), decodes it, validates JSON, then fires `asyncio.create_task(_process_event_guarded(raw_payload))` and loops.
  - If the process is killed between the `BRPOP` and the completion of `_process_event_guarded` — including container SIGKILL, OOM, unhandled exceptions inside `_process_event_guarded` that escape the `try/except`, or shutdown that cancels the task before decomposition finishes — the payload is already out of Redis and nowhere on disk.
  - The decomposition step is an LLM call (`decompose(raw_text)`) that can run for many seconds; the semaphore allows 5 in flight. On SIGTERM there is **no** drain logic in `lifespan` — `_ingestion_task.cancel()` is called, but outstanding `asyncio.create_task` spawns are not awaited or re-queued.
  - On restart, the data is gone. There is no "pending" / "dead-letter" mirror for ingestion (orchestrator has one for pipeline tasks, but not memory-service).
- **Impact:** Any bounce of the memory-service container (crash, redeploy, OOM) during ingestion silently loses whatever was in-flight. For chat ingestion the user can retype, but for intel and knowledge-worker feed pushes the source material is usually one-shot — the item's ID is already in the orchestrator's intel content table, so the user never gets a retry. Silent memory gaps after crashes erode trust in the memory system.
- **Recommendation:** Two-part fix. Short-term: use `BRPOPLPUSH`/`BLMOVE` to atomically move the item to an `engram:ingestion:processing` list; delete it only after successful commit; on startup, re-drain the processing list back into the main queue. Medium-term: add `_ingestion_task` siblings to the shutdown drain in `memory-service/app/main.py` lifespan so in-flight decompositions get up to N seconds to finish before cancellation.
- **Effort:** M

### [P1] Memory-service leaks Redis connections — 3+ module-level singletons, zero `close_redis()` in lifespan

- **Evidence:**
  - `memory-service/app/embedding.py:20-27`: `_redis` singleton; no close function.
  - `memory-service/app/engram/retrieval_logger.py:32-44`: `_train_redis` singleton (uses `RETRIEVAL_TRAIN_REDIS_DB`); no close function.
  - `memory-service/app/engram/cortex_stimulus.py:14-23`: `_cortex_redis` singleton (db5); no close function.
  - `memory-service/app/engram/decomposition.py:50-53`: creates a fresh `aioredis.from_url(...)` per call (looked up per LLM call). This one does call `aclose()` in a finally.
  - `memory-service/app/main.py:41-56` lifespan shutdown cancels the ingestion and consolidation tasks but calls no `close_redis()`, violating the CLAUDE.md rule: *"Every service with `get_redis()` must have a corresponding `close_redis()` called in the FastAPI lifespan shutdown path. Connection leaks accumulate across restarts."*
  - LLM gateway has the same gap on a smaller scale: `llm-gateway/app/discovery.py`, `llm-gateway/app/registry.py`, `llm-gateway/app/health.py` each hold a `_redis`/`_strategy_redis` singleton; `llm-gateway/app/main.py:50-56` closes only `rate_limiter`, `response_cache`, `editor_tracker` — not the discovery/registry/health clients.
- **Impact:** Across many redeploys/hot-reloads, these connections accumulate against Redis's connection limit. The docstring in CLAUDE.md calls this out specifically — the gap is present and real. Memory-service is the highest-traffic offender because the consolidation daemon opens db0/db5 on every cycle.
- **Recommendation:** Add `close_redis()` helpers to the three singleton sites in memory-service (embedding, retrieval_logger, cortex_stimulus) and invoke them in `lifespan`'s shutdown. Do the same for llm-gateway discovery/registry/health. Add a tiny lint rule or test that walks service modules and asserts every file defining `_redis = None` also exposes a close function imported into lifespan.
- **Effort:** S

### [P1] Factory-reset references five non-existent tables — partial resets silently succeed while leaving stale data

- **Evidence:** `recovery-service/app/factory_reset.py:13-35` defines `CATEGORY_TABLES` with these table names:
  - `stage_results` — does not exist in any migration (no `CREATE TABLE stage_results` in `orchestrator/app/migrations/` or `memory-service/app/db/schema.sql`).
  - `sessions` — does not exist (the service has `agent_sessions`, not `sessions`).
  - `messages` — exists (migration 014).
  - `memories` — does not exist (the 4-tier `working_memories/episodic_memories/semantic_memories/procedural_memories` tables were replaced by the engram network; memory-service `schema.sql:10-13` explicitly drops them).
  - `pods`, `pod_agents`, `api_keys`, `usage_events` — exist.
- The function calls `information_schema.tables` at line 77-80 to check existence, so the non-existent tables are silently skipped. The reset "succeeds" but the category labels say e.g. "Memories (embeddings + semantic store)" — this promises a wipe that doesn't happen.
- **Impact:** A user who ticks "wipe memories" in the Recovery UI expecting their engram graph to be cleared will find the old data still present after "successful" reset. This is a data-retention surprise — the opposite of what they asked for. Chat-sessions reset hits `messages` but not the conversation rows in `conversations` (from migration 014). API-keys reset works.
- **Recommendation:** Rewrite `CATEGORY_TABLES` against the current schema. Remove `stage_results`, `sessions`, `memories`. For "memories" → add `engrams`, `engram_edges`, `engram_archive`, `sources`, `consolidation_log`, `retrieval_log`, `working_memory_slots`. For "chat_sessions" → add `conversations`. Add an integration test that, for every category, confirms the listed tables exist in the DB before the test runs (catches schema drift on every CI run).
- **Effort:** S

### [P1] `_run_schema_migrations` runs each migration file in a single transaction, but several files contain non-idempotent DDL that can half-apply across restarts if a statement errors mid-file

- **Evidence:**
  - `orchestrator/app/db.py:161-166` wraps every migration file in `async with conn.transaction():` and inserts into `schema_migrations` at the end. Good pattern for PostgreSQL — a failure anywhere in the file rolls back and the version is not recorded.
  - However, individual migrations routinely have non-idempotent statements that depend on state from a previous file. If the DB crashes between migration N committing and migration N+1 completing, the retry of N+1 is fine; but if someone manually alters the DB (very plausible during development or restore) and a migration file's non-idempotent statement fails partway:
    - `orchestrator/app/migrations/020_rbac_and_tenants.sql:18-31`: `DO $$ IF NOT EXISTS ... ALTER TABLE users ADD COLUMN role ...` is guarded, but the adjacent `UPDATE users SET role = 'owner' WHERE ...` at 36-38 is not and will run again on every retry (harmless here, but pattern-unsafe for migrations that do data transforms).
    - `orchestrator/app/migrations/021_cortex_goals.sql:68-77`: seeds cortex@system.nova with a specific UUID but the column `role` might differ — the ON CONFLICT is on `email` only, so a rerun after a renamed user won't normalize.
  - Migration numbering has a **gap at 042, 043** (jumps from `041_knowledge_schema.sql` to `044_rich_error_context.sql`). That's not an error by itself — nothing reads the numbers — but indicates that migrations were dropped from the repo after being applied in some environments. If one of those environments ever restores from a pre-fix backup and re-runs migrations, 044+ assume state produced by 042/043 that never runs.
- **Impact:** The migration framework is robust for the happy path. The risk is dev-laptop divergence and restore-from-old-backup scenarios where a file fails partway and leaves the `schema_migrations` table behind but the schema is partially mutated. Not a daily blocker, but a footgun during any recovery or environment clone.
- **Recommendation:** (1) Add a CI job that runs all migrations against an empty DB, then again against a DB with the previous N-1 migrations applied — proves idempotency on every PR. (2) Fill or document the 042/043 gap (either rename files to close the gap or record the missing versions in a `_deprecated_migrations` table so future me doesn't wonder). (3) Adopt a standard guard pattern in all data-transforming migrations (e.g., `UPDATE ... WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = current_version)` or an idempotency-safe pattern with a migration-local "already applied" marker).
- **Effort:** M

### [P1] Memory-service `schema.sql` is a single 305-line monolith with no versioning — divergence between dev and prod is invisible

- **Evidence:**
  - `memory-service/app/db/database.py:41-81` reads `schema.sql` once at startup and executes every statement in one transaction. No `schema_migrations` equivalent — every startup re-runs the whole file.
  - The file uses `CREATE TABLE IF NOT EXISTS` and `DO $$ BEGIN ALTER TABLE ... EXCEPTION WHEN duplicate_column THEN NULL; END $$` patterns (e.g. `schema.sql:124-142`) to achieve idempotency. Works, but:
    - There is no audit trail for *when* a column was added. A developer pulling an older commit and running against their prod DB will get unexpected schema mutations with no log.
    - The `DROP TABLE IF EXISTS working_memories CASCADE` etc. at `schema.sql:10-13` will re-run on every boot. If someone creates a table with one of those exact names for any purpose (debugging, a new feature), it gets silently dropped every restart.
    - Some ALTERs are wrapped in `DO $$ ... EXCEPTION` (lines 124-142) but others like `schema.sql:278-280` use the simpler `ADD COLUMN IF NOT EXISTS` — inconsistent style suggests the migration style evolved ad hoc.
  - Comparing this to the orchestrator's versioned migration runner (56 files), the inconsistency is itself a reliability problem: two different DBs, two different safety models, one codebase.
- **Impact:** Schema drift is undetectable. A rollback or branch-switch that reverts the `schema.sql` file doesn't un-apply prior changes. The "drop if exists" safety valves can clobber user state if a name ever collides.
- **Recommendation:** Port memory-service to the same versioned migration pattern as orchestrator (reuse the runner — even copy-paste — pointing at `memory-service/app/db/migrations/*.sql`). The one-time migration is to split the current `schema.sql` into ordered files (`001_base.sql`, `002_source_provenance.sql`, etc.) and seed the `schema_migrations` table on upgrade so existing DBs don't re-run everything.
- **Effort:** M

### [P1] Source provenance is opt-in and ~99% of live engrams have no `source_ref_id` — the provenance guarantee in CLAUDE.md is aspirational

- **Evidence:**
  - CLAUDE.md: *"Every engram links back to a `sources` table tracking where knowledge came from."*
  - Live DB at audit time: `engrams` = 6,462 rows; `engrams WHERE source_ref_id IS NULL` = 6,396 (98.9%). Only 34 rows in `sources`.
  - `memory-service/app/engram/ingestion.py:175-207`: `find_or_create_source(...)` is wrapped in a try/except with `log.warning("Source creation failed (non-fatal): %s")`. If anything goes wrong during source creation, the engram is still created with `source_ref_id = NULL`. Errors are warning-level — invisible at default `LOG_LEVEL=INFO`.
  - The decompose path constructs a `source_kind` from `source_type` via `_map_source_type_to_kind` (line 122-137) but there is no input validation that a source URI/title is actually present. A chat-style ingest with `metadata={}` still flows through, but `find_or_create_source` may fail to find meaningful dedup keys and create low-quality sources.
- **Impact:** Downstream features that rely on provenance (trust-weighting, `read_source` tool, "where did you learn this?" UX, RBAC-by-source, deletion/right-to-forget) cannot be implemented correctly — the data just isn't there. Anything built on the assumption "every engram has a source" is a bug.
- **Recommendation:** Treat `source_ref_id` as an assertable invariant: (1) make source creation *fatal* (not warning) inside ingestion; if we can't persist a source, we shouldn't persist the engram. (2) Add a one-time backfill: for every engram with `source_ref_id IS NULL`, create a `manual_paste`/`task_output` source from whatever metadata is present (conversation_id, task_id) and link. (3) Add a DB `NOT NULL` constraint on `source_ref_id` once the backfill completes (design decision — may want to relax for `consolidation` source_type). (4) Alert (not just warning-log) on any future `source creation failed` occurrence.
- **Effort:** M

### [P2] Consolidation mutex is a module-level `asyncio.Lock` — safe for the current single-replica deployment but has no cross-process protection if someone ever scales the service

- **Evidence:**
  - `memory-service/app/engram/consolidation.py:36` — `_consolidation_lock = asyncio.Lock()` at module scope.
  - `run_consolidation` at `:94-97` checks `if _consolidation_lock.locked()` and early-returns. Inside the mutex, each phase is wrapped in a nested transaction savepoint (good) and stats are logged at the end.
  - Dockerfile runs uvicorn with a single worker (verified: `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]` — no `--workers` flag), so in practice the mutex works. But any future move to multi-worker uvicorn or horizontal scaling silently gives up the mutex protection; two concurrent consolidation cycles can corrupt edge-weight and importance updates.
  - Also: a crash mid-cycle leaves `_engrams_since_last` untouched (reset only on the success path at :224), so the next restart will not re-trigger the threshold. The mutex itself is process-local so a crash loses it cleanly — no deadlock — but the **audit** of what ran where is lost (`consolidation_log` is only inserted right before commit).
- **Impact:** Not a daily-driver blocker on single-host. Becomes a data-corruption risk if the service ever runs with multiple workers or replicas. The "crash mid-cycle loses the completed-phases audit" is a minor UX issue on restarts.
- **Recommendation:** Swap `_consolidation_lock` for a Redis-based advisory lock (e.g. `SET nova:memory:consolidation_lock nxex 3600`) so protection survives worker scaling. Persist per-phase audit rows as each phase completes so a mid-cycle crash leaves breadcrumbs. Don't block on this now — put it on the "before we horizontal-scale" list.
- **Effort:** S

### [P2] Stale Redis `nova:config:*` keys survive container recreation but there is no "sanity check vs DB" step at orchestrator startup for all keys

- **Evidence:**
  - CLAUDE.md warns explicitly: *"Stale Redis config values survive container restarts. If inference is broken, check `inference.state` and `inference.backend` in Redis before debugging code."*
  - `orchestrator/app/main.py:102-108` does call `sync_llm_config_to_redis`, `sync_inference_config_to_redis`, etc. on startup — good.
  - But `config_sync.py:82-100` (inference sync) explicitly *preserves* Redis values over DB defaults: the docstring says "existing Redis values take precedence over DB defaults. DB values only fill in keys that are missing from Redis." This is on purpose for `inference.*` (recovery service writes runtime overrides) — but it also means a one-time buggy write sticks forever.
  - Observed: Redis currently has `nova:config:inference.backend=none`, `inference.state=stopped`. If these were written during an earlier broken state, they will survive every future restart with no mechanism to verify they still reflect reality.
  - There is no observability — the orchestrator `/health/ready` doesn't list key config values, so a user can't notice drift.
- **Impact:** The exact class of incident CLAUDE.md calls out. The current symptom set (local inference disabled, cloud-only routing) may or may not be the user's intent — but there's no easy path to tell.
- **Recommendation:** Add a `POST /api/v1/admin/config/reconcile` endpoint that walks every `nova:config:*` key and overwrites Redis with the DB's current value, with a dry-run mode. Expose it in the dashboard Settings > Maintenance area. For `inference.*` specifically, add a `drift` field that flags when the Redis override was written more than N hours ago without a matching DB write — lets the user see "your Redis value is stale."
- **Effort:** S

### [P2] `_apply_adaptive_skips` mutates the shared `checkpoint` dict before saving it, creating a subtle race if multiple pipeline retries race

- **Evidence:**
  - `orchestrator/app/pipeline/executor.py:281-286` writes synthetic checkpoint entries into `state.completed` AND `checkpoint` in-memory, then calls `save_checkpoint` in a loop.
  - If two pipeline executions ever race (e.g. reaper re-enqueued a task while the original process was still clearing up, or the Lua `SADD` dedup fails in a degraded Redis), both would inject skips and then call `save_checkpoint`. The DB update is `checkpoint || jsonb_build_object(...)` (line 98 of checkpoint.py), which is a merge — but if one execution set `context` to real output and the other sets `context` to `{"_merged": True}`, the last write wins and the real output is lost.
  - Today, the orchestrator's Lua enqueue dedup prevents double-enqueue; but `queue_worker` (`queue.py:148-173`) fires the pipeline as `asyncio.create_task` with no guard against "same task already in flight on this process". Not a current daily issue (single-process) but fragile.
- **Impact:** Unlikely in normal operation, but possible when the reaper re-enqueues a long-running task whose heartbeat failed (it is also possible for the original execution to keep writing checkpoints after the reaper requeued — and then the new execution overwrites them). Could silently downgrade a completed stage to a "synthetic skip" entry.
- **Recommendation:** Gate pipeline execution on a short-TTL Redis lock per `task_id` before touching any state. The Reaper already owns stale-detection; a lock in `execute_pipeline` prevents two live copies. As a fallback, change the merge in `save_checkpoint` to "only insert if key is absent or has `_merged` flag" so real stage output can never be overwritten by synthetic skip output.
- **Effort:** S

### [P2] Heartbeat TTL (120 s) is LESS than stale threshold (150 s) — by design for slack, but dark corners surface when an LLM call takes 120-150 s

- **Evidence:**
  - `orchestrator/app/config.py:56,61,71` — `task_heartbeat_interval_seconds=30`, `task_stale_seconds=150`, `task_heartbeat_ttl_seconds=120`.
  - `executor.py:1532-1567` — heartbeat loop; on 3 consecutive failures, sets a cancel event so the pipeline aborts.
  - The reaper query (`reaper.py:83-94`) uses `last_heartbeat_at` from the tasks table (DB column updated via `transition_task_status` only), not the Redis heartbeat key. The Redis key TTL is 120 s; the DB column is updated only on status transition. So the reaper is effectively checking "last DB state change". If the Task Agent is running a single LLM call that takes 120-149 s, no DB transition occurs, no heartbeat write to DB happens, and the reaper might trigger a false-positive stale. Looking at the executor, the heartbeat coroutine (`_heartbeat_loop` at executor.py:1532) calls `write_heartbeat` on Redis only — not on the DB. `transition_task_status` (state_machine.py:176) sets `last_heartbeat_at = now()` only when the new status ends with `_running`.
  - That means: while an agent is inside a long LLM call (not transitioning to a new running stage), `last_heartbeat_at` does not advance. 150 s of "silence" triggers the reaper, even though the task is healthy.
- **Impact:** Edge case today (most LLM calls are faster than 150 s), but with reasoning models and large contexts this gets easier to hit. A false-positive reap will re-enqueue the task mid-LLM call, the original pipeline writes a stage checkpoint before crashing, the new pipeline reads it, and both end up writing — potentially confused output. Clock skew between the container and Postgres can shave additional margin.
- **Recommendation:** Make the heartbeat coroutine also update `tasks.last_heartbeat_at` every 30 s (not just on transitions). Or flip the reaper to read Redis heartbeat presence (`EXISTS nova:heartbeat:task:{id}`) instead of the DB column — Redis TTL (120 s) then becomes authoritative, and missing-key means stale. The code already has `is_heartbeat_alive` at `queue.py:87-91` ready to use.
- **Effort:** S

### [P3] `tasks.output = COALESCE($4, output)` in `_pause_for_human_review` can stale-override with an empty preview

- **Evidence:** `orchestrator/app/pipeline/executor.py:1312-1314` — the pause-for-review update uses `output = COALESCE($4, output)`. If `$4` is provided but is `""` (empty string rather than NULL), the existing `output` column is replaced with `""`. Look at the preview builder at `:1291-1308`: it joins parts with `\n\n`; if all parts are empty strings (task result present but all its fields empty), `preview_output` is `""` not `None`. This can overwrite a real prior output.
- **Impact:** Minor; affects pause/resume with empty preview.
- **Recommendation:** Guard: `preview_output = preview_output or None` before the call.
- **Effort:** S

### [P3] `_backfill_outcome_scores` mutates every `usage_events` row whose metadata task_id matches — unindexed on `metadata->>'task_id'`

- **Evidence:** `executor.py:1723-1745` runs after every successful pipeline. `UPDATE usage_events SET outcome_score = ... WHERE metadata->>'task_id' = $1`. `usage_events` is a high-volume table (every LLM call). No expression index on `metadata->>'task_id'` in any migration. Full-table scan per successful task.
- **Impact:** On a system with heavy usage history, every pipeline completion triggers a DB scan proportional to total `usage_events`. Visible as tail latency on task completion.
- **Recommendation:** Add a partial expression index: `CREATE INDEX idx_usage_events_task_id ON usage_events((metadata->>'task_id')) WHERE metadata->>'task_id' IS NOT NULL;`.
- **Effort:** S

---

## Summary

- **The reaper is actively stuck in a log-spamming loop** on 9 live tasks (4 from 13 days ago) because the state machine rejects `task_running → queued`. This is the exact "stale `task_running` surviving restart" incident called out in the audit brief, and it's happening right now. P0 small fix.
- **Backups silently exclude `/data/sources/` filesystem content.** `make backup` produces an archive that `make restore` can't fully restore — any source > ~100 KB leaves a `content_path` row with a missing file post-restore. The Recovery UI promises reliability it doesn't deliver. P0 small fix.
- **Engram ingestion can silently lose payloads on crash.** `BRPOP` removes the item before decomposition; no at-least-once recovery path. Chat is recoverable by retype; intel and knowledge crawls are not. P0 medium fix (use `BLMOVE` + processing list).
- **Provenance is aspirational, not enforced.** 99% of live engrams lack `source_ref_id`, making source-based features (trust weighting, deletion, "where did you learn this") unimplementable on current data. P1 medium fix with backfill.
- **Reliability invariants the codebase asserts in CLAUDE.md aren't validated anywhere.** `close_redis()` in every lifespan — violated by memory-service and llm-gateway. Every-engram-has-a-source — violated by 99%. Migration idempotency — not tested. A few lightweight CI checks would catch all three.
