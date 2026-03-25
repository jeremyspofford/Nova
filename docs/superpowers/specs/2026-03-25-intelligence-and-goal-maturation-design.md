# AI Ecosystem Intelligence & Goal Maturation Pipeline

**Date:** 2026-03-25
**Status:** Draft
**Author:** Jeremy Spofford + Claude

## Overview

Two interconnected systems that make Nova self-improving:

1. **Intelligence System** — Nova monitors the AI ecosystem (Reddit, provider docs, blogs, GitHub, tooling), accumulates knowledge in its engram memory network, synthesizes recommendations for improvements, and presents them for human review with full source citations and discussion threads.

2. **Goal Maturation Pipeline** — All complex goals (whether from intelligence recommendations or human-created) go through a structured engineering lifecycle: triage → scope analysis → spec generation → human review → implementation → verification. Simple goals bypass this and execute directly.

Both systems share a unified comment/discussion thread model and the same expandable detail UI pattern in the dashboard.

## Architecture

### System Overview

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ intel-worker  │────▶│ engram ingestion │────▶│  engram memory  │
│ (feed poller) │     │  queue (Redis)   │     │  network        │
│               │     └──────────────────┘     └────────┬────────┘
│ RSS, Reddit,  │                                       │
│ pages, GitHub │     ┌──────────────────┐              │
│               │────▶│ intel:new_items  │              │
└──────────────┘     │  queue (Redis)   │              │
                      └───────┬──────────┘              │
                              │                         │
                      ┌───────▼─────────────────────────▼──┐
                      │          Cortex Goals               │
                      │                                     │
                      │  Daily:  read + cross-reference     │
                      │  Weekly: synthesize + grade          │
                      │  2x/wk: self-improvement check      │
                      └───────┬─────────────────────────────┘
                              │
                      ┌───────▼──────────┐
                      │ Recommendations  │
                      │ (orchestrator DB)│
                      └───────┬──────────┘
                              │
                      ┌───────▼──────────┐     ┌──────────────────┐
                      │  Dashboard UI    │────▶│  Human Review    │
                      │  Intelligence    │     │  + Discussion    │
                      │  page            │     └────────┬─────────┘
                      └──────────────────┘              │
                                                        │ approve
                                               ┌────────▼─────────┐
                                               │ Goal Maturation   │
                                               │ Pipeline          │
                                               │                   │
                                               │ scope → spec →    │
                                               │ review → build →  │
                                               │ verify            │
                                               └──────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|---|---|
| **intel-worker** | Feed poller with minimal health endpoint. RSS, Reddit JSON, page change detection, GitHub trending. Content hashing + dedup. Stores content and pushes queue notifications via orchestrator HTTP API — does NOT access postgres directly. |
| **Orchestrator (intel_router.py)** | CRUD API for recommendations, feeds, comments, stats. Serves the dashboard Intelligence page data. Handles approval workflow and goal spawning. |
| **Orchestrator (goal maturation)** | Triage, scope analysis, spec generation, review gates, implementation orchestration, verification for complex goals. |
| **Cortex goals** | Three recurring goals drive the intelligence cycle. Post-approval goals drive the engineering lifecycle. |
| **Engram memory** | Knowledge network. Articles decomposed into engrams, cross-referenced via spreading activation. Clusters of related knowledge inform recommendation synthesis. |
| **Dashboard** | Intelligence page (feed list, detail view, discussion threads, feed management). Enhanced Goals page with maturation status and discussion threads. |

---

## 1. Intel Worker

### Container Configuration

- **Port:** 8110 (health endpoint only)
- **Redis DB:** db6
- **Image:** Same Python base as other services
- **Dependencies:** orchestrator (healthy), redis (healthy)
- **Docker Compose profile:** Default (always runs)

**Health endpoints:**
- `GET /health/live` — returns 200 if process is running
- `GET /health/ready` — returns 200 if orchestrator is reachable and polling loop is active

### Data Access Pattern

Intel-worker does NOT access postgres directly. All persistent data flows through orchestrator HTTP endpoints:
- `GET /api/v1/intel/feeds` — fetch feed configuration
- `POST /api/v1/intel/content` — store new content items (orchestrator handles dedup)
- `PATCH /api/v1/intel/feeds/:id/status` — update last_checked_at, error_count

