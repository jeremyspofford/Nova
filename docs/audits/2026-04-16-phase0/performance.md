# Performance Audit — 2026-04-16

## Scope

Reviewed: container memory/CPU footprint (live `docker stats`), DB query shape across `orchestrator/app/`, `memory-service/app/`, `cortex/`, `knowledge-worker/`, engram spreading-activation CTE cost, consolidation cycle cost, cold-start timings from live container logs, frontend bundle composition under `dashboard/dist/assets/`, SSE streaming paths, and Neural Router training behaviour.

Out of scope: micro-optimisation of hot loops, distributed-scaling concerns, GPU overlay behaviour. Tier-1 streaming-chat work from `2026-03-17-performance-optimization-design.md` is already partially landed (`skip_tool_preresolution=True` at `orchestrator/app/router.py:284` and `:497`), so those items are not restated as findings.

Live observations (snapshot during audit):
- 6,462 engrams, 79,117 edges, 34 sources, 19,765 usage events, 8,283 retrieval-log rows, DB total 232 MB
- All services healthy; no queue backlog
- Ollama `stopped` / `cloud-only` routing → every embedding is a Gemini round-trip

---

## Findings

### [P0] `/api/v1/engrams/context` takes 6–14 s per call — blocks every chat message

- **Evidence:** Live timing (two consecutive calls) on `http://localhost:8002/api/v1/engrams/context`:
  - Cold call: 13.76 s
  - Warm call: 6.08 s
  Code path `memory-service/app/engram/working_memory.py:74-264` (`assemble_context`) calls: `get_self_model_summary` → `_get_active_goal` → `spreading_activation` → optional `neural_rerank` → `_semantic_dedup` → `_find_clusters` → `reconstruct` (which can fire `_narrative_reconstruct` LLM call at `reconstruction.py:310`) → `_get_sticky_decisions` → `_get_open_threads`. `get_embedding` is invoked at least twice (once in activation, once in `log_retrieval`) and is currently falling back to cloud Gemini per call (see P0 on Ollama fallback). The spec at `2026-03-17-performance-optimization-design.md#3.3` calls out "memory context pre-warming" but the cache is not implemented in `orchestrator/app/agents/runner.py`.
- **Impact:** This is the single largest fixed latency on every chat turn. Daily-driver users wait 6–14 s before the LLM even starts. Tier-1 streaming work that eliminated pre-resolution is largely negated by this call sitting on the critical path.
- **Recommendation:** (1) Memoise `self_model` / `active_goal` in-process with a 60 s TTL — they change only during consolidation. (2) Pre-warm memory context per session in Redis (`nova:memory_cache:{session_id}`, 60 s TTL) as designed in spec 3.3. (3) Short-circuit `_narrative_reconstruct` below 3 engrams per cluster (template is sufficient). (4) Dedupe the two `get_embedding(query)` calls in `assemble_context` — the query embedding is computed inside `spreading_activation` and then recomputed for `log_retrieval` at `working_memory.py:204`.
- **Effort:** M

### [P0] Embedding provider falls back to cloud Gemini on every call

- **Evidence:** Redis runtime config: `nova:config:inference.backend=none`, `inference.state=stopped`, `llm.routing_strategy=cloud-only`. `memory-service/app/embedding.py:170` logs `Using fallback embedding model: gemini-embedding-001`. The tail of `memory-service` logs shows 194 occurrences of "fallback embedding model" in the most recent 300 lines alone — every ingestion, every query, every clustering run. Each call is an HTTP round-trip to Gemini (~150–250 ms). In the consolidation window of 68 s, log timestamps show an embedding call roughly every 200 ms.
- **Impact:** Every engram write, every context fetch, every consolidation phase, every ingestion event incurs a cloud embedding round-trip. This is the root cause of the P0 `/context` latency above and of the P0 consolidation duration below. It also sends content to a cloud provider even when the user would expect local-only behaviour.
- **Recommendation:** Detect the no-local-inference state at startup and warn loudly; run a local embedding model (nomic-embed-text in a containerised Ollama, or the `sentence-transformers` path) as an in-memory-service fallback that does not require LLM-gateway; and/or batch all embedding calls in the consolidation/ingestion hot path with `get_embeddings_batch()` which already exists at `memory-service/app/embedding.py:83` but is not called from consolidation, ingestion, or clustering.
- **Effort:** M

