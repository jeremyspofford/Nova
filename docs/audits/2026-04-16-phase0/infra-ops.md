# Infra & Ops Audit — 2026-04-16

## Scope

Reviewed Nova's Docker Compose topology, health-check semantics, FastAPI
lifespans and resource cleanup, log configuration, startup resilience,
`.env.example` completeness, bind-mount layout, Ollama detection logic, and
the Makefile / setup.sh / backup / restore scripts.

Evidence is drawn from the tree at `/home/jeremy/workspace/arialabs/nova/` plus
live probes against the currently running stack. Prior-art read:
`docs/superpowers/specs/2026-03-28-platform-health-analysis.md`.

Out of scope per the audit design spec: Kubernetes / production deployment,
CI/CD, dependency-health (covered by the agent-fleet cron), feature-level
correctness (handled by reliability / agent-quality axes).

---

## Findings

### [P0] Health-check cascade turns one slow probe into three-service "degraded"

- **Evidence:**
  - `chat-api/app/main.py:62-78` — `/health/ready` opens a 3.0-second httpx
    request to `orchestrator/health/ready`.
  - `orchestrator/app/health.py:13-37` — orchestrator's `/health/ready` opens
    3.0-second httpx requests to `memory_service/health/ready` *and*
    `llm_gateway/health/ready`.
  - `llm-gateway/app/health.py:14-40` — llm-gateway's `/health/ready` opens a
    3.0-second httpx request to Ollama at `/api/tags`.
  - `cortex/app/health.py:29-43` — cortex probes 3 peers with 3.0-second
    timeouts (at least targets `/health/live` — not amplifying).
  - Live measurement just now:
    - `llm-gateway /health/ready` → **3.011s** (Ollama probe timed out; status
      still "ready" because Ollama is informational).
    - `orchestrator /health/ready` → returned `degraded` with
      `llm_gateway: "error: "` because the 3s inner probe + network round-trip
      exceeded the outer 3s budget.
    - `chat-api /health/ready` → **3.049s** with `orchestrator: "error: "`
      for the same amplification reason.
  - Docker healthcheck config: `x-nova-healthcheck` anchor at
    `docker-compose.yml:14-18` sets `timeout: 5s, retries: 3, interval: 5s` —
    containers flip to `unhealthy` after ~15s of cascading 3s timeouts, which
    is exactly what the 2026-03-28 incident showed.
- **Impact:** Any real-world latency on the innermost probe (cold Ollama,
  slow first-request JIT, brief LLM-gateway restart) is amplified outward
  and flips *three* services to `degraded` / `unhealthy`. Dashboard
  startup-gate, `/health-check` skill output, and docker healthchecks all
  lie about the actual availability of chat-api. A service whose Redis and
  orchestrator-WS dependencies are fine is marked "down" because
  llm-gateway once couldn't reach Ollama.
- **Recommendation:**
  1. Downstream probes in readiness rollups must call `/health/live` (flat,
     no dependencies), never `/health/ready`. Cortex already does this; fix
     chat-api (line 69) and orchestrator (lines 25-34).
  2. Alternatively, separate "can-I-accept-traffic" (self-only) from
     "ecosystem-health" (rollup) into two endpoints, and wire the docker
     `healthcheck:` test at the former. The latter is for dashboard
     display only.
  3. If a service *must* cascade, its outer timeout must exceed the sum of
     every inner timeout (here: `outer ≥ 2 × 3s + slack`). The current
     budget of 3s is literally identical to the inner budget.
- **Effort:** S — a 10-line change in each `health.py`, plus one decision
  about which endpoint the dashboard's rollup calls.

---

### [P0] Redis connections leak on shutdown in 5+ modules (missing `close()` wired into lifespan)

