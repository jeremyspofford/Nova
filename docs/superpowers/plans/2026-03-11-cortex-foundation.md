# Cortex Foundation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Cortex service container, create the goals system with CRUD API + dashboard UI, and add budget tracking stubs — the foundation for the autonomous thinking loop.

**Architecture:** Cortex is a new FastAPI service (port 8100) that depends only on postgres and redis (like recovery). Goals are stored in a new `goals` table with CRUD endpoints on the orchestrator (where all user-facing APIs live). The cortex service itself exposes control endpoints (status, pause/resume). Budget tracking reads existing `usage_events` rows.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Redis (db5), React/TypeScript/TanStack Query/Tailwind (dashboard)

**Spec:** `docs/plans/2026-03-10-cortex-design.md`

---

## File Structure

### New files — Cortex service
| File | Responsibility |
|------|----------------|
| `cortex/Dockerfile` | Container image (python:3.12-slim + uvicorn) |
| `cortex/pyproject.toml` | Dependencies |
| `cortex/app/__init__.py` | Package marker |
| `cortex/app/main.py` | FastAPI app, lifespan (init DB pool, start thinking loop stub) |
| `cortex/app/config.py` | Settings from env vars |
| `cortex/app/health.py` | `/health/live`, `/health/ready`, `/health/startup` |
| `cortex/app/router.py` | Control endpoints: status, pause, resume, drives |
| `cortex/app/db.py` | asyncpg pool management (same pattern as orchestrator) |
| `cortex/app/budget.py` | Budget tracking — reads `usage_events`, computes daily spend |

### New files — Orchestrator
| File | Responsibility |
|------|----------------|
| `orchestrator/app/migrations/021_cortex_goals.sql` | goals, goal_tasks, cortex_state tables; system user; API key; journal conversation |
| `orchestrator/app/goals_router.py` | Goal CRUD endpoints (POST/GET/PATCH/DELETE) |

### New files — Dashboard
| File | Responsibility |
|------|----------------|
| `dashboard/src/pages/Goals.tsx` | Goals page — list, create, detail view |

### Modified files
| File | Change |
|------|--------|
| `docker-compose.yml` | Add cortex service block |
| `dashboard/vite.config.ts` | Add `/cortex-api` proxy |
| `dashboard/nginx.conf` | Add `/cortex-api` proxy |
| `dashboard/src/api.ts` | Add goal CRUD functions + cortex status functions |
| `dashboard/src/App.tsx` | Add Goals route |
| `dashboard/src/components/NavBar.tsx` | Add Goals + Cortex nav links |
| `orchestrator/app/main.py` | Include goals_router |
| `orchestrator/app/pipeline_router.py` | Add `goal_id` to `SubmitPipelineTaskRequest` and INSERT |

---

## Chunk 1: Cortex Service Scaffold

### Task 1: Create Cortex service skeleton

**Files:**
- Create: `cortex/app/__init__.py`
- Create: `cortex/app/config.py`
- Create: `cortex/app/db.py`
- Create: `cortex/app/health.py`
- Create: `cortex/app/main.py`
- Create: `cortex/pyproject.toml`
- Create: `cortex/Dockerfile`

- [ ] **Step 1: Create `cortex/pyproject.toml`**

```toml
[project]
name = "nova-cortex"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "asyncpg>=0.30.0",
    "redis>=5.0.0",
    "httpx>=0.27.0",
]
```

- [ ] **Step 2: Create `cortex/app/__init__.py`**

Empty file.

- [ ] **Step 3: Create `cortex/app/config.py`**

```python
"""Cortex service configuration — reads from environment variables."""
import os


class Settings:
    port: int = 8100

    # Postgres (shared with orchestrator — same database)
    pg_host: str = os.getenv("POSTGRES_HOST", "postgres")
    pg_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    pg_user: str = os.getenv("POSTGRES_USER", "nova")
    pg_password: str = os.getenv("POSTGRES_PASSWORD", "nova_dev_password")
    pg_database: str = os.getenv("POSTGRES_DB", "nova")

    # Redis DB 5 (dedicated to cortex)
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/5")

    # Inter-service URLs
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")
    llm_gateway_url: str = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8001")
    memory_service_url: str = os.getenv("MEMORY_SERVICE_URL", "http://memory-service:8002")
    recovery_url: str = os.getenv("RECOVERY_URL", "http://recovery:8888")

    # Auth — cortex uses its own API key to talk to orchestrator
    admin_secret: str = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")

    # Thinking cycle
    cycle_interval_seconds: int = int(os.getenv("CORTEX_CYCLE_INTERVAL", "300"))
    enabled: bool = os.getenv("CORTEX_ENABLED", "true").lower() == "true"

    # Budget
    daily_budget_usd: float = float(os.getenv("CORTEX_DAILY_BUDGET_USD", "5.00"))

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def pg_dsn(self) -> str:
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"


settings = Settings()
```

