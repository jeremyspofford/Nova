# Nova Chat & Pipeline Performance Optimization

> **Date:** 2026-03-17
> **Status:** Approved for implementation
> **Scope:** All three optimization tiers — quick wins, model-tier optimization, and architecture changes

---

## Problem Statement

Nova's chat and pipeline flows are slower than necessary. A simple chat message takes 5-15s (with 3-10s before the first token due to tool pre-resolution). A pipeline task takes 18-47s typical, up to 132s worst case. ~80% of wall time is LLM inference, but significant time is also wasted on sequential operations that could be parallelized or eliminated.

## Current Performance Profile

### Chat Flow (time-to-first-token: 5-15s)
```
Auth (50ms) → Session (20ms) → [Parallel: Memory + Context + Classify] (200-500ms)
→ Tool Pre-Resolution (3-10s, 1-5 LLM calls) → Streaming LLM call → Response
```
**Bottleneck:** Tool pre-resolution makes full LLM calls before streaming starts. Most chat messages don't need tools.

### Pipeline Flow (18-47s typical)
```
Context Agent (5-10s) → Task Agent (10-30s) → Guardrail (1-2s) → Code Review (2-5s)
→ Decision (2-5s, conditional)
```
**Bottlenecks:** All stages sequential. Guardrail + Code Review are independent but run serially. Each stage makes 1-10 LLM calls. Refactor loop costs 10-30s per iteration.

---

## Design: Three Optimization Tiers

### Tier 1: Quick Wins

#### 1.1 — Skip Tool Pre-Resolution for Simple Messages

**Files:** `orchestrator/app/agents/runner.py`

**Current behavior:** `run_agent_turn()` calls the LLM in a tool-use loop (`/complete`) to resolve all tool calls before starting the streaming response (`/stream`). This adds 3-10s of latency before the user sees any output.

**Change:** Add a `skip_tool_preresolution` parameter (already exists in the function signature at `runner.py` but not used by the chat endpoint). For the streaming chat endpoint (`/api/v1/tasks/stream`), default to `skip_tool_preresolution=True`. The streaming LLM call handles tool calls inline — the LLM streams text, pauses for tool calls, executes them, and resumes streaming.

**Implementation:**
1. In `orchestrator/app/router.py` — the `/api/v1/tasks/stream` endpoint: pass `skip_tool_preresolution=True` to `run_agent_turn()` unless the request explicitly sets `tools_required=True`.
2. In `orchestrator/app/agents/runner.py` — when `skip_tool_preresolution=True`, skip the `/complete` tool loop entirely. Go straight to the `/stream` call with tools attached. The LLM gateway already supports tool_calls in streaming mode.
3. Handle tool execution mid-stream: when a `tool_call` chunk arrives in the SSE stream, pause forwarding to client, execute the tool, send the result back to the LLM, and resume streaming. This requires making the streaming path tool-aware.

**Expected impact:** 3-10s reduction in time-to-first-token for ~70% of chat messages.

**Risk:** Some queries genuinely need tool results before they can generate a coherent response. The LLM handles this naturally by making tool calls within the streaming loop — it just means the stream pauses while tools execute.

#### 1.2 — Parallelize Guardrail + Code Review

**Files:** `orchestrator/app/pipeline/executor.py`, pod configuration (DB)

**Current behavior:** Guardrail and Code Review run sequentially. They're independent assessments of the Task Agent's output — neither depends on the other's result.

**Change:** Assign Guardrail and Code Review to the same `parallel_group` in the pod configuration. The executor already has parallel group support (`_run_parallel_group` at executor.py:200). This requires:

1. **DB migration:** Update the default pod's agent configuration to set `parallel_group = 'review'` on both the `guardrail` and `code_review` agents.
2. **Refactor loop adjustment:** If Code Review returns `needs_refactor`, the loop back to Task Agent must still work. After the parallel group completes, check Code Review's verdict and loop if needed.
3. **Decision agent condition:** Decision currently requires both `guardrail_blocked` AND `code_review_rejected`. This still works — both flags are set after the parallel group completes.

