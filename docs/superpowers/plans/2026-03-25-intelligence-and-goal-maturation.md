# AI Ecosystem Intelligence & Goal Maturation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-improving intelligence system where Nova monitors the AI ecosystem, accumulates knowledge, surfaces graded recommendations, and engineers approved improvements through a structured goal maturation pipeline.

**Architecture:** Thin intel-worker polls feeds and pushes content via orchestrator HTTP API into the engram memory network. Cortex scheduled goals synthesize knowledge into graded recommendations. A unified comment system enables discussion on both recommendations and goals. Complex goals mature through triage → scope → spec → review → build → verify.

**Tech Stack:** Python/FastAPI (intel-worker, orchestrator), asyncpg (DB), Redis (queues), React/TypeScript/TanStack Query (dashboard), Tailwind CSS, Lucide icons

**Spec:** `docs/superpowers/specs/2026-03-25-intelligence-and-goal-maturation-design.md`

---

## File Structure

### New Files

```
orchestrator/app/
├── intel_router.py                    # Intel CRUD API (feeds, content, recommendations, comments, stats)
├── migrations/
│   ├── 038_intel_schema.sql           # intel_feeds, intel_content_items, intel_recommendations, linkage tables
│   ├── 039_comments_and_goal_maturation.sql  # comments table, goal maturation columns
│   └── 040_intel_system_goals.sql     # System goal seeding, default feeds

intel-worker/
├── Dockerfile
├── pyproject.toml
└── app/
    ├── __init__.py
    ├── main.py                        # FastAPI app (health endpoints only)
    ├── config.py                      # Settings (ORCHESTRATOR_URL, REDIS_URL, etc.)
    ├── poller.py                      # Main polling loop
    ├── fetchers/
    │   ├── __init__.py
    │   ├── rss.py                     # RSS/Atom feed parser
    │   ├── reddit.py                  # Reddit JSON fetcher
    │   ├── page.py                    # Page change detection
    │   └── github.py                  # GitHub trending + releases
    ├── queue.py                       # Redis queue pushing (db0 engram, db6 intel)
    ├── url_validator.py               # SSRF prevention
    └── client.py                      # httpx client to orchestrator

dashboard/src/
├── pages/
│   └── Intelligence.tsx               # Main Intelligence page
├── components/
│   ├── intel/
│   │   ├── RecommendationCard.tsx      # Feed list item
│   │   ├── RecommendationDetail.tsx    # Expandable detail view
│   │   └── FeedManagerModal.tsx        # Feed CRUD modal
│   └── DiscussionThread.tsx           # Shared comment thread (recs + goals)
└── api.ts                            # (modify) Add intel API functions

tests/
└── test_intel.py                      # Integration tests for intel endpoints
```

### Modified Files

```
orchestrator/app/main.py              # Register intel_router
orchestrator/app/goals_router.py      # Add comment, maturation, delete-guard endpoints
orchestrator/app/stimulus.py          # Add new stimulus type constants
docker-compose.yml                    # Add intel-worker service
dashboard/src/App.tsx                 # Add Intelligence route
dashboard/src/components/layout/Sidebar.tsx  # Add Intelligence nav item
dashboard/src/pages/Goals.tsx         # Add maturation status, discussion thread
dashboard/src/api.ts                  # Add intel API functions
CLAUDE.md                            # Document new service
```

---

## Task 1: Database Migrations — Intel Schema

**Files:**
- Create: `orchestrator/app/migrations/038_intel_schema.sql`

- [ ] **Step 1: Write the intel tables migration**

```sql
-- Migration 038: Intelligence system schema
-- Tables for feed monitoring, content ingestion, and recommendations

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

CREATE INDEX IF NOT EXISTS idx_intel_content_items_feed ON intel_content_items(feed_id);
CREATE INDEX IF NOT EXISTS idx_intel_content_items_ingested ON intel_content_items(ingested_at);

CREATE TABLE IF NOT EXISTS intel_content_items_archive (LIKE intel_content_items INCLUDING ALL);

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
    dismissed_hash_cluster TEXT[],
    decided_by          TEXT,
    decided_at          TIMESTAMPTZ,
    implemented_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intel_recommendations_status ON intel_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_intel_recommendations_grade ON intel_recommendations(grade);
CREATE INDEX IF NOT EXISTS idx_intel_recommendations_dismissed_hashes ON intel_recommendations USING GIN (dismissed_hash_cluster) WHERE status = 'dismissed';

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

- [ ] **Step 2: Verify migration applies cleanly**

Run: `docker compose restart orchestrator && docker compose logs orchestrator 2>&1 | grep -i "migration\|038"`
Expected: Migration 038 applied successfully, no errors.

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/migrations/038_intel_schema.sql
git commit -m "feat(db): add intel feeds, content items, and recommendations schema"
```

---

## Task 2: Database Migrations — Comments & Goal Maturation

**Files:**
- Create: `orchestrator/app/migrations/039_comments_and_goal_maturation.sql`

- [ ] **Step 1: Write the comments and goal maturation migration**

```sql
-- Migration 039: Unified comments table and goal maturation columns

CREATE TABLE IF NOT EXISTS comments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('recommendation', 'goal')),
    entity_id   UUID NOT NULL,
    author_type TEXT NOT NULL CHECK (author_type IN ('human', 'nova')),
    author_name TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_comments_entity ON comments(entity_type, entity_id);

-- Goal maturation extensions
ALTER TABLE goals ADD COLUMN IF NOT EXISTS maturation_status TEXT
    CHECK (maturation_status IN ('triaging', 'scoping', 'speccing', 'review', 'building', 'verifying'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS complexity TEXT
    CHECK (complexity IN ('simple', 'complex'));
ALTER TABLE goals ADD COLUMN IF NOT EXISTS scope_analysis JSONB;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_approved_at TIMESTAMPTZ;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS spec_approved_by TEXT;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS source_recommendation_id UUID REFERENCES intel_recommendations(id);

-- Update created_via comment to include 'system'
COMMENT ON COLUMN goals.created_via IS 'How the goal was created: api | chat | cortex | system';
```

