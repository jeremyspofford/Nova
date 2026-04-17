# Phase 1.0 — Heal the Stack — Design Spec

> **Date:** 2026-04-16
> **Status:** Draft — awaiting user approval
> **Approach:** Five small P0/S-effort fixes grouped into one coherent "quiet + fast" sprint; each lands as its own commit
> **Backlog refs:** REL-001, OPS-001, OPS-002, PERF-002, SEC-005 (see `docs/audits/2026-04-16-phase0/BACKLOG.md`)

---

## Problem

The Phase 0 audit surfaced 113 defect findings across nine axes. A cluster of five of them are unique in shape:

- **P0 severity**, **small effort** (≤1 day each)
- **Actively broken on Jeremy's running stack right now** (observable in live logs and live Redis state at audit time)
- **Independent of each other** — each can ship alone, land in any order, or be reverted without affecting the others
- **Together they change the baseline user experience** — from "6–14s cloud-fallback chat on a stack spam-logging task-transition errors" to "sub-second local chat on a quiet stack"

This is the cheapest possible opening move for Phase 1: close the noisy, slow, half-cloud state before starting any of the bigger clusters (security redesign, memory trust model, triggers feature). Every Phase 1 cluster that follows is easier to execute on a healed stack.

## Goals

1. **Stop the reaper error spam.** `orchestrator` is currently looping `Invalid task status transition: task_running -> queued (rejected by state machine)` every 60 seconds against 9 tasks — 4 of them stuck since 2026-04-04.
2. **Eliminate the health-rollup cascade.** A 3-second probe timeout on an inner service should not flip three services to `degraded`.
3. **Plug the Redis connection leaks** in the five modules that violate `CLAUDE.md`'s explicit "every `get_redis()` has a matching `close_redis()` in the lifespan" rule.
4. **Restore local-first inference.** Flip Ollama back on so chat latency drops and embeddings stop going to cloud Gemini on every call.
5. **Lock the default install path.** `./scripts/setup.sh` must auto-rotate the default admin secret and Postgres password (matching the existing pattern for `CREDENTIAL_MASTER_KEY`).

## Non-Goals

- **The larger sandbox / host-root-mount redesign** (SEC-001, SEC-002, SEC-006, PRIV-002, OPS-014). Separate security-cluster spec.
- **Structured logging rollout** in cortex/intel-worker/knowledge-worker/recovery (OPS-004). Separate infra spec.
- **Metrics / tracing / observability plumbing** (OPS-005). Separate infra spec.
- **Deeper root-cause investigation of the 9 stuck tasks.** We fail them cleanly with an audit-trail reason and move on. If a pattern emerges post-heal, that's a follow-up.
- **New regression tests for mechanical changes** (OPS-002 lifespan wiring, PERF-002 Redis config flip, SEC-005 shell script). If we tested every lifespan cleanup we'd never ship.

---

## The Five Fixes

Each fix below is independent. Presented in the order they will be implemented — OPS-001 + OPS-002 first to quiet the logs, then REL-001 to clean stuck state, then PERF-002, then SEC-005.

### Fix 1 — OPS-001: Health-rollup cascade

**Defect.** Every downstream probe in the readiness rollup uses `httpx` with a 3-second timeout, and the outer probe's own budget is also 3 seconds. When Ollama is unreachable, `llm-gateway`'s `/health/ready` takes ~3.01s → `orchestrator`'s probe of it times out → orchestrator reports `degraded` with empty-message error → `chat-api`'s probe of orchestrator also times out → three services are "degraded" because one informational sub-check (Ollama) is slow.

**Fix.** Downstream probes in rollups must call `/health/live` (flat, self-only — DB, Redis, disk), never `/health/ready` (which itself cascades). `cortex/app/health.py` already does this correctly; `chat-api/app/main.py:62-78` and `orchestrator/app/health.py:13-37` are the two places that need changing.

**Shape of change.** Two small edits, each ~3 lines. URLs change from `…/health/ready` to `…/health/live`. No timeout/budget adjustment needed.

**Verification.**
- **Integration test** (new): with Ollama deliberately stopped (or pointing at an unreachable URL), hit `chat-api/health/ready`. Assert `status == "ready"` (not `"degraded"`). High value — we just saw the bug; guard against regression.
- **Manual check**: after the fix, `curl localhost:8000/health/ready` and `curl localhost:8080/health/ready` return `ready` independent of Ollama state.

