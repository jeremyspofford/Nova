# Neural Router ML Pipeline — Design Spec

> Learned re-ranker that personalizes memory retrieval per user. Sits on top of cosine similarity + spreading activation. Automatically improves as usage data accumulates.

---

## 1. System Overview

The Neural Router is a **learned re-ranker** on top of spreading activation. It doesn't replace cosine similarity or graph traversal — it learns which results matter most to each user based on their actual usage patterns.

### Lifecycle (per tenant)

| Observations | Mode | Behavior |
|---|---|---|
| 0–199 | `cosine_only` | Current system unchanged. 10 seeds, spread, top 20. Observations logged. |
| 200–999 | `scalar_reranker` | 30 seeds, spread, ~50 candidates, NN re-ranks using scalar features, top 20. |
| 1000+ | `embedding_reranker` | Same flow, but NN adds embedding projection layers (768→32) for richer query-engram interaction. |

Mode transitions are automatic based on observation count. No manual cutover, no config flag.

### Data Flow

```
Query → Embedding → Cosine top-30 seeds → 3-hop spread → ~50 candidates
                                                              ↓
                                              Neural Router re-ranks (if trained model exists)
                                                              ↓
                                                    Top 20 → Working Memory Gate
```

When no trained model exists (new user, <200 observations), the re-ranking step is skipped. The existing cosine + spreading activation result passes through unchanged.

### Why This Architecture

The engram graph stores unlimited memories. The router's job is to find the *right* 20 out of thousands, fast. Cosine similarity is excellent at **recall** (finding relevant candidates) but weak at **precision** (ranking by personal relevance, temporal patterns, context). The re-ranker focuses the NN on the hard part (precision) while keeping cosine's strong recall as the candidate generator.

This is analogous to how human memory works: generic similarity gets you into the right neighborhood, but personal associations — learned over time — determine what actually surfaces. The temporal features (time of day, day of week, active goal) let the router learn patterns like "morning queries are usually about planning, evening queries are reflective."

---

## 2. Training Pipeline

### Trigger

Memory-service pushes a Redis message to `neural_router:train_signal` when new observations since last training exceed a configurable threshold (default: 50 observations). The training container listens via BRPOP.

### Training Data Assembly

1. Query `retrieval_log` for all observations with non-null `engrams_used` for the target tenant
2. For each observation, fetch the candidate engrams (from `engrams_surfaced`)
3. Label: `1` if engram was in `engrams_used`, `0` if surfaced but not used
4. Extract features per candidate (see Feature Set below)

### Feature Set

**Scalar features (always available, used from 200+ observations):**

| Feature | Dim | Source |
|---------|-----|--------|
| Cosine similarity | 1 | Pre-computed by activation query |
| Engram importance | 1 | `engrams.importance` |
| Engram activation score | 1 | From spreading activation |
| Recency (days since accessed) | 1 | `engrams.last_accessed` |
| Engram type | 8 (one-hot) | fact/episode/entity/preference/procedure/schema/goal/self_model |
| Time of day (normalized 0–1) | 1 | `temporal_context.time_of_day` |
| Day of week | 7 (one-hot) | `temporal_context.day_of_week` |
| Has active goal | 1 | `temporal_context.active_goal` is non-null |
| Convergence paths | 1 | From spreading activation |
| Outcome average | 1 | `engrams.outcome_avg` |
| Outcome count | 1 | `engrams.outcome_count` |
| **Total** | **~25** | |

**Embedding features (added at 1000+ observations):**

| Feature | Dim | Source |
|---------|-----|--------|
| Query embedding (projected) | 32 | Linear(768→32) on `retrieval_log.query_embedding` |
| Engram embedding (projected) | 32 | Linear(768→32) on `engrams.embedding` |
| Dot product of projections | 1 | Learned interaction |
| Element-wise difference | 32 | Captures directional relationship |
| **Additional total** | **~65** | |

### Model Architecture

**Scalar architecture (200–999 observations, ~4K params):**
```
Input (25) → Linear(64) → ReLU → Linear(32) → ReLU → Linear(1) → Sigmoid
```

**Embedding architecture (1000+ observations, ~57K params):**
```
Query embedding (768) → Linear(32)  ─┐
                                      ├─ dot product (1) + difference (32)
Engram embedding (768) → Linear(32) ─┘
                                      ↓
Concat [scalar_features(25), dot(1), diff(32)] → Linear(64) → ReLU → Linear(32) → ReLU → Linear(1) → Sigmoid
```

### Training Loop

- **Loss:** Binary cross-entropy (used vs not-used)
- **Optimizer:** Adam, learning rate 1e-3 with cosine decay
- **Epochs:** 20 with early stopping on validation loss (patience=3)
- **Split:** 80% train / 20% validation (temporal split — oldest 80% train, newest 20% validate)
- **Regularization:** L2 weight decay (1e-4) to prevent overfitting on small datasets
- **Architecture gate:** Observation count determines which architecture to use

### Validation Gate

New model must achieve validation accuracy >= previous active model's accuracy. If it doesn't, the model is stored (for debugging/analysis) but not promoted to `is_active = TRUE`. This prevents regression — a bad training run can never make retrieval worse.

---

## 3. Serving (Inference in Memory-Service)

### Model Loading

On startup and every 60 seconds, memory-service checks the `neural_router_models` table for a newer active model than what's cached (simple `trained_at` comparison). If found, deserializes via `torch.load()` into eval mode. Cached in memory — no DB hit per request.

### Integration Point

New function `neural_rerank()` called at the end of `spreading_activation()` in `activation.py`:

1. If no trained model exists → return current results unchanged (fallback)
2. Extract features for each candidate (cheap — data already in memory from activation query)
3. `model(feature_tensor)` → score per candidate
4. Sort descending, return top 20

### Performance

- Feature extraction: <0.5ms (in-memory operations)
- Model inference: <1ms (PyTorch forward pass on ~50×25 tensor, CPU)
- Total re-ranking overhead: <2ms
- Fallback (no model): 0ms overhead

### Fallback Guarantees

Re-ranking is always optional. If any of these are true, spreading activation returns results exactly as it does today:
- `neural_router_enabled` is `False`
- No active model exists in `neural_router_models` for this tenant
- Model loading fails (log warning, continue without re-ranking)
- Inference fails (log warning, return un-reranked candidates)

---

## 4. Infrastructure

### Training Container

Same Docker image as memory-service with a different entrypoint:
```
python -m app.engram.neural_router.train
```

Docker Compose service:
```yaml
neural-router-trainer:
  build: ./memory-service
  command: python -m app.engram.neural_router.train
  restart: unless-stopped
  depends_on:
    - postgres
    - redis
  environment:
    - DATABASE_URL=${DATABASE_URL}
    - REDIS_URL=${REDIS_URL}
```

Idles on BRPOP waiting for train signals. Lightweight — near-zero resource usage when not training.

Redis DB allocation: shares memory-service's db0 (training signals are ephemeral).

### Database Schema

```sql
CREATE TABLE IF NOT EXISTS neural_router_models (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    architecture        TEXT NOT NULL,          -- 'scalar' or 'embedding'
    weights             BYTEA NOT NULL,
    observation_count   INTEGER NOT NULL,
    validation_accuracy REAL,
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    trained_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nrm_tenant_active
    ON neural_router_models(tenant_id) WHERE is_active;
```

Only one row per tenant has `is_active = TRUE`. Training container promotes new model atomically:
```sql
BEGIN;
UPDATE neural_router_models SET is_active = FALSE WHERE tenant_id = :tid AND is_active;
INSERT INTO neural_router_models (..., is_active) VALUES (..., TRUE);
COMMIT;
```

### New Files

| File | Purpose |
|---|---|
| `memory-service/app/engram/neural_router/__init__.py` | Package |
| `memory-service/app/engram/neural_router/model.py` | PyTorch model definitions (scalar + embedding architectures) |
| `memory-service/app/engram/neural_router/features.py` | Feature extraction from candidates |
| `memory-service/app/engram/neural_router/train.py` | Training loop + BRPOP listener (entrypoint for training container) |
| `memory-service/app/engram/neural_router/serve.py` | Model loading, caching, `neural_rerank()` function |

### Modified Files

| File | Change |
|---|---|
| `memory-service/app/engram/activation.py` | Widen seed count when model exists (10→30), call `neural_rerank()` before returning |
| `memory-service/app/engram/router.py` | Extend `/router-status` with mode, model version, accuracy, latency |
| `memory-service/app/engram/retrieval_logger.py` | Emit Redis train signal when observation threshold crossed |
| `memory-service/app/config.py` | Add neural router settings |
| `memory-service/app/db/schema.sql` | Add `neural_router_models` table |
| `docker-compose.yml` | Add `neural-router-trainer` service |
| `memory-service/requirements.txt` | Add `torch` (CPU-only wheel) |

---

## 5. Configuration

New settings in `memory-service/app/config.py`:

```python
# Neural Router — Phase 5
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
neural_router_min_accuracy_gain: float = 0.0
```

**Behavioral notes:**
- `neural_router_enabled: False` disables re-ranking entirely — pure cosine + spread, same as today
- `neural_router_seed_count` (30) is used only when a trained model exists; otherwise the original `engram_seed_count` (10) applies — no point widening the funnel without a re-ranker to narrow it
- All thresholds operate per-tenant. For now they're global config; the training pipeline already keys on `tenant_id`

---

## 6. Testing Strategy

### Unit Tests (run in training container or CI)

- Model forward pass produces valid scores (0–1) for both architectures
- Feature extraction produces correct tensor shapes for scalar and embedding modes
- Architecture gate selects scalar vs embedding based on observation count
- Validation gate rejects models that don't beat baseline
- Model serialization round-trip: save → load → identical predictions

### Integration Tests (in `tests/`, require running services)

- `/router-status` returns correct mode (`cosine_only`, `scalar_reranker`, `embedding_reranker`) based on observation count
- Log 200+ observations via `/ingest` + simulated retrievals, verify train signal fires on Redis
- After training completes, `/context` endpoint returns re-ranked results (different ordering than pure cosine)
- Model persists across memory-service restart (loaded from PostgreSQL on startup)
- Fallback: delete model from DB, verify `/context` still works identically to cosine-only mode
- Tenant isolation: two tenants' models don't interfere

### Shadow Metrics (production observability)

- Log both cosine ranking and NN ranking for every re-ranked request
- Track precision@K: what fraction of NN's top-20 ended up in `engrams_used`
- Track cosine-vs-NN agreement: how much does re-ranking change the ordering
- Expose rolling averages via `/router-status`

---

## Implementation Sequence

1. Schema + config (table, settings)
2. Model definitions (PyTorch architectures, feature extraction)
3. Training pipeline (data assembly, training loop, validation gate, BRPOP listener)
4. Serving (model loading, caching, `neural_rerank()`)
5. Integration (wire into `activation.py`, widen funnel, update `/router-status`)
6. Training container (Docker Compose service, entrypoint)
7. Observation threshold signal (update `retrieval_logger.py`)
8. Tests (unit + integration)
9. Dashboard update (extend Engram Explorer with router metrics)