### [P0] Consolidation cycle runs 65–110 s and stalls memory-service threads

- **Evidence:** `consolidation_log` table samples:

  ```
  trigger | reviewed | topics | merged | duration_ms
  idle    |        5 |      6 |     20 |       68541
  idle    |        3 |      2 |     20 |       98334
  idle    |      349 |      7 |     20 |       86187
  idle    |      368 |      8 |     20 |       88113
  ...
  ```

  Every single entry over the last 15 cycles runs 65–112 s. The 2026-04-17 02:34 cycle took 68.5 s while reviewing only 5 engrams. The lock at `memory-service/app/engram/consolidation.py:36` (`_consolidation_lock`) holds a single `AsyncSession` open for the full duration (`consolidation.py:114-222`). All six phases share that session. Phase 2 (`_extract_patterns`) loops over entities and issues one embedding-similarity `SELECT` per source engram inside the coherence gate (`consolidation.py:313-320`) — `O(entities × sources)` serial DB round-trips. Phase 2.5 (`clustering.py`) runs UMAP + HDBSCAN + per-cluster LLM naming; Phase 2.5's `assign_new_engrams_to_topics` at `clustering.py:451-462` runs `O(unassigned × topics)` separate round-trip similarity queries to compute cosine sim one pair at a time instead of a single JOIN.
- **Impact:** While consolidation runs, the same engine pool (`memory-service/app/db/database.py:18`) is also serving `/context` calls. The one-minute-granularity trigger in `consolidation_loop()` means a 68 s cycle consumes a connection for most of that minute. Concurrent chat calls see the DB pool exhausted or the embedding cache evicted. Idle trigger fires every 30 min but each fire blocks for >1 min.
- **Recommendation:** (1) Replace the `SELECT ... WHERE id = :id` loops in Phase 2 with a single `SELECT embedding FROM engrams WHERE id = ANY(...)` + one set-returning similarity computation. (2) Collapse `assign_new_engrams_to_topics` to a single correlated query that ranks topics by centroid similarity in SQL, not Python. (3) Run consolidation in its own connection pool or even its own worker process so it cannot starve the serving path. (4) Batch all `get_embedding` calls inside a phase via `get_embeddings_batch`.
- **Effort:** L

### [P1] Spreading-activation CTE has no tenant filter on the recursive step

- **Evidence:** `memory-service/app/engram/activation.py:79-177`. The recursive anchor correctly filters by `tenant_id = :tenant_id` at lines 100 and 127, but the recursive step at lines 137-152 joins `engram_edges` and the neighbor `engrams` with no tenant predicate. When multi-tenancy actually ships, activation can and will cross tenants by following an edge across the boundary. Separately, the recursive step scans `engram_edges` twice (once with `edge.source_id = spread.id`, once with `edge.target_id = spread.id`) via an `OR` join — the planner cannot use the index-per-direction cleanly, and a UNION-ALL of two recursive branches is ~2× cheaper on large graphs. With 79K edges today it is fast (activation endpoint measured sub-second); at 1M edges the planner cost explodes.
- **Impact:** Pre-multi-tenant, no correctness hit; post-multi-tenant, a privacy leak. The perf cost today is small but grows superlinearly with edge count.
- **Recommendation:** Add `AND neighbor.tenant_id = CAST(:tenant_id AS uuid)` to the recursive step. Rewrite the `OR` join as two separate anchors / UNION ALL arms so the planner uses `idx_edges_source` and `idx_edges_target` independently. Consider capping per-hop breadth (`LIMIT 50` per hop) before multi-tenant scale.
- **Effort:** S

### [P1] Dashboard main bundle is 2.9 MB, no route code-splitting