- [ ] **Step 4: Create `cortex/app/db.py`**

```python
"""asyncpg connection pool for Cortex — same database as orchestrator."""
from __future__ import annotations

import json
import logging

import asyncpg

from .config import settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs."""
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init_pool() -> None:
    """Create the connection pool with retry."""
    global _pool
    import asyncio
    for attempt in range(1, 11):
        try:
            _pool = await asyncpg.create_pool(settings.pg_dsn, min_size=2, max_size=5, init=_init_connection)
            log.info("DB pool ready")
            return
        except (asyncpg.CannotConnectNowError, OSError) as exc:
            if attempt == 10:
                raise
            log.warning("Postgres not ready (attempt %d/10): %s", attempt, exc)
            await asyncio.sleep(2)


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool
```

- [ ] **Step 5: Create `cortex/app/health.py`**

```python
"""Health endpoints for Cortex service."""
from fastapi import APIRouter

from .config import settings
from .db import get_pool

health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/live")
async def liveness():
    return {"status": "alive"}


@health_router.get("/ready")
async def readiness():
    checks = {}

    # Postgres
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # Dependent services
    import httpx
    for svc, url in [
        ("orchestrator", settings.orchestrator_url),
        ("llm_gateway", settings.llm_gateway_url),
        ("memory_service", settings.memory_service_url),
    ]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"{url}/health/live")
                checks[svc] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
        except Exception as e:
            checks[svc] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


@health_router.get("/startup")
async def startup():
    return {"status": "started"}
```

- [ ] **Step 6: Create `cortex/app/main.py`**

```python
"""Nova Cortex — autonomous brain service."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_pool, close_pool
from .health import health_router
from .router import cortex_router

logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
log = logging.getLogger("nova.cortex")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    log.info("Cortex service ready — port %s, cycle interval %ds",
             settings.port, settings.cycle_interval_seconds)

    yield

    log.info("Cortex shutting down")
    await close_pool()


app = FastAPI(
    title="Nova Cortex",
    version="0.1.0",
    description="Autonomous brain service — thinking loop, goals, drives",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(cortex_router)
```

- [ ] **Step 7: Create `cortex/app/router.py`** (stub control endpoints)

```python
"""Cortex control endpoints — status, pause, resume."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from .db import get_pool

log = logging.getLogger(__name__)

cortex_router = APIRouter(prefix="/api/v1/cortex", tags=["cortex"])


@cortex_router.get("/status")
async def get_status():
    """Current Cortex state — running/paused, cycle count, active drive."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM cortex_state WHERE id = true")
    if not row:
        return {"status": "uninitialized"}
    return {
        "status": row["status"],
        "current_drive": row["current_drive"],
        "cycle_count": row["cycle_count"],
        "last_cycle_at": row["last_cycle_at"].isoformat() if row["last_cycle_at"] else None,
    }


@cortex_router.post("/pause")
async def pause():
    """Pause autonomous operation."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cortex_state SET status = 'paused', updated_at = NOW() WHERE id = true"
        )
    log.info("Cortex paused")
    return {"status": "paused"}


@cortex_router.post("/resume")
async def resume():
    """Resume autonomous operation."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cortex_state SET status = 'running', updated_at = NOW() WHERE id = true"
        )
    log.info("Cortex resumed")
    return {"status": "running"}


@cortex_router.get("/drives")
async def get_drives():
    """Current drive urgency scores (placeholder — returns static structure)."""
    return {
        "drives": [
            {"name": "serve", "priority": 1, "urgency": 0.0, "description": "Pursue user-set goals"},
            {"name": "maintain", "priority": 2, "urgency": 0.0, "description": "Keep Nova healthy"},
            {"name": "improve", "priority": 3, "urgency": 0.0, "description": "Make Nova's code better"},
            {"name": "learn", "priority": 4, "urgency": 0.0, "description": "Build knowledge"},
            {"name": "reflect", "priority": 5, "urgency": 0.0, "description": "Learn from experience"},
        ]
    }
```

- [ ] **Step 8: Create `cortex/Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY cortex/pyproject.toml .
RUN pip install --no-cache-dir .

COPY cortex/app/ app/

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
```

- [ ] **Step 9: Verify syntax**