**Expected impact:** 2-5s reduction per pipeline run (Guardrail and Code Review overlap instead of stacking).

#### 1.3 — Configurable Queue Worker Concurrency

**Files:** `orchestrator/app/queue.py`, `orchestrator/app/config.py`

**Current behavior:** Single `queue_worker()` task in main.py lifespan. The worker spawns pipeline executions as `asyncio.create_task` so they run concurrently, but there's no semaphore limiting concurrency — if 100 tasks are queued, all 100 start simultaneously.

**Change:**
1. Add `pipeline_max_concurrent: int = 5` to orchestrator `config.py`.
2. In `queue_worker()`, add `asyncio.Semaphore(settings.pipeline_max_concurrent)` gating pipeline execution.
3. Optionally spawn multiple queue_worker tasks (configurable) for true parallel BRPOP consumption — but a single worker with `create_task` and a semaphore is sufficient since BRPOP is already non-blocking.

**Expected impact:** Controlled concurrent pipeline execution. Prevents resource exhaustion under load while allowing parallel task processing.

#### 1.4 — Verify LLM Response Caching

**Files:** `llm-gateway/app/router.py`, `llm-gateway/app/config.py`

**Current behavior:** The gateway has `response_cache_ttl: 300` (5 min) and caching code in the `/complete` and `/embed` handlers. Verify that:
- Deterministic requests (same model + same messages + temperature=0) hit cache.
- Embedding requests are cached (they are — already verified).
- Non-deterministic requests (temperature > 0) are NOT cached (correct behavior).

**Implementation:** Add cache hit/miss logging. Verify with a test: send the same embedding request twice, confirm second is instant.

### Tier 2: Model-Tier Optimization

#### 2.1 — Right-Size Models Per Pipeline Stage

**Files:** `orchestrator/app/pipeline/agents/{context,guardrail,code_review}.py`, pod agent DB config

**Current behavior:** Each pipeline agent uses the pod's `default_model` unless a per-agent `model` is set in DB. In practice, all stages use the same model.

**Change:** Set per-agent model overrides in the default pod configuration:

| Stage | Current | Recommended | Rationale |
|-------|---------|-------------|-----------|
| Context Agent | default (full model) | `tier:cheap` | Just reads files and gathers info — doesn't need a powerful model |
| Task Agent | default (full model) | `tier:best` (keep current) | Does the actual work — needs the best model |
| Guardrail Tier 1 | already uses haiku-class | keep | Already optimized |
| Code Review | default (full model) | `tier:mid` | Assessment task, mid-tier is sufficient |
| Decision | default (full model) | `tier:best` | High-stakes decision — keep best model |

**Implementation:** DB migration to update `pod_agents.model` for context and code_review agents. Use the tier-based routing that already exists in the llm-gateway (`tier_resolver.py`).

**Expected impact:** Context Agent runs 2-5x faster with a cheap model. Code Review runs 1.5-2x faster with a mid-tier model. Total pipeline savings: 3-8s.

#### 2.2 — Prompt Caching for Pipeline System Prompts

**Files:** `orchestrator/app/pipeline/agents/*.py`, `orchestrator/app/agents/runner.py`

**Current behavior:** Each pipeline stage sends a full system prompt with every LLM call. These prompts are static (same text across all runs).

**Change:** Add `cache_control` markers to system prompts when calling Anthropic models. The Anthropic API supports `cache_control: {"type": "ephemeral"}` on message blocks, which caches the prefix for 5 minutes. After the first call, subsequent calls with the same prefix pay only for the new tokens.

**Implementation:**
1. In `run_agent_turn()` and pipeline agent runners, detect if the model is an Anthropic model.
2. If so, wrap the system prompt in a cache-control block: `{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}`.
3. The llm-gateway passes this through to the Anthropic API. LiteLLM supports `cache_control` in message content blocks.

**Expected impact:** 50-90% cost reduction on cached system prompt tokens. 100-500ms latency reduction per call (cached tokens process faster). Across a 5-stage pipeline with ~10 LLM calls total, this saves $0.01-0.05 per run and 1-5s total latency.

