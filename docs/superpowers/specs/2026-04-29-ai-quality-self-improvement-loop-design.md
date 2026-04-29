---
title: AI Quality v2 — Self-Improvement Closed Loop
date: 2026-04-29
status: approved
---

# AI Quality v2 — Self-Improvement Closed Loop

## Problem

The current AI Quality page (dashboard route `/ai-quality`) is two systems on one page that don't share a vocabulary, and the benchmark half is broken. Symptoms a user observes today:

- Click "Run Benchmark", wait, see only the word "complete" in the run table — no composite score, no case results, no error context.
- Status badge color is gray (neutral) even when the benchmark "succeeded".
- No way to tell what changed between runs because configuration isn't captured.
- Benchmark seed engrams (tagged `[benchmark:abc12345]`) accumulate in the user's main memory store with no teardown.

Root causes:

1. **Three different dimension vocabularies.** The dashboard labels seven dimensions, the live scorer (`chat_scorer.py` / `quality_scorer.py`) implements five, the benchmark uses three completely different ones (`memory_hit`, `tool_selection`, `no_hallucination`). A passing benchmark says nothing about what live scoring is measuring.
2. **Benchmark cases are inline Python.** `quality_router.py:204` hard-codes 6 cases inside the route handler, scored by 3-word substring match against seed engrams. Naive scoring + brittle setup.
3. **No configuration snapshot.** Each benchmark run captures *that it ran* but not *what was active when it ran*. "Did this change help?" is structurally unanswerable.
4. **Status string mismatch.** Background task writes `status='complete'`; external-runner endpoint writes `status='completed'`. Dashboard's `statusBadgeColor` only matches `'completed'`. Cosmetic but confusing.
5. **Silent failure mode.** When agent discovery returns empty (or 401s), every case scores 0; benchmark "completes" with composite=0; nothing surfaces to the user.
6. **No closed loop.** The page measures but cannot act. Cortex (the autonomous brain) cannot consume quality signal to drive self-improvement.

The deepest problem isn't any one of those bugs — the page was built as a passive dashboard, but Nova actually needs it to be a **closed-loop self-improvement system** that exposes a dashboard. Cortex needs to use this to detect regressions, propose changes, apply them, and verify the result.

## Goals

Two-cycle redesign:

**Cycle 1 — Truth-telling measurement.** Make the existing measurement layer accurate, observable, and unified. The page stops lying about empty results. Delivers the "alert-only" baseline (E in our scenario taxonomy) for free.

**Cycle 2 — Closed loop primitive + first instance.** Build the `QualityLoop` abstraction in orchestrator, ship Loop A (Retrieval Tuning) as the first concrete instance, integrate Cortex as the policy driver.

**Long-term — additional loops as plugins.** Loops B, C, D land as additional plugins of the same primitive once Cycle 2 is solid.

## Non-goals

- **LLM-as-judge dimensions** (`reasoning_quality`, `context_utilization`). Both require an LLM call per scored turn or per benchmark case — too expensive for live scoring, deferred until the closed loop is producing trustworthy signal. Re-evaluate after Cycle 2.
- **User-defined benchmark cases.** No UI for users to author cases; for v2, cases are code-defined fixtures in `benchmarks/quality/cases/*.yaml`. Revisit if/when SaaS users want custom benchmarks.
- **Multi-tenant benchmark isolation.** Single-tenant scope; revisit when SaaS lifecycle requires per-tenant benchmark runs. Schema is forward-compatible (`tenant_id` column added, nullable).
- **Cortex code-mod / migration self-modification.** Cortex's action space is bounded to runtime config + prompts in v2. Code/migration changes via PRs are out of scope.
- **Cross-loop coordination.** No explicit "don't run consolidation tuning while retrieval tuning is mid-experiment". First conflict observed → first conflict solved.
- **Continuous benchmarking.** v2 runs benchmarks on demand (cortex-triggered or manual), not on a fixed always-on schedule.