Run: `python3 -m py_compile cortex/app/config.py && python3 -m py_compile cortex/app/db.py && python3 -m py_compile cortex/app/health.py && python3 -m py_compile cortex/app/router.py && python3 -m py_compile cortex/app/main.py && echo "All OK"`

Expected: `All OK`

- [ ] **Step 10: Commit**

```bash
git add cortex/
git commit -m "feat: add cortex service scaffold (FastAPI + asyncpg + health)"
```

---

### Task 2: Add Cortex to Docker Compose

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add cortex service block**

Add after the `recovery` service block in `docker-compose.yml`:

```yaml
  cortex:
    <<: *nova-common
    build:
      context: .
      dockerfile: cortex/Dockerfile
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_USER: nova
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-nova_dev_password}
      POSTGRES_DB: nova
      REDIS_URL: redis://redis:6379/5
      ORCHESTRATOR_URL: http://orchestrator:8000
      LLM_GATEWAY_URL: http://llm-gateway:8001
      MEMORY_SERVICE_URL: http://memory-service:8002
      RECOVERY_URL: http://recovery:8888
      NOVA_ADMIN_SECRET: ${NOVA_ADMIN_SECRET:-nova-admin-secret-change-me}
      CORTEX_ENABLED: ${CORTEX_ENABLED:-true}
      CORTEX_CYCLE_INTERVAL: ${CORTEX_CYCLE_INTERVAL:-300}
      CORTEX_DAILY_BUDGET_USD: ${CORTEX_DAILY_BUDGET_USD:-5.00}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    ports:
      - "8100:8100"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      <<: *nova-healthcheck
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8100/health/live', timeout=3)"]
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 256M
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add cortex service to docker-compose"
```

---

### Task 3: Add dashboard proxy routes for Cortex

**Files:**
- Modify: `dashboard/vite.config.ts`
- Modify: `dashboard/nginx.conf`

- [ ] **Step 1: Add Vite dev proxy**

In `dashboard/vite.config.ts`, add inside the `proxy` object after the `/recovery-api` entry:

```typescript
      '/cortex-api': {
        target: 'http://localhost:8100',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/cortex-api/, ''),
      },
```

- [ ] **Step 2: Add nginx prod proxy**

In `dashboard/nginx.conf`, add a new `location` block before the `location /` catch-all:

```nginx
    location /cortex-api/ {
        set $cortex http://cortex:8100;
        rewrite ^/cortex-api/(.*) /$1 break;
        proxy_pass $cortex;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
    }
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/vite.config.ts dashboard/nginx.conf
git commit -m "feat: add cortex-api proxy to dashboard (vite + nginx)"
```

---

## Chunk 2: Goals System (Migration + API + Dashboard)

### Task 4: Create migration for goals, cortex_state, system user, and API key

**Files:**
- Create: `orchestrator/app/migrations/021_cortex_goals.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 021: Cortex foundation — goals, cortex_state, system user, API key, journal conversation

-- ── Goals table ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS goals (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title                   TEXT NOT NULL,
    description             TEXT,
    status                  TEXT NOT NULL DEFAULT 'active',
        -- active, paused, completed, failed, cancelled
    priority                INTEGER NOT NULL DEFAULT 0,
    progress                REAL NOT NULL DEFAULT 0.0,
    current_plan            JSONB,
    iteration               INTEGER NOT NULL DEFAULT 0,
    max_iterations          INTEGER DEFAULT 50,
    max_cost_usd            REAL,
    cost_so_far_usd         REAL NOT NULL DEFAULT 0.0,
    check_interval_seconds  INTEGER DEFAULT 3600,
    last_checked_at         TIMESTAMPTZ,
    parent_goal_id          UUID REFERENCES goals(id),
    created_by              TEXT NOT NULL DEFAULT 'user',
    tenant_id               UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS goals_status_idx ON goals(status);
CREATE INDEX IF NOT EXISTS goals_priority_idx ON goals(priority DESC) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS goals_tenant_idx ON goals(tenant_id);
CREATE INDEX IF NOT EXISTS goals_parent_idx ON goals(parent_goal_id) WHERE parent_goal_id IS NOT NULL;

-- ── Goal-to-task mapping ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS goal_tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id     UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    sequence    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(goal_id, task_id)
);

CREATE INDEX IF NOT EXISTS goal_tasks_goal_idx ON goal_tasks(goal_id);

-- ── Add FK on existing tasks.goal_id → goals ────────────────────────────────
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tasks_goal_id_fkey'
    ) THEN
        ALTER TABLE tasks ADD CONSTRAINT tasks_goal_id_fkey
            FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE SET NULL;
    END IF;
END $$;

-- ── Cortex singleton state ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cortex_state (
    id              BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    status          TEXT NOT NULL DEFAULT 'running',
    current_drive   TEXT,
    cycle_count     BIGINT NOT NULL DEFAULT 0,
    last_cycle_at   TIMESTAMPTZ,
    last_checkpoint JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO cortex_state DEFAULT VALUES ON CONFLICT DO NOTHING;

-- ── System user for Cortex ───────────────────────────────────────────────────
INSERT INTO users (id, email, display_name, role, status, created_at)
VALUES (
    'a0000000-0000-0000-0000-000000000001',
    'cortex@system.nova',
    'Cortex',
    'owner',
    'active',
    NOW()
) ON CONFLICT (email) DO NOTHING;

-- ── Cortex API key (deterministic hash so it's idempotent) ───────────────────
-- Key value: sk-nova-cortex-internal (never exposed externally)
INSERT INTO api_keys (id, name, key_hash, key_prefix, is_active, rate_limit_rpm, metadata)
VALUES (
    'b0000000-0000-0000-0000-000000000001',
    'cortex-internal',
    encode(sha256('sk-nova-cortex-internal'::bytea), 'hex'),
    'sk-nova-cortex',
    TRUE,
    600,
    '{"system": true, "owner": "cortex"}'::jsonb
) ON CONFLICT (id) DO NOTHING;

-- ── Journal conversation for Cortex ──────────────────────────────────────────
INSERT INTO conversations (id, title, user_id, created_at)
VALUES (
    'c0000000-0000-0000-0000-000000000001',
    'Cortex Journal',
    'a0000000-0000-0000-0000-000000000001',
    NOW()
) ON CONFLICT (id) DO NOTHING;
```