- [ ] **Step 2: Verify migration applies cleanly**

Run: `docker compose restart orchestrator && docker compose logs orchestrator 2>&1 | grep -i "migration\|039"`
Expected: Migration 039 applied successfully.

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/migrations/039_comments_and_goal_maturation.sql
git commit -m "feat(db): add unified comments table and goal maturation columns"
```

---

## Task 3: Orchestrator Intel Router — Feed & Content Endpoints

**Files:**
- Create: `orchestrator/app/intel_router.py`
- Modify: `orchestrator/app/main.py` (register router)

- [ ] **Step 1: Create intel_router.py with feed CRUD and content ingestion endpoints**

Create `orchestrator/app/intel_router.py`. Follow the pattern from `goals_router.py`:
- Import `APIRouter`, `HTTPException`, `Query` from fastapi
- Import `BaseModel`, `Field` from pydantic
- Import `AdminDep`, `UserDep` from `app.auth`, `get_pool` from `app.db`
- Use `UserDep` for dashboard-facing endpoints (list feeds, list/update recommendations, comments, stats)
- Use `AdminDep` for worker-facing endpoints (`POST /api/v1/intel/content`, `PATCH /api/v1/intel/feeds/{id}/status`)
- Create `intel_router = APIRouter(tags=["intel"])`

Endpoints to implement in this step:

```python
# GET /api/v1/intel/feeds — list all feeds (filterable by enabled, category)
# POST /api/v1/intel/feeds — create a new feed (with SSRF URL validation)
# PATCH /api/v1/intel/feeds/{feed_id} — update feed config
# DELETE /api/v1/intel/feeds/{feed_id} — remove feed
# PATCH /api/v1/intel/feeds/{feed_id}/status — update check status (for intel-worker)
# POST /api/v1/intel/content — store new content items, dedup by hash, return newly stored
# GET /api/v1/intel/stats — aggregate stats
```

Request/response models:

```python
class CreateFeedRequest(BaseModel):
    name: str
    url: str
    feed_type: str  # rss, reddit_json, page, github_trending, github_releases
    category: str | None = None
    check_interval_seconds: int = 3600

class UpdateFeedRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    check_interval_seconds: int | None = None
    enabled: bool | None = None

class FeedStatusUpdate(BaseModel):
    last_checked_at: str  # ISO timestamp
    error_count: int
    last_hash: str | None = None

class ContentItem(BaseModel):
    feed_id: str
    content_hash: str
    title: str | None = None
    url: str | None = None
    body: str | None = None
    author: str | None = None
    score: int | None = None
    published_at: str | None = None
    metadata: dict = {}

class IngestContentRequest(BaseModel):
    items: list[ContentItem]
```

SSRF validation on feed creation — reject URLs matching:
- Non-HTTP(S) schemes
- `localhost`, `127.0.0.1`, `[::1]`, `0.0.0.0`
- Docker hostnames: `redis`, `postgres`, `orchestrator`, `memory-service`, `llm-gateway`, `cortex`, `recovery`, `chat-api`, `chat-bridge`, `dashboard`
- `169.254.169.254`, `metadata.google.internal`
- Private IP ranges: `10.*`, `172.16-31.*`, `192.168.*`

Content ingestion (`POST /api/v1/intel/content`):
- For each item, attempt `INSERT ... ON CONFLICT (content_hash) DO NOTHING RETURNING *`
- Return only newly inserted items (not duplicates)

Stats (`GET /api/v1/intel/stats`):
- Query counts: items this week, active feeds, recommendations by grade, total recommendations

- [ ] **Step 2: Register the router in main.py**

In `orchestrator/app/main.py`, add:
```python
from app.intel_router import intel_router
# ... after other include_router calls:
app.include_router(intel_router)
```

- [ ] **Step 3: Verify the service starts and endpoints respond**

Run: `docker compose restart orchestrator && curl -s http://localhost:8000/api/v1/intel/feeds -H "X-Admin-Secret: $(grep NOVA_ADMIN_SECRET .env | cut -d= -f2)" | python3 -m json.tool`
Expected: Empty JSON array `[]`

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/intel_router.py orchestrator/app/main.py
git commit -m "feat(orchestrator): add intel router with feed CRUD and content ingestion"
```

---

## Task 4: Orchestrator Intel Router — Recommendation & Comment Endpoints

**Files:**
- Modify: `orchestrator/app/intel_router.py`
- Modify: `orchestrator/app/stimulus.py` (add constants)

- [ ] **Step 1: Add stimulus constants**

In `orchestrator/app/stimulus.py`, add after existing constants:
```python
# Intelligence stimuli
RECOMMENDATION_CREATED = "recommendation.created"
RECOMMENDATION_APPROVED = "recommendation.approved"
RECOMMENDATION_COMMENTED = "recommendation.commented"
GOAL_SPEC_APPROVED = "goal.spec_approved"
GOAL_SPEC_REJECTED = "goal.spec_rejected"
GOAL_COMMENTED = "goal.commented"
```

- [ ] **Step 2: Add recommendation endpoints to intel_router.py**

```python
# GET /api/v1/intel/recommendations — list (filterable by status, grade, category; paginated limit/offset)
# GET /api/v1/intel/recommendations/{rec_id} — detail with sources, engrams, comments
# PATCH /api/v1/intel/recommendations/{rec_id} — update status (approve/defer/dismiss)
#   On approve:
#     1. Create a new goal linked to recommendation (set goal_id on recommendation)
#     2. Set recommendation status to 'speccing'
#     3. Emit RECOMMENDATION_APPROVED stimulus with goal_id
#   On dismiss: populate dismissed_hash_cluster from linked source content hashes
```

Request models:
```python
class UpdateRecommendationRequest(BaseModel):
    status: str | None = None  # approve, defer, dismiss
    decided_by: str | None = None
