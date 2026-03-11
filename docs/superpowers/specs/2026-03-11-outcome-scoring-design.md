# Unified Outcome Scoring Design

Nova learns which models work best for which tasks by scoring every LLM interaction and feeding those scores into the adaptive routing effectiveness matrix. This spec covers scoring across all interaction surfaces: pipeline tasks, chat conversations, and cortex autonomous cycles.

## 1. Signal Taxonomy

Every outcome score is a float from 0.0 (failure) to 1.0 (success), written to `usage_events.outcome_score`. Each score is accompanied by an `outcome_confidence` float (0.0–1.0) indicating how reliable the signal is.

### 1.1 Pipeline Signals (deterministic, inline)

| Stage | Signal | Score | Confidence |
|-------|--------|-------|------------|
| Guardrail | passed | 0.9 | 0.95 |
| Guardrail | blocked | 0.2 | 0.95 |
| Code Review | verdict=pass | 0.85 | 0.9 |
| Code Review | verdict=needs_refactor | 0.5 | 0.85 |
| Code Review | verdict=reject | 0.2 | 0.9 |
| Task Agent | completed successfully | 0.8 | 0.8 |
| Task Agent | failed/errored | 0.3 | 0.9 |
| Context Agent | completed (always succeeds) | 0.7 | 0.6 |
| Decision Agent | completed | 0.7 | 0.6 |

**Pipeline success backfill:** When the overall pipeline completes successfully (`pipeline_success=true`), all stage scores are bumped by +0.1 (capped at 1.0).

### 1.2 Chat Signals (implicit heuristics, async)

| User Behavior | Detection Method | Score | Confidence |
|---------------|-----------------|-------|------------|
| Acknowledgment ("thanks", "perfect", "got it") | Short message (<30 chars) + keyword match | 0.9 | 0.85 |
| Topic change (new subject) | Low semantic similarity (<0.3), no negation | 0.8 | 0.6 |
| Follow-up (builds on response) | Moderate similarity (0.3–0.8), no negation | 0.75 | 0.7 |
| Correction ("no", "not what I meant", "actually") | Negation keyword patterns at start of message | 0.4 | 0.8 |
| Rephrased question | High similarity (>0.8) to previous user message | 0.3 | 0.85 |
| Abandonment (no response 30+ min) | Timeout detection | 0.5 | 0.2 |

The abandonment score has deliberately low confidence (0.2) because silence is ambiguous — the user may be busy, driving, or otherwise occupied. Strong signals (thanks, corrections, rephrasing) dominate the effectiveness matrix due to their high confidence.

### 1.3 Cortex Signals (deterministic, inline)

| Outcome | Score | Confidence |
|---------|-------|------------|
| Task dispatched successfully | 0.7 | 0.7 |
| Cycle idle (no drives urgent) | 0.6 | 0.5 |
| Cycle skipped (budget exhausted) | not scored | — |
| Cycle errored | 0.2 | 0.9 |

## 2. Scoring Architecture

### 2.1 Design Decision: Hybrid Inline + Async

Pipeline and cortex outcomes are deterministic and known immediately — they are scored inline at completion time (zero delay). Chat outcomes inherently require seeing the user's next message — they are scored by an async background worker.

### 2.2 Pipeline Inline Scoring

**Location:** `orchestrator/app/pipeline/executor.py`, inside `_persist_stage_records()`.

After each agent stage completes:
1. `_score_stage_outcome()` computes score + confidence from the agent's output
2. `insert_usage_event()` is called with `outcome_score`, `outcome_confidence`, and `metadata` containing `task_type`, `stage`, `task_id`, and `engram_ids` (if memory context was used)

When the overall pipeline completes, `_backfill_outcome_scores()` bumps all stage scores by +0.1 (capped at 1.0). This mirrors the existing `_backfill_training_success()` pattern.

```
_run_agent() completes
  → _persist_stage_records() writes guardrail_findings, code_reviews, etc.
  → _score_stage_outcome() computes score from agent output
  → insert_usage_event(outcome_score=score, outcome_confidence=conf, metadata={...})

Pipeline completes
  → _backfill_outcome_scores() bumps all stage scores +0.1
```

### 2.3 Cortex Inline Scoring

**Location:** `cortex/app/cycle.py`, at the end of `run_cycle()` before `_update_state()`.

Cortex maps its cycle outcome to a score and POSTs to the orchestrator's usage event endpoint:

```
POST /api/v1/usage/events
{
  "model": "<model used for planning>",
  "outcome_score": 0.7,
  "outcome_confidence": 0.7,
  "metadata": {"task_type": "planning", "source": "cortex", "cycle": 42}
}
```

This keeps data ownership clean — cortex doesn't write to the orchestrator's DB directly. The endpoint is `POST /api/v1/usage/events` (not `/api/v1/usage`) to avoid confusion with the existing `GET /api/v1/usage` admin reporting endpoint.

### 2.4 Chat Async Scorer

**Location:** New module `orchestrator/app/chat_scorer.py` with a background loop.

**Interval:** Every 30 seconds.

**Process:**
1. Query `messages` table for conversations with new user messages since the last scoring pass
2. For each new user message, look at the preceding assistant message
3. Apply heuristic detection (keyword matching first, embedding similarity only when needed)
4. Compute score + confidence
5. Find the corresponding `usage_events` row by matching `session_id` (which equals `conversation_id` for authenticated users) and `created_at` within a 120-second window before the assistant message's `created_at`. If multiple rows match, pick the one closest in time. As a future improvement, the `log_usage()` call can store a `usage_event_id` in the message metadata for exact joins.
6. UPDATE the matched `usage_events` row to set `outcome_score` and `outcome_confidence`

**Embedding cost management:** Keyword-based heuristics (correction detection, acknowledgment) run first — they're free. Embedding-based heuristics (rephrasing, topic change) only run if keyword heuristics didn't produce a high-confidence result. Embeddings are batched per scoring pass and use the cheap tier.

**Tracking state:** A `nova:state:chat_scorer_cursor` key in Redis stores the timestamp of the last processed message, so the scorer doesn't reprocess old messages on restart.

### 2.5 Conversation-Level Success Score

When a conversation goes quiet (no new message for 30+ min), the chat scorer computes a session-level score: a weighted average of per-turn scores, biased toward the final turns (most recent turns weighted highest).

**Dedup:** Before computing, check if a `conversation_outcomes` row already exists for this conversation with `computed_at` within the last hour. If so, skip. Track recently-scored conversation IDs in a Redis set (`nova:state:scored_conversations`, entries expire after 2 hours) for fast lookup.

This is stored as a standalone metric in a new `conversation_outcomes` table:

```sql
CREATE TABLE conversation_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id),
    session_id TEXT,
    session_score REAL NOT NULL,
    turn_count INTEGER NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

The session score is available for analytics and future refinement but does not retroactively adjust per-turn scores. Per-turn signals are strong enough on their own.

## 3. Engram ID Breadcrumbs

When the orchestrator assembles memory context for an LLM call (pipeline or chat), the engram IDs that were included in context are stored in `usage_events.metadata`:

```json
{
  "task_type": "chat",
  "task_id": "uuid-of-pipeline-task",
  "engram_ids": ["uuid-1", "uuid-2", "uuid-3"],
  "retrieval_log_id": "uuid-of-retrieval-log-entry"
}
```

This creates a traceable path from outcome score → specific memories, enabling the outcome-weighted memory feedback loop (Section 5). The `task_id` field enables pipeline success backfill (matching usage_events to their pipeline task via `metadata->>'task_id'`).

### 3.1 Plumbing Changes Required

The engram ID path does not exist today — the following changes create it:

1. **Memory service `/api/v1/engrams/context` response** (`memory-service/app/engram/router.py`): Add `engram_ids: list[str]` to the response body alongside the existing `context`, `sections`, and `total_tokens` fields. The working memory gate already has the activated engram IDs internally — they just need to be included in the response.

2. **Orchestrator `_get_memory_context()`** (`orchestrator/app/agents/runner.py`): Update the return type from `tuple[str, int]` to a dataclass or named tuple that includes `engram_ids: list[str]`. Update callers (`run_agent_turn()` and `run_agent_turn_streaming()`) to destructure the new return type.

3. **Orchestrator `log_usage()` wrapper** (`orchestrator/app/usage.py`): Extend to accept optional `metadata`, `outcome_score`, and `outcome_confidence` kwargs and pass them through to `insert_usage_event()`. The call sites in `runner.py` then pass `metadata={"engram_ids": engram_ids, "task_type": "chat"}` when memory context was used.

## 4. Scoring Confidence and Weighted Effectiveness Matrix

### 4.1 Schema Change

Add `outcome_confidence` column to `usage_events`:

```sql
ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS outcome_confidence REAL;
```

### 4.2 Weighted Aggregation

The effectiveness matrix computation in `orchestrator/app/effectiveness.py` changes from simple averaging to confidence-weighted averaging:

```sql
SELECT model,
       COALESCE(metadata->>'task_type', 'unknown') AS task_type,
       SUM(outcome_score * outcome_confidence) / NULLIF(SUM(outcome_confidence), 0) AS avg_score,
       COUNT(*) AS sample_count