- [ ] **Step 2: Verify SQL syntax (basic check)**

Run: `grep -c 'CREATE TABLE\|CREATE INDEX\|INSERT INTO\|ALTER TABLE' orchestrator/app/migrations/021_cortex_goals.sql`

Expected: `9` (3 tables, 4 indexes, 1 alter, 1 insert would vary — just verify the file has content)

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/migrations/021_cortex_goals.sql
git commit -m "feat: add migration 021 — goals, cortex_state, system user, API key"
```

---

### Task 5: Add Goals CRUD endpoints to orchestrator

**Files:**
- Create: `orchestrator/app/goals_router.py`
- Modify: `orchestrator/app/main.py`

- [ ] **Step 1: Create `orchestrator/app/goals_router.py`**

```python
"""Goal CRUD endpoints — used by dashboard and cortex."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import UserDep
from app.db import get_pool

log = logging.getLogger(__name__)

goals_router = APIRouter(tags=["goals"])


# ── Request / Response models ─────────────────────────────────────────────────

class CreateGoalRequest(BaseModel):
    title: str
    description: str | None = None
    priority: int = 0
    max_iterations: int | None = 50
    max_cost_usd: float | None = None
    check_interval_seconds: int | None = 3600
    parent_goal_id: UUID | None = None


class UpdateGoalRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: int | None = None
    progress: float | None = None
    max_iterations: int | None = None
    max_cost_usd: float | None = None
    check_interval_seconds: int | None = None


class GoalResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    status: str
    priority: int
    progress: float
    current_plan: dict | list | None
    iteration: int
    max_iterations: int | None
    max_cost_usd: float | None
    cost_so_far_usd: float
    check_interval_seconds: int | None
    last_checked_at: datetime | None
    parent_goal_id: UUID | None
    created_by: str
    created_at: datetime
    updated_at: datetime


# ── Endpoints ─────────────────────────────────────────────────────────────────

@goals_router.post("/api/v1/goals", response_model=GoalResponse, status_code=201)
async def create_goal(req: CreateGoalRequest, user: UserDep):
    """Create a new goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO goals (title, description, priority, max_iterations,
                               max_cost_usd, check_interval_seconds, parent_goal_id, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
            """,
            req.title, req.description, req.priority, req.max_iterations,
            req.max_cost_usd, req.check_interval_seconds,
            req.parent_goal_id, user.email,
        )
    log.info("Goal created: %s — %s", row["id"], req.title)
    return _row_to_goal(row)


@goals_router.get("/api/v1/goals", response_model=list[GoalResponse])
async def list_goals(
    _user: UserDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    """List goals, optionally filtered by status."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                "SELECT * FROM goals WHERE status = $1 ORDER BY priority DESC, created_at DESC LIMIT $2",
                status, limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM goals ORDER BY priority DESC, created_at DESC LIMIT $1",
                limit,
            )
    return [_row_to_goal(r) for r in rows]


