# Unified Outcome Scoring Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the adaptive routing learning loop by scoring every LLM interaction — pipeline, chat, and cortex — and feeding scores into the effectiveness matrix, memory network, and cortex self-awareness.

**Architecture:** Pipeline and cortex write scores inline at completion. A chat scorer background loop infers quality from user behavior heuristics. Scores flow to: (1) confidence-weighted effectiveness matrix for model routing, (2) engram outcome feedback for memory reinforcement, (3) cortex learn drive for capability gap awareness. Model exploration budget prevents feedback-loop stagnation.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Redis, httpx, Pydantic

**Spec:** `docs/superpowers/specs/2026-03-11-outcome-scoring-design.md`

---

## Progress Tracker

| Chunk | Status | Notes |
|-------|--------|-------|
| 1: Schema + DB Layer | pending | |
| 2: Pipeline Inline Scoring | pending | |
| 3: Cortex Usage Endpoint + Scoring | pending | |
| 4: Chat Async Scorer | pending | |
| 5: Conversation-Level Scoring | pending | |
| 6: Engram ID Breadcrumbs | pending | |
| 7: Confidence-Weighted Effectiveness Matrix | pending | |
| 8: Memory Outcome Feedback | pending | |
| 9: Model Exploration Budget | pending | |
| 10: Cortex Learn Drive | pending | |

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `orchestrator/app/chat_scorer.py` | Chat implicit signal heuristics + 30s async scoring loop |
| `orchestrator/app/migrations/023_outcome_scoring.sql` | outcome_confidence column, conversation_outcomes table, indexes |

### Modified Files

| File | Change |
|------|--------|
| `orchestrator/app/db.py` | Add `outcome_confidence` param to `insert_usage_event()` |
| `orchestrator/app/usage.py` | Extend `log_usage()` with `metadata`, `outcome_score`, `outcome_confidence` kwargs |
| `orchestrator/app/pipeline/executor.py` | Add `_score_stage_outcome()`, `_backfill_outcome_scores()` |
| `orchestrator/app/effectiveness.py` | Confidence-weighted aggregation, failure pattern detection, memory outcome feedback |
| `orchestrator/app/main.py` | Start chat_scorer loop in lifespan |
| `orchestrator/app/router.py` | Add `POST /api/v1/usage/events` endpoint |
| `orchestrator/app/agents/runner.py` | Return engram_ids from `_get_memory_context()`, thread into `log_usage()` |
| `cortex/app/cycle.py` | Score cycle outcomes, POST to orchestrator |
| `cortex/app/drives/learn.py` | Read capability gaps from Redis in `assess()` |
| `llm-gateway/app/tier_resolver.py` | Add exploration budget in `_resolve_tier_to_model()` |
| `memory-service/app/engram/router.py` | Return engram_ids from `/context`, add `/outcome-feedback` endpoint |
| `memory-service/app/engram/working_memory.py` | Return activated engram IDs from `assemble_context()` |
| `memory-service/app/db/schema.sql` | Add `outcome_avg`, `outcome_count`, `last_recalibrated_at` columns to engrams |

---

## Chunk 1: Schema + DB Layer

Foundation: migration, extend `insert_usage_event()`, extend `log_usage()`.

### Task 1.1: Create migration 023

**Files:**
- Create: `orchestrator/app/migrations/023_outcome_scoring.sql`

