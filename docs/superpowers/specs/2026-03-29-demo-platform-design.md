# Demo Platform Design

**Date:** 2026-03-29
**Status:** Draft
**Goal:** Self-serve ephemeral demo platform where anyone can try Nova from a "Try Nova Free" button on arialabs.ai — no signup, no install, no friction.

## Context

Nova is a 9+ service Docker Compose stack. To go viral on social media, people need to experience it before committing to the self-host deployment process. The demo must show what makes Nova different from a chatbot: the pipeline, memory graph, autonomous goals, and the full dashboard experience.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Demo experience | Full dashboard with onboarding | People need to see the dashboard to understand differentiation |
| LLM costs | Cheap model + token budget cap | Bounds cost per session; still feels real |
| Scale | Single VPS now, cloud orchestration later | Prove demand before investing in infra |
| Architecture | Hybrid — demo mode in Nova, provisioner separate | Clean separation: Nova knows it's a demo, provisioner handles lifecycle |
| Expiry | 1 hour active + 30 min read-only freeze | Soft freeze lets users browse results at near-zero cost |
| Seed data | Pre-populated examples + onboarding for first goal | Empty dashboards look broken; examples show value immediately |
| Auth | None — zero friction | No signup, no email. Click button, get Nova. |
| Abuse protection | IP rate limit + capacity cap, optional CAPTCHA later | Start simple, add friction only if needed |
| Future path | Multi-tenancy replaces per-instance isolation | Demo mode carries forward; only provisioner gets replaced |

## Architecture Overview

Three components with clean boundaries:

```
[arialabs.ai "Try Nova Free"]
        |
        v
[Demo Provisioner]  --creates-->  [Nova instance (NOVA_DEMO=true)]
        |                                |
        |                         [Traefik label: demo-{id}.demo.arialabs.ai]
        |                                |
        v                                v
[TTL reaper]                      [User's browser]
```

### Component A: Demo Mode (inside Nova)

Activated by `NOVA_DEMO=true` environment variable. Changes behavior across three services:

**LLM Gateway — Budget Enforcement:**
- Reads `DEMO_TOKEN_BUDGET` from env (default: 150,000 tokens)
- Tracks cumulative usage in Redis key `demo:budget:used`
- Every `/complete` and `/stream` response increments the counter with actual token usage from the provider response
- When budget is exhausted, returns structured error: `{"error": "demo_limit_reached", "message": "..."}`
- Model locked to `DEFAULT_CHAT_MODEL` in demo `.env` (e.g., Haiku, Gemini Flash)

**Dashboard — Onboarding & Help:**
- First load: dismissible onboarding overlay explaining what Nova is, what makes it different, and what to try
- Persistent "?" help button to reopen the guide
- Countdown timer in the header showing remaining session time
- Demo badge in the corner
- "Demo limit reached" state: chat disabled, CTA to self-host or start new demo
- Disabled features behind `isDemo` check:
  - API key management (hidden)
  - Remote access settings (hidden)
  - Recovery / factory reset (hidden)
  - Auth / user management (hidden)

**Dashboard — Soft Freeze (post-expiry):**
- When `DEMO_EXPIRES_AT` has passed, dashboard switches to read-only
- Chat input and new goal submission disabled
- All existing data still browsable: memory graph, task history, pipeline results, settings
- Banner: "Your demo has ended. [Start a new demo] [Self-host Nova] [GitHub]"
- Freeze lasts 30 minutes, then the provisioner tears down the instance

**Orchestrator — Session Expiry:**
- Reads `DEMO_EXPIRES_AT` env var (ISO 8601 timestamp, set by provisioner)
- Exposes demo status on `/api/v1/demo/status` endpoint: `{ demo: true, expires_at, frozen, budget_remaining }`
- Dashboard polls this endpoint to drive countdown and freeze transition
- After expiry, orchestrator rejects **all write operations** (task creation, goal submission, chat messages) with 403 "demo expired". This is the hard enforcement layer — the dashboard's read-only UI is cosmetic/UX, but the orchestrator is the gate. No API-level bypass is possible during the frozen window.
- **Forward-compatibility note:** `DEMO_EXPIRES_AT` is baked into the env at container start and cannot be changed at runtime. If session extension is needed in the future (e.g., "extend for 30 more minutes" CTA), add a Redis override key (`demo:expires_at` in db2) that the orchestrator checks at runtime, similar to how `nova:config:` keys work for other runtime config.

### Component B: Demo Provisioner (new, separate service)

A standalone FastAPI service running on the demo host. ~500-800 lines of Python.