### Fix 2 — OPS-002: Redis connection leaks

**Defect.** CLAUDE.md codifies: "Every service with `get_redis()` must have a corresponding `close_redis()` called in the FastAPI lifespan shutdown path." Five module-level Redis singletons violate this. Developer hot-reload accumulates zombie connections visible in `redis-cli client list`.

**Fix.** Add `async def close_redis()` to each offender and wire it into the service's FastAPI lifespan shutdown path:

| Module | Current state | Fix |
|---|---|---|
| `memory-service/app/embedding.py` | singleton `_redis`, no close function | Add `close_redis()`; call from `memory-service/app/main.py` lifespan shutdown |
| `llm-gateway/app/discovery.py` | singleton `_redis`, no close | Same pattern |
| `llm-gateway/app/registry.py` | singleton `_strategy_redis`, no close | Same pattern |
| `cortex/app/budget.py` | singleton `_redis`, no close | Wire into `cortex/app/main.py` lifespan (stimulus close already there) |
| `orchestrator/app/stimulus.py` | singleton `_redis`, no close | Wire into `orchestrator/app/main.py` lifespan |

**Shape of change.** Five ~4-line additions (close function), five ~1-line lifespan wiring. No behavior change under steady-state; cleanup only on shutdown/reload.

**Verification.** Manual: after changes, `docker compose restart memory-service llm-gateway cortex orchestrator` and check `redis-cli client list | wc -l` is stable across restarts (not climbing). No formal regression test — the mechanical change is its own verification.

**Out of this fix.** The 11 ad-hoc `aioredis.from_url(...)` sites in `engram_router.py` and `config_sync.py` (correctly opened+closed per-request but wasteful). Cleanup task, not a leak — move to OPS-related backlog instead.

### Fix 3 — REL-001: Reaper infinite-loop on state transition

**Defect.** `orchestrator/app/reaper.py:107-110` calls `transition_task_status(task_id, "queued", …)` for tasks with expired heartbeats. `orchestrator/app/pipeline/state_machine.py:49-53` does not include `queued` among the legal successors from `task_running`. Every reaper cycle: rejected transition → warning + error log → retry counter doesn't advance → next cycle repeats forever. Currently 9 tasks affected, 4 from 13 days ago.

**Fix (two parts).**

1. **Code change — reaper behavior.** Introduce a dedicated recovery helper that *bypasses the state machine* for reap scenarios and transitions stuck `*_running` rows directly to `failed` (not `queued`) with a clear `error` column value like `"reaped: heartbeat expired (stuck in $state for $duration)"`. This matches what operators expect from a stuck task: visible failure, out of the running set, eligible for retry through the normal re-queue UX rather than through the reaper.
2. **One-time cleanup at startup.** On orchestrator boot, scan for any task in a `*_running` state whose heartbeat is ≥ `task_stale_seconds` old, and fail-migrate it using the same recovery helper. This runs once at startup, idempotent — existing stuck tasks surface as `failed` with `error = "reaped at startup: previously stuck since $timestamp"`.

**Why "fail" and not "requeue".** Tasks stuck for minutes-to-days have lost all context (heartbeat channel, connection state, whatever LLM call was in flight). Silently re-enqueuing them masks whatever caused the stick. Failing them preserves the audit trail and forces re-submission through the normal path.

**Shape of change.** New helper in `orchestrator/app/pipeline/state_machine.py` (~15 lines); reaper call-site update (~3 lines); startup cleanup hook in `orchestrator/app/main.py` lifespan startup (~10 lines).

**Verification.**
- **Regression test** (new): enqueue a task, manipulate its `last_heartbeat_at` to be older than `task_stale_seconds`, run one reaper cycle, assert the task is in `failed` state with a meaningful `error` string. This is the load-bearing fix for a service the whole pipeline depends on.
- **Manual check**: after the fix lands and startup cleanup runs, `SELECT count(*) FROM tasks WHERE status IN ('task_running', 'context_running', …)` with stale heartbeats should return 0. `docker compose logs orchestrator --since 5m | grep "Invalid task status"` should return nothing.

### Fix 4 — PERF-002: Ollama fallback to cloud on every call

