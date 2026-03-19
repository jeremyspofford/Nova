# Phase 4 Completion — Pipeline, Routing, Critique, Post-Pipeline Agents

**Date:** 2026-03-18
**Status:** Draft
**Repository:** jeremyspofford/nova

## Overview

Phase 4 (Quartet Pipeline + Async Queue) is ~95% complete. This spec covers the remaining work to check it off: E2E pipeline testing, subscription provider routing, clarification loop, two-phase critique agent, post-pipeline agents, and a notification system. All work follows TDD — tests first, then implementation.

The pipeline expands from 5 stages to 7, adding a Critique-Direction gate after Task and a Critique-Acceptance gate after Code Review. Four post-pipeline agents (Documentation, Diagramming, Security Review, Memory Extraction) run in parallel after completion.

## Pipeline Architecture

### Stage Order (7 stages + post-pipeline)

```
Context → Task → Critique-Direction → Guardrail → Code Review → Critique-Acceptance → Decision
                      ↕                                              ↕
                 clarification                                   revision loop
                 (user answers)                                  (back to Task)

Post-pipeline (parallel, best-effort):
  Documentation, Diagramming, Security Review, Memory Extraction
```

### Stage Responsibilities

| # | Stage | Role | Model Tier | Run Condition |
|---|-------|------|-----------|---------------|
| 1 | Context | Curate relevant files, docs, prior task history | cheap | always |
| 2 | Task | Produce the actual output (code, config, answer) | best | always |
| 3 | Critique-Direction | "Is this attempting the right thing?" | mid | `critique_approved == false` |
| 4 | Guardrail | Security scan: prompt injection, PII, credentials, spec drift | cheap (Tier 1), mid (Tier 2) | always |
| 5 | Code Review | Code quality: pass / needs_refactor / reject | mid | always |
| 6 | Critique-Acceptance | "Does this completely fulfill the original request?" | mid | always |
| 7 | Decision | ADR + human escalation (only on hard blocks) | best | `guardrail_blocked AND code_review_rejected` |

### Critique Agent — Two-Phase Design

The Critique agent fills a gap in the existing pipeline: no stage checks whether the output actually fulfills the user's request. Code Review checks code quality. Guardrail checks safety. Critique checks requirement fulfillment.

**Critique-Direction (position 3):**
- Compares Task Agent output against original request
- Three outcomes:
  - **Approved** — sets `critique_approved=true` in pipeline state, proceeds
  - **Needs revision** — loops back to Task with feedback ("you built X but the user asked for Y")
  - **Needs clarification** — triggers `clarification_needed` status, user answers in dashboard
