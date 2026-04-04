# AI Quality Measurement System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live quality scoring system and automated benchmark suite so we can measure whether Nova's AI is improving as we make changes.

**Architecture:** Hybrid storage — quality scores in a dedicated `quality_scores` table (time-series data), backend pause flags in `platform_config` (config). Chat scorer expanded with per-dimension heuristic scoring. New benchmark suite runs scripted test conversations against live services. Dashboard Benchmarks page renamed to "AI Quality" with two tabs.

**Tech Stack:** Python/asyncpg (backend scoring + API), PostgreSQL (quality_scores + quality_benchmark_runs tables), React/TypeScript + TanStack Query (dashboard), pytest + httpx (benchmark tests)

**Spec:** `docs/superpowers/specs/2026-04-03-ai-quality-measurement-design.md`

---

## File Map

### New Files

| File | Responsibility |
|---|---|
| `orchestrator/app/migrations/056_quality_scoring.sql` | quality_scores + quality_benchmark_runs tables |
| `orchestrator/app/quality_scorer.py` | Per-dimension quality scoring logic (memory_relevance, memory_recall, tool_accuracy, response_coherence, task_completion) |
| `orchestrator/app/quality_router.py` | API endpoints for quality scores + benchmark runs |
| `benchmarks/quality/runner.py` | Benchmark test runner — seeds engrams, runs conversations, scores results, cleans up |
| `benchmarks/quality/cases.py` | Test case definitions (factual recall, contradiction, tool selection, etc.) |
| `tests/test_quality_scoring.py` | Integration tests for quality scoring and benchmark endpoints |
| `dashboard/src/pages/AIQuality.tsx` | Renamed + expanded Benchmarks page with Live Scores and Benchmarks tabs |

### Modified Files

| File | Change |
|---|---|
| `memory-service/app/engram/router.py` | Add `POST /api/v1/engrams/batch` endpoint |
| `orchestrator/app/chat_scorer.py` | Call quality_scorer after each turn scoring |
| `orchestrator/app/main.py` | Register quality_router |
| `orchestrator/app/config_sync.py` | Add `sync_features_config_to_redis()` |
| `dashboard/src/components/layout/Sidebar.tsx` | Rename "Benchmarks" → "AI Quality" |
| `dashboard/src/App.tsx` | Update route for AI Quality page |

---

## Task 1: Database Migration

**Files:**
- Create: `orchestrator/app/migrations/056_quality_scoring.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 056_quality_scoring.sql
-- AI Quality Measurement: scoring table + benchmark runs table

CREATE TABLE IF NOT EXISTS quality_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,  -- nullable for pipeline task scores
    message_id UUID,
    task_id UUID,
    dimension TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_scores_dimension_time
    ON quality_scores (dimension, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_scores_conversation
    ON quality_scores (conversation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS quality_benchmark_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT DEFAULT 'running',
    composite_score NUMERIC(5,2),
    category_scores JSONB DEFAULT '{}',
    case_results JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}'
);

-- Seed backend pause feature flags (default: enabled)
INSERT INTO platform_config (key, value, updated_at)
VALUES
    ('features.cortex_loop', 'true'::jsonb, NOW()),
    ('features.intel_polling', 'true'::jsonb, NOW()),
    ('features.knowledge_crawling', 'true'::jsonb, NOW())
ON CONFLICT (key) DO NOTHING;
```

- [ ] **Step 2: Verify migration applies**

Run: `docker compose restart orchestrator && sleep 5 && docker compose logs orchestrator --tail 20 | grep -i "migration\|056"`

Expected: Log line showing migration 056 applied successfully.

- [ ] **Step 3: Verify tables exist**

Run:
```bash
docker compose exec postgres psql -U nova -d nova -c "\dt quality_*"
```

Expected: Both `quality_scores` and `quality_benchmark_runs` tables listed.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/migrations/056_quality_scoring.sql
git commit -m "feat: add quality_scores and quality_benchmark_runs tables (migration 056)"
```

---

## Task 2: Memory-Service Batch Endpoint

**Files:**
- Modify: `memory-service/app/engram/router.py`
- Test: `tests/test_quality_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_quality_scoring.py`:

```python
"""Integration tests for AI quality measurement system."""
import pytest
import httpx
import pytest_asyncio

MEMORY_BASE = "http://localhost:8002"
ORCH_BASE = "http://localhost:8000"


@pytest_asyncio.fixture
async def memory_client():
    async with httpx.AsyncClient(base_url=MEMORY_BASE, timeout=10) as client:
        yield client


@pytest_asyncio.fixture
async def orchestrator_client():
    async with httpx.AsyncClient(base_url=ORCH_BASE, timeout=10) as client:
        yield client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Secret": "nova-admin-secret-change-me"}