**API Surface:**

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/v1/demos` | None (rate-limited) | Create a new demo instance. Returns `{ id, url, expires_at }` |
| `GET /api/v1/demos/{id}/status` | None | Poll instance state: `provisioning`, `ready`, `active`, `frozen`, `reaped` |
| `GET /api/v1/demos` | Admin secret | List all active demos with resource usage |

**Provisioning Flow (POST /api/v1/demos):**

The creation endpoint returns **202 Accepted** immediately with `{ id, url, status: "provisioning", expires_at }`. The URL is deterministic (derived from the ID) so it can be returned before health is confirmed. The website polls `GET /api/v1/demos/{id}/status` and redirects when status reaches `ready`.

1. **Rate-limit check** — max 3 demos per IP per hour (Redis-backed, survives restarts, shared across future multi-host setups)
2. **Capacity check** — reject with 503 if at max concurrent instances
3. **Disk check** — reject with 503 if host free disk is below 10GB floor
4. **Generate short ID** — e.g., `demo-a7x3` (8 char random)
5. **Create working directory** — `/opt/nova-demos/demo-a7x3/`
6. **Write `.env`** with demo-specific config:
   - `NOVA_DEMO=true`
   - `DEMO_TOKEN_BUDGET=150000`
   - `DEMO_EXPIRES_AT=<now + 1 hour, ISO 8601>`
   - `DEFAULT_CHAT_MODEL=<cheap model>`
   - `COMPOSE_PROJECT_NAME=demo-a7x3`
   - `REQUIRE_AUTH=false`
   - `LLM_ROUTING_STRATEGY=cloud-only`
   - Unique `POSTGRES_PASSWORD`
   - LLM provider API key(s) from provisioner's own env
   - **Security note:** API keys are written to per-instance `.env` files on disk and persist for up to 90 minutes. All demo instances share the same key(s) — use a dedicated demo-only API key with provider-side spend limits, not your primary production keys. The reaper verifies directory removal succeeded and retries on failure. On provisioner startup, a reconciliation pass removes any orphaned demo directories older than 2 hours.
7. **Copy `docker-compose.demo.yml`** — slimmed compose with resource limits and Traefik labels
8. **Run `docker compose up -d`**
9. **Background health poll** — wait for dashboard `/health/ready`, update state to `ready` when confirmed, or `failed` after 5 min timeout (reaper cleans up failed instances)
10. **Return** (already returned 202 at step start)

**Instance Lifecycle:**

```
provisioning  →  ready  →  active  →  frozen  →  reaped
                              |          |
                         (1 hour)   (30 min read-only)