```

Detail query should JOIN `intel_recommendation_sources` → `intel_content_items` for sources, and include `intel_recommendation_engrams` and `comments WHERE entity_type='recommendation'`.

- [ ] **Step 3: Add comment endpoints to intel_router.py**

```python
# GET /api/v1/intel/recommendations/{rec_id}/comments — list (paginated limit/offset, default 50)
# POST /api/v1/intel/recommendations/{rec_id}/comments — add comment
#   Emit RECOMMENDATION_COMMENTED stimulus if author_type='human'
# DELETE /api/v1/intel/recommendations/{rec_id}/comments/{comment_id} — delete

class CreateCommentRequest(BaseModel):
    author_type: str = "human"
    author_name: str
    body: str
```

- [ ] **Step 4: Verify endpoints work**

Run: `docker compose restart orchestrator && curl -s http://localhost:8000/api/v1/intel/recommendations -H "X-Admin-Secret: $(grep NOVA_ADMIN_SECRET .env | cut -d= -f2)" | python3 -m json.tool`
Expected: Empty array `[]`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/intel_router.py orchestrator/app/stimulus.py
git commit -m "feat(orchestrator): add recommendation and comment endpoints with stimuli"
```

---

## Task 5: Orchestrator — Goal Comments & Maturation Endpoints

**Files:**
- Modify: `orchestrator/app/goals_router.py`

- [ ] **Step 1: Add comment endpoints to goals_router.py**

Add to `goals_router`:
```python
# GET /api/v1/goals/{goal_id}/comments — list (paginated, default 50)
# POST /api/v1/goals/{goal_id}/comments — add comment
#   Emit GOAL_COMMENTED stimulus if author_type='human'
# DELETE /api/v1/goals/{goal_id}/comments/{comment_id} — delete
```

Import `CreateCommentRequest` from `app.intel_router` to avoid duplication.

- [ ] **Step 2: Add goal maturation endpoints**

```python
# POST /api/v1/goals/{goal_id}/approve-spec — set maturation_status='building', spec_approved_at/by
#   Emit GOAL_SPEC_APPROVED stimulus
# POST /api/v1/goals/{goal_id}/reject-spec — set maturation_status='speccing' (back to revise)
#   Emit GOAL_SPEC_REJECTED stimulus with feedback body
# GET /api/v1/goals/{goal_id}/scope — return scope_analysis JSONB
```

- [ ] **Step 3: Update GoalResponse model and _row_to_goal() for new columns**

In `goals_router.py`, update the `GoalResponse` Pydantic model to include the new fields:
```python
maturation_status: str | None = None
complexity: str | None = None
scope_analysis: dict | None = None
spec: str | None = None
spec_approved_at: str | None = None
spec_approved_by: str | None = None
source_recommendation_id: str | None = None
```

Update `_row_to_goal()` to map these columns from the DB row. Update `UpdateGoalRequest` to allow patching `complexity` and `maturation_status` (for manual override).

- [ ] **Step 4: Add system goal delete guard**

In the existing `delete_goal` handler, add before the DELETE query:
```python
row = await conn.fetchrow("SELECT created_via FROM goals WHERE id = $1", goal_id)
if row and row["created_via"] == "system":
    raise HTTPException(status_code=403, detail="System goals cannot be deleted")
```

- [ ] **Step 5: Verify goal comments endpoint**

Run: Create a goal via API, then POST a comment to it, then GET comments.
Expected: Comment appears in the response.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/app/goals_router.py
git commit -m "feat(orchestrator): add goal comments, maturation endpoints, and system goal protection"
```

---

## Task 6: Intel Worker — Service Scaffold

**Files:**
- Create: `intel-worker/pyproject.toml`
- Create: `intel-worker/Dockerfile`
- Create: `intel-worker/app/__init__.py`
- Create: `intel-worker/app/main.py`
- Create: `intel-worker/app/config.py`
- Create: `intel-worker/app/client.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "intel-worker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "httpx>=0.28",
    "redis[hiredis]>=5.2",
    "feedparser>=6.0",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
]
```

- [ ] **Step 2: Create config.py**

```python
import os

class Settings:
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/6")
    admin_secret: str = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "60"))
    port: int = int(os.getenv("PORT", "8110"))

settings = Settings()
```

- [ ] **Step 3: Create client.py**

httpx async client to orchestrator with `X-Admin-Secret` header:
```python
import httpx
from app.config import settings

_client: httpx.AsyncClient | None = None

async def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=settings.orchestrator_url,
        timeout=30.0,
        headers={"X-Admin-Secret": settings.admin_secret},
    )

def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialized")
    return _client

async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None
```

- [ ] **Step 4: Create main.py with health endpoints and lifespan**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.config import settings
from app.client import init_client, close_client, get_client

_poller_healthy = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_client()
    # Start polling loop as background task
    import asyncio
    from app.poller import run_polling_loop
    task = asyncio.create_task(run_polling_loop())
    global _poller_healthy
    _poller_healthy = True
    yield
    task.cancel()
    await close_client()

app = FastAPI(title="Nova Intel Worker", lifespan=lifespan)

@app.get("/health/live")
async def health_live():
    return {"status": "alive"}

@app.get("/health/ready")
async def health_ready():
    if not _poller_healthy:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    try:
        client = get_client()
        resp = await client.get("/health/live", timeout=5)
        if resp.status_code != 200:
            return JSONResponse(status_code=503, content={"status": "orchestrator_unreachable"})
    except Exception:
        return JSONResponse(status_code=503, content={"status": "orchestrator_unreachable"})
    return {"status": "ready"}
```

- [ ] **Step 5: Create Dockerfile**

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y curl && apt-get clean
WORKDIR /app
COPY intel-worker/pyproject.toml .
RUN pip install .
COPY intel-worker/app/ app/
EXPOSE 8110
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8110"]
```

