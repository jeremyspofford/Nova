# AI Quality Measurement System — Design Spec

> **Date:** 2026-04-03
> **Status:** Approved
> **Approach:** Hybrid — feature config in platform_config, quality scores in dedicated table

---

## Problem

Nova has sophisticated AI infrastructure (memory, pipeline, cortex) but no way to measure whether it's actually working well. Changes to memory retrieval, decomposition, or pipeline logic have no regression gate. There's no trend line showing "is Nova getting smarter?"

The existing Benchmarks page measures memory retrieval precision (Precision@5, MRR, latency) — useful but narrow. We need:

1. **Live quality scoring** on every conversation (trend line)
2. **Automated benchmarks** run on demand (regression gate)

## Non-Goals

- LLM judge scoring (future upgrade — too expensive per-message today)
- Feature flag UI system (descoped — just add missing backend pause config keys ad-hoc)
- User feedback (thumbs up/down) — nice-to-have, not in scope

---

## Quality Dimensions

Each assistant response is scored across these dimensions (0.0–1.0):

| Dimension | What it Measures | Scoring Method |
|---|---|---|
| `memory_relevance` | Were retrieved engrams actually relevant to the query? | Re-embed engram content text via gateway `/embed`, cosine similarity vs query embedding (average). Engram content fetched via new `POST /api/v1/engrams/batch` endpoint on memory-service (accepts list of IDs, returns ID→content pairs). |
| `memory_recall` | Did Nova remember things it should have? | Pattern detection for user corrections ("I told you", "I already said", "no, it's", etc.). Only writes a row when correction IS detected (score=0.3). Absence of a row = implicit 1.0 when aggregating. |
| `tool_accuracy` | Did the agent call the right tools correctly? | Parse `agent_sessions.output` conversation messages for tool_use/tool_result blocks. Detect errors via known prefixes ("Tool execution blocked:", "MCP dispatch error:", "Error:"). Score = (total_calls - errored_calls) / total_calls. 1.0 if no tools used. |
| `response_coherence` | Was the response on-topic and well-structured? | Cosine similarity of query embedding vs response embedding. Note: tool-heavy responses (where tool_calls > 0) are excluded from this dimension to avoid penalizing correct tool-use responses with low textual similarity. |
| `task_completion` | Did the pipeline produce a usable result? | Pipeline tasks only. Scoring: `complete` with no guardrail findings=1.0, `complete` with `guardrail_findings` rows present=0.6, `pending_human_review`=0.4, `failed`=0.2, `cancelled`=0.1. Join tasks with guardrail_findings to determine finding presence. |
| `conversation_quality` | Overall conversation health | Computed at query time as weighted composite — not stored. Default weights: memory_relevance=0.30, memory_recall=0.25, tool_accuracy=0.20, response_coherence=0.15, task_completion=0.10. |

**Future dimension:** `llm_judge` — post-response LLM evaluation for deeper quality assessment (option B upgrade). Would run async, opt-in, with configurable judge model.

---

## Data Model

### quality_scores table (new migration)

```sql
CREATE TABLE quality_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id UUID,              -- NULL for pipeline task scores (no FK — messages are embedded in conversations JSONB)
    task_id UUID,                 -- NULL for chat scores (no FK — scores may outlive task cleanup)
    dimension TEXT NOT NULL,       -- 'memory_relevance', 'tool_accuracy', etc.
    score REAL NOT NULL,           -- 0.0 to 1.0 (matches usage_events.outcome_score type)
    confidence REAL,               -- how confident the scorer is
    metadata JSONB DEFAULT '{}',  -- dimension-specific evidence
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_quality_scores_dimension_time ON quality_scores (dimension, created_at DESC);
CREATE INDEX idx_quality_scores_conversation ON quality_scores (conversation_id, created_at DESC);
```

One row per dimension per message, but only when there is signal (e.g., `memory_recall` only writes on correction detection, not on every turn). A single chat response may produce up to 4 rows. The `metadata` JSONB holds evidence: which engrams were retrieved and their similarity scores, which tools errored, what pattern triggered detection.

**New memory-service endpoint required:** `POST /api/v1/engrams/batch` — accepts `{"ids": [...]}`, returns `[{id, content, node_type}]`. Used by the scorer to fetch engram text for re-embedding. Lightweight, no graph traversal.

### quality_benchmark_runs table (new migration)

```sql
CREATE TABLE quality_benchmark_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT DEFAULT 'running',        -- running, completed, failed
    composite_score NUMERIC(5,2),         -- 0.00 to 100.00
    category_scores JSONB DEFAULT '{}',   -- {factual_recall: 0.85, contradiction: 0.60, ...}
    case_results JSONB DEFAULT '[]',      -- per-test-case detail
    metadata JSONB DEFAULT '{}'           -- run config, model used, etc.
);
```

---

## Expanded Chat Scorer

The existing `chat_scorer.py` is extended. After each assistant response, the scoring pipeline runs async (no user-facing latency):