## Builds on / related work

- `docs/superpowers/specs/2026-04-03-ai-quality-measurement-design.md` — the v1 spec this redesign supersedes. Most goals and dimensions originate there; the divergence happened during implementation.
- `docs/superpowers/plans/2026-04-28-cortex-goal-decomposition.md` — Cortex Phase 4 plan adding goal trees + maturation phases. The Quality drive proposed here registers in cortex's existing drive system; integration is a thin hook, not a rewrite.
- `chat_scorer.py` (orchestrator) — existing live-scoring background loop. Untouched in v2 — its dimension scorers are reused as-is, with two additions (`instruction_adherence`, `safety_compliance`).

## Architecture

Three layers, with orchestrator as execution engine and cortex as policy driver:

```
┌─────────────────────────────────────────────────────────────┐
│  Cortex (policy)                                            │
│  • Quality drive — "maintain composite >= rolling baseline" │
│  • Decides which loop to run when                           │
│  • Approves "propose_for_approval" actions or escalates     │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────────────────────┐
│  Orchestrator (execution)                                   │
│  • app/quality_loop/runner.py — Background scheduler        │
│  • app/quality_loop/sense.py — Benchmark + live aggregation │
│  • app/quality_loop/snapshot.py — Config snapshot capture   │
│  • app/quality_loop/score.py — Unified dimension scorers    │
│  • app/quality_loop/cases.py — Fixture loader               │
│  • app/quality_loop/loops/retrieval_tuning.py — Loop A      │
│  • app/quality_router.py — APIs (cortex + dashboard)        │
│  • app/chat_scorer.py — Existing live scoring (untouched)   │
└────────────────────┬────────────────────────────────────────┘
                     │ asyncpg / Redis
┌────────────────────▼────────────────────────────────────────┐
│  Storage                                                    │
│  • quality_scores (live, exists)                            │
│  • quality_benchmark_runs (exists, schema additions)        │
│  • quality_config_snapshots (new)                           │
│  • quality_loop_sessions (new)                              │
│  • benchmarks/quality/cases/*.yaml (new — fixtures)         │
└─────────────────────────────────────────────────────────────┘
```

**Why orchestrator executes:** The measurement layer (`chat_scorer.py`, `quality_scorer.py`) already runs in orchestrator. Orchestrator owns the Redis runtime-config keys (`nova:config:*`). Splitting execution to cortex would re-implement chat-scorer plumbing in a second service.

**Why cortex drives policy:** Cortex is Nova's autonomous brain. It already has goals, drives, and budget tracking. Adding "Quality" as a drive is the natural integration; the alternative (orchestrator deciding when to act) puts decision-making in the wrong layer.

**Module boundaries:** The new `orchestrator/app/quality_loop/` package is intentionally split into single-purpose files. Each module has one responsibility — snapshot capture, dimension scoring, fixture loading, runner scheduling, individual loop classes. The package is consumed by `quality_router.py` (HTTP layer) and `chat_scorer.py` (live scoring path); neither depends on internal loop implementation details.

## Quality dimensions

Eight dimensions, shared between live and benchmark scoring. Each has two scoring paths.

| Dimension | Live (cheap heuristic) | Benchmark (ground truth) |
|---|---|---|
| `memory_relevance` | Cosine sim of query vs retrieved engram embeddings | Test case declares expected engram; scored by exact ID hit + cosine threshold |
| `memory_recall` | Regex on user message for correction patterns; only writes on detection | Multi-turn case; assistant must reference seeded fact in later turn |
| `memory_usage` | 3-gram substring of engram in response | Did the response cite the seeded engram content? |
| `tool_accuracy` | Parse `agent_sessions.output` for tool_use/tool_result errors | Test case declares `expect_tool_call`; scored by name match |
| `response_coherence` | Cosine sim of query vs response (skip when tools used) | Same — applies to both modes |
| `task_completion` | Pipeline task terminal status + guardrail-finding presence | Test case declares expected terminal status |
| `instruction_adherence` | LLM judge async — opt-in via `nova:config:quality.instruction_adherence_live` (default `false`); benchmark mode always runs it | Test case declares expected behavior; LLM judge with rubric |
| `safety_compliance` | Guardrail findings count in last N turns | Test case may seed adversarial input; expects refusal/clarification |