#### 2.3 — Adaptive Stage Skipping

**Files:** `orchestrator/app/pipeline/executor.py`, `orchestrator/app/pipeline/complexity_classifier.py`

**Current behavior:** The complexity classifier runs at pipeline start but only affects model selection. All stages always run.

**Change:** Use complexity classification to skip unnecessary stages:

| Complexity | Skip |
|------------|------|
| `trivial` | Skip Context Agent (no codebase exploration needed for simple text tasks) |
| `simple` (non-code) | Skip Code Review (no code to review) |
| Any | Skip Decision Agent (already conditional — only runs when both guardrail AND code_review fail) |

**Implementation:** Add `skip_stages` logic in `_run_pipeline()` based on the classified complexity and task type. The `run_condition` mechanism already supports this — update the default pod agent `run_condition` configs.

**Expected impact:** Trivial tasks save 5-10s (skip Context Agent). Non-code tasks save 2-5s (skip Code Review).

### Tier 3: Architecture Changes

#### 3.1 — Streaming-First Chat (Eliminate Pre-Resolution)

**Files:** `orchestrator/app/agents/runner.py`, `orchestrator/app/router.py`

**Current behavior:** The chat streaming endpoint calls `run_agent_turn()` which does a full tool-resolution loop via `/complete` calls, THEN starts streaming via `/stream`.

**Change:** Restructure the streaming path to be tool-aware:

```
User message → [Parallel: Memory + Context + Classify]
→ Start streaming LLM call immediately (with tools attached)
→ If LLM makes tool_call:
    → Pause stream to client (send a "thinking" indicator)
    → Execute tool
    → Feed result back to LLM
    → Resume streaming
→ Continue until stream ends
→ Fire-and-forget: usage log + memory storage
```

**Implementation:**
1. New function `stream_agent_turn()` in `runner.py` that yields SSE chunks.
2. The function calls `/stream` on the gateway with tools. When the stream contains a `tool_call` chunk (finish_reason="tool_use"), it:
   - Yields a `{"type": "status", "status": "tool_call", "tool": "..."}` event to the client
   - Executes the tool
   - Sends the tool result back to the LLM as a new `/stream` call
   - Continues yielding content chunks
3. The router's streaming endpoint switches from `run_agent_turn()` to `stream_agent_turn()`.
4. Dashboard WebSocket handler already processes SSE — add handling for the "status" event type to show a "using tool..." indicator.

**Expected impact:** Near-instant first token for all chat messages. Tool-using queries see brief pauses mid-stream (1-3s per tool call) instead of a long upfront wait.

#### 3.2 — Speculative Pipeline Execution

**Files:** `orchestrator/app/pipeline/executor.py`

**Current behavior:** Each stage completes fully before the next begins.

**Change:** Start the next stage speculatively when the current stage is ~90% likely to succeed:

1. **Guardrail starts during Task Agent's last tool round.** When the Task Agent returns a result (before JSON extraction finishes), start Guardrail Tier 1 with the raw output. If the Task Agent's JSON extraction changes the output, restart Guardrail.
2. **Code Review starts immediately when Guardrail Tier 1 passes.** Don't wait for Tier 2 to begin Code Review — Tier 2 only fires if Tier 1 found something, and that's rare (~5% of tasks).

**Implementation:**
1. After Task Agent completes, launch both Guardrail and Code Review as concurrent tasks (this overlaps with 1.2 — parallel group).
2. If Guardrail Tier 1 finds issues and triggers Tier 2, the Tier 2 result can override after Code Review starts. The Decision Agent reconciles any conflicts.
3. Add a `speculative: bool` flag to pipeline state so agents know they're running speculatively and their results may be discarded.

**Expected impact:** 3-7s overlap savings. Combined with parallel Guardrail+CodeReview (1.2), the post-TaskAgent phase drops from ~7-10s to ~2-3s.

#### 3.3 — Memory Context Pre-Warming