- [ ] **Step 6: Create empty __init__.py and poller.py stub**

`intel-worker/app/__init__.py`: empty file
`intel-worker/app/poller.py`: stub with `async def run_polling_loop(): pass`

- [ ] **Step 7: Commit**

```bash
git add intel-worker/
git commit -m "feat(intel-worker): scaffold service with health endpoints and config"
```

---

## Task 7: Intel Worker — URL Validator & Queue Helpers

**Files:**
- Create: `intel-worker/app/url_validator.py`
- Create: `intel-worker/app/queue.py`

- [ ] **Step 1: Create url_validator.py with SSRF prevention**

```python
import ipaddress
from urllib.parse import urlparse

BLOCKED_HOSTS = {
    "localhost", "0.0.0.0", "redis", "postgres", "orchestrator", "memory-service",
    "llm-gateway", "cortex", "recovery", "chat-api", "chat-bridge",
    "dashboard", "intel-worker", "metadata.google.internal",
}

def validate_url(url: str) -> str | None:
    """Return error message if URL is unsafe, None if OK."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Scheme '{parsed.scheme}' not allowed"
    hostname = parsed.hostname or ""
    if hostname.lower() in BLOCKED_HOSTS:
        return f"Host '{hostname}' is blocked"
    try:
        # Normalize to catch decimal/hex/octal encoding tricks
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return f"Private/loopback IP '{ip}' not allowed"
        # Block cloud metadata endpoint
        if ip == ipaddress.ip_address("169.254.169.254"):
            return "Cloud metadata endpoint blocked"
    except ValueError:
        pass  # Not an IP — that's fine
    return None
```

- [ ] **Step 2: Create queue.py with dual-Redis pushing**

```python
import json
import redis.asyncio as aioredis
from app.config import settings

_redis_intel: aioredis.Redis | None = None  # db6
_redis_engram: aioredis.Redis | None = None  # db0

async def init_queues() -> None:
    global _redis_intel, _redis_engram
    _redis_intel = aioredis.from_url(settings.redis_url, decode_responses=True)
    # Parse base URL and swap db to 0 (robust to query params)
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(settings.redis_url)
    engram_url = urlunparse(parsed._replace(path="/0"))
    _redis_engram = aioredis.from_url(engram_url, decode_responses=True)

async def push_to_engram_queue(item: dict) -> None:
    payload = {
        "raw_text": f"{item.get('title', '')}\\n\\n{item.get('body', '')}",
        "source_type": "intel",
        "metadata": {
            "feed_name": item.get("feed_name", ""),
            "url": item.get("url", ""),
            "content_item_id": item.get("id", ""),
        },
    }
    await _redis_engram.lpush("engram:ingestion:queue", json.dumps(payload))

async def push_to_intel_queue(item: dict) -> None:
    payload = {
        "content_item_id": item.get("id", ""),
        "feed_id": item.get("feed_id", ""),
        "title": item.get("title", ""),
        "category": item.get("category", ""),
    }
    await _redis_intel.lpush("intel:new_items", json.dumps(payload))

async def close_queues() -> None:
    if _redis_intel:
        await _redis_intel.aclose()
    if _redis_engram:
        await _redis_engram.aclose()
```

- [ ] **Step 3: Wire queue init/close into main.py lifespan**

Add `init_queues()` and `close_queues()` calls.

- [ ] **Step 4: Commit**

```bash
git add intel-worker/app/url_validator.py intel-worker/app/queue.py intel-worker/app/main.py
git commit -m "feat(intel-worker): add SSRF URL validator and dual-Redis queue helpers"
```

---

## Task 8: Intel Worker — Feed Fetchers

**Files:**
- Create: `intel-worker/app/fetchers/__init__.py`
- Create: `intel-worker/app/fetchers/rss.py`
- Create: `intel-worker/app/fetchers/reddit.py`
- Create: `intel-worker/app/fetchers/page.py`
- Create: `intel-worker/app/fetchers/github.py`

- [ ] **Step 1: Create fetchers/__init__.py with dispatcher**

```python
from app.fetchers.rss import fetch_rss
from app.fetchers.reddit import fetch_reddit
from app.fetchers.page import fetch_page
from app.fetchers.github import fetch_github_trending, fetch_github_releases

FETCHERS = {
    "rss": fetch_rss,
    "reddit_json": fetch_reddit,
    "page": fetch_page,
    "github_trending": fetch_github_trending,
    "github_releases": fetch_github_releases,
}

async def fetch_feed(feed: dict) -> list[dict]:
    fetcher = FETCHERS.get(feed["feed_type"])
    if not fetcher:
        raise ValueError(f"Unknown feed type: {feed['feed_type']}")
    return await fetcher(feed)
```

Each fetcher returns a list of dicts with keys: `content_hash`, `title`, `url`, `body`, `author`, `score`, `published_at`, `metadata`.

- [ ] **Step 2: Create rss.py**

Uses `feedparser` library. Parse XML, extract entries, compute SHA-256 hash of `title + summary`.

- [ ] **Step 3: Create reddit.py**

GET `https://old.reddit.com/r/{sub}/new/.json?limit=25` with User-Agent header. Parse JSON listing. Extract `title`, `selftext`, `score`, `num_comments`, `author`, `url`, `created_utc`.

- [ ] **Step 4: Create page.py**

GET URL, convert HTML to text via BeautifulSoup `get_text()`. Hash full text. Compare against `feed.last_hash`. If changed, return a single content item with the new text.

- [ ] **Step 5: Create github.py**

Two fetchers:
- `fetch_github_trending`: GET `https://github.com/trending?since=daily&spoken_language_code=en`, parse HTML for repo names/descriptions. Filter to AI/ML by keywords.
- `fetch_github_releases`: GET `https://api.github.com/repos/{owner}/{repo}/releases?per_page=5`. Compare against known latest tag.