```
Assistant response arrives
    |
    +-- memory_relevance: fetch engram content via POST /api/v1/engrams/batch,
    |   re-embed via gateway /embed, cosine similarity vs query embedding
    |   Metadata: {engram_ids, similarities, query}
    |
    +-- memory_recall: regex scan for correction patterns
    |   Only writes row if correction detected (score=0.3). Skips 1.0 rows.
    |   Metadata: {matched_pattern, user_message_excerpt}
    |
    +-- tool_accuracy: parse agent_sessions.output for tool_use/tool_result
    |   message blocks. Detect errors via known prefixes.
    |   Metadata: {tools_called, errors, retries}
    |
    +-- response_coherence: cosine similarity of query vs response embeddings
    |   Metadata: {similarity, query_tokens, response_tokens}
    |
    +-- Write all rows to quality_scores table
```

**task_completion** scoring runs separately, triggered when a pipeline task reaches terminal state.

**Performance:** All async, post-response. Embedding calls ~2-4ms each (gateway cache). Pattern matching is pure regex.

The existing `outcome_score` on `usage_events` stays — different signal (user engagement) that complements per-dimension scores.

---

## Automated Benchmark Suite

Scripted test conversations run against Nova's live API (same pattern as integration tests — real services, no mocks).

### Test Case Structure

Each test case has:
- **Setup:** Pre-seed specific engrams tagged with a `benchmark_run_id` so memory state is known and cleanup is deterministic
- **Input:** User message or sequence of messages
- **Expected behaviors:** Should retrieve memory X, use tool Y, not hallucinate about Z
- **Scoring:** Against quality dimensions
- **Teardown:** Delete all engrams and edges tagged with the `benchmark_run_id` after scoring completes

### Test Categories

| Category | What it Tests | Example |
|---|---|---|
| Factual recall | "What's my favorite language?" after seeding that preference | Memory retrieval accuracy |
| Multi-turn context | Ask about A, switch to B, return to A — does Nova retain context? | Working memory / sliding tier |
| Contradiction handling | Seed "I prefer Python", then "I've switched to Go" — which wins? | Newer info should win |
| Tool selection | "Check if memory-service is healthy" — calls check_service_health? | Tool accuracy |
| Temporal recall | "What was I working on last week?" with dated engrams | Temporal filtering |
| No-hallucination | Ask about something with no engrams — does Nova say "I don't know"? | Groundedness |

### Execution

- **Endpoint:** `POST /api/v1/benchmarks/run-quality` — kicks off async benchmark run
- **Results:** Written to `quality_benchmark_runs` table
- **CLI:** `make benchmark-quality`
- **Key metric:** Composite "AI Quality Score" (0–100) weighted across categories. Run before and after changes. Score goes up = improvement confirmed.

Test cases live as Python code in `benchmarks/quality/`, not user-configurable UI.

---

## Dashboard

Expand the existing Benchmarks page. Rename sidebar item to "AI Quality". Two tabs:

### Tab 1: Live Scores

- Composite score prominently displayed at top
- Time-series sparklines for each dimension (7-day default, selectable range)
- Current average + trend arrow (up/down vs previous period) per dimension
- Filterable by conversation (drill into per-message scores)
- Click any data point to see metadata evidence

### Tab 2: Benchmarks

- Run history table (date, composite score, per-category scores, delta from previous run)
- "Run Benchmark" button → `POST /api/v1/benchmarks/run-quality`
- Progress indicator (SSE) while running
- Expandable rows for per-test-case results
- Existing memory retrieval benchmarks (JSONL file-based) displayed as a "Memory Retrieval" category alongside the new DB-backed quality benchmarks. The existing `GET /api/v1/benchmarks/results` endpoint stays as-is — both data sources render on the same page.

### API Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/quality/scores?dimension=&from=&to=&granularity=` | Live scores for charts (time-bucketed aggregation: hourly/daily averages for sparklines, raw rows only for conversation drill-down via `?conversation_id=`) |
| `GET /api/v1/quality/summary?period=7d` | Aggregated averages + trends |
| `POST /api/v1/benchmarks/run-quality` | Kick off benchmark run |
| `GET /api/v1/benchmarks/quality-results` | Benchmark run history |

---

## Backend Pause Config Keys (ad-hoc)

Not a feature flag system — just add missing config keys for pausing background processing while focusing on specific areas:

| Key | Default | Effect |
|---|---|---|
| `features.cortex_loop` | `true` | Cortex thinking cycle runs/pauses (check at top of cycle loop) |
| `features.intel_polling` | `true` | Intel-worker feed fetching runs/pauses |
| `features.knowledge_crawling` | `true` | Knowledge-worker crawl cycles run/pause |

`engram.consolidation_enabled` already exists for consolidation. Memory ingestion can be paused by stopping the queue consumer.

**Storage:** Keys live in `platform_config` table (DB-backed, survives restarts, editable from dashboard) with seed defaults of `true`. A new `sync_features_config_to_redis()` function in `config_sync.py` syncs them to Redis as `nova:config:features.*` at orchestrator startup (same pattern as `sync_engram_config_to_redis`). Services read from Redis at the top of each loop iteration. When `false`, sleep 60s and re-check. No container restart needed.

Add these to Settings > System as simple toggles when convenient. Not a priority deliverable.

---

## Implementation Order

1. Migration: `quality_scores` + `quality_benchmark_runs` tables
2. Expand `chat_scorer.py` with multi-dimension scoring pipeline
3. Quality API endpoints (scores, summary)
4. Benchmark test suite framework + first test cases
5. Benchmark API endpoints (run, results)
6. Dashboard: rename Benchmarks → AI Quality, add Live Scores tab
7. Backend pause config keys (ad-hoc, low priority)
