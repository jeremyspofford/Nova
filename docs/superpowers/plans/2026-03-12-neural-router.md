# Neural Router ML Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a learned re-ranker that personalizes engram retrieval per user, auto-improving as usage data accumulates. Three modes: cosine-only (0-199 obs), scalar NN (200-999), embedding NN (1000+).

**Architecture:** NN re-ranker on top of spreading activation candidates. Separate training container (shared image, different entrypoint) trains on `retrieval_log` observations via Redis BRPOP signals. Model weights stored in PostgreSQL, loaded by memory-service background task. Integration point is `assemble_context()` in `working_memory.py`, not inside `spreading_activation()`.

**Tech Stack:** PyTorch (CPU-only), FastAPI, PostgreSQL + pgvector, Redis (db6), SQLAlchemy async, Docker Compose

**Spec:** `docs/superpowers/specs/2026-03-12-neural-router-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|---|---|
| `memory-service/app/engram/neural_router/__init__.py` | Package init, exports `ENGRAM_TYPES` constant |
| `memory-service/app/engram/neural_router/model.py` | PyTorch model definitions: `ScalarReranker`, `EmbeddingReranker` |
| `memory-service/app/engram/neural_router/features.py` | Feature extraction: candidate dict to tensor. `extract_scalar_features()`, `extract_embedding_features()` |
| `memory-service/app/engram/neural_router/serve.py` | Model loading from PostgreSQL, caching, `neural_rerank()` function, background refresh loop |
| `memory-service/app/engram/neural_router/train.py` | Training loop, data assembly, validation gate, BRPOP listener, startup probe, model retention. Entrypoint for training container. |

### Modified Files

| File | Change |
|---|---|
| `memory-service/app/db/schema.sql` | Add `neural_router_models` table, add `tenant_id` + indexes to `retrieval_log` |
| `memory-service/app/config.py` | Add 12 neural router settings |
| `memory-service/app/engram/retrieval_logger.py` | Add `tenant_id` param, store `time_of_day` as float, emit Redis train signal, wire `log_retrieval()` call |
| `memory-service/app/engram/working_memory.py` | Call `log_retrieval()` after activation, call `neural_rerank()` before reconstruction, widen seed/result counts |
| `memory-service/app/engram/router.py` | Add `POST /mark-used` endpoint, extend `GET /router-status` with mode/model/accuracy |
| `memory-service/app/main.py` | Add background task for model refresh loop |
| `memory-service/pyproject.toml` | Add `torch` CPU-only dependency |
| `orchestrator/app/agents/runner.py` | Add engram mark-used callback after LLM response |
| `docker-compose.yml` | Add `neural-router-trainer` service |

---

## Chunk 1: Schema, Config & Retrieval Logger Fixes

### Task 1: Add `neural_router_models` table and `retrieval_log` changes to schema.sql

**Files:**
- Modify: `memory-service/app/db/schema.sql`

- [ ] **Step 1: Add neural_router_models table and retrieval_log changes**

Append after line 179 (end of file) in `memory-service/app/db/schema.sql`:

```sql
-- Neural Router: learned re-ranker model storage
CREATE TABLE IF NOT EXISTS neural_router_models (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    architecture            TEXT NOT NULL,
    weights                 BYTEA NOT NULL,
    observation_count       INTEGER NOT NULL,
    validation_precision_at_k REAL,
    is_active               BOOLEAN NOT NULL DEFAULT FALSE,
    trained_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nrm_tenant_active
    ON neural_router_models(tenant_id) WHERE is_active;

-- Neural Router: add tenant_id to retrieval_log for per-tenant observation counts
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS tenant_id UUID
    NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
CREATE INDEX IF NOT EXISTS idx_retrieval_log_tenant ON retrieval_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_log_used ON retrieval_log(tenant_id)
    WHERE engrams_used IS NOT NULL;
```

- [ ] **Step 2: Verify SQL reads correctly**

Run: `python3 -c "print('Schema file ends at line:', len(open('memory-service/app/db/schema.sql').readlines()))"`

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/db/schema.sql
git commit -m "feat: add neural_router_models table and retrieval_log tenant_id"
```

---

### Task 2: Add neural router config settings

**Files:**
- Modify: `memory-service/app/config.py`

- [ ] **Step 1: Add neural router settings after line 60 (after Phase 4 block)**

Insert after the `engram_merge_similarity_threshold` line (line 60):

```python
    # Engram Network (Phase 5: Neural Router)
    neural_router_enabled: bool = True
    neural_router_min_observations: int = 200
    neural_router_embedding_threshold: int = 1000
    neural_router_retrain_every: int = 50
    neural_router_candidate_count: int = 50
    neural_router_seed_count: int = 30
    neural_router_model_check_interval: int = 60
    neural_router_training_epochs: int = 20
    neural_router_learning_rate: float = 1e-3
    neural_router_validation_split: float = 0.2
    neural_router_min_precision_gain: float = 0.0
    neural_router_max_inactive_models: int = 5
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/config.py', doraise=True); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/config.py
git commit -m "feat: add neural router config settings (Phase 5)"
```

---

### Task 3: Fix retrieval_logger with tenant_id, float time, and train signal

**Files:**
- Modify: `memory-service/app/engram/retrieval_logger.py`

- [ ] **Step 1: Rewrite retrieval_logger.py with all fixes**

Replace the entire file content. Key changes:
- `log_retrieval()` accepts `tenant_id` param and stores it
- `time_of_day` stored as normalized float (`hour/24 + minute/1440`) not string
- `get_observation_count()` filters by `tenant_id`
- New `get_labeled_observation_count()` for training readiness
- New `_maybe_emit_train_signal()` emits Redis signal on db6 when observation threshold crossed

The full replacement code includes all these changes plus a Redis client helper for db6. See spec Section 2 for the trigger mechanism details.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/engram/retrieval_logger.py', doraise=True); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/engram/retrieval_logger.py
git commit -m "feat: add tenant_id, float time_of_day, and train signal to retrieval logger"
```

---

## Chunk 2: PyTorch Model Definitions & Feature Extraction

### Task 4: Create neural_router package with model definitions

**Files:**
- Create: `memory-service/app/engram/neural_router/__init__.py`
- Create: `memory-service/app/engram/neural_router/model.py`

- [ ] **Step 1: Create package init with ENGRAM_TYPES constant**

8 types matching the engrams table: fact, episode, entity, preference, procedure, schema, goal, self_model

- [ ] **Step 2: Create model.py with ScalarReranker and EmbeddingReranker**

`ScalarReranker`: Input(25) -> Linear(64) -> ReLU -> Linear(32) -> ReLU -> Linear(1) -> Sigmoid
`EmbeddingReranker`: Adds two projection layers (768->32 each), computes dot product + difference, concatenates with scalar features (25 + 1 + 32 = 58 combined dim), then same MLP structure.

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/engram/neural_router/__init__.py', doraise=True); py_compile.compile('memory-service/app/engram/neural_router/model.py', doraise=True); print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add memory-service/app/engram/neural_router/
git commit -m "feat: add PyTorch model definitions for Neural Router (scalar + embedding)"
```

---

### Task 5: Create feature extraction module

**Files:**
- Create: `memory-service/app/engram/neural_router/features.py`

- [ ] **Step 1: Create features.py with extract_scalar_features() and extract_embedding_features()**

`extract_scalar_features()`: Takes list of candidate dicts + temporal context, returns (n_candidates, 25) float tensor.
Feature order: cosine(1), importance(1), activation(1), recency(1), type_onehot(8), time_of_day(1), day_onehot(7), has_goal(1), convergence(1), outcome_avg(1), outcome_count(1).

`extract_embedding_features()`: Takes query embedding + list of candidate embeddings, returns (query_tensor, engram_tensor) both shape (n, 768).

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/engram/neural_router/features.py', doraise=True); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/engram/neural_router/features.py
git commit -m "feat: add feature extraction for Neural Router re-ranker"
```

---

## Chunk 3: Training Pipeline

### Task 6: Create training pipeline with BRPOP listener

**Files:**
- Create: `memory-service/app/engram/neural_router/train.py`

- [ ] **Step 1: Create train.py with full training pipeline**

Key components:
- `assemble_training_data(tenant_id)`: Fetches labeled retrieval_log rows, joins with engram metadata, builds training examples with scalar features + labels (1 if engram was in engrams_used, 0 otherwise). Handles legacy string time_of_day format.
- `train_model(examples, obs_count)`: Architecture gate (scalar if < 1000 obs, embedding otherwise). Adam optimizer with L2 weight decay. BCE loss. Early stopping (patience=3). Returns (model, arch_name, precision_at_k).
- `_precision_at_k(scores, labels, k=20)`: Validation metric.
- `save_model(...)`: Serializes via `torch.save(state_dict)`, stores in PostgreSQL. Atomically swaps active model if new precision >= current. Enforces retention policy (last N inactive per tenant).
- `startup_probe()`: On startup, checks for tenants with >= min_observations but no active model. Enqueues synthetic train signal.
- `main_loop()`: BRPOP on `neural_router:train_signal` (Redis db6), calls `train_for_tenant()` for each signal.
- `__main__` block: Runs schema migrations then enters main_loop.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/engram/neural_router/train.py', doraise=True); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/engram/neural_router/train.py
git commit -m "feat: add Neural Router training pipeline with BRPOP listener"
```

---

## Chunk 4: Serving & Integration

### Task 7: Create serving module (model loading + reranking)

**Files:**
- Create: `memory-service/app/engram/neural_router/serve.py`

- [ ] **Step 1: Create serve.py**

Key components:
- Module-level cache: `_cached_model`, `_cached_arch`, `_cached_trained_at`, `_cached_tenant_id`
- `load_latest_model(session, tenant_id)`: Queries `neural_router_models` for active model, skips if already cached. Deserializes with `torch.load(buf, weights_only=True)` (security requirement). Sets model to `.eval()` mode.
- `get_cached_model()`: Returns `(model, arch)` or `(None, None)`.
- `neural_rerank(candidates, ...)`: If no model or disabled, returns candidates unchanged. Otherwise extracts features, runs forward pass, sorts by score, returns top max_results. Catches all exceptions and falls back to un-reranked results.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('memory-service/app/engram/neural_router/serve.py', doraise=True); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add memory-service/app/engram/neural_router/serve.py
git commit -m "feat: add Neural Router serving module (model loading + re-ranking)"
```

---

### Task 8: Wire neural router into working_memory.py and main.py

**Files:**
- Modify: `memory-service/app/engram/working_memory.py`
- Modify: `memory-service/app/main.py`
- Modify: `memory-service/app/engram/router.py`

- [ ] **Step 1: Add imports to working_memory.py**

Add `from datetime import datetime, timezone`, `from .neural_router.serve import get_cached_model, neural_rerank`, and `from .retrieval_logger import log_retrieval`.

- [ ] **Step 2: Add `retrieval_log_id` field to WorkingMemoryContext dataclass**

- [ ] **Step 3: Rewrite the activation section of assemble_context()**

Replace the simple `spreading_activation(session, query)` call with:
1. Check if neural router model is cached
2. If model exists: widen seed_count to `settings.neural_router_seed_count` and max_results to `settings.neural_router_candidate_count`
3. Run spreading_activation with widened params
4. If model exists: convert ActivatedEngram list to dicts, call `neural_rerank()`, convert back to ActivatedEngram list
5. Call `log_retrieval()` to record the observation for training
6. Proceed to reconstruction

- [ ] **Step 4: Add retrieval_log_id to /context response in router.py**

- [ ] **Step 5: Add model refresh background task to main.py**

New `_neural_router_refresh()` async function that loops every `settings.neural_router_model_check_interval` seconds, calling `load_latest_model()`. Register as `asyncio.create_task()` in lifespan, cancel on shutdown.

- [ ] **Step 6: Verify syntax of all changed files**

Run py_compile on working_memory.py, router.py, and main.py.

- [ ] **Step 7: Commit**

```bash
git add memory-service/app/engram/working_memory.py memory-service/app/engram/router.py memory-service/app/main.py
git commit -m "feat: wire neural router into working memory assembly and model refresh loop"
```

---

### Task 9: Update router-status endpoint and add mark-used endpoint

**Files:**
- Modify: `memory-service/app/engram/router.py`

- [ ] **Step 1: Add imports for get_cached_model, get_labeled_observation_count, mark_engrams_used**

- [ ] **Step 2: Replace router_status endpoint**

Return: observation_count, labeled_count, mode (cosine_only/scalar_reranker/embedding_reranker), model_loaded, architecture, ready_for_training, message.

- [ ] **Step 3: Add POST /mark-used endpoint**

Accepts `retrieval_log_id` and `engram_ids_used` (Body params). Calls `mark_engrams_used()` then commits.

- [ ] **Step 4: Verify syntax**

- [ ] **Step 5: Commit**

```bash
git add memory-service/app/engram/router.py
git commit -m "feat: extend router-status with mode/model info, add mark-used endpoint"
```

---

## Chunk 5: Orchestrator Callback & Infrastructure

### Task 10: Add engram mark-used callback to orchestrator runner

**Files:**
- Modify: `orchestrator/app/agents/runner.py`

- [ ] **Step 1: Add _mark_engrams_used() helper**

After `_store_exchange()`. Calls `POST /api/v1/engrams/mark-used` on memory-service with retrieval_log_id and engram_ids. Fire-and-forget with try/except (failure is safe - just means fewer training labels).

Initial heuristic: mark ALL context engrams as used. This is a coarse but functional signal. The NN learns "these engrams were selected for context" which is still valuable. Refinement (LLM response analysis) can be added later.

- [ ] **Step 2: Update _get_memory_context to return retrieval_log_id (4-tuple)**

Change return type to `tuple[str, int, list[str], str | None]`. Extract `retrieval_log_id` from response JSON.

- [ ] **Step 3: Update both callers (non-streaming and streaming paths)**

Destructure the 4th element. Add `_retrieval_log_id` variable. Call `_mark_engrams_used()` after `_store_exchange()` in both paths.

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('orchestrator/app/agents/runner.py', doraise=True); print('OK')"`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/agents/runner.py
git commit -m "feat: add engram mark-used callback after LLM response"
```

---

### Task 11: Add PyTorch dependency and training container

**Files:**
- Modify: `memory-service/pyproject.toml`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add torch to pyproject.toml dependencies**

Add `"torch>=2.0,<3.0"` to the dependencies list.

- [ ] **Step 2: Add neural-router-trainer service to docker-compose.yml**

After the memory-service block. Uses same build context + Dockerfile. Command: `python -m app.engram.neural_router.train`. Environment: DATABASE_URL, REDIS_URL=redis://redis:6379/6, LLM_GATEWAY_URL, LOG_LEVEL. Depends on postgres + redis. Resource limits: 1 CPU, 512M RAM.

- [ ] **Step 3: Commit**

```bash
git add memory-service/pyproject.toml docker-compose.yml
git commit -m "feat: add PyTorch dependency and neural-router-trainer container"
```

---

## Chunk 6: Verification

### Task 12: Full verification pass

- [ ] **Step 1: Verify all Python files compile**

Run py_compile on all .py files in memory-service/app/ and orchestrator/app/.

- [ ] **Step 2: Verify no dangling imports to deleted old memory files**

Grep for old imports that should no longer exist.

- [ ] **Step 3: Verify dashboard builds**

Run: `cd dashboard && npm run build`

- [ ] **Step 4: Push to main**

Run: `git push origin main`