- [ ] **Step 6: Commit**

```bash
git add intel-worker/app/fetchers/
git commit -m "feat(intel-worker): add feed fetchers for RSS, Reddit, page, and GitHub"
```

---

## Task 9: Intel Worker — Polling Loop

**Files:**
- Modify: `intel-worker/app/poller.py`

- [ ] **Step 1: Implement the main polling loop**

```python
import asyncio
import logging
from app.client import get_client
from app.fetchers import fetch_feed
from app.queue import push_to_engram_queue, push_to_intel_queue
from app.config import settings

log = logging.getLogger(__name__)

async def run_polling_loop() -> None:
    while True:
        try:
            client = get_client()
            resp = await client.get("/api/v1/intel/feeds", params={"enabled": "true"})
            if resp.status_code != 200:
                log.warning("Failed to fetch feeds: %s", resp.status_code)
                await asyncio.sleep(settings.poll_interval)
                continue
            feeds = resp.json()

            for feed in feeds:
                if not _is_due(feed):
                    continue
                try:
                    items = await fetch_feed(feed)
                    if not items:
                        await _update_feed_status(feed["id"], success=True, last_hash=feed.get("last_hash"))
                        continue

                    # Post content to orchestrator (handles dedup)
                    post_resp = await client.post("/api/v1/intel/content", json={
                        "items": [{**item, "feed_id": feed["id"]} for item in items]
                    })
                    if post_resp.status_code == 200:
                        stored = post_resp.json()
                        for item in stored:
                            item["feed_name"] = feed["name"]
                            item["category"] = feed.get("category")
                            await push_to_engram_queue(item)
                            await push_to_intel_queue(item)

                    new_hash = items[0].get("content_hash") if items else feed.get("last_hash")
                    await _update_feed_status(feed["id"], success=True, last_hash=new_hash)
                except Exception as e:
                    log.warning("Feed %s failed: %s", feed["name"], e)
                    await _update_feed_status(feed["id"], success=False)

        except Exception as e:
            log.error("Polling loop error: %s", e)

        await asyncio.sleep(settings.poll_interval)
```

Helper functions:
- `_is_due(feed)` — check if `last_checked_at` is None or older than `check_interval_seconds` (with exponential backoff on `error_count`)
- `_update_feed_status(feed_id, success, last_hash)` — PATCH `/api/v1/intel/feeds/{feed_id}/status`

- [ ] **Step 2: Verify the polling loop starts**

Run: `docker compose build intel-worker && docker compose up -d intel-worker && docker compose logs -f intel-worker`
Expected: Logs show "Polling loop started" and feed fetch attempts.

- [ ] **Step 3: Commit**

```bash
git add intel-worker/app/poller.py
git commit -m "feat(intel-worker): implement main polling loop with adaptive timing"
```

---

## Task 10: Docker Compose Integration

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add intel-worker service to docker-compose.yml**

Add after the cortex service definition:

```yaml
  intel-worker:
    <<: *nova-common
    container_name: nova-intel-worker
    build:
      context: .
      dockerfile: intel-worker/Dockerfile
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8110", "--reload"]
    develop:
      watch:
        - action: sync
          path: ./intel-worker/app
          target: /app/app
          ignore:
            - __pycache__
            - "*.pyc"
    environment:
      ORCHESTRATOR_URL: http://orchestrator:8000
      REDIS_URL: redis://redis:6379/6
      NOVA_ADMIN_SECRET: ${NOVA_ADMIN_SECRET}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    ports:
      - "8110:8110"
    depends_on:
      orchestrator:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      <<: *nova-healthcheck
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8110/health/live', timeout=3)"]
```

- [ ] **Step 2: Build and start**

Run: `docker compose build intel-worker && docker compose up -d intel-worker`
Expected: Container starts, health check passes.

- [ ] **Step 3: Verify health**

Run: `curl -s http://localhost:8110/health/ready | python3 -m json.tool`
Expected: `{"status": "ready"}`

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): add intel-worker service to compose stack"
```

---

## Task 11: System Goals & Default Feeds Migration

**Files:**
- Create: `orchestrator/app/migrations/040_intel_system_goals.sql`

- [ ] **Step 1: Write the seeding migration**

```sql
-- Migration 040: Seed system intelligence goals and default feeds

-- System goals (idempotent: ON CONFLICT DO NOTHING)
INSERT INTO goals (id, title, description, status, priority, schedule_cron, max_completions,
                   max_cost_usd, check_interval_seconds, created_via, created_by)
VALUES
    ('d0000000-0000-0000-0000-000000000001',
     'Daily Intelligence Sweep',
     'Read all new intel content, cross-reference with engram memory, classify and build knowledge network.',
     'active', 5, '0 6 * * *', NULL, 0.50, 86400, 'system', 'system'),
    ('d0000000-0000-0000-0000-000000000002',
     'Weekly Intelligence Synthesis',
     'Find knowledge clusters, generate graded recommendations, re-evaluate deferred recommendations.',
     'active', 5, '0 8 * * 1', NULL, 2.00, 604800, 'system', 'system'),
    ('d0000000-0000-0000-0000-000000000003',
     'Self-Improvement Check',
     'Compare Nova capabilities against accumulated intelligence. Identify gaps, suggest improvements.',
     'active', 4, '0 10 * * 3,6', NULL, 1.50, 345600, 'system', 'system')
ON CONFLICT (id) DO NOTHING;

-- Add unique constraint for idempotent seeding
ALTER TABLE intel_feeds ADD CONSTRAINT intel_feeds_url_unique UNIQUE (url);