- **Evidence:** `dashboard/dist/assets/index-uirgZuxE.js` is 2,906,406 bytes. `dashboard/src/App.tsx:17-36` eagerly imports every page: Chat, Usage, Integrations, Settings, Models, Tasks, Pods, Goals, Sources, Recovery, About, AIQuality, UserProfile, Users, Invite, Expired, Friction, Brain, OnboardingWizard, ComponentGallery. Only `Editor` and `Editors` are `React.lazy()` (App.tsx:39-40). That means every first load pays for:
  - `three` + `3d-force-graph` (Brain) — `node_modules/three` is 38 MB of source; the minified bundle keeps a very large share
  - `recharts` (Usage) — ~200 KB
  - `react-markdown` + `rehype-highlight` (Chat, Tasks, FileViewer) — ~200 KB + highlight.js
  - `mermaid` is `await import('mermaid')` at `components/ArtifactRenderer.tsx:34` (correctly lazy)
  - Additional chunks like `cytoscape.esm-CyJtwmzi.js` (442 KB) and `mermaid.core-DvKBwqde.js` (437 KB) are code-split but only load on demand — good.
  The 2026-03-28 Brain instanced-rendering spec assumes Brain can be a feature flag with route-level code splitting (`React.lazy`); the flag and the lazy import were never wired.
- **Impact:** First page load downloads three.js, recharts, markdown, and the full page graph for users who will only ever open `/chat`. On slower links (mobile, Tailscale from off-LAN) this is measurable page-load pain.
- **Recommendation:** Convert Brain, Usage, Tasks, AIQuality, Goals, Pods, Models, Users, Friction, Sources, Recovery, OnboardingWizard to `React.lazy()` with `<Suspense>` fallbacks. Verify with `vite build --mode=production` that no route pulls three/recharts unless the route opens. Add a Vite `rollupOptions.output.manualChunks` for three and recharts so they're stable vendor chunks.
- **Effort:** S

### [P1] Topic regeneration in consolidation does per-member embedding parse in Python

- **Evidence:** `memory-service/app/engram/clustering.py:534-553` and `clustering.py:258-275`. Inside `maintain_topics` and `_create_topic_engram`, the code does `SELECT embedding::text FROM engrams WHERE id = ANY(...)` then parses each pgvector text blob in Python (`float(x) for x in vec_str.split(",")`) before calling `np.mean`. Each embedding is 768 halfvec → 768 float32 parses per row. With a topic of 20 members, that's 15,360 `float()` calls per topic per regeneration pass, plus `numpy` allocation. A single SQL `avg(embedding)` is not supported by pgvector halfvec, but the list-parse in Python is roughly 20–50× slower than fetching the embedding once as bytes and feeding to numpy frombuffer.
- **Impact:** Adds seconds per consolidation cycle (small cost individually, large on the hot path). Also silently compounds whenever cortex or ingestion triggers `assign_new_engrams_to_topics`.
- **Recommendation:** Fetch the halfvec binary directly (`SELECT embedding FROM ... ` and use the pgvector Python driver instead of stringly-typed parsing), or precompute and store centroids in a dedicated table so regen reads one row. Either way stop re-parsing text vectors in a Python loop.
- **Effort:** S

### [P1] Dashboard `fields=minimal` graph API parameter was designed but not implemented

- **Evidence:** The 2026-03-28 Brain spec specified a `fields=minimal` query on `/api/v1/engrams/graph`. Live test:
  ```
  curl /api/v1/engrams/graph                 → 27,615 bytes, activation/access_count/confidence present
  curl /api/v1/engrams/graph?fields=minimal  → 27,615 bytes (identical), all fields still present
  ```
  `grep -n 'fields' memory-service/app/engram/router.py` finds no matches. The full-node payload ships on every Brain load even though the spec projected a 50–60% payload reduction.
- **Impact:** Larger initial Brain payload, larger JS parse cost. Minor today (27 KB) but grows linearly with graph size — at 10 K nodes this becomes hundreds of KB of unused fields per load.
- **Recommendation:** Implement the `fields=minimal` branch as specified — conditional SELECT list, truncated content, drop `activation/access_count/confidence/created_at/source_type`. Update `GraphNode` TS interface optional. This is exactly the spec's design point 1.
- **Effort:** S