```

**Reaper (background task, runs every 60s):**
- Scans all demo directories for `expires_at + 30 min` past
- Expired: `docker compose down -v`, remove working directory, verify removal succeeded (retry on failure)
- Stuck in provisioning >5 min: same cleanup (failed startup)
- **Startup reconciliation:** On provisioner boot, scan `/opt/nova-demos/` and reconcile against running Docker Compose projects. Any orphaned directory older than 2 hours or with an expired `DEMO_EXPIRES_AT` gets reaped immediately. This handles the case where the provisioner crashes mid-cleanup.

**Abuse Protection:**
- IP rate limiting: 3 demos/hour per IP, stored in Redis (survives restarts, works across multiple hosts)
- Capacity ceiling: configurable max concurrent instances (default 5-8)
- No auth required to create a demo (friction kills conversion)
- **Provisioner WAF:** `demo.arialabs.ai` (the provisioner API) sits behind Cloudflare proxy (orange cloud ON) with Cloudflare rate limiting rules as a second layer. Only the `*.demo.arialabs.ai` wildcard subdomains need proxy OFF for the Let's Encrypt DNS-01 challenge.
- Future: Cloudflare Turnstile (invisible CAPTCHA) if abuse appears

### Component C: Infrastructure

**VPS:**
- Hetzner CPX41 or equivalent: 8 vCPU, 32GB RAM, 240GB disk (~$30-40/mo)
- Ubuntu 22.04, Docker + Docker Compose
- Pre-pull all Nova images so cold starts only wait for container creation

**DNS (Cloudflare):**
- `demo.arialabs.ai` — A record → VPS IP (**proxy ON** — provisioner API gets Cloudflare DDoS protection and rate limiting)
- `*.demo.arialabs.ai` — wildcard CNAME → `demo.arialabs.ai` (**proxy OFF** — required for Traefik to terminate TLS via Let's Encrypt DNS-01 challenge; demo instances do not get Cloudflare DDoS protection, which is an acceptable tradeoff since each instance is ephemeral and low-value)

**Traefik:**
- Runs as a container alongside the provisioner
- Docker provider: auto-discovers demo containers by label
- Let's Encrypt wildcard cert via DNS-01 challenge (Cloudflare API token)
- **Shared network:** A pre-created external Docker network (`traefik-public`) bridges Traefik and all demo instances. Traefik attaches to this network at startup. Each demo's `docker-compose.demo.yml` declares this external network and attaches the dashboard container to it. This is required because each demo's `COMPOSE_PROJECT_NAME` creates an isolated bridge network — without the shared network, Traefik discovers the labels but can't reach the backend IPs. Created once during host setup: `docker network create traefik-public`.
- Each demo's dashboard container gets labels:
  ```
  traefik.enable=true
  traefik.http.routers.demo-a7x3.rule=Host(`demo-a7x3.demo.arialabs.ai`)
  traefik.http.routers.demo-a7x3.tls=true
  traefik.http.routers.demo-a7x3.tls.certresolver=letsencrypt
  traefik.http.services.demo-a7x3.loadbalancer.server.port=3000
  ```
- No manual config reload — Traefik watches Docker events

**Resource Limits per Demo Instance:**
- Each Python service: 512MB memory, 0.5 CPU
- Postgres: 256MB memory
- Redis: 128MB memory
- Disk: no per-instance quota enforced (Docker overlay2 `storage-opt` requires backing filesystem support that may not be available); instead, the provisioner checks host free disk before provisioning (10GB floor) and the reaper monitors disk usage, blocking new provisioning if free disk drops below threshold
- Total per instance: ~3-4GB RAM
- 32GB host → 7-8 concurrent instances with headroom

## Demo Compose Profile

A slimmed `docker-compose.demo.yml` running only essential services:

| Include | Skip |
|---|---|
| dashboard | cortex |
| orchestrator | intel-worker |
| llm-gateway | knowledge-worker |
| memory-service | voice-service |
| chat-api | chat-bridge |
| postgres | recovery |
| redis | cloudflared / tailscale |

6 application services + 2 data stores = 8 containers per demo.

Recovery is skipped because the provisioner handles lifecycle externally. Cortex, intel-worker, knowledge-worker, and voice are optional services that aren't needed to demonstrate the core pipeline experience.

**Critical: No host port mappings.** The demo compose file uses only `expose:` (not `ports:`) for all services. Inter-service communication uses Docker's internal DNS within the Compose project network. The dashboard is reached exclusively via Traefik routing by Docker label. This prevents port collisions between concurrent demo instances.

## Demo Data Seeding

Each instance starts with pre-seeded data loaded from `scripts/demo-seed.sql` after migrations:

- **Memory:** 3-5 engrams showing Nova already "knows things" (what it is, what it can do, sample domain knowledge)
- **Tasks:** 1 completed task showing a pipeline run (goal → subtasks → execution → result)
- **Brain:** Small memory graph with connected nodes so the visualization isn't empty
- **Labeling:** All example data clearly marked in the UI as pre-seeded

Seed file is a Postgres dump generated from a manually curated demo instance. Updating it: curate a fresh instance, dump, commit.

**Seed validation:** The provisioner's startup check (or CI) loads the seed file against a fresh post-migration database and verifies row counts are nonzero. A migration that breaks the seed should fail loudly before reaching the demo host. Seed freshness should be part of the release checklist when schema changes are shipped.

## Website Integration

**arialabs.ai changes:**
- New hero CTA: **"Try Nova Free"** alongside existing "Explore Nova"
- Click triggers `POST https://demo.arialabs.ai/api/v1/demos`
- Interstitial page shows provisioning progress:
  - "Spinning up your own Nova instance..." (provisioning)
  - "Almost ready..." (health check pending)
  - Redirect to `https://demo-{id}.demo.arialabs.ai`
- Error states:
  - Capacity full: "All demo slots are taken. Try again in a few minutes." + retry button
  - Rate limited: "You've started a few demos recently. Try again in an hour."

**Zero friction:** No signup, no email, no account creation. Click the button, get a Nova.

## Cost Estimates

**Infrastructure:**
- VPS: ~$30-40/month
- Domain/DNS: already owned
- TLS: free (Let's Encrypt)

**Per-session LLM cost (cheap model, 150k token budget):**
- Haiku: ~$0.04-0.08
- Gemini Flash: ~$0.01-0.03
- Groq Llama 3: free tier or ~$0.01

**At 50 demos/day on Haiku:** ~$2-4/day LLM cost, ~$60-120/month total (infra + LLM).

**At viral spike (200 demos/day):** constrained by capacity (5-8 concurrent), not cost. Queue naturally throttles. Scale host or add second host if sustained.

## Future: Multi-Tenancy Migration

When Nova gains proper multi-tenancy (needed for SaaS regardless):

1. `NOVA_DEMO=true` flag, budget caps, onboarding, and session expiry carry forward unchanged
2. Provisioner replaced: instead of spinning up a Compose stack, it creates a tenant account with `expires_at` set
3. Single shared Nova instance handles all demo users with isolated conversations and memory
4. Cost per demo drops to near-zero (LLM only, no per-instance infra)
5. Concurrency limit removed (single instance can handle 50+ simultaneous demos)

The application-level demo work (Component A) is permanent. Only the orchestration layer (Component B) gets replaced.