This preserves service boundaries — orchestrator owns all database writes. Intel-worker only needs Redis (for queue pushing) and HTTP access to orchestrator.

### Feed Polling Loop

```python
async def run_polling_loop():
    while True:
        feeds = await get_feeds_from_orchestrator()  # GET /api/v1/intel/feeds?due=true
        for feed in feeds:
            try:
                items = await fetch_feed(feed)  # dispatch by feed_type
                stored = await post_content_to_orchestrator(items)  # POST, returns new items only
                for item in stored:
                    await push_to_engram_queue(item)   # Redis db0
                    await push_to_intel_queue(item)     # Redis db6
                await update_feed_status(feed, success=True)
            except Exception:
                await update_feed_status(feed, success=False)  # bump error_count
        await asyncio.sleep(60)  # check for due feeds every minute
```

### Feed Types

| Type | Fetch Strategy |
|---|---|
| `rss` | Parse RSS/Atom XML, extract entries with title/link/summary/published |
| `reddit_json` | GET `old.reddit.com/r/{sub}/new/.json`, parse structured listing data (title, selftext, score, num_comments, url, author) |
| `page` | GET URL, convert HTML to text, hash full content for change detection. On change, extract the diff (new sections) if possible. |
| `github_trending` | GET unofficial trending endpoint or scrape `github.com/trending?since=daily&spoken_language_code=en` filtered to AI/ML topics |
| `github_releases` | GET `api.github.com/repos/{owner}/{repo}/releases` RSS or API, track latest release tag |

### Content Dedup

Each item is hashed: `SHA-256(title + body)`. If the hash already exists in `intel_content_items`, the item is skipped. This prevents re-ingesting duplicate content across feeds (e.g., the same blog post linked from Reddit and RSS).

### Adaptive Timing

- Feeds have a `check_interval_seconds` (user-configurable per feed)
- On error: exponential backoff — `min(check_interval * 2^error_count, 86400)`
- On success: reset `error_count` to 0
- RSS feeds can respect the feed's TTL hint if present

### Redis Queues

- `engram:ingestion:queue` (db0) — Raw text for memory-service decomposition. Payload: `{"raw_text": "...", "source_type": "intel", "metadata": {"feed_name": "...", "url": "...", "content_item_id": "..."}}`
- `intel:new_items` (db6) — Notification for Cortex synthesis goals. Payload: `{"content_item_id": "...", "feed_id": "...", "title": "...", "category": "..."}`

**Multi-DB Redis note:** Intel-worker connects to two Redis databases — db0 (engram ingestion queue) and db6 (intel queue). The `REDIS_URL` env var points to db6; the worker creates a second connection to db0 explicitly for engram queue pushes.

**Queue failure handling:** Items pushed to `intel:new_items` are consumed by the daily sweep goal. If the sweep fails to process an item, it remains in the content_items table and will be picked up on the next daily run (sweep queries by `ingested_at`, not the queue). The queue is a notification trigger, not the source of truth — data is durable in postgres.

---

## 2. Database Schema

All tables live in orchestrator's postgres, managed via SQL migrations. Intel-worker accesses these tables exclusively through orchestrator's HTTP API — it never connects to postgres directly.

### Feed Configuration

```sql
CREATE TABLE IF NOT EXISTS intel_feeds (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  TEXT NOT NULL,
    url                   TEXT NOT NULL,
    feed_type             TEXT NOT NULL CHECK (feed_type IN ('rss', 'reddit_json', 'page', 'github_trending', 'github_releases')),
    category              TEXT,
    check_interval_seconds INTEGER NOT NULL DEFAULT 3600,
    last_checked_at       TIMESTAMPTZ,
    last_hash             TEXT,
    error_count           INTEGER NOT NULL DEFAULT 0,
    enabled               BOOLEAN NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Content Items

```sql
CREATE TABLE IF NOT EXISTS intel_content_items (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feed_id       UUID NOT NULL REFERENCES intel_feeds(id) ON DELETE CASCADE,
    content_hash  TEXT NOT NULL UNIQUE,
    title         TEXT,
    url           TEXT,
    body          TEXT,
    author        TEXT,
    score         INTEGER,
    published_at  TIMESTAMPTZ,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata      JSONB DEFAULT '{}'
);