**Files:** `orchestrator/app/agents/runner.py`, `orchestrator/app/store.py`

**Current behavior:** Memory context is fetched fresh for every message via `POST /api/v1/engrams/context`. This is on the critical path for prompt assembly.

**Change:** For active sessions, pre-fetch memory context in the background:

1. After each message response, schedule a background task that pre-fetches memory context for likely follow-up queries.
2. Cache the result in Redis with a 60s TTL, keyed by `session_id`.
3. On the next message, check the cache first. If the cached context is <60s old, use it directly. If not, fetch fresh.
4. The engram system updates asynchronously anyway (ingestion queue), so a 60s-old context is still accurate.

**Implementation:**
1. In `run_agent_turn()` post-response, `asyncio.create_task(_prewarm_memory(session_id, query))`.
2. `_prewarm_memory` calls the memory-service and stores result in Redis: `nova:memory_cache:{session_id}`.
3. In `_get_memory_context()`, check Redis cache first. Use cached result if available and <60s old.

**Expected impact:** Saves 200-500ms per message in active conversations (memory context is pre-warmed). First message in a session still fetches fresh.

#### 3.4 — Pipeline Stage Merging for Simple Tasks

**Files:** `orchestrator/app/pipeline/executor.py`, `orchestrator/app/pipeline/agents/context.py`

**Current behavior:** Context Agent always runs as a separate stage, making its own LLM calls to explore the workspace before the Task Agent starts.

**Change:** For `trivial` and `simple` complexity tasks, merge Context and Task into a single agent call:

1. Give the Task Agent access to Context Agent's tools (list_dir, read_file, search_codebase) in addition to its own write tools.
2. Skip the Context Agent stage entirely — the Task Agent gathers context as needed during its own tool loop.
3. This eliminates an entire LLM call (or several) for simple tasks.

**Implementation:**
1. When complexity is `trivial` or `simple`, set `state.completed["context"] = {"merged": True}` and skip Context Agent.
2. Extend Task Agent's `allowed_tools` to include read-only tools when running in merged mode.
3. The Task Agent's system prompt already instructs it to use context — it just needs access to the tools.

**Expected impact:** Saves 5-10s on simple tasks by eliminating the Context Agent stage entirely.

---

## Implementation Order

| Step | What | Tier | Est. Effort | Impact |
|------|------|------|-------------|--------|
| 1 | Skip tool pre-resolution in chat streaming | 1.1 | 2-3 hours | High — instant first token |
| 2 | Parallelize Guardrail + Code Review | 1.2 | 1-2 hours | Medium — 2-5s savings |
| 3 | Right-size models per stage | 2.1 | 1 hour (DB migration) | Medium — 3-8s savings |
| 4 | Queue worker concurrency control | 1.3 | 1 hour | Medium — throughput |
| 5 | Prompt caching for Anthropic | 2.2 | 2-3 hours | Medium — cost + latency |
| 6 | Adaptive stage skipping | 2.3 | 2-3 hours | Medium — 2-10s on simple tasks |
| 7 | Streaming-first chat (full) | 3.1 | 4-6 hours | High — transforms UX |
| 8 | Memory context pre-warming | 3.3 | 2-3 hours | Low-Medium — 200-500ms |
| 9 | Stage merging for simple tasks | 3.4 | 3-4 hours | Medium — 5-10s on simple tasks |
| 10 | Speculative pipeline execution | 3.2 | 4-6 hours | Medium — 3-7s on all tasks |

**Total estimated effort:** 22-34 hours across all tiers.

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| Chat time-to-first-token (simple query) | 5-15s | <2s |
| Chat time-to-first-token (tool query) | 5-15s | <3s (stream starts, tools run mid-stream) |
| Pipeline (trivial task) | 18-30s | 8-15s |
| Pipeline (standard task) | 25-47s | 15-30s |
| Concurrent pipeline capacity | Unbounded (no control) | Configurable (default 5) |
| Cost per pipeline run (Anthropic) | ~$0.05-0.15 | ~$0.02-0.08 (prompt caching + model routing) |