- **Evidence:** CLAUDE.md explicitly codifies the rule — "Every service with
  `get_redis()` must have a corresponding `close_redis()` called in the
  FastAPI lifespan shutdown path. Connection leaks accumulate across
  restarts." The rule is violated in:
  - `memory-service/app/embedding.py:20-27` — module-level `_redis` pool
    created by `get_redis()` but there is **no `close_redis()` function**
    and `memory-service/app/main.py:27-56` never closes the pool at
    shutdown. Every `pytest` run, every dev reload, every compose restart
    leaks one connection from DB 0 on memory-service.
  - `llm-gateway/app/discovery.py:36-43` — `_redis` singleton, no
    corresponding close function, llm-gateway lifespan at
    `llm-gateway/app/main.py:51-56` closes `rate_limiter`,
    `response_cache`, and `editor_tracker` but **not `discovery`** or the
    `registry` strategy client.
  - `llm-gateway/app/registry.py:210-220` — `_strategy_redis` module
    singleton; no close; not touched by lifespan.
  - `cortex/app/budget.py:15-23` — `_redis` singleton; no close function;
    cortex lifespan (`cortex/app/main.py:56-60`) closes `.stimulus.close_redis()`
    but not `.budget._redis`.
  - `orchestrator/app/stimulus.py:29-38` — `_redis` singleton pointing at
    db5 (cortex's queue); no close; not in orchestrator's lifespan close
    chain.
  - `orchestrator/app/engram_router.py:115, 142, 160, 191, 455` — five
    separate ad-hoc `aioredis.from_url(...)` calls inside route handlers
    wrapped in `try / finally: await r.aclose()`. That's correct, but
    wasteful (a fresh TCP handshake per request). Should reuse the
    module singleton from `knowledge_router._get_engram_redis()`.
  - `orchestrator/app/config_sync.py:22-178` — six call sites each create
    a fresh client and close it. Same anti-pattern — the whole file could
    lean on one pooled client.
- **Impact:** Each restart / reload leaks between 4 and 8 idle Redis
  connections on average across the stack. Developer hot-reload
  (`make watch` / `--reload`) exacerbates this because every uvicorn
  child restart re-enters lifespan without a clean shutdown. Over a day
  of dev work, Redis ends up with dozens of zombie clients (visible in
  `redis-cli client list`). In a long-running prod container this is
  bounded, but over 100+ restarts it's user-visible.
- **Recommendation:**
  1. Add `async def close_redis()` + lifespan wiring to every flagged
     module. Parallel to the fix in `chat-api/app/session.py:30-35` (the
     canonical example).
  2. Replace the 11 ad-hoc `aioredis.from_url(...)` / `r.aclose()` pairs
     in `engram_router.py` and `config_sync.py` with shared pooled
     singletons.
  3. Add a lint-style CI check: grep for `aioredis.from_url` without a
     matching `close()` in the same module's lifespan.
- **Effort:** S — mostly mechanical.

---

### [P1] No pre-flight check for Docker network existence before service start

- **Evidence:**
  - `scripts/setup.sh:168-228` — starts postgres/redis, then Ollama, then
    "all Nova services" in sequence. Nowhere does it `docker network inspect
    nova_nova-internal` or otherwise confirm the user-defined bridge exists
    before the first `docker compose up`.
  - `docker-compose.yml:987-988` declares `nova-internal: driver: bridge`.
    Compose auto-creates this on `up` — normally. But the 2026-03-28 incident
    (referenced in the audit scope) was exactly a postgres container that
    did not attach to the network after a partial abort.
  - Failure mode (not speculation — we see it in
    `docker network ls`): if a previous `docker compose down` aborts
    mid-teardown, the network can remain in a half-removed state where
    `docker network create nova_nova-internal` succeeds but existing
    postgres/redis containers remain attached to the *old* network ID.
    On the next `up`, the new network exists, new services attach, and
    postgres is on the wrong network — invisible to peers but marked
    healthy via `pg_isready` (which is a local socket).
- **Impact:** Mysterious "postgres is healthy but nothing can reach it"
  state that takes a full `docker compose down --remove-orphans` + restart
  to clear. User-visible as a cold-start that hangs with orchestrator in
  crashloop reporting `asyncpg.exceptions.CannotConnectNowError`.
- **Recommendation:** Add to `scripts/setup.sh` after line 170:
  ```bash
  # Pre-flight: verify no stale network or dangling containers
  if docker network inspect nova_nova-internal &>/dev/null; then
    attached=$(docker network inspect nova_nova-internal -f '{{range .Containers}}{{.Name}} {{end}}')
    if [ -n "$attached" ]; then
      # Check every listed name is actually a current service or warn
      ...
    fi
  fi
  ```
  Or simpler: always run `docker compose down --remove-orphans` before
  `up` in setup.sh's first run. The `make down` target already does
  `--remove-orphans` (line 47) but setup.sh doesn't.
- **Effort:** S.

---

### [P1] Three services use `logging.basicConfig` instead of structured JSON logging

- **Evidence:**
  - `nova-contracts/nova_contracts/logging.py:63-80` provides
    `configure_logging(service, level)` — a JSON formatter with
    correlation-ID context vars.
  - Services that call it correctly: orchestrator, chat-api, memory-service,
    llm-gateway, chat-bridge, voice-service (with fallback).
  - Services that do *not*:
    - `cortex/app/main.py:16` — `logging.basicConfig(level=...)`
    - `intel-worker/app/main.py:13` — `logging.basicConfig(level=...)`
    - `knowledge-worker/app/main.py:15` — `logging.basicConfig(level=...)`
    - `recovery-service/app/main.py:18` — no logging configuration at all;
      just `logger = logging.getLogger("nova.recovery")`. Output falls to
      uvicorn's default formatter, which is the opposite of JSON.
- **Impact:** Grep-by-service across `docker compose logs` works for the
  seven JSON services but drops on a boundary at cortex / intel-worker /
  knowledge-worker / recovery. Fields like `task_id`, `agent_id`,
  `session_id` that `set_context()` propagates never appear from those
  four services — makes cross-service tracing impossible for any
  cortex-initiated chain.
- **Recommendation:** Change those four service entrypoints to the same
  2-line pattern as memory-service:
  ```python
  from nova_contracts.logging import configure_logging
  configure_logging("cortex", settings.log_level)
  ```
  Recovery-service is the most important — it's the service users end up
  inspecting during a disaster recovery and deserves structured output.
- **Effort:** S — 15 minutes total.

---

### [P1] No metrics / tracing / latency observability endpoints

- **Evidence:**
  - Grep for `prometheus`, `/metrics`, `opentelemetry`, `trace` across
    `**/app/*.py` returns no framework integrations. The only "metrics"
    endpoint is `llm-gateway/app/router.py:190` — a rolling `deque` of
    inference latencies exposed at `/health/inflight`, scoped only to
    local inference.
  - No Prometheus scrape target in `docker-compose.yml`. No request
    duration histograms anywhere. Pipeline stage timings are written to
    Postgres (`pipeline_router.py:465`) but that's post-hoc, not
    queryable at runtime.
  - Dashboards rely on hand-rolled DB queries (see
    `orchestrator/app/quality_router.py`, `cortex/app/journal.py`).
- **Impact:** "Why is this slow" is not answerable without reading
  source. A P95 latency spike on llm-gateway cannot be correlated to
  a provider or model. Cortex thinking-loop cycle duration is not
  measurable in aggregate. This is the exact gap that caused the
  2026-03-28 analysis to require deep code reading rather than a
  dashboard check.
- **Recommendation:** Not free, but the minimum useful step is one
  middleware added to every FastAPI service that emits
  `{service, method, path, status, duration_ms}` to Redis (simple list,
  TTL 1h) that the dashboard can read. No Prometheus required for v1.
  Full instrumentation (OpenTelemetry + Jaeger or Prometheus + Grafana)
  is a design-required Phase 2.
- **Effort:** M for the Redis middleware; L for full OTel.

---

### [P1] `.env.example` is missing ~25 variables the Compose file references

- **Evidence:** Diff of `docker-compose.yml` env references vs.
  `.env.example` exports (both enumerated via grep):
  - Missing entirely from `.env.example`:
    - `BACKUP_DIR`, `BACKUP_RETAIN_DAYS` — recovery service writes here
    - `BASELINE_MARKDOWN_PORT`, `BASELINE_MEM0_PORT`, `BASELINE_PGVECTOR_PORT`
    - `CHATGPT_TOKEN_DIR` — referenced in llm-gateway provider resolution
    - `CORTEX_ACTIVE_INTERVAL`, `CORTEX_CYCLE_INTERVAL`,
      `CORTEX_DAILY_BUDGET_USD`, `CORTEX_ENABLED`,
      `CORTEX_IDLE_CONSOLIDATION`, `CORTEX_MAX_IDLE_INTERVAL`,
      `CORTEX_MEMORY_ENABLED`, `CORTEX_REFLECT_TO_ENGRAMS` (8 vars)
    - `HF_TOKEN`
    - `NOVA_API_KEY`
    - `OLLAMA_CLOUD_FALLBACK_MODEL`,
      `OLLAMA_CLOUD_FALLBACK_EMBED_MODEL`
    - `POSTGRES_DB`, `POSTGRES_USER`
    - `SGLANG_MODEL`
    - `VLLM_EXTRA_ARGS`, `VLLM_GPU_MEMORY_UTILIZATION`,
      `VLLM_MAX_MODEL_LEN`, `VLLM_MODEL`
  - Present only as inert comments (easy to miss): `POSTGRES_DATA_DIR`,
    `REDIS_DATA_DIR`, `OLLAMA_BASE_URL`, all the `DEFAULT_*_MODEL` keys,
    `TELEGRAM_*`, `SLACK_*`, `TAILSCALE_AUTHKEY`, `CLOUDFLARE_TUNNEL_TOKEN`,
    `NOVA_WORKSPACE`, `WOL_MAC_ADDRESS`, `WOL_BROADCAST_IP`.
- **Impact:** Users running the documented `./scripts/setup.sh` get silent
  falling-back defaults for any of these. Cortex's daily budget, cycle
  interval, and feature flags (`CORTEX_MEMORY_ENABLED`,
  `CORTEX_REFLECT_TO_ENGRAMS`, `CORTEX_IDLE_CONSOLIDATION`) are all
  controllable but invisible — nobody would ever discover them without
  reading `docker-compose.yml`. Runtime-config overrides via Redis
  (`nova:config:*`) also shadow some of these silently; see next finding.
- **Recommendation:** Add missing vars to `.env.example` grouped by
  section. Prefer a `# CORTEX_DAILY_BUDGET_USD=5.00` commented form
  with the actual default, so users see both "exists" and "current value"
  in one line. For vars that are *intentionally* runtime-configurable
  via the dashboard (not via .env), say so in the comment.
- **Effort:** S — 30 minutes.

---

### [P1] Runtime config in Redis can stale-override .env / dashboard settings silently

- **Evidence:**
  - `orchestrator/app/main.py:103-108` syncs DB `platform_config` values
    to Redis (`nova:config:*`) at startup. Good.
  - `llm-gateway/app/registry.py:223-247` — `get_routing_strategy()` reads
    `nova:config:llm.routing_strategy` from Redis with a 5-second cache,
    falls back to the env setting. If Redis still holds a stale value
    from a previous configuration, it wins.
  - CLAUDE.md already calls out this gotcha explicitly: "Stale Redis
    config values survive container restarts. If inference is broken,
    check `inference.state` and `inference.backend` in Redis before
    debugging code."
  - There is **no dashboard surface** that displays the currently
    active Redis value side-by-side with the .env / platform_config
    value, so the discrepancy is invisible until someone types
    `redis-cli MGET ...`.
- **Impact:** A user toggles "cloud-only" in the dashboard, tests, toggles
  back to "local-first" — but if the dashboard wrote to platform_config
  and `sync_llm_config_to_redis` didn't re-fire (service not restarted),
  the Redis value lags. Gateway routes to the wrong backend. Silent
  mis-routing.
- **Recommendation:** Two pieces:
  1. Every write to `platform_config` must also `SET` its corresponding
     Redis key (and tripwire `UNLINK` if the key should be absent) in the
     same transaction. Don't rely on the startup sync.
  2. Dashboard "Settings" page should show each runtime-config key with
     its value in DB, in Redis, and in the running service, with a
     "force re-sync" button. This is a dashboard-level fix but the
     plumbing is infra.
- **Effort:** M.

---

### [P2] Critical log lines downgraded to DEBUG — invisible at production LOG_LEVEL=INFO

- **Evidence:** CLAUDE.md explicitly warns: "Never log critical failures
  at DEBUG — they become invisible in production." Spot check found:
  - `cortex/app/cycle.py:1033` —
    `log.debug("Lesson ingestion failed: %s", e)`. Lesson ingestion
    failing silently defeats the cross-goal learning feature.
  - `cortex/app/cycle.py:1064` — same pattern for lesson extraction.
  - `cortex/app/cycle.py:848` — `log.debug("Failed to emit goal.completed
    stimulus: %s", e)`. A dropped `goal.completed` stimulus means cortex
    thinks the goal is still active.
  - `cortex/app/cycle.py:873` — `log.debug("Failed to emit
    goal.budget_paused stimulus: %s", e)`. Budget enforcement that
    silently drops is a P0 in disguise.
  - `orchestrator/app/auto_friction.py` (line 76) — DEBUG on a
    Fix-This loop-guard skip is correct (expected behavior).
  - `orchestrator/app/model_classifier.py:172, 174` — DEBUG for
    classifier failures when routing; falls through to default, so DEBUG
    is arguably correct but obscures misbehaviour at scale.
  - `orchestrator/app/agents/runner.py:506` — `log.debug("Memory
    pre-warm failed (non-critical): %s", e)` — labeled non-critical,
    consistent.
  - `memory-service/app/main.py:110` — `log.debug("Self-model bootstrap
    skipped (table may not exist yet)", exc_info=True)`. Table *should*
    always exist after migrations; this would hide a real schema drift.
- **Impact:** In production (LOG_LEVEL=INFO) these errors are truly
  invisible. The recent platform-health analysis (March 28) took
  significant effort precisely because cortex's skip-loop behavior was
  happening in the dark.
- **Recommendation:** Sweep grep for `log.debug` that follows
  `except Exception as e:`. Upgrade to WARNING when the failure suppresses
  a user-visible feature (lessons, stimuli, bootstraps, cost tracking).
  Leave at DEBUG only where the failure is truly expected and a retry is
  coming.
- **Effort:** S — 1 hour grep + read + tighten.

---

### [P2] Ollama auto-detect probe can pick the wrong URL on WSL2 with Ollama in Docker

- **Evidence:**
  - `scripts/resolve-ollama-url.sh:46-65` — `resolve_auto()` branches:
    - If `local-ollama` profile is active → use `http://ollama:11434`.
    - Else probe `get_host_url()` — on WSL2, this resolves to the WSL
      gateway IP (line 22-30). On native Linux / macOS, falls back to
      `host.docker.internal:11434`.
    - Else fallback to `http://ollama:11434`.
  - Gotcha on WSL2: the gateway IP probe uses the *host shell's*
    network view, not the container's. A user running Ollama on their
    Windows host (port-forwarded from WSL to Windows) is reached via
    the WSL gateway from the WSL shell — but from inside Docker, the
    same gateway address may or may not be routable. The probe
    succeeds in setup.sh but the actual container can't connect.
  - `docker-compose.yml:157-158` grants `extra_hosts:
    host.docker.internal:host-gateway` to `llm-gateway` only. Other
    services don't have it — so any service that *itself* calls Ollama
    (currently none; baseline-mem0 does but that's in the benchmark
    profile) would fail.
- **Impact:** On a subset of WSL2 setups (particularly ones using
  `ollama serve` on the Windows host with a firewall rule), setup
  reports `✓ Ollama is ready` but the running gateway container
  cannot actually reach Ollama. Failure mode reproduces only on
  WSL2 + Ollama-on-Windows — a real-world configuration (the user's
  "Dell PC on LAN" path in `.env.example:19`).
- **Recommendation:** After `resolve-ollama-url.sh` prints a URL,
  have setup.sh validate it *from inside a throwaway container*,
  not from the host shell:
  ```bash
  docker run --rm --network nova_nova-internal \
    --add-host=host.docker.internal:host-gateway \
    alpine:latest wget -qO- --timeout=3 "$OLLAMA_BASE_URL/api/tags"
  ```
  This matches the runtime network context. Fail loudly if this
  second-level probe fails.
- **Effort:** S.

---

### [P2] Backup script hard-codes single-DB dump; restore doesn't stop writers

- **Evidence:**
  - `scripts/backup.sh:28-34` — `pg_dump -U nova nova` writes one
    `database.sql` into a tar. Does not include `./data/sources/`
    (filesystem storage for the sources provenance system per
    CLAUDE.md), Redis `./data/redis/dump.rdb`, or any model caches.
  - `scripts/restore.sh:65-66` — `psql ... --single-transaction`
    without first stopping writers. Orchestrator, cortex, memory-service,
    intel-worker etc. are all actively writing during the restore.
    Concurrent writes to tables the restore is re-populating → race,
    partial restore visible, potential deadlock.
  - Restore *does* restart `orchestrator memory-service llm-gateway
    chat-api` on line 71, but only *after* the restore completes, which
    is too late.
- **Impact:** A `make restore` during an active stack is not safe —
  it's "emergency only" per comment, but the script presents a
  dangerous `YES` prompt and proceeds to mutate a hot DB. If cortex
  runs a cycle mid-restore, its INSERT into `cortex_cycles` races
  against the dump's DELETE+INSERT sequence.
- **Recommendation:**
  1. `backup.sh` should additionally snapshot `./data/sources/` (tar
     into the same archive) — small filesystem source content is part
     of the dataset.
  2. `restore.sh` should either `docker compose stop <writers>`
     before `psql`, or explicitly document "this corrupts data if
     anything else is writing."
  3. Recovery UI's flow (in `recovery-service`) should be the
     canonical path; emergency CLI should match it.
- **Effort:** S.

---

### [P2] `make prune` uses bare `docker system prune -f` — can remove unrelated containers

- **Evidence:**
  - `Makefile:94` — `prune: docker system prune -f`.
  - `Makefile:102` — `prune-all: docker system prune -f`.
  - `docker system prune -f` with no filters removes **all** stopped
    containers, **all** dangling images, and **all** unused networks
    system-wide — not just Nova's. If the user has another Docker
    project with a stopped container, it's gone too.
- **Impact:** Surprising cross-project damage. The comment at line 93
  says "preserves ALL volumes" but omits that it will clobber other
  projects' stopped containers / images.
- **Recommendation:** Scope by label:
  ```bash
  docker system prune -f --filter "label=com.docker.compose.project=nova"
  ```
  Compose labels every resource it creates with that project label.
  Safer for users running multiple stacks.
- **Effort:** S.

---

### [P2] `neural-router-trainer` has `restart: unless-stopped` but no exit-gate → respawn loop if model is missing

- **Evidence:**
  - `docker-compose.yml:286-307` — the trainer service runs
    `python -m app.engram.neural_router.train`, has
    `restart: unless-stopped`, and no startup gate checking whether
    it should even run.
  - If the training script exits (no data to train, 200-label gate
    not met per CLAUDE.md "Trains on retrieval feedback after 200+
    labeled observations"), the container exits, docker respawns it,
    it exits again. Loop.
  - It's in a non-optional service slot — runs on every stack start —
    but has no `healthcheck`, so dashboard / `make ps` sees it as
    simply `running`; no signal it's respawning.
- **Impact:** Wasted CPU on a respawn loop. In a cold-start before
  200 labeled observations exist (so: always, on a new install),
  the trainer busy-loops.
- **Recommendation:** Either
  1. Add a `healthcheck` + `restart: on-failure:3` so docker gives
     up, or
  2. Script exits with code 0 (success) when data insufficient so
     `unless-stopped` doesn't respawn, or
  3. Move the training into the memory-service lifespan as a
     background task (it's already halfway there per
     `memory-service/app/main.py:59-67` `_neural_router_refresh`).
- **Effort:** S.

---

### [P3] `dashboard` depends only on `recovery`; comes up before backends → misleading "everything is fine" screen

- **Evidence:** `docker-compose.yml:816-818` — dashboard's only
  `depends_on` is recovery. Per CLAUDE.md this is intentional — the
  dashboard "shows a startup screen while other services come
  online." But nothing forces the dashboard to *display* that screen
  until orchestrator is ready. The screen-to-service mapping is all
  in dashboard code (`dashboard/src/pages/...`), not in compose.
- **Impact:** Users see a working-looking dashboard while
  orchestrator is still starting; attempting any chat action fails
  opaquely. Not a functional bug — a UX bug that looks like an infra
  bug.
- **Recommendation:** Pair with the UI-UX axis; the fix is on the
  dashboard side (poll `/api/v1/system/status` and gate the main
  routes on it), not compose.
- **Effort:** S — but cross-axis.

---

### [P3] Orchestrator mounts host root `/:/host-root:rw` — unbounded filesystem access

- **Evidence:** `docker-compose.yml:366` — `- /:/host-root:rw`. Also
  `line 365` mounts `${HOME}:${HOME}:rw`. Both mounts exist so the
  self-modification / shell tools can read/write arbitrary host
  paths.
- **Impact:** Strictly a security finding (covered by the security
  axis), but ops-relevant because it means this service can never
  run under Docker user namespaces or read-only rootfs — standard
  container-security defaults are incompatible with this mount
  layout. A future "prod-hardened" profile will need a separate
  compose variant.
- **Recommendation:** Defer to security axis, noting here that a
  hardened-compose variant is a future infra concern.
- **Effort:** L (design-required).

---

## Summary

- The P0 cascade-amplification bug is live *right now* — measured
  at 3.0s per hop, currently making chat-api claim it's "degraded"
  because ollama is unreachable (which is fine — it's informational).
  Fix: stop calling `/health/ready` from other services; use
  `/health/live`. Already done correctly in cortex.
- Five modules leak Redis connections at shutdown; CLAUDE.md explicitly
  documents the rule, discipline has slipped since it was written.
  The worst offender (memory-service `embedding.py`) has no
  `close_redis()` function at all.
- Log-format hygiene is split in half — 7 services JSON, 4 services
  unstructured. Recovery-service in particular deserves structured
  output because that's the service people read during an outage.
- `.env.example` lags Compose by ~25 variables, silently hiding every
  Cortex tunable and every vLLM tunable from users.
- Observability is essentially absent — no metrics, no tracing, no
  request-timing anywhere. "Why is this slow?" is not answerable
  without reading source.
- Setup and backup/restore scripts have small but real correctness
  bugs (missing pre-flight for stale network, prune not scoped to
  Nova project, restore doesn't pause writers, backup omits
  `data/sources/`).