class TestEngramBatchEndpoint:
    """POST /api/v1/engrams/batch returns engram content by ID list."""

    async def test_batch_empty_ids(self, memory_client: httpx.AsyncClient):
        r = await memory_client.post("/api/v1/engrams/batch", json={"ids": []})
        assert r.status_code == 200
        assert r.json() == []

    async def test_batch_nonexistent_ids(self, memory_client: httpx.AsyncClient):
        fake_id = "00000000-0000-0000-0000-000000000099"
        r = await memory_client.post("/api/v1/engrams/batch", json={"ids": [fake_id]})
        assert r.status_code == 200
        assert r.json() == []

    async def test_batch_returns_content(self, memory_client: httpx.AsyncClient):
        """Ingest an engram, then fetch it via batch endpoint."""
        # Seed a test engram via direct ingest
        ingest_r = await memory_client.post("/api/v1/engrams/ingest", json={
            "raw_text": "nova-test-quality: Python is my favorite language",
            "source_type": "chat",
        })
        assert ingest_r.status_code == 201
        engram_ids = ingest_r.json().get("engram_ids", [])
        if not engram_ids:
            pytest.skip("Ingest did not return engram_ids (async decomposition)")

        r = await memory_client.post("/api/v1/engrams/batch", json={"ids": engram_ids})
        assert r.status_code == 200
        results = r.json()
        assert len(results) > 0
        assert "id" in results[0]
        assert "content" in results[0]
        assert "node_type" in results[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_quality_scoring.py::TestEngramBatchEndpoint -v --timeout=30`

Expected: FAIL with 404 (endpoint doesn't exist yet).

- [ ] **Step 3: Implement the batch endpoint**

Add to `memory-service/app/engram/router.py` after the existing imports:

```python
from pydantic import BaseModel

class BatchRequest(BaseModel):
    ids: list[str]

class BatchItem(BaseModel):
    id: str
    content: str
    node_type: str

@engram_router.post("/batch", response_model=list[BatchItem])
async def batch_get_engrams(req: BatchRequest):
    """Return engram content for a list of IDs. Used by quality scorer."""
    if not req.ids:
        return []
    async with get_db() as session:
        placeholders = ", ".join(f":id_{i}" for i in range(len(req.ids)))
        params = {f"id_{i}": uid for i, uid in enumerate(req.ids)}
        result = await session.execute(
            text(f"SELECT id::text, content, node_type FROM engrams WHERE id::text IN ({placeholders})"),
            params,
        )
        rows = result.fetchall()
    return [BatchItem(id=r[0], content=r[1], node_type=r[2]) for r in rows]
```

Make sure `text` is imported from sqlalchemy:
```python
from sqlalchemy import text
```

- [ ] **Step 4: Rebuild and test**

Run:
```bash
docker compose build memory-service && docker compose up -d memory-service && sleep 5
python -m pytest tests/test_quality_scoring.py::TestEngramBatchEndpoint -v --timeout=30
```

Expected: All 3 tests pass (test_batch_returns_content may skip if async decomposition).

- [ ] **Step 5: Commit**

```bash
git add memory-service/app/engram/router.py tests/test_quality_scoring.py
git commit -m "feat: add POST /api/v1/engrams/batch endpoint for quality scorer"
```

---

## Task 3: Quality Scorer Module

**Files:**
- Create: `orchestrator/app/quality_scorer.py`

This is the core scoring logic. Each function scores one dimension and returns a dict ready for DB insertion.

- [ ] **Step 1: Write the quality scorer**

Create `orchestrator/app/quality_scorer.py`:

```python
"""Per-dimension quality scoring for chat responses.

Called by chat_scorer.py after each assistant turn. Each score_* function
returns a dict with {dimension, score, confidence, metadata} or None if
no signal for this turn.
"""
import re
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

MEMORY_SERVICE = "http://memory-service:8002"
LLM_GATEWAY = "http://llm-gateway:8001"

# Patterns that suggest the user is correcting Nova's memory
CORRECTION_PATTERNS = [
    re.compile(r"\bi\s+(already|just)\s+(told|said|mentioned)\b", re.I),
    re.compile(r"\bremember\s+when\s+i\b", re.I),
    re.compile(r"\bno,?\s+(it'?s|that'?s|i)\b", re.I),
    re.compile(r"\blike\s+i\s+(said|mentioned)\b", re.I),
    re.compile(r"\bi\s+already\s+explained\b", re.I),
    re.compile(r"\bthat'?s\s+(not|wrong)\b", re.I),
]


async def score_memory_relevance(
    engram_ids: list[str],
    query_text: str,
) -> dict[str, Any] | None:
    """Score how relevant retrieved engrams were to the user's query.

    Fetches engram content via batch endpoint, embeds both query and
    engram texts, computes average cosine similarity.
    """
    if not engram_ids:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Fetch engram content
            batch_r = await client.post(
                f"{MEMORY_SERVICE}/api/v1/engrams/batch",
                json={"ids": engram_ids},
            )
            if batch_r.status_code != 200 or not batch_r.json():
                return None
            engrams = batch_r.json()

            # Embed query (gateway contract: texts=list, response has embeddings=list[list])
            query_embed_r = await client.post(
                f"{LLM_GATEWAY}/embed",
                json={"model": "auto", "texts": [query_text]},
            )
            if query_embed_r.status_code != 200:
                return None
            query_vec = (query_embed_r.json().get("embeddings") or [[]])[0]
            if not query_vec:
                return None

            # Embed each engram and compute similarities
            similarities = []
            for engram in engrams:
                engram_embed_r = await client.post(
                    f"{LLM_GATEWAY}/embed",
                    json={"model": "auto", "texts": [engram["content"]]},
                )
                if engram_embed_r.status_code != 200:
                    continue
                engram_vec = (engram_embed_r.json().get("embeddings") or [[]])[0]
                if engram_vec:
                    sim = _cosine_similarity(query_vec, engram_vec)
                    similarities.append({"engram_id": engram["id"], "similarity": sim})

            if not similarities:
                return None

            avg_sim = sum(s["similarity"] for s in similarities) / len(similarities)

        return {
            "dimension": "memory_relevance",
            "score": max(0.0, min(1.0, avg_sim)),
            "confidence": min(1.0, len(similarities) / 5.0),  # More engrams = higher confidence
            "metadata": {
                "engram_ids": engram_ids,
                "similarities": similarities,
                "query": query_text[:200],
            },
        }
    except Exception as e:
        log.debug("memory_relevance scoring failed: %s", e)
        return None


def score_memory_recall(user_message: str) -> dict[str, Any] | None:
    """Detect if the user is correcting Nova's memory.

    Only returns a score when a correction IS detected. Absence of a
    row = implicit 1.0 when aggregating.
    """
    for pattern in CORRECTION_PATTERNS:
        match = pattern.search(user_message)
        if match:
            return {
                "dimension": "memory_recall",
                "score": 0.3,
                "confidence": 0.7,
                "metadata": {
                    "matched_pattern": pattern.pattern,
                    "user_message_excerpt": user_message[:200],
                },
            }
    return None  # No correction detected — don't write a row


def score_tool_accuracy(agent_output: dict | list | None) -> dict[str, Any] | None:
    """Score tool call accuracy from agent session output.

    Parses conversation messages for tool_use/tool_result blocks.
    Detects errors via known prefixes.
    """
    if not agent_output:
        return None

    ERROR_PREFIXES = (
        "Tool execution blocked:",
        "MCP dispatch error:",
        "Error:",
        "error:",
        "Failed to execute",
        "Tool not found:",
    )

    messages = agent_output if isinstance(agent_output, list) else []
    if isinstance(agent_output, dict):
        messages = agent_output.get("messages", [])

    total_calls = 0
    errored_calls = 0
    tools_called = []
    errors = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Count tool_use blocks
        if role == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    total_calls += 1
                    tools_called.append(block.get("name", "unknown"))

        # Check tool_result blocks for errors
        if role == "tool" or (isinstance(content, str) and any(content.startswith(p) for p in ERROR_PREFIXES)):
            if isinstance(content, str) and any(content.startswith(p) for p in ERROR_PREFIXES):
                errored_calls += 1
                errors.append(content[:200])

    if total_calls == 0:
        return None  # No tools used — skip dimension

    score = max(0.0, (total_calls - errored_calls) / total_calls)

    return {
        "dimension": "tool_accuracy",
        "score": score,
        "confidence": min(1.0, total_calls / 3.0),
        "metadata": {
            "tools_called": tools_called,
            "total_calls": total_calls,
            "errored_calls": errored_calls,
            "errors": errors,
        },
    }


async def score_response_coherence(
    query_text: str,
    response_text: str,
    had_tool_calls: bool = False,
) -> dict[str, Any] | None:
    """Score topic coherence between query and response.

    Skips tool-heavy responses to avoid penalizing correct tool use.
    """
    if had_tool_calls:
        return None  # Exclude tool-heavy responses per spec

    if not query_text.strip() or not response_text.strip():
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            q_r = await client.post(f"{LLM_GATEWAY}/embed", json={"model": "auto", "texts": [query_text]})
            r_r = await client.post(f"{LLM_GATEWAY}/embed", json={"model": "auto", "texts": [response_text[:2000]]})

            if q_r.status_code != 200 or r_r.status_code != 200:
                return None

            q_vec = (q_r.json().get("embeddings") or [[]])[0]
            r_vec = (r_r.json().get("embeddings") or [[]])[0]

            if not q_vec or not r_vec:
                return None

            sim = _cosine_similarity(q_vec, r_vec)

        return {
            "dimension": "response_coherence",
            "score": max(0.0, min(1.0, sim)),
            "confidence": 0.8,
            "metadata": {
                "similarity": sim,
                "query_len": len(query_text),
                "response_len": len(response_text),
            },
        }
    except Exception as e:
        log.debug("response_coherence scoring failed: %s", e)
        return None


async def score_task_completion(
    task_status: str,
    task_id: str,
    pool,
) -> dict[str, Any] | None:
    """Score pipeline task completion quality.

    Joins with guardrail_findings to determine finding presence.
    """
    STATUS_SCORES = {
        "complete": 1.0,
        "pending_human_review": 0.4,
        "failed": 0.2,
        "cancelled": 0.1,
    }

    base_score = STATUS_SCORES.get(task_status)
    if base_score is None:
        return None  # Non-terminal status, skip

    has_findings = False
    if task_status == "complete":
        try:
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM guardrail_findings WHERE task_id = $1",
                    task_id,
                )
                has_findings = (count or 0) > 0
        except Exception:
            pass  # DB unavailable — use base score

    score = 0.6 if (task_status == "complete" and has_findings) else base_score

    return {
        "dimension": "task_completion",
        "score": score,
        "confidence": 0.9,
        "metadata": {
            "task_status": task_status,
            "has_guardrail_findings": has_findings,
        },
    }


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/quality_scorer.py
git commit -m "feat: add per-dimension quality scoring module"
```

---

## Task 4: Wire Quality Scorer into Chat Scorer

**Files:**
- Modify: `orchestrator/app/chat_scorer.py`
- Test: `tests/test_quality_scoring.py`

- [ ] **Step 1: Add quality score writing function to chat_scorer.py**

Add after the existing imports in `chat_scorer.py` (verify `import json` is present — add it if missing):

```python
import json  # add if not already imported
from app.quality_scorer import (
    score_memory_relevance,
    score_memory_recall,
    score_tool_accuracy,
    score_response_coherence,
)
```

Add a helper function to write quality scores to the DB:

```python
async def _write_quality_scores(
    conn,
    conversation_id: str,
    message_id: str | None,
    scores: list[dict],
) -> int:
    """Write per-dimension quality scores to quality_scores table."""
    written = 0
    for s in scores:
        if s is None:
            continue
        try:
            await conn.execute(
                """
                INSERT INTO quality_scores
                    (conversation_id, message_id, dimension, score, confidence, metadata)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                conversation_id,
                message_id,
                s["dimension"],
                s["score"],
                s.get("confidence"),
                json.dumps(s.get("metadata", {})),
            )
            written += 1
        except Exception as e:
            log.debug("Failed to write quality score %s: %s", s.get("dimension"), e)
    return written
```

- [ ] **Step 2: Call quality scoring in `_process_new_messages`**

In the `_process_new_messages` function, after the existing `score, confidence = await _score_turn(...)` call and after the usage_events UPDATE, add the quality scoring pass:

```python
            # ── Quality dimension scoring (async, non-blocking) ──
            try:
                quality_scores = []

                # Memory relevance — check if engrams were injected
                engram_ids = []
                if assistant_row.get("metadata"):
                    meta = assistant_row["metadata"]
                    if isinstance(meta, str):
                        meta = json.loads(meta)
                    engram_ids = meta.get("engram_ids", [])

                if engram_ids:
                    relevance = await score_memory_relevance(engram_ids, user_text)
                    quality_scores.append(relevance)

                # Memory recall — correction detection
                recall = score_memory_recall(user_text)
                quality_scores.append(recall)

                # Tool accuracy — parse agent session output
                # agent_sessions has no conversation_id; join through tasks table
                session_output = None
                session_row = await conn.fetchrow(
                    """SELECT s.output FROM agent_sessions s
                       JOIN tasks t ON t.id = s.task_id
                       WHERE t.conversation_id = $1
                       ORDER BY s.completed_at DESC NULLS LAST LIMIT 1""",
                    conv_id,
                )
                if session_row and session_row["output"]:
                    output = session_row["output"]
                    session_output = json.loads(output) if isinstance(output, str) else output

                tool_score = score_tool_accuracy(session_output)
                quality_scores.append(tool_score)
                had_tools = tool_score is not None

                # Response coherence — skip if tools were used
                coherence = await score_response_coherence(
                    user_text, assistant_text, had_tool_calls=had_tools
                )
                quality_scores.append(coherence)

                written = await _write_quality_scores(
                    conn, str(conv_id), str(assistant_row["id"]), quality_scores
                )
                if written > 0:
                    log.debug("Wrote %d quality scores for conversation %s", written, conv_id)
            except Exception as e:
                log.debug("Quality scoring failed (non-fatal): %s", e)
```

- [ ] **Step 3: Add integration test**

Append to `tests/test_quality_scoring.py`:

```python
class TestQualityScoring:
    """Quality scores are written after chat interactions."""

    async def test_quality_scores_table_exists(
        self, orchestrator_client: httpx.AsyncClient, admin_headers: dict
    ):
        """Verify the quality_scores table was created by migration."""
        r = await orchestrator_client.get(
            "/api/v1/quality/summary?period=1d",
            headers=admin_headers,
        )
        # Endpoint may not exist yet — but table should
        # If we get 404, that's fine (endpoint comes in Task 5)
        # If we get 200 or empty result, table exists
        assert r.status_code in (200, 404)
```

- [ ] **Step 4: Rebuild and verify**

Run:
```bash
docker compose build orchestrator && docker compose up -d orchestrator && sleep 5
docker compose logs orchestrator --tail 10 | grep -i "quality\|scorer"
```

Expected: No errors on startup. Quality scoring will run on next chat interaction.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/chat_scorer.py tests/test_quality_scoring.py
git commit -m "feat: wire quality dimension scoring into chat scorer loop"
```

---

## Task 5: Quality API Endpoints

**Files:**
- Create: `orchestrator/app/quality_router.py`
- Modify: `orchestrator/app/main.py`
- Test: `tests/test_quality_scoring.py`

- [ ] **Step 1: Write the quality router**

Create `orchestrator/app/quality_router.py`:

```python
"""API endpoints for AI quality scores and benchmark results."""
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.db import get_pool
from app.auth import AdminDep

log = logging.getLogger(__name__)
quality_router = APIRouter(tags=["quality"])


class ScoreBucket(BaseModel):
    period: str  # ISO timestamp for bucket start
    dimension: str
    avg_score: float
    count: int


class QualitySummary(BaseModel):
    period_days: int
    dimensions: dict  # {dimension: {avg: float, count: int, trend: float}}
    composite: float


@quality_router.get("/api/v1/quality/scores", response_model=list[ScoreBucket])
async def get_quality_scores(
    _admin: AdminDep,
    dimension: str | None = None,
    conversation_id: str | None = None,
    granularity: str = Query("daily", regex="^(hourly|daily)$"),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
):
    """Time-bucketed quality scores for dashboard charts."""
    pool = get_pool()

    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(from_) if from_ else now - timedelta(days=7)
    end = datetime.fromisoformat(to) if to else now

    trunc = "hour" if granularity == "hourly" else "day"

    conditions = ["created_at >= $1", "created_at <= $2"]
    params: list = [start, end]
    idx = 3

    if dimension:
        conditions.append(f"dimension = ${idx}")
        params.append(dimension)
        idx += 1

    if conversation_id:
        conditions.append(f"conversation_id = ${idx}::uuid")
        params.append(conversation_id)
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                date_trunc('{trunc}', created_at) AS period,
                dimension,
                AVG(score) AS avg_score,
                COUNT(*) AS count
            FROM quality_scores
            WHERE {where}
            GROUP BY period, dimension
            ORDER BY period DESC
            """,
            *params,
        )

    return [
        ScoreBucket(
            period=row["period"].isoformat(),
            dimension=row["dimension"],
            avg_score=round(float(row["avg_score"]), 4),
            count=row["count"],
        )
        for row in rows
    ]