-- Default feeds (idempotent via ON CONFLICT on url)
INSERT INTO intel_feeds (name, url, feed_type, category, check_interval_seconds) VALUES
    ('r/artificial', 'https://old.reddit.com/r/artificial/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/artificialintelligence', 'https://old.reddit.com/r/artificialintelligence/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/openai', 'https://old.reddit.com/r/openai/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/ClaudeAI', 'https://old.reddit.com/r/ClaudeAI/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/LocalLLaMA', 'https://old.reddit.com/r/LocalLLaMA/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/MachineLearning', 'https://old.reddit.com/r/MachineLearning/new/.json', 'reddit_json', 'reddit', 86400),
    ('r/aitoolsupdate', 'https://old.reddit.com/r/aitoolsupdate/new/.json', 'reddit_json', 'reddit', 43200),
    ('Anthropic Blog', 'https://www.anthropic.com/rss.xml', 'rss', 'blog', 21600),
    ('OpenAI Blog', 'https://openai.com/blog/rss.xml', 'rss', 'blog', 21600),
    ('Google AI Blog', 'https://blog.google/technology/ai/rss/', 'rss', 'blog', 43200),
    ('Ollama Releases', 'https://github.com/ollama/ollama/releases.atom', 'github_releases', 'tooling', 86400),
    ('vLLM Releases', 'https://github.com/vllm-project/vllm/releases.atom', 'github_releases', 'tooling', 86400),
    ('LiteLLM Releases', 'https://github.com/BerriAI/litellm/releases.atom', 'github_releases', 'tooling', 86400),
    ('GitHub Trending AI/ML', 'https://github.com/trending?since=daily', 'github_trending', 'github', 86400)
ON CONFLICT (url) DO NOTHING;
```

- [ ] **Step 2: Verify migration applies**

Run: `docker compose restart orchestrator && curl -s http://localhost:8000/api/v1/intel/feeds -H "X-Admin-Secret: $(grep NOVA_ADMIN_SECRET .env | cut -d= -f2)" | python3 -c "import sys,json; feeds=json.load(sys.stdin); print(f'{len(feeds)} feeds seeded')"`
Expected: `14 feeds seeded`

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/migrations/040_intel_system_goals.sql
git commit -m "feat(db): seed system intelligence goals and default feeds"
```

---

## Task 12: Cortex — Serve Drive Maturation Awareness

**Files:**
- Modify: `cortex/app/drives/serve.py`
- Modify: `cortex/app/stimulus.py` (add constants)

- [ ] **Step 1: Add new stimulus constants to cortex**

In `cortex/app/stimulus.py`, add:
```python
RECOMMENDATION_APPROVED = "recommendation.approved"
RECOMMENDATION_COMMENTED = "recommendation.commented"
GOAL_SPEC_APPROVED = "goal.spec_approved"
GOAL_SPEC_REJECTED = "goal.spec_rejected"
GOAL_COMMENTED = "goal.commented"
```

- [ ] **Step 2: Update serve drive to handle maturation statuses**

In `cortex/app/drives/serve.py`, update the stale goals query to also find goals with active maturation:
- Goals in `maturation_status = 'scoping'` or `'speccing'` or `'building'` or `'verifying'` are work items for the serve drive
- Goals in `maturation_status = 'review'` are waiting for human — not stale
- Add stimulus boost for `goal.spec_approved`: urgency = max(urgency, 0.9)

In `_execute_serve`, update the task prompt based on maturation_status:
- `scoping`: prompt = "Analyze the scope of this goal: {title}. Identify all affected scopes..."
- `speccing`: prompt = "Write a detailed spec for this goal: {title}. Scope analysis: {scope_analysis}..."
- `building`: prompt = "Implement the next sub-task for goal: {title}. Spec: {spec}..."
- `verifying`: prompt = "Run verification for goal: {title}. Run tests, check builds..."
- Default (no maturation): existing behavior

- [ ] **Step 3: Commit**

```bash
git add cortex/app/drives/serve.py cortex/app/stimulus.py
git commit -m "feat(cortex): add maturation awareness to serve drive and new stimulus types"
```

---

## Task 13: Dashboard — API Layer

**Files:**
- Modify: `dashboard/src/api.ts`

- [ ] **Step 1: Add intel API functions**

Add to `dashboard/src/api.ts`:

```typescript
// Intel types
export interface IntelFeed {
  id: string; name: string; url: string; feed_type: string;
  category: string | null; check_interval_seconds: number;
  last_checked_at: string | null; error_count: number;
  enabled: boolean; created_at: string;
}

export interface IntelContentItem {
  id: string; title: string | null; url: string | null;
  body: string | null; author: string | null; score: number | null;
  published_at: string | null; metadata: Record<string, unknown>;
}

export interface IntelRecommendation {
  id: string; title: string; summary: string; rationale: string | null;
  features: string[]; grade: string; confidence: number;
  category: string | null; status: string;
  auto_implementable: boolean; complexity: string | null;
  sources?: IntelContentItem[]; comments?: Comment[];
  source_count?: number; memory_count?: number; comment_count?: number;
  created_at: string; updated_at: string;
}

export interface Comment {
  id: string; entity_type: string; entity_id: string;
  author_type: string; author_name: string; body: string;
  created_at: string;
}

export interface IntelStats {
  items_this_week: number; active_feeds: number;
  grade_a: number; grade_b: number; grade_c: number;
  total_recommendations: number; engrams_added: number;
}