**Defect.** Redis runtime config holds `nova:config:inference.backend=none`, `inference.state=stopped`, `llm.routing_strategy=cloud-only`, and `llm.ollama_url=http://172.24.32.1:11434` (WSL gateway IP, currently unreachable from containers because of Windows firewall or the Ollama host-binding history). Every embedding call, every engram ingest, every consolidation phase is a cloud Gemini round-trip (~150–250 ms each). Observed: 194 "fallback embedding model" log lines in 300 memory-service log lines.

**Fix.** Two coordinated Redis config updates plus one potential compose adjustment:

1. **Update Redis config keys** (user A-fix confirmed host Ollama binding is now 0.0.0.0):
   - `nova:config:llm.ollama_url` → `http://host.docker.internal:11434` (verified reachable from `llm-gateway` container during design; resolves 14 models)
   - `nova:config:inference.backend` → `ollama`
   - `nova:config:inference.state` → `ready`
   - `nova:config:llm.routing_strategy` → `local-first`

2. **Ensure memory-service can reach Ollama** (plan step — may or may not be needed depending on whether memory-service calls Ollama directly or routes through `llm-gateway`). If direct: add `extra_hosts: host.docker.internal:host-gateway` to memory-service in `docker-compose.yml` (currently present on llm-gateway only per OPS-009). If it routes through gateway's `/embed`: no compose change needed.

3. **Verify** by a live `curl` from inside each container that needs Ollama, and by watching the memory-service log for "fallback embedding model" to disappear.

**Shape of change.** Four `redis-cli SET` commands (or UI flips via Dashboard Settings); potentially one ~2-line compose addition; one restart of memory-service if the compose changes.

**Verification.**
- **Manual check**: immediately after the Redis flip, send one chat message. Assert turn latency drops from 6–14s to <1s on warm path.
- **Log check**: `docker compose logs memory-service --since 2m | grep "fallback embedding model"` returns nothing.
- No formal regression test. The fix is a config change; its observable effect is the verification.

**Out of this fix.** The deeper OPS-009 finding (Ollama auto-detect probe runs from host shell, not from inside a container, so setup-time detection can pass while runtime fails). That needs a distinct small spec addressing setup.sh's validation step.

### Fix 5 — SEC-005: Default secrets survive non-wizard install