FROM usage_events
WHERE outcome_score IS NOT NULL
  AND outcome_confidence IS NOT NULL
  AND created_at > NOW() - INTERVAL '30 days'
GROUP BY 1, 2
```

High-confidence signals (explicit corrections, guardrail verdicts) dominate. Low-confidence signals (abandonment) contribute minimally. This prevents thousands of ambiguous 0.5 scores from drowning out the strong signals.

## 5. Outcome-Weighted Memory Decay

### 5.1 Problem

Engram activation decays at a fixed rate, and importance is set once at ingestion. Memories that prove useful in practice should persist longer and surface more readily. Memories that consistently appear in low-scoring interactions should fade faster.

### 5.2 Outcome Feedback Loop

An hourly background job in the orchestrator reads recent outcome scores with associated engram_ids and sends a batch signal to the memory service:

```
orchestrator (hourly, alongside effectiveness matrix computation)
  → query usage_events WHERE outcome_score IS NOT NULL
    AND metadata->'engram_ids' IS NOT NULL
    AND created_at > last_feedback_run
  → extract engram_ids from metadata JSON array: metadata->'engram_ids'
  → POST /api/v1/engrams/outcome-feedback
    body: [{ "engram_id": "uuid", "outcome_score": 0.85, "task_type": "chat" }, ...]
```

**Cursor tracking:** The last-run timestamp is stored in Redis at `nova:state:outcome_feedback_cursor` (set after each successful batch). On first run or after Redis flush, defaults to `NOW() - INTERVAL '1 hour'`.

### 5.3 Memory Service Adjustments

New endpoint: `POST /api/v1/engrams/outcome-feedback`

For each engram in the batch:

**Activation boost (per event):**
- Score > 0.7: `activation += 0.05 × (1.0 - activation)` (same ACT-R formula as retrieval, half magnitude)
- Score < 0.4: no activation change (don't punish — the memory might be fine, the model might have fumbled)

**Importance recalibration (rolling):**
- Track rolling outcome stats per engram via three new columns on the `engrams` table (memory-service migration):
  - `outcome_avg REAL DEFAULT NULL` — rolling average of outcome scores
  - `outcome_count INTEGER DEFAULT 0` — number of outcome observations
  - `last_recalibrated_at TIMESTAMPTZ DEFAULT NULL` — prevents recalibrating more than once per day
- Updated incrementally: `outcome_avg = (outcome_avg * outcome_count + new_score) / (outcome_count + 1)`, then `outcome_count += 1`
- When an engram has 5+ outcome observations with avg > 0.7: nudge importance up by 0.05 (capped at 1.0)
- When an engram has 5+ outcome observations with avg < 0.4: nudge importance down by 0.05 (floor at 0.1)
- Recalibration happens at most once per engram per day (`last_recalibrated_at` check) to prevent jitter

**Outcome-driven Hebbian learning:**
- When multiple engrams from the same interaction both appear in a high-scoring outcome (>0.7): strengthen edges between them (`co_activations += 1`, `weight += 0.02`, capped at 1.0)
- This is the key neural mechanism — the network doesn't just wire together memories that fire together, it wires together memories that *succeed* together

### 5.4 Guardrails

- Importance can never go below 0.1 or above 1.0
- Activation adjustments from outcomes are capped at half the magnitude of retrieval-triggered adjustments
- Edge weight adjustments from outcomes are capped at +0.02 per event
- The existing consolidation cycle (pruning, merging, contradiction detection) runs independently — outcome feedback is an additional signal, not a replacement

## 6. Failure Pattern Detection → Cortex Learn Drive

### 6.1 Detection

The effectiveness matrix computation already aggregates scores by `model × task_type`. When ALL models score below 0.5 for a given task_type, that's not a routing problem — it's a capability gap.

After computing the effectiveness matrix, check for task_types where:
```
MAX(avg_score) < 0.5 AND SUM(sample_count) >= 20
```

This means: we have enough data (20+ interactions), and even the best model underperforms.

### 6.2 Signal to Cortex

Write detected capability gaps to Redis:

```
nova:signals:capability_gaps → JSON list of {task_type, best_score, sample_count, since}
```

The cortex `learn` drive reads this during its `assess()` phase. If capability gaps exist, the learn drive reports high urgency with a proposed action like: "Users consistently report poor quality on [task_type] interactions. Consider: improving context retrieval for this domain, adjusting system prompts, or flagging for human review."

This is Nova becoming self-aware about its weaknesses and proactively trying to fix them.

## 7. Model Exploration Budget

### 7.1 Problem

Without intervention, the effectiveness matrix creates a positive feedback loop: the best-scoring model gets all traffic → gets more data → stays on top. Nova never discovers if a newer or cheaper model would perform equally well.

### 7.2 Solution: Explore/Exploit

In the tier resolver (`llm-gateway/app/tier_resolver.py`), inside `_resolve_tier_to_model()`, apply exploration *before* iterating the candidate list. The current function iterates candidates in preference order and returns the first available one — there is no single "top model" to override. Instead:

```python
import random