CREATE INDEX idx_intel_content_items_feed ON intel_content_items(feed_id);
CREATE INDEX idx_intel_content_items_ingested ON intel_content_items(ingested_at);
```

**Retention policy:** Content items older than 180 days are archived (moved to `intel_content_items_archive`). Items linked to active recommendations are retained regardless of age. A scheduled cleanup runs weekly.

```sql
-- Archive table (same schema, created in the same migration as intel_content_items)
CREATE TABLE IF NOT EXISTS intel_content_items_archive (LIKE intel_content_items INCLUDING ALL);
```

### Recommendations

```sql
CREATE TABLE IF NOT EXISTS intel_recommendations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title               TEXT NOT NULL,
    summary             TEXT NOT NULL,
    rationale           TEXT,
    features            TEXT[],
    grade               CHAR(1) NOT NULL CHECK (grade IN ('A', 'B', 'C')),
    confidence          REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    category            TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'speccing', 'review', 'building', 'implemented', 'deferred', 'dismissed')),
    auto_implementable  BOOLEAN NOT NULL DEFAULT false,
    implementation_plan TEXT,
    complexity          TEXT CHECK (complexity IN ('low', 'medium', 'high')),
    goal_id             UUID REFERENCES goals(id),
    task_id             UUID,
    dismissed_hash_cluster TEXT[],     -- content hashes to prevent re-recommendation (GIN indexed for overlap queries)
    decided_by          TEXT,
    decided_at          TIMESTAMPTZ,
    implemented_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_intel_recommendations_status ON intel_recommendations(status);
CREATE INDEX idx_intel_recommendations_grade ON intel_recommendations(grade);
CREATE INDEX idx_intel_recommendations_dismissed_hashes ON intel_recommendations USING GIN (dismissed_hash_cluster) WHERE status = 'dismissed';
```

### Recommendation ↔ Source Linkage

```sql
CREATE TABLE IF NOT EXISTS intel_recommendation_sources (
    recommendation_id UUID NOT NULL REFERENCES intel_recommendations(id) ON DELETE CASCADE,
    content_item_id   UUID NOT NULL REFERENCES intel_content_items(id) ON DELETE CASCADE,
    relevance_note    TEXT,
    PRIMARY KEY (recommendation_id, content_item_id)
);

CREATE TABLE IF NOT EXISTS intel_recommendation_engrams (
    recommendation_id UUID NOT NULL REFERENCES intel_recommendations(id) ON DELETE CASCADE,
    engram_id         UUID NOT NULL,
    activation_score  REAL,
    PRIMARY KEY (recommendation_id, engram_id)
);
```

**Note:** `engram_id` is a soft reference — engrams live in memory-service's database, not orchestrator's postgres. No FK constraint. Implementers should handle missing engrams gracefully (engrams may be pruned by consolidation).

### Unified Comments

```sql
CREATE TABLE IF NOT EXISTS comments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('recommendation', 'goal')),
    entity_id   UUID NOT NULL,
    author_type TEXT NOT NULL CHECK (author_type IN ('human', 'nova')),
    author_name TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_comments_entity ON comments(entity_type, entity_id);