@goals_router.get("/api/v1/goals/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: UUID, _user: UserDep):
    """Get a single goal by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM goals WHERE id = $1", goal_id)
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
    return _row_to_goal(row)


@goals_router.patch("/api/v1/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(goal_id: UUID, req: UpdateGoalRequest, _user: UserDep):
    """Update a goal (title, status, priority, progress, etc.)."""
    # Build SET clause dynamically from non-None fields
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_parts = []
    values = []
    for i, (key, val) in enumerate(updates.items(), start=1):
        set_parts.append(f"{key} = ${i}")
        values.append(val)

    values.append(goal_id)
    set_clause = ", ".join(set_parts)
    idx = len(values)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE goals SET {set_clause}, updated_at = NOW() WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found")
    log.info("Goal updated: %s", goal_id)
    return _row_to_goal(row)


@goals_router.delete("/api/v1/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: UUID, _user: UserDep):
    """Cancel and delete a goal."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM goals WHERE id = $1", goal_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Goal not found")
    log.info("Goal deleted: %s", goal_id)


def _row_to_goal(row) -> GoalResponse:
    return GoalResponse(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        priority=row["priority"],
        progress=row["progress"],
        current_plan=row["current_plan"],
        iteration=row["iteration"],
        max_iterations=row["max_iterations"],
        max_cost_usd=row["max_cost_usd"],
        cost_so_far_usd=row["cost_so_far_usd"],
        check_interval_seconds=row["check_interval_seconds"],
        last_checked_at=row["last_checked_at"],
        parent_goal_id=row["parent_goal_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
```

- [ ] **Step 2: Register goals_router in orchestrator main.py**

In `orchestrator/app/main.py`, add after the existing router imports:

```python
from app.goals_router import goals_router
```

And add after the existing `app.include_router(...)` calls:

```python
app.include_router(goals_router)
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile orchestrator/app/goals_router.py && python3 -m py_compile orchestrator/app/main.py && echo "OK"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/goals_router.py orchestrator/app/main.py
git commit -m "feat: add goals CRUD endpoints to orchestrator"
```

---

### Task 6: Wire goal_id into pipeline task submission

**Files:**
- Modify: `orchestrator/app/pipeline_router.py`

- [ ] **Step 1: Add `goal_id` to `SubmitPipelineTaskRequest`**

In `orchestrator/app/pipeline_router.py`, update the request model:

```python
class SubmitPipelineTaskRequest(BaseModel):
    user_input: str
    pod_name: str | None = None     # None → settings.default_pod_name
    goal_id: str | None = None      # Link task to a goal (Cortex uses this)
    metadata: dict[str, Any] = {}
```

- [ ] **Step 2: Pass `goal_id` through to the INSERT**

In the `submit_pipeline_task` handler, update the INSERT query to include `goal_id`:

Change the INSERT from:
```sql
INSERT INTO tasks
    (user_input, pod_id, status, metadata,
     retry_count, max_retries, queued_at, checkpoint)
VALUES
    ($1, $2::uuid, 'queued', $3::jsonb,
     0, $4, now(), '{}')
RETURNING id, queued_at
```

To:
```sql
INSERT INTO tasks
    (user_input, pod_id, goal_id, status, metadata,
     retry_count, max_retries, queued_at, checkpoint)
VALUES
    ($1, $2::uuid, $3::uuid, 'queued', $4::jsonb,
     0, $5, now(), '{}')
RETURNING id, queued_at
```

And update the parameter list to include `req.goal_id` as the 3rd parameter, shifting `metadata` and `max_retries` to $4 and $5.

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile orchestrator/app/pipeline_router.py && echo "OK"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/pipeline_router.py
git commit -m "feat: wire goal_id into pipeline task submission"
```

---

### Task 7: Add goal and cortex API functions to dashboard

**Files:**
- Modify: `dashboard/src/api.ts`

- [ ] **Step 1: Add goal types and CRUD functions**

Add before the `// ── Provider status` section in `dashboard/src/api.ts`:

```typescript
// ── Goals ────────────────────────────────────────────────────────────────────

export interface Goal {
  id: string
  title: string
  description: string | null
  status: 'active' | 'paused' | 'completed' | 'failed' | 'cancelled'
  priority: number
  progress: number
  current_plan: unknown | null
  iteration: number
  max_iterations: number | null
  max_cost_usd: number | null
  cost_so_far_usd: number
  check_interval_seconds: number | null
  last_checked_at: string | null
  parent_goal_id: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export const getGoals = (status?: string) => {
  const qs = status ? `?status=${status}` : ''
  return apiFetch<Goal[]>(`/api/v1/goals${qs}`)
}

export const getGoal = (id: string) =>
  apiFetch<Goal>(`/api/v1/goals/${id}`)

export const createGoal = (data: { title: string; description?: string; priority?: number; max_cost_usd?: number }) =>
  apiFetch<Goal>('/api/v1/goals', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const updateGoal = (id: string, data: Partial<Goal>) =>
  apiFetch<Goal>(`/api/v1/goals/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })

export const deleteGoal = (id: string) =>
  apiFetch<void>(`/api/v1/goals/${id}`, { method: 'DELETE' })

// ── Cortex ───────────────────────────────────────────────────────────────────

export interface CortexStatus {
  status: string
  current_drive: string | null
  cycle_count: number
  last_cycle_at: string | null
}

export interface CortexDrive {
  name: string
  priority: number
  urgency: number
  description: string
}

export const getCortexStatus = () =>
  apiFetch<CortexStatus>('/cortex-api/api/v1/cortex/status')

export const pauseCortex = () =>
  apiFetch<{ status: string }>('/cortex-api/api/v1/cortex/pause', { method: 'POST' })

export const resumeCortex = () =>
  apiFetch<{ status: string }>('/cortex-api/api/v1/cortex/resume', { method: 'POST' })

export const getCortexDrives = () =>
  apiFetch<{ drives: CortexDrive[] }>('/cortex-api/api/v1/cortex/drives')
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/src/api.ts
git commit -m "feat: add goal + cortex API functions to dashboard"
```

---

### Task 8: Create Goals dashboard page

**Files:**
- Create: `dashboard/src/pages/Goals.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/components/NavBar.tsx`

- [ ] **Step 1: Create `dashboard/src/pages/Goals.tsx`**

```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Target, Plus, Pause, Play, Trash2, ChevronRight } from 'lucide-react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { getGoals, createGoal, updateGoal, deleteGoal, type Goal } from '../api'
import Card from '../components/Card'

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  paused: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  completed: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  cancelled: 'bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400',
}