**Composite weights (initial — tunable later, stored in `platform_config`):**

| Dimension | Weight |
|---|---|
| memory_relevance | 0.20 |
| memory_recall | 0.15 |
| memory_usage | 0.10 |
| tool_accuracy | 0.15 |
| response_coherence | 0.10 |
| task_completion | 0.10 |
| instruction_adherence | 0.15 |
| safety_compliance | 0.05 |

Dimensions dropped from current dashboard (no implementation, no near-term plan): `reasoning_quality`, `context_utilization`. Re-evaluate after Cycle 2 lands.

## Data model

### Existing tables (modified)

**`quality_scores`** — no schema change in Cycle 1. Two new valid `dimension` values: `instruction_adherence`, `safety_compliance`. New scorer functions in `quality_scorer.py`.

**`quality_benchmark_runs`** — additions in Cycle 1:

```sql
ALTER TABLE quality_benchmark_runs
  ADD COLUMN config_snapshot_id UUID REFERENCES quality_config_snapshots(id),
  ADD COLUMN dimension_scores JSONB DEFAULT '{}',
  ADD COLUMN vocabulary_version INT DEFAULT 2,
  ADD COLUMN error_summary TEXT;

UPDATE quality_benchmark_runs SET status = 'completed' WHERE status = 'complete';
```

Status canonicalized: values are `running` | `completed` | `failed`. The legacy `category_scores` column stays for backward compat (read-only after migration); new code reads `dimension_scores`.

### New tables (Cycle 1)

**`quality_config_snapshots`**:

```sql
CREATE TABLE quality_config_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_hash TEXT UNIQUE NOT NULL,        -- SHA-256 of normalized JSON
    config JSONB NOT NULL,
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    captured_by TEXT NOT NULL,                -- "benchmark_run" | "loop_session" | "manual"
    tenant_id UUID                            -- nullable; reserved for SaaS
);

CREATE INDEX idx_quality_config_snapshots_hash ON quality_config_snapshots (config_hash);
```

Hash-based dedup — most adjacent runs have identical configs, shouldn't double-store.

Snapshot contents (initial schema, extensible):