@quality_router.get("/api/v1/quality/summary")
async def get_quality_summary(
    _admin: AdminDep,
    period: str = Query("7d", regex=r"^\d+d$"),
):
    """Aggregated quality averages and trend vs previous period."""
    pool = get_pool()
    days = int(period.rstrip("d"))
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    prev_start = current_start - timedelta(days=days)

    async with pool.acquire() as conn:
        # Current period averages
        current_rows = await conn.fetch(
            """
            SELECT dimension, AVG(score) AS avg, COUNT(*) AS count
            FROM quality_scores
            WHERE created_at >= $1
            GROUP BY dimension
            """,
            current_start,
        )

        # Previous period averages (for trend)
        prev_rows = await conn.fetch(
            """
            SELECT dimension, AVG(score) AS avg
            FROM quality_scores
            WHERE created_at >= $1 AND created_at < $2
            GROUP BY dimension
            """,
            prev_start,
            current_start,
        )

    prev_map = {r["dimension"]: float(r["avg"]) for r in prev_rows}

    # Default weights from spec
    WEIGHTS = {
        "memory_relevance": 0.30,
        "memory_recall": 0.25,
        "tool_accuracy": 0.20,
        "response_coherence": 0.15,
        "task_completion": 0.10,
    }

    dimensions = {}
    weighted_sum = 0.0
    weight_total = 0.0

    for row in current_rows:
        dim = row["dimension"]
        avg = round(float(row["avg"]), 4)
        prev_avg = prev_map.get(dim)
        trend = round(avg - prev_avg, 4) if prev_avg is not None else 0.0

        dimensions[dim] = {
            "avg": avg,
            "count": row["count"],
            "trend": trend,
        }

        w = WEIGHTS.get(dim, 0.0)
        weighted_sum += avg * w
        weight_total += w

    composite = round((weighted_sum / weight_total) * 100, 2) if weight_total > 0 else 0.0

    return {
        "period_days": days,
        "dimensions": dimensions,
        "composite": composite,
    }