### [P1] Postgres is running on out-of-the-box defaults; `shared_buffers=128MB`, `work_mem=4MB`

- **Evidence:** Live `pg_settings`:
  ```
  shared_buffers       | 16384    (128 MB)
  effective_cache_size | 524288   (4 GB)
  work_mem             | 4096     (4 MB)
  max_connections      | 100
  ```
  No `postgresql.conf` override is mounted in `docker-compose.yml` — we inherit the pgvector image's defaults. Database is already 232 MB (larger than `shared_buffers`); `embedding_cache` alone is 48 MB. HNSW index scans on `engrams` (1107 shared hits in EXPLAIN on a simple top-20 similarity query) fit in shared buffers today but won't once the graph grows.
- **Impact:** Once the engram graph crosses ~50 K engrams (engrams table doubles in size), HNSW queries will start hitting disk instead of buffers, and sort-heavy consolidation phases will spill to disk at `work_mem=4MB`. Today this is latent; at the planned daily-driver scale it becomes the bottleneck.
- **Recommendation:** Mount a `postgresql.conf` with `shared_buffers=512MB`, `effective_cache_size=4GB`, `work_mem=16MB`, `maintenance_work_mem=256MB`, `max_parallel_workers_per_gather=2`. These are conservative for a 16 GB WSL2 host. Also schedule `VACUUM ANALYZE engrams` after consolidation; `n_dead_tup=697` on engrams with `last_autoanalyze` two hours ago means HNSW scans are already walking through 700 dead rows.
- **Effort:** S

### [P2] MCP server spawn on orchestrator startup adds ~22 s cold start

- **Evidence:** Live orchestrator log timeline:
  ```
  01:32:43.294  Uvicorn running (port 8000)
  01:32:44.312  MCP server 'puppeteer' spawned (pid=14)
  01:32:50.902  MCP server 'firecrawl': discovered 12 tool(s)   (+6.6s from spawn)
  01:33:06.184  MCP server 'puppeteer':  discovered 7 tool(s)   (+21.9s from spawn)
  01:33:06.193  Queue worker, reaper, effectiveness loop, ... started
  ```
  Startup is blocked waiting for both MCP subprocesses to finish tool discovery. Puppeteer alone took 22 seconds (starting Chrome). The stack takes ~23 s before the queue worker runs.
- **Impact:** Every restart of orchestrator causes ~25 s of "services up but queue dead" window. The reaper (150 s stale-task timeout) and heartbeat (30 s) don't fire until then. User-perceived cold start of "did my chat just lose its message" is long enough to be noticed.
- **Recommendation:** Spawn MCP servers non-blocking (`asyncio.create_task`) and let them register tools as they discover. Queue worker, reaper, and health endpoints should come up immediately. Add `/health/ready` rollup that reports MCP discovery state but doesn't block overall readiness on it.
- **Effort:** S

### [P2] `retrieval_log` grows unbounded (8,283 rows, no TTL)

- **Evidence:** `retrieval_log` is written on every `/context` call (`working_memory.py:204`) and is already 21 MB / 8283 rows. The only consumer is the Neural Router training job (`neural_router/train.py:60-72`) which caps reads at `max_training_obs` rows. There is no delete/archive path in the codebase (no `DELETE FROM retrieval_log` anywhere). On a daily-driver with hundreds of chat messages per day, this table will cross 1 M rows inside a year.
- **Impact:** DB growth, larger backups, slower Neural Router training queries. Not urgent today but becomes silent bloat.
- **Recommendation:** Add a cleanup step to consolidation Phase 5b: `DELETE FROM retrieval_log WHERE created_at < NOW() - INTERVAL '90 days' AND engrams_used IS NOT NULL`. Keep the unlabeled (possibly still-training) rows longer.
- **Effort:** S

### [P2] Neural Router precision@20 is perfectly 1.0000 — it isn't actually learning