- `models`: `{tier_fast, tier_balanced, tier_powerful, tier_embedding}` from runtime config
- `retrieval`: `{top_k, threshold, spread_weight, max_hops}` from `nova:config:retrieval.*`
- `routing_strategy`: from `nova:config:llm.routing_strategy`
- `prompts`: agent prompt versions (hash of each agent's system prompt at snapshot time)
- `consolidation`: cadence, thresholds, decay rate

### New tables (Cycle 2)

**`quality_loop_sessions`**:

```sql
CREATE TABLE quality_loop_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loop_name TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    baseline_snapshot_id UUID REFERENCES quality_config_snapshots(id),
    baseline_run_id UUID REFERENCES quality_benchmark_runs(id),
    proposed_changes JSONB NOT NULL,           -- {"retrieval.top_k": {"from": 5, "to": 7}}
    applied BOOLEAN DEFAULT FALSE,
    verification_run_id UUID REFERENCES quality_benchmark_runs(id),
    outcome TEXT,                               -- "improved" | "no_change" | "regressed" | "aborted"
    decision TEXT,                              -- "persist" | "revert" | "pending_approval" | "approved" | "rejected"
    decided_by TEXT,                            -- "auto" | user_id | "cortex"
    decided_at TIMESTAMPTZ,
    notes JSONB DEFAULT '{}',                   -- evidence, reasoning, error context
    tenant_id UUID                              -- nullable; reserved for SaaS
);

CREATE INDEX idx_quality_loop_sessions_loop_started
    ON quality_loop_sessions (loop_name, started_at DESC);
CREATE INDEX idx_quality_loop_sessions_pending
    ON quality_loop_sessions (decision)
    WHERE decision = 'pending_approval';
```

### Benchmark fixtures

`benchmarks/quality/cases/*.yaml` — one file per category. Example:

```yaml
# benchmarks/quality/cases/factual_recall.yaml
- name: simple_preference_recall
  category: factual_recall
  seed_engrams:
    - content: "The user's favorite programming language is Rust"
      source_type: chat
  conversation:
    - user: "What's my favorite programming language?"
  scoring:
    memory_relevance:
      expect_engram_match: true
      min_cosine: 0.7
    instruction_adherence:
      rubric: "Response correctly identifies Rust as the user's favorite language"
```

Cases are loaded at orchestrator startup; the runner scores against the dimension-specific rules each case declares. No more inline Python.

## QualityLoop primitive (Cycle 2)

`orchestrator/app/quality_loop/base.py`:

```python
from typing import Protocol, Literal
from dataclasses import dataclass

@dataclass
class SenseReading:
    composite: float
    dimensions: dict[str, float]
    sample_size: int
    snapshot_id: str

@dataclass
class Proposal:
    description: str           # human-readable
    changes: dict[str, dict]   # {"retrieval.top_k": {"from": 5, "to": 7}}
    rationale: str             # why this candidate, not another

@dataclass
class AppliedChange:
    proposal: Proposal
    applied_at: str
    revert_actions: list[dict]  # how to undo

@dataclass
class Verification:
    baseline: SenseReading
    after: SenseReading
    delta: dict[str, float]
    significant: bool          # passed decision threshold?

@dataclass
class Decision:
    outcome: Literal["improved", "no_change", "regressed", "aborted"]
    action: Literal["persist", "revert", "pending_approval"]
    confidence: float


class QualityLoop(Protocol):
    name: str
    watches: list[str]
    agency: Literal["auto_apply", "propose_for_approval", "alert_only"]

    async def sense(self) -> SenseReading: ...
    async def snapshot(self) -> str: ...                 # returns snapshot_id
    async def propose(self, reading: SenseReading) -> Proposal | None: ...
    async def apply(self, proposal: Proposal) -> AppliedChange: ...
    async def verify(self, baseline: SenseReading, applied: AppliedChange) -> Verification: ...
    async def decide(self, verification: Verification) -> Decision: ...
    async def revert(self, applied: AppliedChange) -> None: ...
```

Runner (`orchestrator/app/quality_loop/runner.py`) schedules `iterate()` calls per loop. Each iteration:

1. Acquire lock (one in-flight session per loop, via Redis `SETNX nova:quality:loop:{name}:lock`)
2. `snapshot()` baseline config
3. `sense()` baseline scores (last benchmark or run a fresh one)
4. `propose()` candidate change (returns `None` if no change warranted → exit)
5. Persist `quality_loop_sessions` row with `applied=False`, `decision='pending_approval'` (unless `auto_apply`)
6. If `auto_apply`: `apply()` → `verify()` → `decide()` → persist or `revert()`, update session row
7. If `propose_for_approval`: pause; cortex/human decides via API; on approval, runner resumes from `apply()`
8. If `alert_only`: stop after `propose()` — emit alert, don't apply

Lock release in `finally` block. Lock TTL 30 min (longer than any expected benchmark) so a crashed orchestrator doesn't permanently wedge a loop.

### Loop A: Retrieval Tuning

`orchestrator/app/quality_loop/loops/retrieval_tuning.py`

- **Watches:** `memory_relevance`, `memory_usage`
- **Action space:** Redis runtime-config keys
  - `nova:config:retrieval.top_k` ∈ [3, 15]
  - `nova:config:retrieval.threshold` ∈ [0.3, 0.7]
  - `nova:config:retrieval.spread_weight` ∈ [0.1, 0.9]
- **Strategy:** Coordinate-descent — one parameter at a time, small steps (top_k ±2, threshold ±0.05, spread_weight ±0.1). Direction chosen by recent regression if any, else exploration.
- **Verification:** Re-run benchmark suite (~2 min); compare composite of watched dimensions only.
- **Decision rule:** persist if watched-dim composite improves by ≥2%; revert if regresses by ≥1%; otherwise no-change (revert).
- **Agency:** `auto_apply`. All changes are reversible Redis runtime-config writes.
- **Cadence:** Triggered by Cortex when watched dimensions regress >5% from rolling baseline, or as a daily exploration cycle (one iteration per day).

### Loops B/C/D — sketches (built later as plugins)

| Loop | Watches | Action surface | Default agency | Notes |
|---|---|---|---|---|
| B. Model selection | composite, `tool_accuracy` | `nova:config:llm.routing.tier_*` | `propose_for_approval` | Latency/cost shifts visible to user before persistence |
| C. Consolidation tuning | `memory_recall`, `memory_usage` | Consolidation cadence + thresholds | `auto_apply` | Slow loop (multi-day observation); easy to revert |
| D. Prompt iteration | `instruction_adherence`, `response_coherence` | Agent system prompts (versioned) | `alert_only` initially | Highest blast radius; needs prompt versioning + human review for first months |

Each is a single new Python file in `orchestrator/app/quality_loop/loops/`, registered with the runner. Not built in Cycle 2.

## Risk gating (agency modes)

Per-loop config — stored in `platform_config` (DB-backed, runtime-editable):

| Mode | Behavior |
|---|---|
| `auto_apply` | Loop runs full lifecycle without human input; persists or reverts based on `decide()` |
| `propose_for_approval` | Loop runs through `propose()`, persists session as `pending_approval`, waits for cortex/human to call `POST /api/v1/quality/loops/sessions/{id}/approve` or `/reject` |
| `alert_only` | Loop runs `sense()` + `propose()` only; emits alert; never calls `apply()` |

**New loops default to `alert_only`.** Promotion to higher agency is an explicit decision (config update). This mirrors how production ML control systems handle progressive autonomy — you don't earn auto-apply, you graduate to it.

## Action surfaces inventory

What loops can actually change:

| Surface | Owner | Reversibility | Eligible loops |
|---|---|---|---|
| `nova:config:retrieval.*` | Redis (orchestrator) | Trivial — write old value | A |
| `nova:config:llm.routing.tier_*` | Redis (gateway) | Trivial — write old value | B |
| `nova:config:engram.consolidation_*` | Redis (memory-service) | Trivial; consolidation effects observable over days | C |
| `agent_prompts` (new versioned table) | DB (orchestrator) | Activate previous version | D |
| `nova:config:context_budget.*` | Redis | Trivial | future |

Out of scope for v2: anything requiring code/migration changes, anything affecting infrastructure, anything cross-tenant.

## APIs

### Orchestrator endpoints

**Benchmark execution** (Cycle 1):

| Method + Path | Purpose | Auth |
|---|---|---|
| `POST /api/v1/quality/benchmarks/run` | Kick off async benchmark run; returns `run_id` | AdminDep |
| `GET /api/v1/quality/benchmarks/runs` | List recent runs | AdminDep |
| `GET /api/v1/quality/benchmarks/runs/{id}` | Single run with case-level detail | AdminDep |
| `DELETE /api/v1/quality/benchmarks/runs` | Clear all (existing, retained) | AdminDep |

The legacy paths (`/api/v1/benchmarks/run-quality`, `/api/v1/benchmarks/quality-results`) stay routed during Cycle 1 as aliases to the new paths. Removed once the dashboard `/ai-quality` page on `main` no longer references the legacy paths (verifiable by `grep` in dashboard code) — that's the gating signal for the cleanup commit.

**Live scores** (Cycle 1, existing endpoints with updated dimension list):

- `GET /api/v1/quality/scores`
- `GET /api/v1/quality/summary`

**Snapshots** (Cycle 1):

| Method + Path | Purpose |
|---|---|
| `GET /api/v1/quality/snapshots/{id}` | Single snapshot |
| `GET /api/v1/quality/snapshots/diff?from={id}&to={id}` | Diff between two snapshots |

**Loops** (Cycle 2):

| Method + Path | Purpose |
|---|---|
| `GET /api/v1/quality/loops` | Registered loops with current agency mode + last session |
| `POST /api/v1/quality/loops/{name}/run-now` | Manual trigger (cortex or admin) |
| `GET /api/v1/quality/loops/{name}/sessions` | Session history |
| `GET /api/v1/quality/loops/sessions/{id}` | Single session detail |
| `POST /api/v1/quality/loops/sessions/{id}/approve` | For `propose_for_approval` |
| `POST /api/v1/quality/loops/sessions/{id}/reject` | For `propose_for_approval` |
| `PATCH /api/v1/quality/loops/{name}/agency` | Change mode (admin only) |

### Cortex consumes

Cortex's thinking cycle includes a Quality drive (`cortex/app/drives/quality.py`) that:

1. Polls `GET /api/v1/quality/summary?period=7d` periodically (default 30 min; configurable via `nova:config:quality.cortex_poll_interval_sec`).
2. Compares against rolling baseline; if regression detected, calls `POST /api/v1/quality/loops/{name}/run-now` for the loop watching that dimension.
3. Polls `GET /api/v1/quality/loops/sessions/{id}` for in-flight sessions.
4. For `propose_for_approval` sessions: cortex either auto-approves (if confidence high + change reversibility easy) or escalates to human via existing notification path.

Cortex does not implement loop logic — it only schedules and interprets.

## Dashboard

Three tabs at `/ai-quality`:

**Live Scores** — existing tab; updated dimension list (8, in vocabulary order); composite color logic unchanged.

**Benchmarks** — existing tab; case results show real per-dimension scores (no more `--`); each run shows the snapshot it ran against; adjacent-run diff button shows what changed between runs; run errors surface in a banner per row instead of being swallowed in `error_summary`.

**Loops** (new) — list of registered loops, each row showing:

- Name, agency mode, last session outcome, composite delta
- Click → session history table (one row per iteration: started_at, proposed change, outcome, decision, evidence link)
- "Run Now" button (admin only)
- "Pending Approval" queue at top when any session needs decision

`statusBadgeColor` mapping updated: `'completed' → success`, `'running' → warning`, `'failed' → danger`. The legacy `'complete'` value is migrated to `'completed'` by the migration; no code path produces `'complete'` after Cycle 1.

## Cycle 1 (truth-telling measurement) — implementation order

Each step is its own commit, independently revertable. TDD per step.

1. **Migration `NNN_quality_v2.sql`** (planner picks next available number — `065_` likely at plan time) — adds `config_snapshot_id`, `dimension_scores`, `vocabulary_version`, `error_summary` columns to `quality_benchmark_runs`; creates `quality_config_snapshots` table; backfills existing `'complete'` rows to `'completed'`.

2. **Snapshot capture utility** — `orchestrator/app/quality_loop/snapshot.py` with `async def capture_snapshot(captured_by: str) -> tuple[UUID, dict]`. Reads from Redis + DB, normalizes, hashes, dedups. Single function, ~50 lines.

3. **Fixture loader + benchmark cases YAML** — `orchestrator/app/quality_loop/cases.py` loads `benchmarks/quality/cases/*.yaml` at startup. Migrate the 6 inline cases from `quality_router.py:204` to YAML. Add cases for `instruction_adherence` and `safety_compliance` dimensions.

4. **Unified scorer** — `orchestrator/app/quality_loop/score.py` replaces inline benchmark scoring. Each dimension has a benchmark-mode scoring function; results write to `dimension_scores` JSONB using the unified vocabulary. Dimension scorer registry indexed by name.

5. **Engram teardown** — Benchmark engrams created with `source_metadata->>'benchmark_run_id'`; teardown after benchmark completes deletes them via `DELETE FROM engrams WHERE source_metadata->>'benchmark_run_id' = $1`. Stops polluting memory.

6. **Replace `_run_benchmark_background`** — rewrite to use fixture loader + unified scorer + snapshot capture + teardown + error surfacing. Status string fixed to `'completed'`.

7. **Add `instruction_adherence` and `safety_compliance` live scorers** — `quality_scorer.py` extensions. `instruction_adherence` is opt-in (off by default in live; benchmark always runs it). `safety_compliance` derived from `guardrail_findings` count.

8. **Auth fix** — benchmark runner uses orchestrator-internal calls (in-process), not admin-secret-via-HTTP self-loop. Eliminates the silent-failure mode where agent discovery returns 401. Also resolves the question of whether agent discovery hit a UserDep endpoint by accident.

9. **Dashboard updates** — drop `reasoning_quality` and `context_utilization` from `DIMENSION_LABELS`; add `instruction_adherence` and `safety_compliance`; add snapshot diff button to benchmark runs; surface `error_summary` in benchmark row banner.

### Cycle 1 success criteria

- "Run Benchmark" → row shows real composite score and per-dimension breakdown
- Adjacent runs show snapshot diff
- Live Scores tab shows 8 dimensions
- Benchmark engrams do not appear in `/sources` after benchmark completes
- All status badges show correct color
- A benchmark with broken auth surfaces the error in `error_summary` instead of silently scoring 0

## Cycle 2 (closed loop) — implementation order

10. **Migration `NNN_quality_loop_sessions.sql`** (planner picks next available, one after Cycle 1's migration) — adds `quality_loop_sessions` table.

11. **`QualityLoop` interface + base classes** — `orchestrator/app/quality_loop/base.py` with `Protocol`, `SenseReading`, `Proposal`, `AppliedChange`, `Verification`, `Decision` types.

12. **Loop runner** — `orchestrator/app/quality_loop/runner.py` background task. Single in-flight session per loop, locking via Redis `SETNX`. Persists session rows.

13. **Loop registry + agency config** — `platform_config` keys `quality.loops.{name}.agency`; loaded at startup, hot-reloadable via dashboard.

14. **`RetrievalTuningLoop`** — `orchestrator/app/quality_loop/loops/retrieval_tuning.py`. ~150 lines. Coordinate-descent over 3 params; full lifecycle implementation.

15. **Loop API endpoints** — `quality_router.py` extensions for `/api/v1/quality/loops/*` paths.

16. **Cortex Quality drive** — `cortex/app/drives/quality.py`. Polls summary, detects regressions, calls `run-now`, monitors sessions. Hooks into existing thinking cycle.

17. **Dashboard Loops tab** — new component `dashboard/src/pages/quality/LoopsTab.tsx`. Reads `/api/v1/quality/loops`. Approval UI for `propose_for_approval` sessions.

18. **Approval flow infrastructure** — built in Cycle 2 to support Loop A's `propose_for_approval` mode (testable by temporarily switching A's agency); will be reused by future B/D loops. Notifications when session enters `pending_approval`; UI to approve/reject; cortex-side auto-approval logic for low-risk reversible cases.

### Cycle 2 success criteria

- Cortex detects a manually-induced regression (e.g., `top_k=2`) and triggers a tuning session
- Loop session runs end-to-end: snapshot baseline → propose → apply → verify (re-run benchmark) → decide (persist if better, revert if worse) → persist session row
- Dashboard Loops tab shows session in real time with outcome
- Manual "Run Now" works
- `propose_for_approval` mode (test by switching loop A's mode temporarily) gates the apply step on approval

## Testing strategy

**Unit tests** (`orchestrator/tests/test_quality_*.py`):

- Snapshot capture / hash dedup (same config → same snapshot ID)
- YAML case loading and validation (malformed case raises clear error)
- Per-dimension benchmark scorers (each scorer in isolation)
- `QualityLoop` lifecycle (mocked sense/snapshot/apply, full state-machine traversal)
- Decision rule logic (persist vs revert thresholds)

**Integration tests** (`tests/test_quality_v2.py`):

- End-to-end benchmark run: real services, real engrams, real teardown, real DB writes
- Adjacent runs produce different snapshot IDs only when config differs
- `RetrievalTuningLoop` end-to-end: induced regression → trigger → propose → apply → verify → decide → revert path
- `propose_for_approval` mode: session persists, agency check blocks `apply`, approval endpoint unblocks
- Dashboard reads: `/api/v1/quality/loops` returns valid shape; loops tab renders without errors

**Regression tests** for the bugs being fixed:

- Benchmark with no agents: surfaces error in `error_summary`, doesn't return composite=0 silently
- Benchmark engrams: cleaned up after run (count of `source_metadata->>'benchmark_run_id'` = 0)
- Status string: all rows have `'completed'` not `'complete'` after migration
- Vocabulary: every benchmark run writes `dimension_scores` keys from the canonical 8-dimension set

## Cross-cutting concerns

### Security

- All quality APIs are `AdminDep` (admin secret) for internal services + cortex; user-facing dashboard fetch uses `UserDep` with admin-role JWT claim once user RBAC ships.
- Loops in `auto_apply` mode write to Redis runtime-config; same scope as existing dashboard runtime-config writes — no privilege escalation.
- Approval endpoints (`/approve`, `/reject`) are `AdminDep` until per-user RBAC exists.
- Cortex calls into orchestrator use the existing service-to-service auth pattern (admin secret); when the deferred service-account-JWT work from the security hardening chain lands, swap to that.

### Multi-tenant readiness

- All new tables include `tenant_id UUID` (nullable for v2 single-tenant; required when SaaS lands).
- Snapshot content is tenant-scoped; cross-tenant snapshot reuse forbidden when `tenant_id` is non-null.
- Loops run per-tenant when SaaS — orchestrator runner becomes tenant-aware. Out of scope for v2 implementation; the data model is forward-compatible.

### Observability

- All loop sessions logged at INFO (`Loop[retrieval_tuning] session={id} outcome={outcome} decision={decision}`).
- Session evidence (proposal reasoning, sense readings, verification scores) stored in `notes` JSONB for post-hoc debugging.
- Failed loop iterations log full context at ERROR; cortex sees these via existing log stream.
- Benchmark `error_summary` field surfaces silent failure modes that were previously swallowed.

### Performance / cost

- Benchmark suite full run: ~2 min (6 cases × ~20s each). Cortex daily exploration cycle adds ~2 min/day per loop in `auto_apply` mode.
- Snapshot capture: ~50ms (Redis MGET + DB rows + hash). Cheap.
- Live scoring overhead unchanged — `instruction_adherence` only runs when opted in.
- LLM-as-judge for `instruction_adherence` benchmark mode: ~1 LLM call per case × 8 cases × ~5s each = 40s added per benchmark run. Acceptable.

## Out of scope (track for follow-up)

- LLM-as-judge dimensions (`reasoning_quality`, `context_utilization`)
- User-defined benchmark cases (UI for case authoring)
- Multi-tenant per-tenant benchmark execution
- Cortex code-mod / migration self-modification
- Cross-loop coordination and conflict resolution
- Continuous benchmarking (always-on, low-rate) vs episodic (on-demand)
- Benchmark cost budgeting (cap LLM spend per benchmark run)
- Per-user benchmark sets (admin vs end-user perspectives)