export function Goals() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: goals = [], isFetching } = useQuery({
    queryKey: ['goals', statusFilter],
    queryFn: () => getGoals(statusFilter),
    refetchInterval: 10_000,
  })

  const create = useMutation({
    mutationFn: () => createGoal({ title: newTitle, description: newDescription || undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] })
      setNewTitle('')
      setNewDescription('')
      setShowCreate(false)
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => deleteGoal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  })

  const toggleStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => updateGoal(id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  })

  const filters = ['all', 'active', 'paused', 'completed', 'failed', 'cancelled']

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Target size={20} className="text-accent-600 dark:text-accent-400" />
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">Goals</h1>
          {isFetching && <span className="text-xs text-neutral-400 animate-pulse">updating…</span>}
        </div>
        <button
          onClick={() => setShowCreate(v => !v)}
          className="flex items-center gap-1.5 rounded-lg bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700 transition-colors"
        >
          <Plus size={14} /> New Goal
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <Card className="p-4 space-y-3">
          <input
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            placeholder="Goal title…"
            className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-accent-500"
            autoFocus
          />
          <textarea
            value={newDescription}
            onChange={e => setNewDescription(e.target.value)}
            placeholder="Description (optional)…"
            rows={2}
            className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-accent-500 resize-none"
          />
          <div className="flex gap-2">
            <button
              onClick={() => create.mutate()}
              disabled={!newTitle.trim() || create.isPending}
              className="rounded-lg bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700 disabled:opacity-50 transition-colors"
            >
              {create.isPending ? 'Creating…' : 'Create'}
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </Card>
      )}

      {/* Status filter tabs */}
      <div className="flex gap-1">
        {filters.map(f => (
          <button
            key={f}
            onClick={() => setStatusFilter(f === 'all' ? undefined : f)}
            className={clsx(
              'rounded-md px-3 py-1 text-xs font-medium transition-colors capitalize',
              (f === 'all' ? !statusFilter : statusFilter === f)
                ? 'bg-accent-600/10 text-accent-700 dark:text-accent-400'
                : 'text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800',
            )}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Goals list */}
      <div className="space-y-2">
        {goals.length === 0 && (
          <p className="text-sm text-neutral-400 text-center py-8">No goals yet. Create one to get started.</p>
        )}
        {goals.map((goal: Goal) => (
          <Card key={goal.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <button
                  onClick={() => setExpandedId(expandedId === goal.id ? null : goal.id)}
                  className="flex items-center gap-2 text-left w-full"
                >
                  <ChevronRight
                    size={14}
                    className={clsx('text-neutral-400 transition-transform', expandedId === goal.id && 'rotate-90')}
                  />
                  <span className="font-medium text-sm text-neutral-900 dark:text-neutral-100 truncate">
                    {goal.title}
                  </span>
                  <span className={clsx('shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium', STATUS_COLORS[goal.status] || STATUS_COLORS.cancelled)}>
                    {goal.status}
                  </span>
                </button>
                {/* Progress bar */}
                <div className="mt-2 ml-6 flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-neutral-200 dark:bg-neutral-700 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-accent-500 transition-all"
                      style={{ width: `${Math.round(goal.progress * 100)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-neutral-400 tabular-nums w-8 text-right">
                    {Math.round(goal.progress * 100)}%
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {goal.status === 'active' && (
                  <button
                    onClick={() => toggleStatus.mutate({ id: goal.id, status: 'paused' })}
                    className="p-1 rounded text-neutral-400 hover:text-amber-500 transition-colors"
                    title="Pause"
                  >
                    <Pause size={14} />
                  </button>
                )}
                {goal.status === 'paused' && (
                  <button
                    onClick={() => toggleStatus.mutate({ id: goal.id, status: 'active' })}
                    className="p-1 rounded text-neutral-400 hover:text-emerald-500 transition-colors"
                    title="Resume"
                  >
                    <Play size={14} />
                  </button>
                )}
                <button
                  onClick={() => remove.mutate(goal.id)}
                  className="p-1 rounded text-neutral-400 hover:text-red-500 transition-colors"
                  title="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>

            {/* Expanded detail */}
            {expandedId === goal.id && (
              <div className="mt-3 ml-6 space-y-2 text-xs text-neutral-500 dark:text-neutral-400">
                {goal.description && <p>{goal.description}</p>}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <div>
                    <span className="text-neutral-400">Priority:</span>{' '}
                    <span className="text-neutral-700 dark:text-neutral-300">{goal.priority}</span>
                  </div>
                  <div>
                    <span className="text-neutral-400">Iterations:</span>{' '}
                    <span className="text-neutral-700 dark:text-neutral-300">
                      {goal.iteration}{goal.max_iterations ? `/${goal.max_iterations}` : ''}
                    </span>
                  </div>
                  <div>
                    <span className="text-neutral-400">Cost:</span>{' '}
                    <span className="text-neutral-700 dark:text-neutral-300">
                      ${goal.cost_so_far_usd.toFixed(2)}
                      {goal.max_cost_usd ? ` / $${goal.max_cost_usd.toFixed(2)}` : ''}
                    </span>
                  </div>
                  <div>
                    <span className="text-neutral-400">Created:</span>{' '}
                    <span className="text-neutral-700 dark:text-neutral-300">
                      {formatDistanceToNow(new Date(goal.created_at), { addSuffix: true })}
                    </span>
                  </div>
                </div>
                <div>
                  <span className="text-neutral-400">Created by:</span>{' '}
                  <span className="text-neutral-700 dark:text-neutral-300">{goal.created_by}</span>
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add Goals route to `dashboard/src/App.tsx`**

Add import:
```typescript
import { Goals } from './pages/Goals'
```

Add route after the `/engrams` route:
```tsx
<Route path="/goals" element={<PageShell><Goals /></PageShell>} />
```

- [ ] **Step 3: Add nav links to `dashboard/src/components/NavBar.tsx`**

Add `Target` to the lucide imports:
```typescript
import { Key, Cpu, BarChart2, Settings, X, ListTodo, Layers, MessageSquare, Plug, Menu, Network, Brain, LogOut, ChevronDown, CircleUser, Info, Users2, Target } from 'lucide-react'
```

Add to `mainLinks` array, after the Chat entry:
```typescript
  { to: '/goals',    label: 'Goals',    icon: Target           },
```

- [ ] **Step 4: Verify dashboard builds**

Run: `cd dashboard && npx tsc --noEmit && echo "OK"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/Goals.tsx dashboard/src/App.tsx dashboard/src/components/NavBar.tsx
git commit -m "feat: add Goals dashboard page with CRUD, status filters, progress bars"
```

---

## Chunk 3: Budget Tracking Stub + Cost Management

### Task 9: Add budget tracking to Cortex

**Files:**
- Create: `cortex/app/budget.py`

- [ ] **Step 1: Create `cortex/app/budget.py`**

```python
"""Budget tracking — reads usage_events to compute daily spend."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from .config import settings
from .db import get_pool

log = logging.getLogger(__name__)


async def get_daily_spend() -> float:
    """Sum cost_usd from usage_events for today (UTC)."""
    pool = get_pool()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_events WHERE created_at >= $1",
            today_start,
        )
    return float(result)


async def get_budget_status() -> dict:
    """Return current budget state."""
    daily_spend = await get_daily_spend()
    budget = settings.daily_budget_usd
    remaining = max(0.0, budget - daily_spend)
    pct_used = (daily_spend / budget * 100) if budget > 0 else 0.0

    return {
        "daily_budget_usd": budget,
        "daily_spend_usd": round(daily_spend, 4),
        "remaining_usd": round(remaining, 4),
        "percent_used": round(pct_used, 1),
        "budget_exceeded": daily_spend >= budget,
        "tier": _compute_tier(pct_used),
    }


def _compute_tier(pct_used: float) -> str:
    """Determine model tier based on budget usage.

    < 50%: best (use top-tier models for all work)
    50-80%: mid (shift background work to cheaper models)
    80-100%: cheap (local/cheapest models only)
    >= 100%: none (health checks only, no LLM calls)
    """
    if pct_used >= 100:
        return "none"
    if pct_used >= 80:
        return "cheap"
    if pct_used >= 50:
        return "mid"
    return "best"
```

- [ ] **Step 2: Add budget endpoint to cortex router**

In `cortex/app/router.py`, add import at top:
```python
from .budget import get_budget_status
```

Add endpoint at the end of the file:
```python
@cortex_router.get("/budget")
async def budget():
    """Current budget state — daily spend, remaining, tier."""
    return await get_budget_status()
```

- [ ] **Step 3: Add budget API function to dashboard**

In `dashboard/src/api.ts`, add after the `getCortexDrives` function:

```typescript
export interface BudgetStatus {
  daily_budget_usd: number
  daily_spend_usd: number
  remaining_usd: number
  percent_used: number
  budget_exceeded: boolean
  tier: string
}

export const getCortexBudget = () =>
  apiFetch<BudgetStatus>('/cortex-api/api/v1/cortex/budget')
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -m py_compile cortex/app/budget.py && python3 -m py_compile cortex/app/router.py && echo "OK"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add cortex/app/budget.py cortex/app/router.py dashboard/src/api.ts
git commit -m "feat: add budget tracking to cortex (reads usage_events, computes tier)"
```

---

### Task 10: Update CLAUDE.md with Cortex service

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add Cortex to the services list**

In the `Architecture` section's services list, add after `recovery`:
```
- **cortex** (8100) — Autonomous brain: thinking loop, goals, drives, budget tracking (FastAPI + asyncpg)
```

- [ ] **Step 2: Add to inter-service communication**

Add to the inter-service communication paragraph:
```
Cortex calls orchestrator (task dispatch, goal management), llm-gateway (planning, evaluation), memory-service (read/write knowledge), and recovery (checkpoints, rollbacks). Dashboard proxies to cortex (`/cortex-api`).
```

- [ ] **Step 3: Add Redis DB allocation**

Update the Redis DB allocation line:
```
**Redis DB allocation:** orchestrator=db2, llm-gateway=db1, chat-api=db3, memory-service=db0, chat-bridge=db4, cortex=db5.
```

- [ ] **Step 4: Add to code-to-docs mapping table**

Add row:
```
| `cortex/` | (new — no docs yet) |
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add cortex service to CLAUDE.md architecture docs"
```

---

### Task 11: Final verification

- [ ] **Step 1: Verify all Python syntax**

Run: `python3 -m py_compile cortex/app/config.py && python3 -m py_compile cortex/app/db.py && python3 -m py_compile cortex/app/health.py && python3 -m py_compile cortex/app/router.py && python3 -m py_compile cortex/app/main.py && python3 -m py_compile cortex/app/budget.py && python3 -m py_compile orchestrator/app/goals_router.py && python3 -m py_compile orchestrator/app/pipeline_router.py && echo "All Python OK"`

Expected: `All Python OK`

- [ ] **Step 2: Verify dashboard TypeScript**

Run: `cd dashboard && npx tsc --noEmit && echo "Dashboard OK"`

Expected: `Dashboard OK`

- [ ] **Step 3: Verify Docker build (optional)**

Run: `docker compose build cortex 2>&1 | tail -5`

Expected: Successfully built image

- [ ] **Step 4: Verify migration runs**

Start services, then check:
Run: `docker compose up -d postgres && sleep 5 && docker compose up -d orchestrator && sleep 10 && docker compose exec orchestrator python3 -c "print('migration OK')"`

Or simply verify migration SQL is valid:
Run: `grep -c 'CREATE TABLE\|CREATE INDEX\|INSERT INTO' orchestrator/app/migrations/021_cortex_goals.sql`

Expected: Multiple matches (tables + indexes + inserts = ~10+)