EXPLORE_RATE = 0.05  # 5% of requests

# Inside _resolve_tier_to_model(), before the candidate iteration loop:
if task_type and random.random() < EXPLORE_RATE:
    # Exploration mode: filter to undersampled models, pick randomly
    undersampled = [
        m for m in candidates
        if _sample_count(m, task_type, effectiveness) < EXPLORE_MIN_SAMPLES
        and _is_available(m)  # check provider + rate limit
    ]
    if undersampled:
        chosen = random.choice(undersampled)
        log.info("Exploration: tier=%s task_type=%s → %s (undersampled)", tier, task_type, chosen)
        return _resolve_virtual(chosen)

# Normal exploitation path: iterate in preference order (existing code)
for model_id in candidates:
    ...
```

This way exploration only fires when there are undersampled models to try, and falls through to normal preference-ordered iteration otherwise.

### 7.3 Decay

The exploration rate decays as data accumulates. Once all models in a tier have 50+ samples for a task_type, exploration stops for that tier×task_type combination. This prevents wasting requests on exploration when we already have confident data.

### 7.4 Configuration

```
EXPLORE_RATE: float = 0.05           # configurable via Redis nova:config:llm.explore_rate
EXPLORE_MIN_SAMPLES: int = 50        # threshold for "well-sampled"
```

## 8. Data Flow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    INTERACTION SURFACES                         │
├──────────────┬──────────────────┬──────────────────────────────┤
│  Pipeline    │  Chat            │  Cortex                      │
│  (inline)    │  (async, 30s)    │  (inline)                    │
│              │                  │                              │
│  guardrail   │  keyword match   │  cycle outcome               │
│  code review │  embedding sim   │  (dispatched/idle/error)     │
│  task pass   │  abandonment     │                              │
│  pipeline    │  timeout         │                              │
│  success     │                  │                              │
└──────┬───────┴────────┬─────────┴──────────────┬───────────────┘
       │                │                        │
       ▼                ▼                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  usage_events (orchestrator DB)                                │
│  outcome_score + outcome_confidence + metadata{engram_ids}     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌──────────────────┐ ┌──────────┐ ┌──────────────────────────┐
│ Effectiveness    │ │ Failure  │ │ Memory Outcome Feedback   │
│ Matrix (hourly)  │ │ Pattern  │ │ (hourly)                  │
│                  │ │ Detection│ │                           │
│ confidence-      │ │          │ │ activation boost          │
│ weighted avg     │ │ caps gap │ │ importance recalibration  │
│ per model×type   │ │ signals  │ │ outcome-driven Hebbian    │
│                  │ │ to Redis │ │ learning on edges         │
│ → Redis for      │ │          │ │                           │
│   tier resolver  │ │ → cortex │ │ → memory-service          │
│                  │ │   learn  │ │   /engrams/outcome-       │
│ + exploration    │ │   drive  │ │   feedback endpoint       │
│   budget (5%)    │ │          │ │                           │
└──────────────────┘ └──────────┘ └──────────────────────────┘
```

## 9. Schema Changes

### 9.1 Migration: `023_outcome_scoring.sql`