- Max 2 revision loops before escalation
- Once `critique_approved=true`, this stage is skipped for all subsequent iterations (Code Review refactor loops don't re-trigger it)

**Critique-Acceptance (position 6):**
- Runs on every pipeline completion attempt
- Sees the full refined, security-checked, code-reviewed output
- Two outcomes:
  - **Pass** — task completes
  - **Fail** — loops back to Task with critique feedback (`critique_approved` stays `true`, Direction is still skipped)
- Max 1 revision loop — if it fails twice, escalate to human review

**Flag behavior:**
- `critique_approved` lives in pipeline checkpoint state alongside stage outputs
- Follows existing flag pattern (`guardrail_blocked`, `code_review_rejected`)
- Initialized to `false` on task start
- Set to `true` by Critique-Direction, stays `true` for pipeline lifetime
- Direction agent's `run_condition`: `{"type": "on_flag", "flag": "critique_approved", "invert": true}`

### Loop Scenarios

| Scenario | Direction runs | Acceptance runs | Total extra LLM calls |
|----------|---------------|-----------------|----------------------|
| Happy path | 1x (approves) | 1x (passes) | 2 |
| Task goes wrong direction | 2-3x until approved or escalated | 1x | 3-4 |
| Code Review refactor loop | 1x (then skipped via flag) | 1x per loop exit | 2+ |
| Ambiguous request (clarification) | 1x, pauses for user | 1x after refinement | 2 |

## Workstream 1: E2E Pipeline Testing

### Test Tier Structure

Tests live in `tests/` at repo root. Two tiers:

**Tier 1: Pipeline Mechanics (no LLM, fast, runs every time)**

| Test | What it proves |
|------|---------------|
| Submit → queued → picked up | Status transition through queue |
| Cancel queued task | Returns 204, status=cancelled |
| Cancel running task returns 409 | Documents the limitation |
| Dedup: double-enqueue same task_id | Second enqueue is no-op |
| Queue depth / dead-letter stats | Stats endpoints return correct counts |
| Pod + agent CRUD | Create, read, update, delete pods and agents |
| Recovery strategy branches | All 7 branches of `recovery_strategy()` |
| Reaper picks up stale tasks | Direct DB setup with expired heartbeat |
| Dead letter on exhausted retries | Direct DB setup with max retry_count |
| Human review approve re-queues | Direct DB setup with `pending_human_review` |
| Human review reject cancels | Same, verify status=cancelled |
| Concurrency saturation | 6+ tasks with semaphore=5, verify queuing |
| `on_failure=skip` path | Agent fails, pipeline continues |
| `on_failure=escalate` path | Agent fails, task pauses for human review |

**Tier 2: Pipeline Behavior (needs LLM, opt-in via `@pytest.mark.pipeline`)**

| Test | What it proves |
|------|---------------|
| Full happy-path completion | All 7 stages run, task completes |
| Stage progression transitions | Status moves through all `*_running` states in order |
| Refactor loop | Code Review → needs_refactor → Task reruns |
| Guardrail block → escalation | End-to-end human review flow |
| Adaptive stage skipping | Simple task skips Context + Code Review |
| Parallel group execution | Agents in same group run concurrently |
| Critique-Direction approval | Direction approves, flag set, skipped on rerun |
| Critique-Direction revision | Direction rejects, Task reruns with feedback |
| Clarification loop | Direction pauses, user answers, pipeline resumes |
| Critique-Acceptance pass/fail | Acceptance checks final output |
| Post-pipeline memory extraction | Engram ingestion queue gets entry after completion |

### Test Infrastructure

**Fixtures:**

- `create_test_pod(agents=[...])` — Creates a pod with configurable agent slots, auto-deletes on teardown. Handles the verbose multi-API-call setup.
- `force_cleanup_task(task_id)` — Deletes task via direct DB access (not API cancel, which only works for queued/pending_human_review). Used in teardown for tasks stuck in running states.
- `pipeline_task(pod_name, input)` — Submits a task, polls until terminal state or timeout, returns final state. Handles the async wait loop.

**New endpoint for testing:**

- `POST /api/v1/pipeline/reap-now` — Admin-only. Triggers one reaper cycle immediately instead of waiting for the 60s loop. Returns reaper results (tasks reaped, actions taken).

**Nondeterminism strategy:**

For tests that need specific agent behavior (e.g., Code Review must return `needs_refactor`), configure the agent's system prompt to guarantee the outcome. Example: Code Review agent with system prompt "Always return needs_refactor on the first iteration, pass on the second." This is configuring the system, not mocking it.

**Test resource convention:**

All test pods use `nova-test-` name prefix. Task cleanup via `force_cleanup_task()` in fixture teardown. Tests must not leak tasks that trigger the reaper in subsequent runs.

## Workstream 2: Subscription Provider Routing

### Goal

Make Claude Max and ChatGPT Plus subscriptions the preferred routing tier so autonomous pipeline runs cost $0.

### Current State

Subscription providers exist:
- `llm-gateway/app/providers/claude_subscription_provider.py` — OAuth token (`sk-ant-oat01-*`)
- `llm-gateway/app/providers/chatgpt_subscription_provider.py` — ChatGPT Plus/Pro

They're registered in the provider registry but not prioritized in routing.

### Design

New routing layer above existing strategy:

```
subscription (Claude Max → ChatGPT Plus) → [existing routing strategy] → fallback
```

**New config:**
- `llm.prefer_subscription` — boolean, default `true`, stored in `platform_config` table, UI-configurable in Settings > AI & Models
- When enabled, gateway tries subscription providers first
- If subscription fails (quota exhausted, token expired, provider down), falls through to normal routing transparently
- Subscription providers self-report health — missing/invalid OAuth token = unavailable, zero latency cost to skip

**Provider priority within subscriptions:** Claude Max → ChatGPT Plus (configurable via `llm.subscription_priority` array).

**What doesn't change:** Existing routing strategies (local-first, cloud-first, etc.) remain untouched. Users without subscriptions see zero difference.

**Dashboard:** Provider Status section shows subscription providers with health/quota state.

## Workstream 3: Clarification Loop

### Flow

```
Task submitted → Context Agent or Critique-Direction detects ambiguity
  → status = 'clarification_needed'
  → questions stored in task metadata
  → pipeline pauses (checkpoint saved)

User sees notification + badge in dashboard → answers questions
  → POST /api/v1/pipeline/tasks/{id}/clarify
  → answers merged into metadata
  → task re-queued, resumes from clarification point with enriched input
```

### Ambiguity Detection

Not a separate classifier. The Context Agent and Critique-Direction agent receive system prompt instructions: "If the request is ambiguous, missing critical information, or could be interpreted multiple ways, output a structured JSON block with your questions instead of proceeding."

The executor checks for the clarification signal in the agent's output and pauses the pipeline.

### Database Changes

None. Uses existing columns:
- `tasks.status` — new value: `'clarification_needed'`
- `tasks.metadata` — `{"clarification_questions": [...], "clarification_answers": [...], "clarification_round": 1}`
- `tasks.checkpoint` — saves agent's partial work for resume

### New Endpoint

`POST /api/v1/pipeline/tasks/{id}/clarify`
- Body: `{"answers": ["answer1", "answer2", ...]}`
- Validates task is in `clarification_needed` status
- Merges answers into `metadata.clarification_answers`
- Increments `clarification_round`
- Re-queues task; executor resumes from the agent that requested clarification

### Constraints

- Max `pipeline.clarification_max_rounds` rounds (default 2) — after that, proceed with available info
- Timeout: `pipeline.clarification_timeout_hours` (default 24h) — unanswered tasks auto-cancel
- User can cancel a `clarification_needed` task at any time (cancel API updated to include this status)

### Dashboard UI

- Tasks in `clarification_needed` show amber indicator in task list
- Task detail view shows questions and an answer form
- Browser notification fires on status change
- Badge counter on Tasks nav includes `clarification_needed` count

## Workstream 4: Post-Pipeline Agents

### Agents

| Agent | Trigger | Input | Output (artifact_type) |
|-------|---------|-------|----------------------|
| Documentation | Always on completion | Task input + Task Agent output + code artifacts | `documentation` — summary of what was done, why, what changed |
| Diagramming | When task produced code or architecture changes | Task input + Task Agent output | `diagram` — Mermaid diagram(s): data flow, component relationships, sequence |
| Security Review | When task produced code | All code artifacts | `security_review` — vulnerability findings (OWASP categories, severity, remediation) |
| Memory Extraction | Always on completion | Full pipeline context (input, all stage outputs) | Pushes to `engram:ingestion:queue` |

### Implementation

These are pod agents configured in `pod_agents`:
- Position values after the main 7 stages
- Shared `parallel_group = 'post_pipeline'`
- `run_condition` controls trigger (e.g., Diagramming has `{"type": "on_flag", "flag": "has_code_artifacts"}`)
- Default model: `tier:cheap`

The executor already has parallel group support. After the final main-pipeline stage, all `post_pipeline` agents run via `asyncio.gather`. Each produces an artifact row. Failures are logged at WARNING but don't affect task status.

### Diagramming Output

Mermaid markdown stored in `artifacts.content`. Dashboard artifact viewer renders Mermaid diagrams (add `mermaid-react` or equivalent to dashboard dependencies).

### Memory Extraction

Partially implemented — `_extract_task_memory()` already exists in the executor. This formalizes it as a configurable pod agent instead of hardcoded logic.

## Workstream 5: Notification System

### SSE Notifications

- New SSE event type: `notification` with payload `{type, task_id, title, body}`
- Backed by Redis pub/sub channel `nova:notifications`
- Any service can publish; dashboard subscribes
- Notification types: `clarification_needed`, `pending_human_review`, `task_complete`, `task_failed`

### Browser Notifications

- Dashboard requests `Notification` permission on first visit
- Toast notification on SSE event
- Browser `Notification` API for background tab visibility

### Badge Counter

- Persistent badge on Tasks nav item in dashboard sidebar
- Counts tasks in `clarification_needed` + `pending_human_review`
- Polled via existing TanStack Query refetch (staleTime=5s)
- Uses existing `GET /api/v1/pipeline/tasks` with status filter — no new endpoint
- Clicking badge filters Tasks page to items needing attention
- Badge clears as items are resolved

## New Configuration Keys

| Key | Type | Default | Location | Description |
|-----|------|---------|----------|-------------|
| `llm.prefer_subscription` | boolean | `true` | platform_config (UI) | Try subscription providers first |
| `llm.subscription_priority` | string[] | `["claude_subscription", "chatgpt_subscription"]` | platform_config (UI) | Subscription provider priority order |
| `pipeline.clarification_max_rounds` | int | `2` | platform_config (UI) | Max clarification rounds before proceeding |
| `pipeline.clarification_timeout_hours` | int | `24` | platform_config (UI) | Hours before unanswered clarification auto-cancels |

## New API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/pipeline/tasks/{id}/clarify` | user | Answer clarification questions |
| `POST` | `/api/v1/pipeline/reap-now` | admin | Trigger one reaper cycle (testing) |

## Database Changes

Minimal:
- `tasks.status` — add `'clarification_needed'` to valid values (status is a TEXT column, not a DB enum — no migration needed)
- New `pod_agents` rows — Critique-Direction, Critique-Acceptance, Documentation, Diagramming, Security Review, Memory Extraction agents added to default Quartet pod
- `critique_approved` flag — stored in `tasks.checkpoint` JSONB (no schema change)

## Implementation Order

TDD throughout. Tests written first, then implementation to make them pass.

1. **E2E Pipeline Testing** — Tier 1 mechanics tests + Tier 2 behavior tests against existing pipeline. Find and fix latent bugs.
2. **Subscription Provider Routing** — Wire up preference layer, test routing cascade.
3. **Clarification Loop** — Context Agent detection, `/clarify` endpoint, dashboard UI, notifications.
4. **Critique Agent** — Direction + Acceptance agents, flag system, revision loops.
5. **Post-Pipeline Agents** — Documentation, Diagramming, Security Review, Memory Extraction.
6. **Notification System** — SSE channel, browser notifications, badge counter.

Workstreams 3-4 have a dependency (clarification is used by Critique-Direction), so they're ordered accordingly. Workstreams 5-6 are additive and can be parallelized.