// Intel API functions
export const getIntelFeeds = () => apiFetch<IntelFeed[]>('/api/v1/intel/feeds')
export const createIntelFeed = (data: Partial<IntelFeed>) => apiFetch<IntelFeed>('/api/v1/intel/feeds', { method: 'POST', body: JSON.stringify(data) })
export const updateIntelFeed = (id: string, data: Partial<IntelFeed>) => apiFetch<IntelFeed>(`/api/v1/intel/feeds/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const deleteIntelFeed = (id: string) => apiFetch<void>(`/api/v1/intel/feeds/${id}`, { method: 'DELETE' })
export const getIntelRecommendations = (params?: Record<string, string>) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return apiFetch<IntelRecommendation[]>(`/api/v1/intel/recommendations${qs}`)
}
export const getIntelRecommendation = (id: string) => apiFetch<IntelRecommendation>(`/api/v1/intel/recommendations/${id}`)
export const updateRecommendation = (id: string, data: { status: string; decided_by?: string }) => apiFetch<IntelRecommendation>(`/api/v1/intel/recommendations/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const getIntelStats = () => apiFetch<IntelStats>('/api/v1/intel/stats')
export const getComments = (entityType: string, entityId: string) => apiFetch<Comment[]>(`/api/v1/${entityType === 'goal' ? 'goals' : 'intel/recommendations'}/${entityId}/comments`)
export const addComment = (entityType: string, entityId: string, body: string, authorName: string) => apiFetch<Comment>(`/api/v1/${entityType === 'goal' ? 'goals' : 'intel/recommendations'}/${entityId}/comments`, { method: 'POST', body: JSON.stringify({ body, author_name: authorName, author_type: 'human' }) })
export const deleteComment = (entityType: string, entityId: string, commentId: string) => apiFetch<void>(`/api/v1/${entityType === 'goal' ? 'goals' : 'intel/recommendations'}/${entityId}/comments/${commentId}`, { method: 'DELETE' })
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd dashboard && npm run build`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/api.ts
git commit -m "feat(dashboard): add intel API types and functions"
```

---

## Task 14: Dashboard — Discussion Thread Component

**Files:**
- Create: `dashboard/src/components/DiscussionThread.tsx`

- [ ] **Step 1: Create the shared DiscussionThread component**

Component that renders a chronological comment list with input box. Used by both Intelligence and Goals pages.

Props:
```typescript
interface Props {
  entityType: 'recommendation' | 'goal'
  entityId: string
  authorName: string  // current user's name for new comments
}
```

Uses TanStack Query:
- `useQuery({ queryKey: ['comments', entityType, entityId], queryFn })` to fetch comments
- `useMutation` for adding/deleting comments
- Invalidate on success

Layout:
- Chronological list of comments
- Nova comments: teal avatar with "N", `text-teal-400` name
- Human comments: blue avatar with initials, `text-blue-400` name
- Timestamp in `text-content-tertiary`
- Input box at bottom with Send button

- [ ] **Step 2: Verify build**

Run: `cd dashboard && npm run build`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/DiscussionThread.tsx
git commit -m "feat(dashboard): add shared DiscussionThread component for recs and goals"
```

---

## Task 15: Dashboard — Intelligence Page

**Files:**
- Create: `dashboard/src/pages/Intelligence.tsx`
- Create: `dashboard/src/components/intel/RecommendationCard.tsx`
- Create: `dashboard/src/components/intel/RecommendationDetail.tsx`
- Modify: `dashboard/src/App.tsx` (add route)
- Modify: `dashboard/src/components/layout/Sidebar.tsx` (add nav item)

- [ ] **Step 1: Create RecommendationCard.tsx**

Feed list item component. Props: recommendation data, `onExpand` callback, `onApprove`/`onDefer` callbacks.

Layout follows the mockup:
- Colored left border by grade (green=A `border-green-500`, amber=B `border-amber-500`, red=C `border-red-500`)
- Grade badge with confidence percentage
- Title, summary, category
- Source count, memory count, comment count badges
- Inline Approve/Defer buttons

- [ ] **Step 2: Create RecommendationDetail.tsx**

Expandable detail view. Props: recommendation ID (fetches full detail).

Sections:
- Header: grade, category, title, action buttons (Approve/Defer/Dismiss)
- Summary paragraph
- Side-by-side "Why Implement" / "Features Enabled" panels
- Sources section: list of content items with "Open" link
- Related Memories: engrams with activation scores
- DiscussionThread component at the bottom

- [ ] **Step 3: Create Intelligence.tsx page**

Main page with:
- PageHeader: title="Intelligence", description, action="Manage Feeds" button
- Stats bar (5 Metric cards): items this week, active feeds, grade A, grade B, engrams
- Filter tabs: Pending | Approved | Deferred | Implemented | All
- Recommendation feed: list of RecommendationCard, clicking expands to RecommendationDetail
- Empty state when no recommendations

Uses:
- `useQuery({ queryKey: ['intel-recommendations', statusFilter], queryFn })` for the list
- `useQuery({ queryKey: ['intel-stats'], queryFn: getIntelStats })` for stats bar
- `useMutation` for approve/defer/dismiss actions with cache invalidation

- [ ] **Step 4: Add route in App.tsx**

Add inside the AppLayout routes:
```tsx
<Route path="/intelligence" element={<Intelligence />} />
```

- [ ] **Step 5: Add nav item in Sidebar.tsx**

Add to the first nav section (after Goals):
```typescript
{ to: '/intelligence', label: 'Intelligence', icon: Lightbulb, minRole: 'member' as Role }
```

Import `Lightbulb` from `lucide-react`.

- [ ] **Step 6: Verify build and navigation**

Run: `cd dashboard && npm run build`
Expected: Build succeeds. Navigate to `/intelligence` in the browser.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/pages/Intelligence.tsx dashboard/src/components/intel/ dashboard/src/App.tsx dashboard/src/components/layout/Sidebar.tsx
git commit -m "feat(dashboard): add Intelligence page with recommendation feed and detail view"
```

---

## Task 16: Dashboard — Feed Manager Modal

**Files:**
- Create: `dashboard/src/components/intel/FeedManagerModal.tsx`

- [ ] **Step 1: Create FeedManagerModal**

Modal with:
- Table of feeds: name, URL, type, category, interval, last checked, enabled toggle, delete button
- "Add Feed" form at top: URL input, name, type selector, category, interval
- Delete confirmation via ConfirmDialog

Uses TanStack Query mutations for CRUD, invalidates `['intel-feeds']` on success.

Follow the `ModelManagerModal.tsx` pattern for modal state management.

- [ ] **Step 2: Wire into Intelligence.tsx**

Add state: `const [feedManagerOpen, setFeedManagerOpen] = useState(false)`
Render: `<FeedManagerModal open={feedManagerOpen} onClose={() => setFeedManagerOpen(false)} />`
PageHeader action button opens the modal.

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npm run build`

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/intel/FeedManagerModal.tsx dashboard/src/pages/Intelligence.tsx
git commit -m "feat(dashboard): add feed manager modal for intelligence feeds"
```

---

## Task 17: Dashboard — Goals Page Enhancement

**Files:**
- Modify: `dashboard/src/pages/Goals.tsx`

- [ ] **Step 1: Add maturation status display to GoalCard**

In the GoalCard component, show maturation_status badge when present:
- Add a colored progress badge showing current maturation phase
- Show "Approve Spec" / "Reject Spec" buttons when `maturation_status === 'review'`

- [ ] **Step 2: Add discussion thread to goal detail**

When a goal card is expanded/clicked, show:
- Scope analysis (if available)
- Spec document (if available, rendered as markdown)
- DiscussionThread component

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npm run build`

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/Goals.tsx
git commit -m "feat(dashboard): add maturation status and discussion threads to Goals page"
```

---

## Task 18: Integration Tests

**Files:**
- Create: `tests/test_intel.py`

- [ ] **Step 1: Write integration tests**

Follow pattern from `tests/test_orchestrator.py`. Use existing `orchestrator` and `admin_headers` fixtures from `conftest.py` (do NOT redefine them). The project uses `asyncio_mode = auto` so no `@pytest.mark.asyncio` decorators needed.

```python
import pytest

class TestIntelFeeds:
    async def test_list_feeds(self, orchestrator, admin_headers):
        resp = await orchestrator.get("/api/v1/intel/feeds", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_feed(self, orchestrator, admin_headers):
        resp = await orchestrator.post("/api/v1/intel/feeds", headers=admin_headers, json={
            "name": "nova-test-feed",
            "url": "https://example.com/rss.xml",
            "feed_type": "rss",
            "category": "test",
        })
        assert resp.status_code == 201
        feed = resp.json()
        assert feed["name"] == "nova-test-feed"
        # Cleanup
        await orchestrator.delete(f"/api/v1/intel/feeds/{feed['id']}", headers=admin_headers)

    async def test_ssrf_blocked(self, orchestrator, admin_headers):
        resp = await orchestrator.post("/api/v1/intel/feeds", headers=admin_headers, json={
            "name": "nova-test-ssrf",
            "url": "http://localhost:8000/health/live",
            "feed_type": "page",
        })
        assert resp.status_code in (400, 422)

class TestIntelRecommendations:
    async def test_list_recommendations(self, orchestrator, admin_headers):
        resp = await orchestrator.get("/api/v1/intel/recommendations", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

class TestIntelStats:
    async def test_get_stats(self, orchestrator, admin_headers):
        resp = await orchestrator.get("/api/v1/intel/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items_this_week" in data
        assert "active_feeds" in data

class TestGoalComments:
    async def test_goal_comments_crud(self, orchestrator, admin_headers):
        # Create a goal
        resp = await orchestrator.post("/api/v1/goals", headers=admin_headers, json={
            "title": "nova-test-comment-goal",
        })
        goal_id = resp.json()["id"]

        # Add comment
        resp = await orchestrator.post(f"/api/v1/goals/{goal_id}/comments", headers=admin_headers, json={
            "author_name": "Test User",
            "body": "Test comment",
        })
        assert resp.status_code == 201
        comment_id = resp.json()["id"]

        # List comments
        resp = await orchestrator.get(f"/api/v1/goals/{goal_id}/comments", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Delete comment
        resp = await orchestrator.delete(f"/api/v1/goals/{goal_id}/comments/{comment_id}", headers=admin_headers)
        assert resp.status_code == 204

        # Cleanup
        await orchestrator.delete(f"/api/v1/goals/{goal_id}", headers=admin_headers)

class TestSystemGoalProtection:
    async def test_cannot_delete_system_goal(self, orchestrator, admin_headers):
        resp = await orchestrator.delete(
            "/api/v1/goals/d0000000-0000-0000-0000-000000000001",
            headers=admin_headers,
        )
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests**

Run: `make test`
Expected: All intel tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_intel.py
git commit -m "test: add integration tests for intel feeds, recommendations, comments, and system goals"
```

---

## Task 19: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

Add intel-worker to the services/ports table:
```
- **intel-worker** (8110) — Feed poller for AI ecosystem monitoring: RSS, Reddit, docs, GitHub (FastAPI, minimal health-only server)
```

Add to Redis DB allocation:
```
intel-worker=db6
```

Add to inter-service communication:
```
Intel-worker calls orchestrator (`/api/v1/intel/feeds`, `/api/v1/intel/content`) and pushes to Redis queues (db0 engram, db6 intel).
```

Add to code-to-docs mapping:
```
| `intel-worker/`, `orchestrator/app/intel_router.py` | (new — needs docs) |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with intel-worker service documentation"
```

---

## Follow-Up Items (out of scope for initial implementation)

These spec requirements are deferred to a follow-up iteration:

1. **Content retention/archival job** — The `intel_content_items_archive` table is created but the weekly archival job is not implemented. Add as a Cortex system goal or background task.
2. **Per-domain rate limiting** — The polling loop has adaptive per-feed timing but no per-domain rate bucket (spec requires Reddit 30/hr, GitHub 50/hr). Add rate tracking in Redis.
3. **Feed validation test fetch on creation** — The spec requires a 10-second test fetch when adding a feed to verify parsability. Not yet in the create feed endpoint.
4. **Website documentation** — The `intel-worker` and Intelligence page need documentation at `website/src/content/docs/nova/docs/`.
5. **Redirect-following SSRF validation** — URL validator checks the initial URL but not the final resolved URL after 3xx redirects. Add `allow_redirects=False` + manual follow with validation.