```sql
-- 023: Outcome scoring infrastructure

-- Confidence column for weighted effectiveness matrix
ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS outcome_confidence REAL;

-- Conversation-level outcome tracking
CREATE TABLE IF NOT EXISTS conversation_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    session_id TEXT,
    session_score REAL NOT NULL,
    turn_count INTEGER NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_outcomes_conv
    ON conversation_outcomes (conversation_id);

-- Index for chat scorer: find usage events by session + time
CREATE INDEX IF NOT EXISTS idx_usage_events_session_created
    ON usage_events (session_id, created_at)
    WHERE session_id IS NOT NULL;
```

### 9.2 New Endpoint: Orchestrator

```
POST /api/v1/usage/events
{
  "model": "string",
  "input_tokens": 0,
  "output_tokens": 0,
  "cost_usd": 0.0,
  "duration_ms": 0,
  "outcome_score": 0.85,
  "outcome_confidence": 0.9,
  "metadata": { "task_type": "planning", "source": "cortex" }
}
```

For cortex to report its own usage events without writing to orchestrator's DB directly.

### 9.3 New Endpoint: Memory Service

```
POST /api/v1/engrams/outcome-feedback
[
  { "engram_id": "uuid", "outcome_score": 0.85, "task_type": "chat" },
  { "engram_id": "uuid", "outcome_score": 0.3, "task_type": "task_execution" }
]
```

Accepts a batch of outcome signals and applies activation/importance/edge adjustments.

## 10. File Changes

### New Files

| File | Responsibility |
|------|----------------|
| `orchestrator/app/chat_scorer.py` | Chat implicit signal heuristics + async scoring loop |
| `orchestrator/app/migrations/023_outcome_scoring.sql` | Schema changes for confidence + conversation_outcomes |

### Modified Files

| File | Change |
|------|--------|
| `orchestrator/app/pipeline/executor.py` | Add `_score_stage_outcome()`, `_backfill_outcome_scores()` (backfill matches via `metadata->>'task_id'`) |
| `orchestrator/app/db.py` | Add `outcome_confidence` param to `insert_usage_event()` |
| `orchestrator/app/usage.py` | Extend `log_usage()` to accept optional `metadata`, `outcome_score`, `outcome_confidence` kwargs |
| `orchestrator/app/effectiveness.py` | Confidence-weighted aggregation, failure pattern detection, memory outcome feedback batch |
| `orchestrator/app/main.py` | Start chat_scorer background loop in lifespan |
| `orchestrator/app/router.py` | Add `POST /api/v1/usage/events` endpoint for external services |
| `orchestrator/app/agents/runner.py` | Update `_get_memory_context()` return type to include engram_ids; thread into `log_usage()` calls |
| `cortex/app/cycle.py` | Score cycle outcomes, POST to orchestrator usage/events endpoint |
| `cortex/app/drives/learn.py` | Read `nova:signals:capability_gaps` from Redis in `assess()` |
| `llm-gateway/app/tier_resolver.py` | Add exploration budget logic before candidate iteration in `_resolve_tier_to_model()` |
| `memory-service/app/engram/router.py` | Add `engram_ids` to `/api/v1/engrams/context` response; register outcome-feedback endpoint |
| `memory-service/app/engram/` | New module for outcome feedback processing (activation, importance, edge adjustments) |
| `memory-service/` | Migration adding `outcome_avg`, `outcome_count`, `last_recalibrated_at` columns to `engrams` table |

## 11. Future Enhancements (Out of Scope)

- **Self-model refinement:** Outcome patterns reveal Nova's strengths/weaknesses → auto-generate self-model engrams ("I perform best when I have code context")
- **Topic-aware model affinity:** Extract topic signals from conversations for finer-grained routing beyond task_type
- **LLM batch calibration:** Periodically use a cheap LLM to evaluate recent conversations and calibrate/correct the heuristic scores (path from rule-based to hybrid scoring)
- **Per-user calibration:** When Nova is multi-tenant, different users have different quality expectations — scoring heuristics should be per-user calibrated

## 12. Success Criteria

- [ ] Pipeline stages write outcome_score + outcome_confidence to usage_events
- [ ] Chat scorer detects implicit signals and backfills scores within 60 seconds
- [ ] Cortex cycles report outcome scores to orchestrator
- [ ] Effectiveness matrix uses confidence-weighted aggregation
- [ ] Engram IDs stored in usage_events.metadata when memory context is used
- [ ] Memory service receives outcome feedback and adjusts activation/importance/edges
- [ ] Failure pattern detection surfaces capability gaps to cortex learn drive
- [ ] Model exploration budget prevents feedback-loop stagnation
- [ ] Conversation-level success score computed and stored
- [ ] All services remain healthy after changes