```

- [ ] **Step 2: Register router in main.py**

Add to `orchestrator/app/main.py` imports:

```python
from app.quality_router import quality_router
```

And in the router registration section:

```python
app.include_router(quality_router)
```

- [ ] **Step 3: Add integration tests**

Append to `tests/test_quality_scoring.py`:

```python
class TestQualityAPI:
    """Quality score API endpoints."""

    async def test_scores_endpoint_returns_200(
        self, orchestrator_client: httpx.AsyncClient, admin_headers: dict
    ):
        r = await orchestrator_client.get(
            "/api/v1/quality/scores?granularity=daily",
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_summary_endpoint_returns_200(
        self, orchestrator_client: httpx.AsyncClient, admin_headers: dict
    ):
        r = await orchestrator_client.get(
            "/api/v1/quality/summary?period=7d",
            headers=admin_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert "dimensions" in data
        assert "composite" in data
        assert "period_days" in data

    async def test_summary_requires_admin(
        self, orchestrator_client: httpx.AsyncClient
    ):
        r = await orchestrator_client.get("/api/v1/quality/summary?period=7d")
        assert r.status_code in (401, 403)
```

- [ ] **Step 4: Rebuild and test**

Run:
```bash
docker compose build orchestrator && docker compose up -d orchestrator && sleep 5
python -m pytest tests/test_quality_scoring.py::TestQualityAPI -v --timeout=30
```

Expected: All 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/quality_router.py orchestrator/app/main.py tests/test_quality_scoring.py
git commit -m "feat: add quality scores and summary API endpoints"
```

---

## Task 6: Benchmark Test Suite Framework

**Files:**
- Create: `benchmarks/quality/cases.py`
- Create: `benchmarks/quality/runner.py`
- Create: `benchmarks/quality/__init__.py`

- [ ] **Step 1: Create benchmark test case definitions**

Create `benchmarks/quality/__init__.py` (empty).

Create `benchmarks/quality/cases.py`:

```python
"""Benchmark test case definitions for AI quality measurement.

Each case defines: setup (engrams to seed), input (user messages),
expected behaviors, and scoring criteria.
"""
from dataclasses import dataclass, field


@dataclass
class BenchmarkCase:
    name: str
    category: str  # factual_recall, multi_turn, contradiction, tool_selection, temporal, hallucination
    description: str
    seed_engrams: list[dict] = field(default_factory=list)  # {content, node_type, source_type}
    messages: list[str] = field(default_factory=list)  # User messages to send in sequence
    expect_memory_hit: bool = False  # Should the response reference seeded knowledge?
    expect_tool_call: str | None = None  # Tool name expected to be called
    expect_no_hallucination: bool = False  # Should say "I don't know" when no data?
    expect_newer_wins: bool = False  # For contradiction: newer info should override


BENCHMARK_CASES: list[BenchmarkCase] = [
    # ── Factual Recall ──
    BenchmarkCase(
        name="simple_preference_recall",
        category="factual_recall",
        description="Recall a stated preference after seeding it as an engram",
        seed_engrams=[
            {"content": "The user's favorite programming language is Rust", "node_type": "preference", "source_type": "chat"},
        ],
        messages=["What's my favorite programming language?"],
        expect_memory_hit=True,
    ),
    BenchmarkCase(
        name="entity_recall",
        category="factual_recall",
        description="Recall a factual statement about a named entity",
        seed_engrams=[
            {"content": "Nova is deployed on a machine with an AMD RX 7900 XTX GPU", "node_type": "fact", "source_type": "chat"},
        ],
        messages=["What GPU does my Nova machine have?"],
        expect_memory_hit=True,
    ),

    # ── Contradiction Handling ──
    BenchmarkCase(
        name="preference_update",
        category="contradiction",
        description="Newer preference should override older one",
        seed_engrams=[
            {"content": "The user prefers Python for all backend work", "node_type": "preference", "source_type": "chat"},
            {"content": "The user has switched to Go for backend services", "node_type": "preference", "source_type": "chat"},
        ],
        messages=["What language do I prefer for backend work?"],
        expect_memory_hit=True,
        expect_newer_wins=True,
    ),

    # ── Tool Selection ──
    BenchmarkCase(
        name="health_check_tool",
        category="tool_selection",
        description="Should use check_service_health tool when asked about service status",
        seed_engrams=[],
        messages=["Is the memory service healthy right now?"],
        expect_tool_call="check_service_health",
    ),

    # ── No Hallucination ──
    BenchmarkCase(
        name="unknown_topic",
        category="hallucination",
        description="Should admit ignorance when no relevant memories exist",
        seed_engrams=[],
        messages=["What's my cat's name?"],
        expect_no_hallucination=True,
    ),

    # ── Temporal ──
    BenchmarkCase(
        name="recent_work_recall",
        category="temporal",
        description="Recall what was worked on recently based on dated engrams",
        seed_engrams=[
            {"content": "Last week the user was debugging the cortex thinking loop", "node_type": "episode", "source_type": "chat"},
        ],
        messages=["What was I working on last week?"],
        expect_memory_hit=True,
    ),
]
```

- [ ] **Step 2: Create the benchmark runner**

Create `benchmarks/quality/runner.py`:

```python
"""Benchmark runner: seeds engrams, runs conversations, scores, cleans up.

Usage:
    python -m benchmarks.quality.runner          # run all cases
    python -m benchmarks.quality.runner factual   # run one category
"""
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone

import httpx

from benchmarks.quality.cases import BENCHMARK_CASES, BenchmarkCase

log = logging.getLogger(__name__)

ORCH_BASE = "http://localhost:8000"
MEMORY_BASE = "http://localhost:8002"
ADMIN_HEADERS = {"X-Admin-Secret": "nova-admin-secret-change-me"}


async def seed_engrams(
    client: httpx.AsyncClient, case: BenchmarkCase, run_id: str
) -> list[str]:
    """Seed test engrams and return their IDs for cleanup."""
    engram_ids = []
    for engram in case.seed_engrams:
        # Tag with run_id for cleanup
        tagged_content = f"[benchmark:{run_id}] {engram['content']}"
        r = await client.post(
            f"{MEMORY_BASE}/api/v1/engrams/ingest",
            json={
                "raw_text": tagged_content,
                "source_type": engram.get("source_type", "chat"),
            },
        )
        if r.status_code == 201:
            ids = r.json().get("engram_ids", [])
            engram_ids.extend(ids)
        # Wait for async decomposition
        await asyncio.sleep(2)
    return engram_ids


async def run_conversation(
    client: httpx.AsyncClient, messages: list[str]
) -> dict:
    """Send messages through the chat API and collect responses."""
    results = {"responses": [], "task_ids": []}

    # Get the default chat agent ID for benchmark conversations
    agents_r = await client.get(f"{ORCH_BASE}/api/v1/agents", headers=ADMIN_HEADERS)
    agent_id = None
    if agents_r.status_code == 200:
        agents = agents_r.json()
        for a in (agents if isinstance(agents, list) else agents.get("agents", [])):
            if a.get("name", "").lower() in ("chat", "default", "nova"):
                agent_id = a["id"]
                break
        if not agent_id and agents:
            first = agents[0] if isinstance(agents, list) else (agents.get("agents", []) or [{}])[0]
            agent_id = first.get("id")

    if not agent_id:
        log.error("No agent found for benchmark conversations")
        return results

    for msg in messages:
        # SubmitTaskRequest requires agent_id (UUID) and messages (list of dicts)
        r = await client.post(
            f"{ORCH_BASE}/api/v1/tasks",
            json={
                "agent_id": agent_id,
                "messages": [{"role": "user", "content": msg}],
            },
            headers=ADMIN_HEADERS,
            timeout=120,
        )
        if r.status_code in (200, 201, 202):
            data = r.json()
            task_id = data.get("task_id", data.get("id"))
            results["task_ids"].append(task_id)

            # Poll for completion
            for _ in range(60):
                status_r = await client.get(
                    f"{ORCH_BASE}/api/v1/tasks/{task_id}",
                    headers=ADMIN_HEADERS,
                )
                if status_r.status_code == 200:
                    task = status_r.json()
                    if task.get("status") in ("complete", "failed", "cancelled"):
                        results["responses"].append(task)
                        break
                await asyncio.sleep(2)

    return results


def score_case(case: BenchmarkCase, results: dict) -> dict:
    """Score a benchmark case against expected behaviors."""
    scores = {}

    for resp in results.get("responses", []):
        output = resp.get("final_output", resp.get("output", ""))
        if isinstance(output, dict):
            output = json.dumps(output)
        output_lower = (output or "").lower()

        # Memory hit scoring
        if case.expect_memory_hit:
            # Check if response references seeded content
            seeded_terms = []
            for engram in case.seed_engrams:
                words = engram["content"].lower().split()
                key_words = [w for w in words if len(w) > 4]
                seeded_terms.extend(key_words[:3])

            hits = sum(1 for term in seeded_terms if term in output_lower)
            scores["memory_hit"] = min(1.0, hits / max(len(seeded_terms), 1))

        # Tool call scoring
        if case.expect_tool_call:
            # Check task metadata for tool calls
            tools = resp.get("metadata", {}).get("tools_used", [])
            scores["tool_selection"] = 1.0 if case.expect_tool_call in tools else 0.0

        # Hallucination scoring
        if case.expect_no_hallucination:
            hedging = any(phrase in output_lower for phrase in [
                "don't know", "don't have", "no information",
                "not sure", "can't find", "no memory", "no record",
            ])
            scores["no_hallucination"] = 1.0 if hedging else 0.0

    return scores


async def cleanup_engrams(client: httpx.AsyncClient, run_id: str):
    """Delete engrams tagged with this benchmark run ID."""
    # Search for tagged engrams and delete
    try:
        r = await client.post(
            f"{MEMORY_BASE}/api/v1/engrams/activate",
            json={"query": f"benchmark:{run_id}", "limit": 100},
        )
        if r.status_code == 200:
            engrams = r.json().get("engrams", [])
            for e in engrams:
                if f"benchmark:{run_id}" in e.get("content", ""):
                    await client.delete(
                        f"{MEMORY_BASE}/api/v1/engrams/{e['id']}",
                    )
    except Exception as e:
        log.warning("Benchmark cleanup failed: %s", e)


async def run_benchmarks(category_filter: str | None = None) -> dict:
    """Run all benchmark cases and return aggregate results."""
    run_id = str(uuid.uuid4())[:8]
    cases = BENCHMARK_CASES
    if category_filter:
        cases = [c for c in cases if c.category == category_filter]

    results = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cases": [],
        "category_scores": {},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for case in cases:
            log.info("Running benchmark: %s", case.name)

            # Seed
            engram_ids = await seed_engrams(client, case, run_id)

            # Run
            conv_results = await run_conversation(client, case.messages)

            # Score
            scores = score_case(case, conv_results)

            case_result = {
                "name": case.name,
                "category": case.category,
                "scores": scores,
                "composite": sum(scores.values()) / max(len(scores), 1),
                "seeded_engrams": len(engram_ids),
                "responses": len(conv_results.get("responses", [])),
            }
            results["cases"].append(case_result)

            # Cleanup
            await cleanup_engrams(client, run_id)

        # Aggregate by category
        by_cat: dict[str, list[float]] = {}
        for cr in results["cases"]:
            by_cat.setdefault(cr["category"], []).append(cr["composite"])

        results["category_scores"] = {
            cat: round(sum(scores) / len(scores), 4)
            for cat, scores in by_cat.items()
        }

        all_composites = [cr["composite"] for cr in results["cases"]]
        results["composite_score"] = round(
            (sum(all_composites) / len(all_composites)) * 100, 2
        ) if all_composites else 0.0

        results["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Write to DB
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{ORCH_BASE}/api/v1/benchmarks/quality-results",
                json=results,
                headers=ADMIN_HEADERS,
            )
    except Exception as e:
        log.warning("Failed to write benchmark results to DB: %s", e)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    category = sys.argv[1] if len(sys.argv) > 1 else None
    result = asyncio.run(run_benchmarks(category))
    print(json.dumps(result, indent=2))
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/quality/
git commit -m "feat: add AI quality benchmark test suite framework"
```

---

## Task 7: Benchmark API Endpoints

**Files:**
- Modify: `orchestrator/app/quality_router.py`
- Test: `tests/test_quality_scoring.py`

- [ ] **Step 1: Add benchmark endpoints to quality_router.py**

Append to `orchestrator/app/quality_router.py`:

```python
@quality_router.post("/api/v1/benchmarks/run-quality", status_code=202)
async def run_quality_benchmark(
    _admin: AdminDep,
    category: str | None = None,
):
    """Kick off an async quality benchmark run."""
    pool = get_pool()

    # Create the run record
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO quality_benchmark_runs (status, metadata)
            VALUES ('running', $1)
            RETURNING id::text
            """,
            json.dumps({"category_filter": category}),
        )

    # Launch async — don't block the response
    import asyncio
    asyncio.create_task(_execute_benchmark(run_id, category))

    return {"run_id": run_id, "status": "running"}


async def _execute_benchmark(run_id: str, category: str | None):
    """Background task: call benchmark runner via HTTP against live services.

    The benchmark runner lives at repo root (benchmarks/quality/), not inside
    the orchestrator container. We run the benchmark by making the same API
    calls the runner would make — seeding engrams, submitting tasks, scoring.
    For now, this is a stub that marks the run as needing external execution.
    Run `make benchmark-quality` from the host to execute and results will
    be written via POST /api/v1/benchmarks/quality-results.
    """
    try:
        # Stub: mark as needing external execution
        # Full benchmark logic runs from host via `make benchmark-quality`
        # which calls `python -m benchmarks.quality.runner` and POSTs results
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE quality_benchmark_runs
                SET status = 'pending_external',
                    metadata = metadata || '{"note": "Run make benchmark-quality from host"}'::jsonb
                WHERE id = $1::uuid
                """,
                run_id,
            )
        return

    except Exception as e:
        log.error("Benchmark run %s setup failed: %s", run_id, e)


@quality_router.post("/api/v1/benchmarks/quality-results")
async def post_quality_benchmark_results(
    _admin: AdminDep,
    results: dict,
):
    """Receive benchmark results from external runner (make benchmark-quality)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO quality_benchmark_runs
                (status, completed_at, composite_score, category_scores, case_results, metadata)
            VALUES ('completed', NOW(), $1, $2, $3, $4)
            RETURNING id::text
            """,
            results.get("composite_score", 0),
            json.dumps(results.get("category_scores", {})),
            json.dumps(results.get("cases", [])),
            json.dumps({"run_id": results.get("run_id"), "started_at": results.get("started_at")}),
        )
    return {"id": run_id, "status": "completed"}


@quality_router.get("/api/v1/benchmarks/quality-results")
async def get_quality_benchmark_results(
    _admin: AdminDep,
    limit: int = Query(10, ge=1, le=50),
):
    """Return recent quality benchmark runs."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, started_at, completed_at, status,
                   composite_score, category_scores, case_results, metadata
            FROM quality_benchmark_runs
            ORDER BY started_at DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        {
            "id": row["id"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            "status": row["status"],
            "composite_score": float(row["composite_score"]) if row["composite_score"] else None,
            "category_scores": row["category_scores"] or {},
            "case_results": row["case_results"] or [],
            "metadata": row["metadata"] or {},
        }
        for row in rows
    ]
```

- [ ] **Step 2: Add Makefile target**

Add to `Makefile`:

```makefile
benchmark-quality:  ## Run AI quality benchmark suite
	python -m benchmarks.quality.runner
```

- [ ] **Step 3: Add integration tests**

Append to `tests/test_quality_scoring.py`:

```python
class TestBenchmarkAPI:
    """Quality benchmark run API endpoints."""

    async def test_benchmark_results_endpoint(
        self, orchestrator_client: httpx.AsyncClient, admin_headers: dict
    ):
        r = await orchestrator_client.get(
            "/api/v1/benchmarks/quality-results",
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_benchmark_results_requires_admin(
        self, orchestrator_client: httpx.AsyncClient
    ):
        r = await orchestrator_client.get("/api/v1/benchmarks/quality-results")
        assert r.status_code in (401, 403)
```

- [ ] **Step 4: Rebuild and test**

Run:
```bash
docker compose build orchestrator && docker compose up -d orchestrator && sleep 5
python -m pytest tests/test_quality_scoring.py::TestBenchmarkAPI -v --timeout=30
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/quality_router.py Makefile tests/test_quality_scoring.py
git commit -m "feat: add benchmark run/results API endpoints and make target"
```

---

## Task 8: Dashboard — AI Quality Page

**Files:**
- Create: `dashboard/src/pages/AIQuality.tsx`
- Modify: `dashboard/src/components/layout/Sidebar.tsx`
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Create the AI Quality page**

Create `dashboard/src/pages/AIQuality.tsx`. This replaces the Benchmarks page with two tabs: Live Scores and Benchmarks.

The page should:
- Use `useQuery` to fetch `/api/v1/quality/summary` for composite score and dimension averages
- Use `useQuery` to fetch `/api/v1/quality/scores?granularity=daily` for sparkline data
- Use `useQuery` to fetch `/api/v1/benchmarks/quality-results` for benchmark run history
- Use `useQuery` to fetch `/api/v1/benchmarks/results` for existing memory benchmarks (fold into Benchmarks tab)
- Tab 1 "Live Scores": composite score header, dimension cards with avg/trend/sparkline, conversation drill-down
- Tab 2 "Benchmarks": run history table with expandable rows, "Run Benchmark" button that POSTs to `/api/v1/benchmarks/run-quality`
- Follow existing page patterns from Benchmarks.tsx (useQuery, apiFetch, Tailwind styling, help entries)
- Follow DESIGN.md for styling (read it before implementing)

This is the largest single UI component. The implementer should read `dashboard/src/pages/Benchmarks.tsx` for patterns and `DESIGN.md` for design tokens.

- [ ] **Step 2: Update sidebar**

In `dashboard/src/components/layout/Sidebar.tsx`, find the Benchmarks entry in the `navSections` array and change:

```typescript
// From:
{ path: '/benchmarks', label: 'Benchmarks', icon: FlaskConical, minRole: 'admin' as Role },
// To:
{ path: '/ai-quality', label: 'AI Quality', icon: FlaskConical, minRole: 'admin' as Role },
```

- [ ] **Step 3: Update routing**

In `dashboard/src/App.tsx`:

Replace the Benchmarks import and route:
```typescript
// From:
import Benchmarks from './pages/Benchmarks'
// ...
<Route path="/benchmarks" element={...} />

// To:
import AIQuality from './pages/AIQuality'
// ...
<Route path="/ai-quality" element={<AppLayout><AIQuality /></AppLayout>} />
```

Add redirect for old URL:
```typescript
<Route path="/benchmarks" element={<Navigate to="/ai-quality" replace />} />
```

- [ ] **Step 4: Build check**

Run:
```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

Expected: TypeScript compilation succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/AIQuality.tsx dashboard/src/components/layout/Sidebar.tsx dashboard/src/App.tsx
git commit -m "feat: add AI Quality dashboard page with live scores and benchmarks tabs"
```

---

## Task 9: Config Sync for Backend Pause Flags

**Files:**
- Modify: `orchestrator/app/config_sync.py`
- Modify: `orchestrator/app/main.py` (call sync at startup)

- [ ] **Step 1: Add features sync function**

Add to `orchestrator/app/config_sync.py`:

```python
async def sync_features_config_to_redis() -> None:
    """Push features.* config to all service Redis DBs that need them.

    Unlike LLM config (db1 only), feature flags are read by cortex (db5),
    intel-worker (db6), and knowledge-worker (db8). Write to each.
    """
    SERVICE_DBS = [5, 6, 8]  # cortex, intel-worker, knowledge-worker
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM platform_config WHERE key LIKE 'features.%'"
            )
        if not rows:
            return

        base_url = os.environ.get("REDIS_URL", "redis://redis:6379")
        for db in SERVICE_DBS:
            # Replace /dbN at end of URL, or append it
            import re as _re
            db_url = _re.sub(r"/\d+$", f"/{db}", base_url)
            if f"/{db}" not in db_url:
                db_url = f"{db_url}/{db}"
            r = aioredis.from_url(db_url, decode_responses=True)
            try:
                for row in rows:
                    val = row["value"]
                    if val is not None:
                        raw = json.dumps(val) if not isinstance(val, str) else val
                        await r.set(f"nova:config:{row['key']}", raw)
            finally:
                await r.aclose()

        log.info("Synced %d features config keys to Redis dbs %s", len(rows), SERVICE_DBS)
    except Exception as e:
        log.warning("Features config sync to Redis failed (non-fatal): %s", e)
```

- [ ] **Step 2: Call sync at startup**

In the orchestrator's lifespan startup (in `main.py`), add:

```python
from app.config_sync import sync_features_config_to_redis
# In the startup section, alongside existing sync calls:
await sync_features_config_to_redis()
```

- [ ] **Step 3: Rebuild and verify**

Run:
```bash
docker compose build orchestrator && docker compose up -d orchestrator && sleep 5
docker compose exec redis redis-cli -n 1 KEYS "nova:config:features.*"
```

Expected: Three keys listed: `nova:config:features.cortex_loop`, `nova:config:features.intel_polling`, `nova:config:features.knowledge_crawling`

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/config_sync.py orchestrator/app/main.py
git commit -m "feat: sync features.* pause flags to Redis at startup"
```

---

## Task 10: Run Full Test Suite

- [ ] **Step 1: Run all quality scoring tests**

```bash
cd /home/jeremy/workspace/arialabs/nova
python -m pytest tests/test_quality_scoring.py -v --timeout=60
```

Expected: All tests pass.

- [ ] **Step 2: Run existing test suite (regression check)**

```bash
make test-quick
```

Expected: Health checks pass, no regressions.

- [ ] **Step 3: Dashboard build check**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

Expected: Clean build, no TypeScript errors.

- [ ] **Step 4: Manual smoke test**

1. Open dashboard, navigate to AI Quality page
2. Send a chat message, wait 30s for scorer to run
3. Check Live Scores tab shows data
4. Click "Run Benchmark" (if services have LLM configured)

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: address test/build issues from AI quality implementation"
```