- **Evidence:** `neural-router-trainer` logs:
  ```
  01:50:32 Validation precision@20: 1.0000
  02:17:44 Validation precision@20: 1.0000
  ```
  Two consecutive training runs on 13,347 then 12,958 examples both hit perfect validation precision. That is a hallmark of label leakage or a trivially separable task. Inspection of `neural_router/train.py:63-68`: training rows include `engrams_surfaced` and `engrams_used`, and the model is given both the query embedding and the candidate engram embedding — positive and negative labels come from the same row. With only "surfaced-and-used" positives vs. "surfaced-not-used" negatives in a context where the surfaced set is already a perfectly correlated top-K by cosine similarity, the re-ranker learns the input ordering, not new signal. Perfect precision at both runs means the router is a no-op in production but will still carry an inference cost per `/context` call when the model is loaded (`working_memory.py:102-199`).
- **Impact:** Wasted CPU on reranking that doesn't change order; false confidence in the "it's working" signal; will never surface genuinely novel engrams because the learned ranker just reflects cosine sim.
- **Recommendation:** Hold out a tenant-level time-split evaluation where `precision@K` is against user-observed outcome, not training-mode "was this surfaced and used". Validate by intentionally withholding 20 % of sessions at training time and measuring on those. If the 1.0000 persists after a proper holdout, the task is degenerate and the router should be gated off until the feature design is fixed.
- **Effort:** M

### [P2] `assemble_context` serialises `_get_active_goal`, `_get_sticky_decisions`, `_get_open_threads` behind `spreading_activation`

- **Evidence:** `memory-service/app/engram/working_memory.py:88-264`. Four of the six section-fetchers (`self_model`, `active_goal`, `sticky_decisions`, `open_threads`) are independent of the query and independent of activation, yet they run sequentially around the expensive activation call. Each is a straightforward SQL query. `asyncio.gather` is not used anywhere in this function.
- **Impact:** Adds 100–300 ms of avoidable serial DB latency per call on top of the already-slow activation/reconstruct path.
- **Recommendation:** Run `self_model`, `active_goal`, `sticky_decisions`, `open_threads`, plus the `spreading_activation` call concurrently via `asyncio.gather`. All are read-only and share no state.
- **Effort:** S

### [P3] `memory-service` steady-state RSS is 606 MB on an idle stack

- **Evidence:** `docker stats` snapshot:
  ```
  nova-memory-service-1          606.5 MiB
  nova-orchestrator-1            556.9 MiB
  nova-llm-gateway-1             320.0 MiB
  nova-neural-router-trainer-1   238.8 MiB  (46% of 512MiB hard cap)
  nova-postgres-1                311.4 MiB
  ```
  Memory-service imports `numpy`, `sklearn.cluster.HDBSCAN`, `umap-learn`, `torch` (via neural_router), plus SQLAlchemy async machinery. Much of it is statically loaded at import time even when consolidation isn't running. Orchestrator holds SQL-schema metadata, MCP client subprocesses, LiteLLM, and the full pipeline registry.
- **Impact:** Not a current pain (15 GB host), but pushes toward the planned mobile/Tailscale deployment story where a smaller footprint matters, and means trying to run the stack on a 4 GB SBC would fail.
- **Recommendation:** Lazy-import sklearn/umap/torch inside the consolidation and neural_router paths so they're loaded only when the feature fires. Verify with `memory_profiler` post-change.
- **Effort:** S

---

## Summary

- The two dominating perf problems are both on the chat critical path: `/context` takes 6–14 s per message, and its underlying embedding calls go to cloud Gemini because Ollama is stopped and the routing strategy is `cloud-only`. Either alone is a daily-driver blocker; together they multiply.
- Consolidation is the slowest background job in the stack at 65–110 s per cycle, mostly because of N+1 embedding-similarity round-trips and cloud-embedding fallback. It holds a DB session for the full cycle, which means chat latency spikes when it fires.
- Frontend bundle is 2.9 MB because only two of ~20 routes are lazy. Memory (`fields=minimal`) and Brain (instanced-rendering flag, lazy route) designs exist on paper but aren't wired.
- Postgres is on out-of-the-box defaults; HNSW queries and consolidation sorts will start spilling once the graph crosses ~50 K engrams.
- Neural Router's perfect precision@20 on consecutive runs indicates it isn't learning anything useful — it's adding inference cost without improving retrieval.