- [ ] **Step 1: Write migration file**

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

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/migrations/023_outcome_scoring.sql
git commit -m "feat: add migration 023 for outcome scoring (confidence, conversation_outcomes)"
```

### Task 1.2: Extend insert_usage_event()

**Files:**
- Modify: `orchestrator/app/db.py:272-303`

- [ ] **Step 1: Add outcome_confidence parameter**

In `insert_usage_event()` (line 272), add `outcome_confidence: float | None = None` after the existing `outcome_score` parameter. Update the INSERT to include it:

```python
async def insert_usage_event(
    api_key_id: UUID | None,
    agent_id: UUID | None,
    session_id: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    duration_ms: int | None,
    metadata: dict | None = None,
    outcome_score: float | None = None,
    outcome_confidence: float | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO usage_events
                (api_key_id, agent_id, session_id, model,
                 input_tokens, output_tokens, cost_usd, duration_ms,
                 metadata, outcome_score, outcome_confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
            """,
            api_key_id,
            agent_id,
            session_id,
            model,
            input_tokens,
            output_tokens,
            float(cost_usd) if cost_usd is not None else None,
            duration_ms,
            json.dumps(metadata) if metadata else "{}",
            outcome_score,
            outcome_confidence,
        )
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/db.py
git commit -m "feat: add outcome_confidence param to insert_usage_event()"
```

### Task 1.3: Extend log_usage() wrapper

**Files:**
- Modify: `orchestrator/app/usage.py:1-57`

- [ ] **Step 1: Add optional kwargs to log_usage()**

The current `log_usage()` (line 22) has a fixed parameter list. Add optional `metadata`, `outcome_score`, and `outcome_confidence` kwargs:

```python
def log_usage(
    api_key_id: UUID | None,
    agent_id: UUID | None,
    session_id: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    duration_ms: int | None,
    metadata: dict | None = None,
    outcome_score: float | None = None,
    outcome_confidence: float | None = None,
) -> None:
    """Schedule a usage event insert as a background task."""
    asyncio.create_task(
        _safe_insert(
            api_key_id=api_key_id,
            agent_id=agent_id,
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            metadata=metadata,
            outcome_score=outcome_score,
            outcome_confidence=outcome_confidence,
        )
    )
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/usage.py
git commit -m "feat: extend log_usage() with metadata, outcome_score, outcome_confidence"
```

---

## Chunk 2: Pipeline Inline Scoring

Score each pipeline stage inline after completion.

### Task 2.1: Add _score_stage_outcome() to executor

**Files:**
- Modify: `orchestrator/app/pipeline/executor.py`

- [ ] **Step 1: Add scoring function**

Add this function near the other helper functions (after `_persist_stage_records()` around line 601):

```python
def _score_stage_outcome(role: str, result: dict, flags: set[str]) -> tuple[float, float]:
    """Compute outcome score + confidence for a pipeline stage.

    Returns (score, confidence) where both are 0.0-1.0.
    """
    if role == "guardrail":
        if result.get("blocked"):
            return 0.2, 0.95
        return 0.9, 0.95

    if role == "code_review":
        verdict = result.get("verdict", "pass")
        if verdict == "pass":
            return 0.85, 0.9
        if verdict == "needs_refactor":
            return 0.5, 0.85
        return 0.2, 0.9  # reject

    if role == "task":
        if result.get("error") or not result.get("output"):
            return 0.3, 0.9
        return 0.8, 0.8

    if role == "context":
        return 0.7, 0.6

    if role == "decision":
        return 0.7, 0.6

    # Unknown role — neutral
    return 0.5, 0.5
```

- [ ] **Step 2: Wire scoring into _run_agent()**

In `_run_agent()`, after the call to `_persist_stage_records()` (around line 505), add outcome scoring. The function already has access to `result`, `agent.role`, `state`, and `task_id`. Add the usage event insert:

```python
    # Score stage outcome for adaptive routing
    try:
        _oscore, _oconf = _score_stage_outcome(agent.role, result, state.flags)
        _meta = {
            "task_type": _task_type,
            "stage": agent.role,
            "task_id": task_id,
        }
        from app.usage import log_usage
        log_usage(
            api_key_id=None,
            agent_id=None,
            session_id=session_id,
            model=model,
            input_tokens=instance._usage.get("input_tokens", 0),
            output_tokens=instance._usage.get("output_tokens", 0),
            cost_usd=instance._usage.get("cost_usd"),
            duration_ms=instance._usage.get("llm_calls", 0),
            metadata=_meta,
            outcome_score=_oscore,
            outcome_confidence=_oconf,
        )
    except Exception as exc:
        logger.debug("Stage outcome scoring failed: %s", exc)
```

Insert this right after the existing `_persist_stage_records()` call but before the return statement. The `instance` variable (the agent instance) is in scope here since it was created earlier in the function. `model` is the resolved model string, `session_id` is returned from the agent session creation, and `_task_type` comes from the `_STAGE_TIER_MAP` added in the previous adaptive routing work.

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/pipeline/executor.py
git commit -m "feat: score pipeline stage outcomes for adaptive routing"
```

### Task 2.2: Add _backfill_outcome_scores()

**Files:**
- Modify: `orchestrator/app/pipeline/executor.py`

- [ ] **Step 1: Add backfill function**

Add this after `_backfill_training_success()` (around line 1110):

```python
async def _backfill_outcome_scores(task_id: str) -> None:
    """Bump outcome scores +0.1 for all usage events in a successful pipeline task."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE usage_events
                SET outcome_score = LEAST(1.0, outcome_score + 0.1)
                WHERE outcome_score IS NOT NULL
                  AND metadata->>'task_id' = $1
                """,
                task_id,
            )
    except Exception as exc:
        logger.debug("Outcome score backfill failed for %s: %s", task_id, exc)
```

- [ ] **Step 2: Call it on pipeline success**

In `_run_pipeline()`, right after the existing `_backfill_training_success(task_id, success=True)` call (line 309), add:

```python
    await _backfill_outcome_scores(task_id)
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/pipeline/executor.py
git commit -m "feat: backfill outcome scores on pipeline success"
```

---

## Chunk 3: Cortex Usage Endpoint + Scoring

### Task 3.1: Add POST /api/v1/usage/events endpoint

**Files:**
- Modify: `orchestrator/app/router.py`

- [ ] **Step 1: Add the endpoint**

Add this endpoint in `router.py`. It accepts usage events from external services (cortex). Place it near the existing `GET /api/v1/usage` endpoint:

```python
from pydantic import BaseModel as PydanticBaseModel

class UsageEventRequest(PydanticBaseModel):
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    duration_ms: int | None = None
    outcome_score: float | None = None
    outcome_confidence: float | None = None
    metadata: dict | None = None

@router.post("/api/v1/usage/events", status_code=201)
async def create_usage_event(req: UsageEventRequest):
    """Accept usage events from external services (e.g. cortex)."""
    from app.db import insert_usage_event
    await insert_usage_event(
        api_key_id=None,
        agent_id=None,
        session_id=None,
        model=req.model,
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        cost_usd=req.cost_usd,
        duration_ms=req.duration_ms,
        metadata=req.metadata,
        outcome_score=req.outcome_score,
        outcome_confidence=req.outcome_confidence,
    )
    return {"status": "created"}
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/router.py
git commit -m "feat: add POST /api/v1/usage/events endpoint for external scoring"
```

### Task 3.2: Score cortex cycle outcomes

**Files:**
- Modify: `cortex/app/cycle.py`

- [ ] **Step 1: Add _report_outcome() helper**

Add this helper function after `_update_state()` (around line 289):

```python
async def _report_outcome(
    state: CycleState, model: str, score: float, confidence: float,
) -> None:
    """Report cycle outcome to orchestrator for effectiveness tracking."""
    try:
        orch = get_orchestrator()
        await orch.post(
            "/api/v1/usage/events",
            json={
                "model": model,
                "outcome_score": score,
                "outcome_confidence": confidence,
                "metadata": {
                    "task_type": "planning",
                    "source": "cortex",
                    "cycle": state.cycle_number,
                    "drive": state.action_taken,
                },
            },
            headers={"Authorization": f"Bearer {settings.cortex_api_key}"},
        )
    except Exception as e:
        log.debug("Failed to report cycle outcome: %s", e)
```

- [ ] **Step 2: Call _report_outcome() in run_cycle()**

In `run_cycle()`, after `await _reflect(state)` and `await _update_state(state)` (line 100), add scoring based on the cycle outcome:

```python
        # ── SCORE ───────────────────────────────────────────────────
        _model = settings.planning_model or "unknown"
        if state.action_taken == "idle":
            await _report_outcome(state, _model, 0.6, 0.5)
        elif state.error:
            await _report_outcome(state, _model, 0.2, 0.9)
        else:
            await _report_outcome(state, _model, 0.7, 0.7)
```

Also add scoring for the idle early-return path (around line 87, after the idle journal entry):

```python
            await _report_outcome(state, settings.planning_model or "unknown", 0.6, 0.5)
```

And in the error handler (around line 104), before the `return state`:

```python
        # Don't score if budget exhausted (no LLM call happened)
        if state.budget_tier != "none":
            await _report_outcome(state, settings.planning_model or "unknown", 0.2, 0.9)
```

- [ ] **Step 3: Commit**

```bash
git add cortex/app/cycle.py
git commit -m "feat: score cortex cycle outcomes and report to orchestrator"
```

---

## Chunk 4: Chat Async Scorer

The core heuristic engine that infers chat quality from user behavior.

### Task 4.1: Create chat_scorer.py

**Files:**
- Create: `orchestrator/app/chat_scorer.py`

- [ ] **Step 1: Create the module**

```python
"""Chat outcome scorer — infers LLM response quality from user behavior.

Runs as a 30-second background loop. For each new user message, scores
the preceding assistant response using implicit heuristics:
  - Acknowledgment ("thanks") → 0.9
  - Topic change (low similarity) → 0.8
  - Follow-up (moderate similarity) → 0.75
  - Correction ("no, I meant...") → 0.4
  - Rephrased question (high similarity) → 0.3
  - Abandonment (30+ min silence) → 0.5 (low confidence)

Keyword heuristics run first (free). Embedding similarity only runs
if keywords don't produce a high-confidence result.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone, timedelta

from .db import get_pool
from .store import get_redis
from .clients import get_memory_client

log = logging.getLogger(__name__)

# Redis keys
CURSOR_KEY = "nova:state:chat_scorer_cursor"
SCORED_CONVOS_KEY = "nova:state:scored_conversations"

# Heuristic patterns
_ACKNOWLEDGMENT_PATTERNS = re.compile(
    r"^(thanks?|thank you|perfect|great|got it|awesome|nice|cool|ok thanks|"
    r"that works|that'?s? (great|perfect|exactly|right|helpful|what i needed))\s*[.!]?$",
    re.IGNORECASE,
)
_CORRECTION_PATTERNS = re.compile(
    r"^(no[,.]?\s|not what i|actually[,.]?\s|that'?s? (wrong|not|incorrect)|"
    r"i (said|meant|asked)|you misunderstood|that'?s? not right)",
    re.IGNORECASE,
)


def _score_by_keywords(user_msg: str) -> tuple[float, float] | None:
    """Try keyword-based scoring. Returns (score, confidence) or None if no match."""
    text = user_msg.strip()

    # Short acknowledgment
    if len(text) < 50 and _ACKNOWLEDGMENT_PATTERNS.match(text):
        return 0.9, 0.85

    # Correction
    if _CORRECTION_PATTERNS.match(text):
        return 0.4, 0.8

    return None


async def _get_embedding(text: str) -> list[float] | None:
    """Get embedding via memory-service /embed endpoint."""
    try:
        client = get_memory_client()
        resp = await client.post("/api/v1/embed", json={"text": text})
        if resp.status_code == 200:
            return resp.json().get("embedding")
    except Exception:
        pass
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _score_by_similarity(
    user_msg: str, prev_user_msg: str | None, assistant_msg: str,
) -> tuple[float, float]:
    """Score using embedding similarity. Fallback when keywords don't match."""
    # If no previous user message, default to follow-up (building on response)
    if not prev_user_msg:
        return 0.75, 0.5

    # Compare current user message with previous user message
    emb_current = await _get_embedding(user_msg)
    emb_prev = await _get_embedding(prev_user_msg)

    if emb_current is None or emb_prev is None:
        return 0.7, 0.4  # Can't compute — neutral with low confidence

    sim = _cosine_similarity(emb_current, emb_prev)

    if sim > 0.8:
        # High similarity to previous question → rephrasing
        return 0.3, 0.85
    elif sim < 0.3:
        # Very different topic → moved on (satisfied)
        return 0.8, 0.6
    else:
        # Moderate similarity → follow-up question
        return 0.75, 0.7


async def _score_turn(
    user_msg: str, prev_user_msg: str | None, assistant_msg: str,
) -> tuple[float, float]:
    """Score a single assistant response based on the user's next message."""
    # Try keywords first (free, high confidence)
    kw_result = _score_by_keywords(user_msg)
    if kw_result:
        return kw_result

    # Fall back to embedding similarity
    return await _score_by_similarity(user_msg, prev_user_msg, assistant_msg)


async def _process_new_messages() -> int:
    """Process new messages and score preceding assistant responses.

    Returns the number of scores written.
    """
    redis = get_redis()
    pool = get_pool()

    # Read cursor
    cursor_raw = await redis.get(CURSOR_KEY)
    if cursor_raw:
        cursor = datetime.fromisoformat(cursor_raw)
    else:
        cursor = datetime.now(timezone.utc) - timedelta(hours=1)

    scores_written = 0

    async with pool.acquire() as conn:
        # Find new user messages since cursor
        rows = await conn.fetch(
            """
            SELECT m.id, m.conversation_id, m.content, m.created_at,
                   m.role
            FROM messages m
            WHERE m.created_at > $1
              AND m.role = 'user'
            ORDER BY m.conversation_id, m.created_at
            LIMIT 100
            """,
            cursor,
        )

        if not rows:
            return 0

        new_cursor = cursor

        for row in rows:
            conv_id = str(row["conversation_id"])
            user_msg = row["content"] or ""
            msg_time = row["created_at"]

            if msg_time > new_cursor:
                new_cursor = msg_time

            # Get the preceding assistant message
            assistant_row = await conn.fetchrow(
                """
                SELECT content FROM messages
                WHERE conversation_id = $1
                  AND role = 'assistant'
                  AND created_at < $2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                row["conversation_id"], msg_time,
            )
            if not assistant_row:
                continue

            # Get the previous user message (for similarity comparison)
            prev_user_row = await conn.fetchrow(
                """
                SELECT content FROM messages
                WHERE conversation_id = $1
                  AND role = 'user'
                  AND created_at < $2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                row["conversation_id"], msg_time,
            )

            assistant_msg = assistant_row["content"] or ""
            prev_user_msg = prev_user_row["content"] if prev_user_row else None

            # Score
            score, confidence = await _score_turn(user_msg, prev_user_msg, assistant_msg)

            # Find matching usage_event (session_id = conversation_id, within 120s)
            updated = await conn.execute(
                """
                UPDATE usage_events
                SET outcome_score = $3, outcome_confidence = $4
                WHERE session_id = $1
                  AND created_at BETWEEN ($2 - INTERVAL '120 seconds') AND $2
                  AND outcome_score IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                conv_id,
                assistant_row.get("created_at", msg_time),
                score,
                confidence,
            )

            # Fallback: use the message timestamp if assistant created_at not available
            if updated == "UPDATE 0":
                await conn.execute(
                    """
                    UPDATE usage_events
                    SET outcome_score = $3, outcome_confidence = $4
                    WHERE session_id = $1
                      AND created_at BETWEEN ($2 - INTERVAL '120 seconds') AND $2
                      AND outcome_score IS NULL
                    """,
                    conv_id, msg_time, score, confidence,
                )

            scores_written += 1

    # Update cursor
    await redis.set(CURSOR_KEY, new_cursor.isoformat())

    return scores_written


async def _check_abandonments() -> int:
    """Score abandoned conversations (no user message for 30+ min)."""
    pool = get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    scores_written = 0

    async with pool.acquire() as conn:
        # Find assistant messages with no follow-up user message for 30+ min
        rows = await conn.fetch(
            """
            SELECT ue.id, ue.session_id, ue.created_at
            FROM usage_events ue
            WHERE ue.outcome_score IS NULL
              AND ue.session_id IS NOT NULL
              AND ue.created_at < $1
              AND NOT EXISTS (
                  SELECT 1 FROM messages m
                  WHERE m.conversation_id::text = ue.session_id
                    AND m.role = 'user'
                    AND m.created_at > ue.created_at
              )
            LIMIT 50
            """,
            cutoff,
        )

        for row in rows:
            await conn.execute(
                "UPDATE usage_events SET outcome_score = 0.5, outcome_confidence = 0.2 WHERE id = $1",
                row["id"],
            )
            scores_written += 1

    return scores_written


async def chat_scorer_loop() -> None:
    """Background loop — score chat interactions every 30 seconds."""
    log.info("Chat scorer started")
    while True:
        try:
            msg_scores = await _process_new_messages()
            abandon_scores = await _check_abandonments()
            if msg_scores or abandon_scores:
                log.info(
                    "Chat scorer: %d message scores, %d abandonment scores",
                    msg_scores, abandon_scores,
                )
        except Exception:
            log.exception("Chat scorer iteration failed")
        await asyncio.sleep(30)
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/chat_scorer.py
git commit -m "feat: add chat outcome scorer with implicit heuristics"
```

### Task 4.2: Wire chat scorer into orchestrator lifespan

**Files:**
- Modify: `orchestrator/app/main.py`

- [ ] **Step 1: Add chat_scorer_loop to background tasks**

In the lifespan function, after the existing effectiveness loop (around line 117), add:

```python
    from app.chat_scorer import chat_scorer_loop
    _chat_scorer_task = asyncio.create_task(chat_scorer_loop(), name="chat-scorer")
```

Update the log message to include it:

```python
    log.info("Queue worker, reaper, effectiveness, and chat scorer started")
```

In the shutdown section, add cancellation:

```python
    _chat_scorer_task.cancel()
```

And add it to the gather:

```python
    await asyncio.gather(
        _queue_task, _reaper_task, _effectiveness_task, _chat_scorer_task,
        return_exceptions=True,
    )
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/main.py
git commit -m "feat: start chat scorer background loop in orchestrator lifespan"
```

---

## Chunk 5: Conversation-Level Scoring

Compute session-level outcome when conversations go quiet.

### Task 5.1: Add conversation scoring to chat_scorer

**Files:**
- Modify: `orchestrator/app/chat_scorer.py`

- [ ] **Step 1: Add _compute_conversation_scores() function**

Add this function after `_check_abandonments()`:

```python
async def _compute_conversation_scores() -> int:
    """Compute session-level scores for quiet conversations."""
    redis = get_redis()
    pool = get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    scores_written = 0

    async with pool.acquire() as conn:
        # Find conversations with scored turns but no recent activity
        rows = await conn.fetch(
            """
            SELECT DISTINCT ue.session_id
            FROM usage_events ue
            WHERE ue.session_id IS NOT NULL
              AND ue.outcome_score IS NOT NULL
              AND ue.created_at < $1
              AND NOT EXISTS (
                  SELECT 1 FROM messages m
                  WHERE m.conversation_id::text = ue.session_id
                    AND m.created_at > $1
              )
            LIMIT 20
            """,
            cutoff,
        )

        for row in rows:
            sid = row["session_id"]

            # Check dedup — skip if already scored recently
            if await redis.sismember(SCORED_CONVOS_KEY, sid):
                continue

            # Get all scored turns for this session, ordered by time
            turns = await conn.fetch(
                """
                SELECT outcome_score, outcome_confidence, created_at
                FROM usage_events
                WHERE session_id = $1 AND outcome_score IS NOT NULL
                ORDER BY created_at ASC
                """,
                sid,
            )

            if not turns:
                continue

            # Weighted average biased toward final turns
            n = len(turns)
            weights = [0.5 + 0.5 * (i / max(n - 1, 1)) for i in range(n)]
            total_w = sum(weights)
            session_score = sum(
                t["outcome_score"] * w for t, w in zip(turns, weights)
            ) / total_w

            # Write to conversation_outcomes
            await conn.execute(
                """
                INSERT INTO conversation_outcomes
                    (session_id, session_score, turn_count)
                VALUES ($1, $2, $3)
                """,
                sid,
                round(session_score, 3),
                n,
            )

            # Mark as scored (2h expiry)
            await redis.sadd(SCORED_CONVOS_KEY, sid)
            await redis.expire(SCORED_CONVOS_KEY, 7200)

            scores_written += 1

    return scores_written
```

- [ ] **Step 2: Call it from the main loop**

In `chat_scorer_loop()`, after the abandonment check, add:

```python
            conv_scores = await _compute_conversation_scores()
            if conv_scores:
                log.info("Chat scorer: %d conversation scores computed", conv_scores)
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/chat_scorer.py
git commit -m "feat: add conversation-level success scoring to chat scorer"
```

---

## Chunk 6: Engram ID Breadcrumbs

Thread engram IDs from memory-service through orchestrator to usage_events.

### Task 6.1: Return engram_ids from memory-service /context

**Files:**
- Modify: `memory-service/app/engram/working_memory.py`
- Modify: `memory-service/app/engram/router.py`

- [ ] **Step 1: Add engram_ids to WorkingMemoryContext**

In `working_memory.py`, the `WorkingMemoryContext` dataclass (find it above `assemble_context()`) needs an `engram_ids` field. Add:

```python
    engram_ids: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Populate engram_ids in assemble_context()**

In `assemble_context()`, after the spreading activation call (around the line `activated = await spreading_activation(session, query)`), store the IDs:

```python
    if activated:
        ctx.engram_ids = [str(e.id) for e in activated]
```

- [ ] **Step 3: Include engram_ids in the /context response**

In `router.py`, the `/context` endpoint (line 163–192) returns a dict. Add `engram_ids`:

```python
    return {
        "context": prompt,
        "total_tokens": ctx.total_tokens,
        "engram_ids": ctx.engram_ids,
        "sections": {
            "self_model": bool(ctx.self_model),
            "active_goal": bool(ctx.active_goal),
            "memories": bool(ctx.memories),
            "key_decisions": bool(ctx.key_decisions),
            "open_threads": bool(ctx.open_threads),
        },
    }
```

- [ ] **Step 4: Commit**

```bash
git add memory-service/app/engram/working_memory.py memory-service/app/engram/router.py
git commit -m "feat: return engram_ids from /api/v1/engrams/context endpoint"
```

### Task 6.2: Thread engram_ids through orchestrator runner

**Files:**
- Modify: `orchestrator/app/agents/runner.py`

- [ ] **Step 1: Update _get_memory_context() return type**

Change the function signature (line 282) from `tuple[str, int]` to `tuple[str, int, list[str]]`. Update the function to extract and return `engram_ids`:

```python
async def _get_memory_context(agent_id: str, query: str, session_id: str = "") -> tuple[str, int, list[str]]:
    """Fetch engram-powered memory context for prompt assembly.

    Returns (context_string, section_count, engram_ids).
    """
    if not query:
        return "", 0, []

    memory_client = get_memory_client()
    try:
        resp = await memory_client.post(
            "/api/v1/engrams/context",
            params={"query": query, "session_id": session_id},
        )
        if resp.status_code != 200:
            return "", 0, []
        data = resp.json()
        context = data.get("context", "")
        if not context:
            return "", 0, []
        sections = data.get("sections", {})
        section_count = sum(1 for v in sections.values() if v)
        engram_ids = data.get("engram_ids", [])
        return context, section_count, engram_ids
    except Exception as e:
        log.warning("Engram memory retrieval failed: %s", e)
        return "", 0, []
```

- [ ] **Step 2: Update callers to destructure new return type**

In `run_agent_turn()` (line 65), the gather call destructures the result:

```python
nova_ctx, (memory_ctx, _mem_count), (category, classified_model) = await asyncio.gather(...)
```

Change to:

```python
nova_ctx, (memory_ctx, _mem_count, _engram_ids), (category, classified_model) = await asyncio.gather(...)
```

In `run_agent_turn_streaming()` (line 190), similarly update:

```python
(nova_ctx, _ctx_ms), ((memory_ctx, memory_count, _engram_ids), mem_ms), ((category, classified_model), cls_ms) = await asyncio.gather(...)
```

- [ ] **Step 3: Pass engram_ids to log_usage() metadata**

In both `run_agent_turn()` (line 90) and `run_agent_turn_streaming()` (line 270), update the `log_usage()` calls to include metadata with engram_ids:

```python
_usage_meta = {"task_type": "chat"}
if _engram_ids:
    _usage_meta["engram_ids"] = _engram_ids

log_usage(
    api_key_id=api_key_id,
    agent_id=UUID(agent_id),
    session_id=session_id,
    model=model,
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    cost_usd=cost_usd,
    duration_ms=duration_ms,
    metadata=_usage_meta,
)
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/agents/runner.py
git commit -m "feat: thread engram IDs from memory context into usage events"
```

---

## Chunk 7: Confidence-Weighted Effectiveness Matrix

Update aggregation, add failure detection, add memory outcome feedback batch.

### Task 7.1: Update effectiveness.py aggregation

**Files:**
- Modify: `orchestrator/app/effectiveness.py`

- [ ] **Step 1: Replace the aggregation query**

In `compute_and_publish()`, replace the existing SQL query with the confidence-weighted version:

```python
        rows = await conn.fetch("""
            SELECT model,
                   COALESCE(metadata->>'task_type', 'unknown') AS task_type,
                   SUM(outcome_score * outcome_confidence) / NULLIF(SUM(outcome_confidence), 0) AS avg_score,
                   COUNT(*) AS sample_count
            FROM usage_events
            WHERE outcome_score IS NOT NULL
              AND outcome_confidence IS NOT NULL
              AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY 1, 2
        """)
```

- [ ] **Step 2: Add failure pattern detection**

Add this function after `compute_and_publish()`:

```python
CAPABILITY_GAP_KEY = "nova:signals:capability_gaps"


async def _detect_capability_gaps(matrix: dict) -> None:
    """Find task_types where all models underperform and signal to cortex."""
    # Group by task_type
    task_types: dict[str, list[dict]] = {}
    for key, entry in matrix.items():
        _, task_type = key.rsplit(":", 1)
        task_types.setdefault(task_type, []).append(entry)

    gaps = []
    for task_type, entries in task_types.items():
        total_samples = sum(e["sample_count"] for e in entries)
        if total_samples < 20:
            continue  # Not enough data
        best_score = max(e["avg_score"] for e in entries)
        if best_score < 0.5:
            gaps.append({
                "task_type": task_type,
                "best_score": best_score,
                "sample_count": total_samples,
            })

    try:
        redis = get_redis()
        if gaps:
            import json
            await redis.set(CAPABILITY_GAP_KEY, json.dumps(gaps), ex=REDIS_TTL)
            log.info("Capability gaps detected: %s", [g["task_type"] for g in gaps])
        else:
            await redis.delete(CAPABILITY_GAP_KEY)
    except Exception:
        log.warning("Failed to publish capability gaps", exc_info=True)
```

- [ ] **Step 3: Call it from compute_and_publish()**

At the end of `compute_and_publish()`, before the `return` statement, add:

```python
    await _detect_capability_gaps(matrix)
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/effectiveness.py
git commit -m "feat: confidence-weighted effectiveness matrix with failure detection"
```

### Task 7.2: Add memory outcome feedback batch

**Files:**
- Modify: `orchestrator/app/effectiveness.py`

- [ ] **Step 1: Add _send_memory_feedback() function**

Add this after `_detect_capability_gaps()`:

```python
FEEDBACK_CURSOR_KEY = "nova:state:outcome_feedback_cursor"


async def _send_memory_feedback() -> int:
    """Send outcome scores for engram-backed interactions to memory-service."""
    redis = get_redis()
    pool = get_pool()

    cursor_raw = await redis.get(FEEDBACK_CURSOR_KEY)
    if cursor_raw:
        cursor = datetime.fromisoformat(cursor_raw)
    else:
        cursor = datetime.now(timezone.utc) - timedelta(hours=1)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT metadata->'engram_ids' AS engram_ids,
                   outcome_score,
                   COALESCE(metadata->>'task_type', 'unknown') AS task_type
            FROM usage_events
            WHERE outcome_score IS NOT NULL
              AND metadata->'engram_ids' IS NOT NULL
              AND jsonb_array_length(metadata->'engram_ids') > 0
              AND created_at > $1
            ORDER BY created_at ASC
            LIMIT 500
            """,
            cursor,
        )

    if not rows:
        return 0

    # Build feedback batch
    feedback = []
    for row in rows:
        engram_ids = row["engram_ids"]  # already parsed as list by asyncpg JSONB codec
        if not isinstance(engram_ids, list):
            continue
        for eid in engram_ids:
            feedback.append({
                "engram_id": str(eid),
                "outcome_score": float(row["outcome_score"]),
                "task_type": row["task_type"],
            })

    if not feedback:
        return 0

    # Send to memory-service
    try:
        from .clients import get_memory_client
        client = get_memory_client()
        resp = await client.post("/api/v1/engrams/outcome-feedback", json=feedback)
        if resp.status_code in (200, 201):
            log.info("Sent %d engram outcome feedback entries", len(feedback))
        else:
            log.warning("Memory outcome feedback failed: %d %s", resp.status_code, resp.text[:200])
    except Exception:
        log.warning("Failed to send memory outcome feedback", exc_info=True)

    # Update cursor
    now = datetime.now(timezone.utc)
    await redis.set(FEEDBACK_CURSOR_KEY, now.isoformat())

    return len(feedback)
```

- [ ] **Step 2: Add necessary imports at top of effectiveness.py**

```python
from datetime import datetime, timezone, timedelta
```

- [ ] **Step 3: Call it from compute_and_publish()**

At the end of `compute_and_publish()`, after the capability gaps call:

```python
    feedback_count = await _send_memory_feedback()
    if feedback_count:
        log.info("Sent %d memory outcome feedback entries", feedback_count)
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/effectiveness.py
git commit -m "feat: add memory outcome feedback batch to hourly effectiveness loop"
```

---

## Chunk 8: Memory Outcome Feedback Endpoint

### Task 8.1: Add outcome columns to engrams schema

**Files:**
- Modify: `memory-service/app/db/schema.sql`

- [ ] **Step 1: Add outcome tracking columns to engrams table**

Add these columns to the `engrams` CREATE TABLE statement (after the existing columns, before the closing paren). Use `IF NOT EXISTS`-safe ALTER statements at the end of the file:

```sql
-- Outcome scoring feedback columns
ALTER TABLE engrams ADD COLUMN IF NOT EXISTS outcome_avg REAL DEFAULT NULL;
ALTER TABLE engrams ADD COLUMN IF NOT EXISTS outcome_count INTEGER DEFAULT 0;
ALTER TABLE engrams ADD COLUMN IF NOT EXISTS last_recalibrated_at TIMESTAMPTZ DEFAULT NULL;
```

- [ ] **Step 2: Commit**

```bash
git add memory-service/app/db/schema.sql
git commit -m "feat: add outcome tracking columns to engrams table"
```

### Task 8.2: Create outcome feedback processor

**Files:**
- Create: `memory-service/app/engram/outcome_feedback.py`

- [ ] **Step 1: Create the module**

```python
"""Outcome feedback processor — adjusts engram activation, importance, and edges
based on LLM interaction outcome scores from the orchestrator.

Called via POST /api/v1/engrams/outcome-feedback with a batch of
{engram_id, outcome_score, task_type} entries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# Thresholds
POSITIVE_THRESHOLD = 0.7
NEGATIVE_THRESHOLD = 0.4
ACTIVATION_BOOST = 0.05
IMPORTANCE_NUDGE = 0.05
IMPORTANCE_FLOOR = 0.1
IMPORTANCE_CEILING = 1.0
MIN_OBSERVATIONS = 5
EDGE_WEIGHT_BOOST = 0.02
EDGE_WEIGHT_CEILING = 1.0


async def process_feedback(
    session: AsyncSession,
    feedback: list[dict],
) -> dict:
    """Process a batch of outcome feedback entries.

    Each entry: {"engram_id": "uuid", "outcome_score": float, "task_type": str}

    Returns stats: {"activations": int, "recalibrations": int, "edges": int}
    """
    stats = {"activations": 0, "recalibrations": 0, "edges": 0}

    # Group by interaction (entries from the same batch with same score = same interaction)
    # For edge reinforcement, we need to know which engrams were in the same interaction
    interactions: dict[float, list[str]] = {}
    for entry in feedback:
        score = entry.get("outcome_score", 0.5)
        eid = entry.get("engram_id")
        if not eid:
            continue
        interactions.setdefault(score, []).append(eid)

    # Process each entry
    for entry in feedback:
        eid = entry.get("engram_id")
        score = entry.get("outcome_score", 0.5)
        if not eid:
            continue

        try:
            eid_uuid = UUID(eid)
        except ValueError:
            continue

        # 1. Activation boost for positive outcomes
        if score > POSITIVE_THRESHOLD:
            await session.execute(
                text("""
                    UPDATE engrams
                    SET activation = LEAST(1.0, activation + :boost * (1.0 - activation)),
                        updated_at = NOW()
                    WHERE id = :eid
                """),
                {"eid": eid_uuid, "boost": ACTIVATION_BOOST},
            )
            stats["activations"] += 1

        # 2. Update rolling outcome stats
        await session.execute(
            text("""
                UPDATE engrams
                SET outcome_avg = CASE
                        WHEN outcome_count = 0 THEN :score
                        ELSE (outcome_avg * outcome_count + :score) / (outcome_count + 1)
                    END,
                    outcome_count = outcome_count + 1,
                    updated_at = NOW()
                WHERE id = :eid
            """),
            {"eid": eid_uuid, "score": score},
        )

        # 3. Importance recalibration (at most once per day per engram)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        result = await session.execute(
            text("""
                SELECT outcome_avg, outcome_count, last_recalibrated_at, importance
                FROM engrams WHERE id = :eid
            """),
            {"eid": eid_uuid},
        )
        row = result.fetchone()
        if row and row.outcome_count >= MIN_OBSERVATIONS:
            can_recalibrate = (
                row.last_recalibrated_at is None or row.last_recalibrated_at < yesterday
            )
            if can_recalibrate:
                new_importance = row.importance
                if row.outcome_avg > POSITIVE_THRESHOLD:
                    new_importance = min(IMPORTANCE_CEILING, row.importance + IMPORTANCE_NUDGE)
                elif row.outcome_avg < NEGATIVE_THRESHOLD:
                    new_importance = max(IMPORTANCE_FLOOR, row.importance - IMPORTANCE_NUDGE)
                else:
                    continue  # No change needed

                if new_importance != row.importance:
                    await session.execute(
                        text("""
                            UPDATE engrams
                            SET importance = :imp, last_recalibrated_at = NOW(), updated_at = NOW()
                            WHERE id = :eid
                        """),
                        {"eid": eid_uuid, "imp": new_importance},
                    )
                    stats["recalibrations"] += 1

    # 4. Outcome-driven Hebbian learning: strengthen edges between co-successful engrams
    for score, eids in interactions.items():
        if score <= POSITIVE_THRESHOLD or len(eids) < 2:
            continue
        # Strengthen edges between all pairs
        for i, eid_a in enumerate(eids):
            for eid_b in eids[i + 1:]:
                try:
                    a_uuid, b_uuid = UUID(eid_a), UUID(eid_b)
                except ValueError:
                    continue
                # Update edge in both directions (if exists)
                result = await session.execute(
                    text("""
                        UPDATE engram_edges
                        SET weight = LEAST(:ceiling, weight + :boost),
                            co_activations = co_activations + 1,
                            last_co_activated = NOW()
                        WHERE (source_id = :a AND target_id = :b)
                           OR (source_id = :b AND target_id = :a)
                    """),
                    {
                        "a": a_uuid, "b": b_uuid,
                        "boost": EDGE_WEIGHT_BOOST,
                        "ceiling": EDGE_WEIGHT_CEILING,
                    },
                )
                stats["edges"] += 1

    await session.commit()
    return stats
```

- [ ] **Step 2: Commit**

```bash
git add memory-service/app/engram/outcome_feedback.py
git commit -m "feat: add outcome feedback processor for engram reinforcement"
```

### Task 8.3: Add /outcome-feedback endpoint to engram router

**Files:**
- Modify: `memory-service/app/engram/router.py`

- [ ] **Step 1: Add the endpoint**

Add this endpoint to the engram router:

```python
from .outcome_feedback import process_feedback

@engram_router.post("/outcome-feedback")
async def receive_outcome_feedback(feedback: list[dict]):
    """Receive outcome scores and adjust engram activation/importance/edges."""
    async with get_db() as session:
        stats = await process_feedback(session, feedback)
    return {"status": "ok", **stats}
```

- [ ] **Step 2: Commit**

```bash
git add memory-service/app/engram/router.py
git commit -m "feat: add /outcome-feedback endpoint to engram router"
```

---

## Chunk 9: Model Exploration Budget

### Task 9.1: Add exploration logic to tier resolver

**Files:**
- Modify: `llm-gateway/app/tier_resolver.py`

- [ ] **Step 1: Add exploration constants and helper**

Near the top of `tier_resolver.py` (after the existing constants), add:

```python
import random

EXPLORE_RATE = 0.05        # 5% of requests explore
EXPLORE_MIN_SAMPLES = 50   # models with fewer samples are "undersampled"
```

Add a helper function:

```python
def _sample_count(model_id: str, task_type: str, effectiveness: dict) -> int:
    """Get sample count for a model×task_type from effectiveness matrix."""
    key = f"{model_id}:{task_type}"
    entry = effectiveness.get(key)
    return entry.get("sample_count", 0) if entry else 0
```

- [ ] **Step 2: Add exploration to _resolve_tier_to_model()**

In `_resolve_tier_to_model()`, right before the main `for model_id in candidates:` loop, add the exploration check:

```python
        # Exploration: occasionally try undersampled models
        if task_type and random.random() < EXPLORE_RATE:
            undersampled = [
                m for m in candidates
                if _sample_count(m, task_type, effectiveness) < EXPLORE_MIN_SAMPLES
            ]
            if undersampled:
                chosen = random.choice(undersampled)
                resolved = _resolve_virtual(chosen)
                if resolved and resolved in MODEL_REGISTRY:
                    provider = MODEL_REGISTRY[resolved]
                    if provider.is_available:
                        has_quota, _ = await check_remaining_quota(resolved)
                        if has_quota:
                            log.info(
                                "Exploration: tier=%s task_type=%s → %s (undersampled)",
                                try_tier, task_type, resolved,
                            )
                            return resolved
```

This goes inside the `for try_tier in TIER_ORDER[tier_idx:]:` loop, after the `candidates` list is built and effectiveness-filtered, but before the normal iteration.

- [ ] **Step 3: Commit**

```bash
git add llm-gateway/app/tier_resolver.py
git commit -m "feat: add model exploration budget to tier resolver"
```

---

## Chunk 10: Cortex Learn Drive

### Task 10.1: Update learn drive to read capability gaps

**Files:**
- Modify: `cortex/app/drives/learn.py`

- [ ] **Step 1: Replace the stub with capability gap awareness**

```python
"""Learn drive — identify and act on capability gaps.

Reads nova:signals:capability_gaps from Redis (published hourly by the
orchestrator's effectiveness matrix computation). When capability gaps
exist (all models underperform for a task_type), reports high urgency
so cortex prioritizes learning actions.
"""
from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from ..config import settings
from . import DriveResult

log = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
CAPABILITY_GAP_KEY = "nova:signals:capability_gaps"


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def assess() -> DriveResult:
    """Check for capability gaps and report urgency."""
    try:
        r = await _get_redis()
        raw = await r.get(CAPABILITY_GAP_KEY)
        if not raw:
            return DriveResult(
                name="learn", priority=4, urgency=0.0,
                description="No capability gaps detected",
            )

        gaps = json.loads(raw)
        if not gaps:
            return DriveResult(
                name="learn", priority=4, urgency=0.0,
                description="No capability gaps detected",
            )

        # Urgency scales with number and severity of gaps
        worst_score = min(g["best_score"] for g in gaps)
        urgency = min(1.0, 0.4 + 0.2 * len(gaps) + 0.3 * (1.0 - worst_score))

        gap_summary = ", ".join(
            f"{g['task_type']} (best={g['best_score']:.2f}, n={g['sample_count']})"
            for g in gaps
        )

        return DriveResult(
            name="learn",
            priority=4,
            urgency=round(urgency, 2),
            description=f"Capability gaps detected: {gap_summary}",
            proposed_action=(
                f"Investigate capability gaps in: {', '.join(g['task_type'] for g in gaps)}. "
                "Consider: improving context retrieval, adjusting system prompts, "
                "or reviewing recent low-scoring interactions for patterns."
            ),
            context={"gaps": gaps},
        )

    except Exception as e:
        log.debug("Learn drive assessment failed: %s", e)
        return DriveResult(
            name="learn", priority=4, urgency=0.0,
            description="Learn drive error — no signal",
        )
```

- [ ] **Step 2: Commit**

```bash
git add cortex/app/drives/learn.py
git commit -m "feat: cortex learn drive reads capability gaps from Redis"
```

---

## Integration Testing

After all chunks are complete:

- [ ] **Test 1: Service health** — `make test-quick` — all services start and pass health checks
- [ ] **Test 2: Migration applied** — `docker compose exec postgres psql -U nova -d nova -c "SELECT * FROM schema_migrations WHERE version LIKE '023%'"` shows the new migration
- [ ] **Test 3: Schema verified** — `docker compose exec postgres psql -U nova -d nova -c "\d usage_events"` shows `outcome_confidence` column
- [ ] **Test 4: Cortex usage endpoint** — `curl -X POST http://localhost:8000/api/v1/usage/events -H "Content-Type: application/json" -d '{"model":"test","outcome_score":0.8,"outcome_confidence":0.9,"metadata":{"task_type":"test"}}'` returns 201
- [ ] **Test 5: Effectiveness matrix** — Check orchestrator logs for "Published effectiveness matrix" after rebuild
- [ ] **Test 6: Chat scorer running** — Check orchestrator logs for "Chat scorer started"
- [ ] **Test 7: Engram context** — `curl http://localhost:8002/api/v1/engrams/context -X POST -d 'query=test'` response includes `engram_ids` field

---

## Post-Implementation

- [ ] Update this plan's progress tracker
- [ ] Update spec success criteria checkboxes
- [ ] Commit final state