```

### Goal Maturation Extensions

```sql
ALTER TABLE goals ADD COLUMN IF NOT EXISTS maturation_status TEXT
    CHECK (maturation_status IN ('triaging', 'scoping', 'speccing', 'review', 'building', 'verifying'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS complexity TEXT
    CHECK (complexity IN ('simple', 'complex'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS scope_analysis JSONB;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_approved_at TIMESTAMPTZ;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_approved_by TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS source_recommendation_id UUID REFERENCES intel_recommendations(id);
```

**Dual-status model:** Goals have two status dimensions:
- `status` (existing column): overall lifecycle — `active`, `paused`, `completed`, `failed`, `cancelled`
- `maturation_status` (new column): engineering pipeline phase — `NULL` for simple goals, or `triaging` → `scoping` → `speccing` → `review` → `building` → `verifying` for complex goals

When `maturation_status` is set, `status` remains `active` throughout. When maturation completes (`verifying` passes), `maturation_status` is set to `NULL` and `status` moves to `completed`. If maturation fails at any phase, `status` moves to `failed` with the `maturation_status` indicating where it stopped.

**`created_via` values:** The existing `created_via` column has no CHECK constraint (it's a bare `TEXT NOT NULL DEFAULT 'api'` with valid values documented in a SQL COMMENT: `'api | chat | cortex'`). Update the comment to include `'system'`. Optionally add a CHECK constraint at this time. The existing `delete_goal` endpoint must be updated to reject deletion of goals where `created_via = 'system'` (return 403 Forbidden).

**`updated_at` enforcement:** All UPDATE queries on `intel_feeds`, `intel_recommendations`, and `goals` must explicitly set `updated_at = NOW()`. No database trigger — application-level responsibility, consistent with existing codebase pattern.

---

## 3. Synthesis Pipeline (Cortex Goals)

Three recurring goals drive the intelligence cycle. These are created during system setup and run on cron schedules.

### Goal 1: Daily Knowledge Accumulation

- **Schedule:** `0 6 * * *` (daily 6am)
- **Purpose:** Read all new content, cross-reference with memory, classify, build knowledge network
- **Does NOT create recommendations** — builds understanding first

**Pipeline task behavior:**
1. Query `intel_content_items` ingested since last run
2. For each item, query `POST /api/v1/engrams/context` for related knowledge
3. Classify each item: new concept, enhancement to existing idea, missing piece for previously incomplete idea, or noise
4. For actionable items, ingest a synthesis engram linking the source material to the insight
5. Track which content items have been processed (prevent re-analysis)

### Goal 2: Weekly Synthesis & Recommendation Generation

- **Schedule:** `0 8 * * 1` (Monday 8am)
- **Purpose:** Find knowledge clusters that have reached actionable density, generate graded recommendations

**Pipeline task behavior:**
1. Query engram memory for clusters of related intelligence insights (spreading activation across intel-tagged engrams)
2. For each cluster with sufficient density:
   - Search Nova codebase — does this capability already exist?
   - Query `intel_recommendations` — was this already recommended?
   - If novel and actionable, create recommendation with:
     - Grade + confidence score
     - Summary, rationale, features list
     - Complexity estimate
     - Links to source content items and related engrams
   - Post initial discussion comment explaining synthesis reasoning
3. Re-evaluate deferred recommendations — update confidence if new evidence arrived

**Grading criteria:**
- **A (80-100%):** Low effort + high value, OR fills a known gap, OR multiple independent sources confirm value
- **B (50-79%):** Moderate effort or value, worth discussing, may need more evidence
- **C (0-49%):** Interesting but speculative, high effort, or Nova already has something similar

### Goal 3: Self-Improvement Check

- **Schedule:** `0 10 * * 3,6` (Wednesday + Saturday 10am)
- **Purpose:** Compare Nova's capabilities against accumulated intelligence, find gaps

**Pipeline task behavior:**
1. Review accumulated knowledge about tools, MCP servers, agent protocols, new model releases
2. Search Nova's codebase for each capability mentioned
3. Identify gaps — things the ecosystem has that Nova doesn't
4. For config-level changes (model additions, MCP server registration): create Grade A recommendation flagged `auto_implementable`
5. For architectural changes: create recommendation requiring human review with detailed plan and risk assessment

---

## 4. Recommendation Lifecycle

```
pending → approved → speccing → review → building → implemented
    |         |                    |
    |         ↓                   ↓
    |      deferred          spec rejected
    |                        (revise, back to speccing)
    ↓
 dismissed
```

### Post-Approval Engineering Pipeline

When a recommendation is approved:

**Phase 1: Specification** (status: `speccing`)
- Nova creates a detailed engineering spec covering all affected scopes:
  - Backend: new endpoints, models, services, shared library reuse
  - Frontend: new pages, components, API hooks, state management
  - Data: migrations, schema changes, seed data, indexes
  - Security: auth requirements, input validation, secret management
  - Infrastructure: Docker changes, new containers, resource limits
  - DevOps/CI/CD: build steps, test stages, deployment order
  - Networking: inter-service calls, ports, proxy rules, CORS
  - Testing: unit, integration, e2e — what to test and why
- Identifies existing code to reuse (DRY)
- Defines implementation order (data → backend → frontend → tests → infra)
- Posts spec as a discussion comment

**Phase 2: Human Review** (status: `review`)
- Human reviews spec in the discussion thread
- Can comment with questions — Nova researches and responds
- Human approves spec or requests revisions

**Phase 3: Implementation** (status: `building`)
- Creates parent goal with sub-goals for each scope
- Executes in dependency order through normal pipeline tasks
- Each task follows standards: DRY, tests alongside code, shared library use, refactoring when touching existing code
- Updates CLAUDE.md, docker-compose, .env.example as needed

**Phase 4: Verification**
- Runs full test suite
- Validates dashboard builds (`npm run build`)
- Checks all service health endpoints
- Posts completion summary
- Status → `implemented`

### Deferred Recommendations

- Stay in the system, hidden from default feed view
- Re-evaluated on each weekly synthesis
- Confidence may increase or decrease as new evidence arrives
- Nova posts a comment when grade changes

### Dismissed Recommendations

- Soft-deleted (visible under "All" tab)
- When dismissed, the recommendation's source content hashes are stored in `dismissed_hash_cluster` on the recommendation row. During weekly synthesis, new recommendation candidates are checked against all dismissed hash clusters — if >50% of a candidate's source hashes overlap with a dismissed cluster, it's suppressed.
- Can be un-dismissed from the All tab (clears the suppression, returns to `pending`)

**Note on deferred recommendations:** Deferred recommendations do NOT return to `pending`. They stay `deferred` while the weekly synthesis updates their confidence score. A human can manually move a deferred recommendation to `approved` from the dashboard if they decide to proceed.

---

## 5. Goal Maturation Pipeline

All goals (not just intelligence recommendations) go through a complexity triage. Complex goals follow the same engineering lifecycle.

### Triage

When a goal is created, Cortex evaluates complexity:

| Signal | Simple | Complex |
|---|---|---|
| Touches multiple services | No | Yes |
| Requires migrations | No | Yes |
| Needs frontend + backend | No | Yes |
| Has security implications | No | Yes |
| Changes infrastructure | No | Yes |
| Estimated files changed | < 3 | 3+ |

Simple goals execute directly (current behavior). Complex goals enter the maturation pipeline.

**Triage fallback:** If the LLM is unavailable or returns an unparseable response, triage defaults to `complex` (safer — human review gate catches over-classification). Triage has a 30-second timeout. Users can manually override complexity from the dashboard Goals page at any time, bypassing LLM triage.

### Maturation Statuses

```
(maturation_status) NULL → triaging → scoping → speccing → review → building → verifying → NULL
(status)            active ──────────────────────────────────────────────────────→ completed
                                  ↑           |
                                  └───────────┘
                                  (spec rejected, revise)
```

### Phase 1: Scope Analysis (status: `scoping`)

- Analyze goal description
- Search codebase for related code
- Query engram memory for context
- Identify all affected scopes (backend, frontend, data, security, infra, networking, CI/CD, testing)
- Post scope summary as a goal comment
- If goal is too vague, post clarifying questions and wait for human response

### Phase 2: Spec Generation (status: `speccing`)

- Full engineering spec covering all identified scopes
- Same format as recommendation specs
- Code reuse analysis, shared library identification
- Implementation order and sub-goal breakdown
- Cost/complexity estimate

### Phase 3: Human Review (status: `review`)

- Spec posted as goal comment
- Human reviews, discusses, revises in comment thread
- Approve to proceed or reject to revise

### Phase 4: Implementation (status: `building`)

- Parent goal spawns sub-goals per scope
- Executes in dependency order
- DRY, tests, refactoring, shared library reuse
- All standards enforced

### Phase 5: Verification (status: `verifying`)

- Full test suite
- Dashboard build check
- Service health validation
- Completion summary posted
- Status → `completed`

### Discussion Threads on Goals

Goals gain the same unified comment system as recommendations. The Goals page in the dashboard gets an expandable detail view showing:
- Maturation status with progress indicator
- Scope analysis (which scopes are affected)
- Spec document (when generated)
- Sub-goals and their status
- Discussion thread

---

## 6. API Endpoints

### Intelligence Endpoints (intel_router.py)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/intel/recommendations` | List recommendations (filterable by status, grade, category; paginated with `limit`/`offset`, default limit=20) |
| `GET` | `/api/v1/intel/recommendations/:id` | Detail with sources, engrams, comments |
| `PATCH` | `/api/v1/intel/recommendations/:id` | Update status (approve/defer/dismiss) |
| `GET` | `/api/v1/intel/feeds` | List configured feeds |
| `POST` | `/api/v1/intel/feeds` | Add a new feed |
| `PATCH` | `/api/v1/intel/feeds/:id` | Update feed (interval, enabled, category) |
| `DELETE` | `/api/v1/intel/feeds/:id` | Remove a feed |
| `POST` | `/api/v1/intel/content` | Store new content items (intel-worker calls this; handles dedup, returns only newly stored items) |
| `PATCH` | `/api/v1/intel/feeds/:id/status` | Update feed check status — last_checked_at, error_count (intel-worker calls this) |
| `GET` | `/api/v1/intel/stats` | Aggregate stats (items this week, recs by grade, engrams added) |

### Comment Endpoints (unified, on existing routers)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/intel/recommendations/:id/comments` | List comments (paginated, default limit=50) |
| `POST` | `/api/v1/intel/recommendations/:id/comments` | Add comment to a recommendation |
| `DELETE` | `/api/v1/intel/recommendations/:id/comments/:comment_id` | Delete a comment |
| `GET` | `/api/v1/goals/:id/comments` | List comments (paginated, default limit=50) |
| `POST` | `/api/v1/goals/:id/comments` | Add comment to a goal |
| `DELETE` | `/api/v1/goals/:id/comments/:comment_id` | Delete a comment |

### Goal Maturation Extensions (on existing goals_router.py)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/goals/:id/approve-spec` | Approve a goal's spec (advance to building) |
| `POST` | `/api/v1/goals/:id/reject-spec` | Reject spec with feedback (back to speccing) |
| `GET` | `/api/v1/goals/:id/scope` | Get scope analysis for a goal |

---

## 7. Dashboard UI

### Intelligence Page

New page in the dashboard sidebar navigation, positioned between "Goals" and "Memory."

**Components:**
- `IntelligencePage.tsx` — Main page with stats bar, filter tabs, recommendation feed
- `RecommendationCard.tsx` — Feed list item (grade badge, title, summary, source/memory/comment counts, approve/defer actions)
- `RecommendationDetail.tsx` — Expandable detail view (summary, why/features panels, sources, related memories, discussion thread)
- `FeedManagerModal.tsx` — Modal for adding/editing/toggling feeds
- `DiscussionThread.tsx` — Shared comment thread component (used by both recommendations and goals)

**Stats bar:** Items this week | Active feeds | Grade A count | Grade B count | Engrams added

**Filter tabs:** Pending | Approved | Deferred | Implemented | All

**Feed list:** Vertical list with colored left border by grade (green=A, amber=B, red=C). Each card shows grade badge, title, summary, source/memory/comment counts, and inline approve/defer buttons. Clicking expands inline to the detail view.

**Detail view (expanded):**
- Header with grade, category, title, action buttons
- Summary paragraph
- Side-by-side "Why Implement" and "Features Enabled" panels
- Sources section — expandable inline previews with "Open" link to original URL
- Related Memories section — engrams with activation scores
- Discussion thread — chronological comments from Nova and humans, input box at bottom

**Feed Manager modal:**
- Table of feeds: name, URL, type, category, interval, last checked, enabled toggle
- Add feed form: URL input, type selector, category, interval
- Delete confirmation

### Goals Page Enhancement

Existing Goals page gains:
- Maturation status badge on complex goals
- Expandable detail view (same pattern as recommendations) showing scope analysis, spec, sub-goals, discussion thread
- "Approve Spec" / "Reject Spec" buttons when in review status

### Shared Components

- `DiscussionThread.tsx` — Used by both IntelligencePage and GoalsPage
- Comment input with author attribution
- Nova comments have teal avatar, human comments have blue avatar

### Dashboard Proxy

Add to Vite/nginx proxy config:
- `/api/v1/intel/*` → orchestrator (8000)

No new proxy targets needed — intel and goal comment endpoints all live on orchestrator, which is already proxied via `/api`. The existing Vite proxy config (`/api → http://localhost:8000`) covers all new routes.

---

## 8. Docker Compose Changes

### New Service: intel-worker

```yaml
intel-worker:
  build:
    context: ./intel-worker
    dockerfile: Dockerfile
  container_name: nova-intel-worker
  restart: unless-stopped
  env_file: .env
  environment:
    REDIS_URL: redis://redis:6379/6
    ORCHESTRATOR_URL: http://orchestrator:8000
    LOG_LEVEL: ${LOG_LEVEL:-INFO}
    NOVA_ADMIN_SECRET: ${NOVA_ADMIN_SECRET}
  ports:
    - "8110:8110"
  depends_on:
    orchestrator:
      condition: service_healthy
    redis:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8110/health/live')"]
    interval: 30s
    timeout: 5s
    retries: 3
  networks:
    - nova-internal
```

**Note:** Intel-worker authenticates to orchestrator using `NOVA_ADMIN_SECRET` via `X-Admin-Secret` header, same as other internal services. It does NOT connect to postgres — all data access is via orchestrator HTTP API.

### Redis DB Allocation Update

| DB | Service |
|---|---|
| 0 | memory-service |
| 1 | llm-gateway |
| 2 | orchestrator |
| 3 | chat-api |
| 4 | chat-bridge |
| 5 | cortex |
| **6** | **intel-worker** |
| 7 | recovery |

---

## 9. Default Feed Configuration

Pre-seeded on first setup via migration seed data. All user-configurable from the dashboard.

| Category | Feed | Type | Default Interval |
|---|---|---|---|
| Reddit | r/artificial | reddit_json | 12h |
| Reddit | r/artificialintelligence | reddit_json | 12h |
| Reddit | r/openai | reddit_json | 12h |
| Reddit | r/ClaudeAI | reddit_json | 12h |
| Reddit | r/LocalLLaMA | reddit_json | 12h |
| Reddit | r/MachineLearning | reddit_json | 24h |
| Reddit | r/aitoolsupdate | reddit_json | 12h |
| Provider Docs | Anthropic Docs changelog | page | 6h |
| Provider Docs | OpenAI Docs changelog | page | 6h |
| Provider Docs | Google AI/Gemini docs | page | 6h |
| Provider Docs | Perplexity docs | page | 12h |
| Blog | Anthropic blog | rss | 6h |
| Blog | OpenAI blog | rss | 6h |
| Blog | Google AI blog | rss | 12h |
| Tooling | MCP servers registry | page | 24h |
| Tooling | Ollama releases (GitHub) | github_releases | 24h |
| Tooling | vLLM releases (GitHub) | github_releases | 24h |
| Tooling | LiteLLM changelog | rss | 24h |
| GitHub | GitHub trending (AI/ML) | github_trending | 24h |

---

## 10. Cortex Integration

### New Stimuli

| Stimulus | Trigger |
|---|---|
| `recommendation.created` | New recommendation generated by synthesis goal |
| `recommendation.approved` | Human approves a recommendation |
| `recommendation.commented` | Human comments on a recommendation |
| `goal.spec_approved` | Human approves a goal spec |
| `goal.spec_rejected` | Human rejects a goal spec |
| `goal.commented` | Human comments on a goal |

### System Goals (created at setup)

Three recurring goals for the intelligence cycle:

1. **"Daily Intelligence Sweep"** — `schedule_cron: "0 6 * * *"`, `max_completions: null`
2. **"Weekly Intelligence Synthesis"** — `schedule_cron: "0 8 * * 1"`, `max_completions: null`
3. **"Self-Improvement Check"** — `schedule_cron: "0 10 * * 3,6"`, `max_completions: null`

These are flagged `created_via: 'system'` so they can't be accidentally deleted.

**Seeding mechanism:** System goals are created via an idempotent SQL migration (same pattern as the Cortex system user in migration 021). Uses `INSERT ... ON CONFLICT (id) DO NOTHING` with fixed UUIDs to prevent duplicates on restart:
- Daily sweep: `d0000000-0000-0000-0000-000000000001`
- Weekly synthesis: `d0000000-0000-0000-0000-000000000002`
- Self-improvement: `d0000000-0000-0000-0000-000000000003`

**Cost budgets:** Each system goal has a `max_cost_usd` to prevent runaway LLM spending:
- Daily sweep: $0.50/run (mostly memory queries, light LLM classification)
- Weekly synthesis: $2.00/run (heavier LLM analysis, codebase search, recommendation generation)
- Self-improvement: $1.50/run (codebase comparison, gap analysis)

### Serve Drive Updates

The serve drive needs awareness of maturation statuses so it can:
- Run triage on newly created complex goals
- Execute scope analysis when a goal enters `scoping`
- Generate specs when a goal enters `speccing`
- Execute implementation when a spec is approved
- Run verification when implementation completes

---

## 11. Security Considerations

- **Feed URL validation (SSRF prevention):** Validate URLs on feed creation AND on every fetch (redirects can change the target). Block:
  - `file://`, `ftp://`, and non-HTTP(S) schemes
  - `localhost`, `127.0.0.1`, `[::1]`, `0.0.0.0`
  - Docker-internal hostnames: `redis`, `postgres`, `orchestrator`, `memory-service`, etc. (any hostname resolvable on `nova-internal` network)
  - Cloud metadata endpoints: `169.254.169.254`, `metadata.google.internal`
  - Private IP ranges: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
  - Decimal/hex/octal IP encoding tricks (normalize before checking)
  - On redirect (3xx): validate the final resolved URL against the same rules before following
- **Feed validation on creation:** When adding a new feed via the API, perform a test fetch (10-second timeout) to verify the URL returns parseable content of the declared type. Reject feeds that fail the test fetch with a descriptive error.
- **Content sanitization:** All fetched content is stored as plain text. No HTML rendering in the dashboard — source previews are text with link-outs to original URLs.
- **Rate limiting:** Per-domain rate limits, not a single global bucket. Defaults: Reddit 30 req/hour, GitHub 50 req/hour (unauthenticated), all others 60 req/hour. Configurable per feed type.
- **API auth:** All intel endpoints require the same `X-Admin-Secret` or API key auth as other orchestrator endpoints. Intel-worker authenticates to orchestrator with the admin secret.
- **`auto_implementable` flag:** This is a UI hint only — it does NOT bypass human approval. All recommendations, including auto-implementable ones, require explicit human approval before any action is taken. The flag just highlights low-effort items in the dashboard.
- **Reddit:** Uses public JSON endpoints (no auth required). If Reddit rate-limits, the per-domain backoff handles it.
- **GitHub:** Uses unauthenticated API for trending. For releases, optional `GITHUB_TOKEN` in .env for higher rate limits (authenticated: 5000 req/hour vs 60).

---

## 12. Testing Strategy

### Integration Tests

- Feed polling: mock HTTP responses, verify content items stored and queued
- Recommendation CRUD: create, list, filter, approve, defer, dismiss
- Comment threads: add comments, list by entity
- Goal maturation: verify status transitions, spec approval flow
- Dedup: verify duplicate content items are skipped

### Dashboard

- Intelligence page renders with empty state
- Recommendation cards display correct grade colors
- Detail view expands with sources and discussion
- Feed manager CRUD operations
- Goal detail view shows maturation status

### Cortex Integration

- Synthesis goal creates recommendations from content items
- Approved recommendation spawns a goal
- Comment stimulus triggers Nova response

---

## 13. Implementation Order

1. **Database migrations** — intel_feeds, intel_content_items, intel_recommendations, recommendation_sources/engrams, comments, goal maturation columns
2. **Intel worker** — Feed polling loop, content fetching by type, dedup, Redis queue pushing
3. **Orchestrator API** — intel_router.py (recommendations, feeds, comments, stats), goal maturation endpoints, comment endpoints on goals
4. **Cortex goals** — System goal seeding, synthesis pipeline task prompts, serve drive maturation awareness
5. **Dashboard** — Intelligence page, recommendation components, feed manager, discussion thread component, goals page enhancement
6. **Docker Compose** — intel-worker service entry, Redis DB6 allocation
7. **Default feeds** — Seed migration with default feed configuration
8. **Testing** — Integration tests for all layers
9. **Documentation** — CLAUDE.md updates (new service: intel-worker port 8110, Redis db6 allocation, inter-service communication), website docs if applicable