**Defect.** `scripts/setup.sh:14-25` copies `.env.example` verbatim but never rotates `NOVA_ADMIN_SECRET` or `POSTGRES_PASSWORD`. In `.env.example`, `NOVA_ADMIN_SECRET` ships with the literal placeholder `nova-admin-secret-change-me`, and `POSTGRES_PASSWORD` ships empty (similar to the already-rotated `CREDENTIAL_MASTER_KEY` / `BRIDGE_SERVICE_SECRET`). When `POSTGRES_PASSWORD` is empty at compose-time, `docker-compose.yml` falls back to `nova_dev_password` (that's where the "nova_dev_password" default lives — in the compose fallback, not in the shipped `.env`). So users who follow CLAUDE.md's quick-start (`./scripts/setup.sh`) end up with a known placeholder admin secret and a predictable Postgres password. `dashboard/src/api.ts:6` also hardcodes the admin secret default as a localStorage value, so a fresh dashboard sends the known-bad secret automatically.

**Fix.** Modify `scripts/setup.sh` to detect-and-rotate both values in the freshly-copied `.env`, using the same `openssl rand`-based pattern already used for `CREDENTIAL_MASTER_KEY` and `BRIDGE_SERVICE_SECRET` at `scripts/setup.sh:33-45`. Note the grep guards need two different patterns: `POSTGRES_PASSWORD=` matches the existing empty-value pattern exactly; `NOVA_ADMIN_SECRET=nova-admin-secret-change-me` is a distinct literal-placeholder pattern. If the user-edited `.env` already contains non-default values, do not touch them (idempotent; preserves user customization).

**Shape of change.** ~10 lines added to `scripts/setup.sh`. No code changes elsewhere in this fix. Dashboard hardcoded-default change (`dashboard/src/api.ts:6`) is a separate P2 concern (SEC-012 localStorage issue); out of scope here.

**Verification.**
- **Manual check**: on a clean repo (fresh `.env.example` copy), run `./scripts/setup.sh` and confirm the resulting `.env` has randomly-generated values for both keys (not the defaults).
- **Idempotency check**: run setup twice in a row; second run must not re-rotate (matches how `CREDENTIAL_MASTER_KEY` behaves today).
- No formal test — the change is in a shell script; live verification is faster than test infrastructure.

---

## Order of Operations

1. **OPS-001 + OPS-002 first.** They quiet the error-log noise and plug the connection leaks. Every subsequent fix is easier to observe on a quiet stack.
2. **REL-001 second.** Clean up the stuck state while the stack is already mid-surgery; startup cleanup hook runs one time only.
3. **PERF-002 third.** With noise gone and state clean, flip Ollama back on and verify chat latency drops.
4. **SEC-005 last.** Tiny script change, zero runtime impact, no dependencies.

Each fix is a separate commit, each independently revertable. If any fix proves problematic, later fixes are unaffected.

## Success Criteria

Phase 1.0 is complete when all of the following are true:

1. `docker compose logs orchestrator --since 5m | grep -E "Invalid task status|Reaper: task .* stale"` returns nothing.
2. `curl -sf localhost:8000/health/ready && curl -sf localhost:8080/health/ready` both return `status=ready` regardless of whether Ollama is running.
3. `docker compose exec redis redis-cli client list | wc -l` returns a stable value across a full stack restart (no climbing).
4. Memory-service log emits zero "fallback embedding model" lines after the PERF-002 flip.
5. A chat turn end-to-end latency measured at `<2s` on a warm stack (vs. 6–14s before). `<1s` is the stretch target — adjust in the plan if early measurement shows it's unreachable with tool-calls + memory activation on the critical path.
6. Fresh `./scripts/setup.sh` run on a blank `.env` produces randomly-generated `NOVA_ADMIN_SECRET` and `POSTGRES_PASSWORD`.
7. The BACKLOG.md entries REL-001, OPS-001, OPS-002, PERF-002, SEC-005 all flip from `Open` to `Done`.

## Testing Discipline

Proportional to risk:

| Fix | Test type | Rationale |
|---|---|---|
| REL-001 | **Regression test** — simulated stale heartbeat, assert `failed` | Reaper is load-bearing; regression would silently rot a core invariant |
| OPS-001 | **Integration test** — stop Ollama, probe chat-api, assert ready | Just saw this bug; test prevents the exact regression |
| OPS-002 | Manual — `redis-cli client list` across restarts | Mechanical plumbing; live verification is faster |
| PERF-002 | Manual — log grep + turn-latency timing | Config flip; the observable effect is the test |
| SEC-005 | Manual — fresh install run, grep `.env` for generated values | Shell script change; test infra would exceed the change size |

---

## Risks & Rollback

- **REL-001 startup cleanup fails partway.** The migration is idempotent — restart the orchestrator; it'll retry on the next boot. Worst case: leave the stuck tasks as-is and ship only the reaper behavior change; cleanup becomes a one-shot script.
- **PERF-002 Ollama flip breaks chat.** Revert by flipping Redis config back (`routing_strategy=cloud-only`). No code changes involved, no redeploy needed.
- **OPS-001 reveals that another service depended on the cascading behavior.** Very unlikely — no service *should* rely on another service's readiness rolling up opaque errors. If it happens, add the specific dependency check back explicitly at the call site rather than in the health probe.
- **OPS-002 lifespan ordering matters.** The `close_redis()` additions must run *before* the service binds are released but *after* any background tasks that use Redis have been cancelled. Follow the pattern in `chat-api/app/session.py:30-35` — the canonical example.

## Definition of Done

- Five commits on `main`, each for one fix, each following the repo's conventional-commit style.
- New regression tests for REL-001 and OPS-001 pass on `make test`.
- Manual verification items in "Success Criteria" all confirmed.
- `BACKLOG.md` entries updated to `Done` with commit SHAs.

## Out-of-Scope Follow-ups

- Clean up the 11 ad-hoc `aioredis.from_url` sites in `engram_router.py` and `config_sync.py` — legit connection hygiene but not the leak class fixed here.
- Dashboard hardcoded admin secret default (`dashboard/src/api.ts:6`) — separate SEC-012 localStorage redesign.
- Ollama setup-time detection mismatch (OPS-009) — separate setup.sh hardening spec.
- Deeper investigation of the root cause behind the 9 stuck tasks from 2026-04-04 — if the pattern recurs post-heal, file as a follow-up.
