# Demo Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Self-serve ephemeral demo platform — "Try Nova Free" button on arialabs.ai provisions isolated 1-hour Nova instances.

**Architecture:** Three components: (A) demo mode inside Nova (`NOVA_DEMO=true` flag activating budget caps, onboarding, expiry enforcement), (B) standalone demo provisioner service, (C) Traefik + VPS infrastructure. Component A ships first and is testable independently.

**Tech Stack:** Python/FastAPI (provisioner), React/TypeScript (dashboard demo UI), Docker Compose (demo profile), Traefik (reverse proxy), Redis (budget tracking, rate limiting), Let's Encrypt (wildcard TLS via DNS-01)

**Spec:** `docs/superpowers/specs/2026-03-29-demo-platform-design.md`

---

## File Structure

### Component A: Demo Mode (inside Nova)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `llm-gateway/app/config.py` | Add `NOVA_DEMO`, `DEMO_TOKEN_BUDGET` settings |
| Modify | `llm-gateway/app/router.py` | Budget tracking and enforcement on `/complete` and `/stream` |
| Create | `llm-gateway/app/budget.py` | Redis-backed token budget tracker |
| Modify | `orchestrator/app/config.py` | Add `NOVA_DEMO`, `DEMO_EXPIRES_AT` settings |
| Modify | `orchestrator/app/router.py` | Add `/api/v1/demo/status` endpoint + block write operations after expiry |
| Modify | `dashboard/src/api.ts` | Add `fetchDemoStatus()` helper |
| Create | `dashboard/src/hooks/useDemoMode.ts` | React hook: polls demo status, provides `isDemo`, `timeRemaining`, `frozen`, `budgetRemaining` |
| Create | `dashboard/src/components/demo/DemoOnboarding.tsx` | Dismissible onboarding overlay |
| Create | `dashboard/src/components/demo/DemoBanner.tsx` | Countdown timer, demo badge, freeze/limit banners |
| Modify | `dashboard/src/components/layout/Sidebar.tsx` | Hide demo-disabled nav items when `isDemo` |
| Modify | `dashboard/src/pages/Settings.tsx` | Hide dangerous sections when `isDemo` |
| Modify | `dashboard/src/pages/chat/ChatInput.tsx` | Disable input when frozen or budget exhausted |
| Modify | `dashboard/src/App.tsx` | Mount DemoOnboarding and DemoBanner |
| Create | `tests/test_demo_mode.py` | Integration tests for budget, expiry, freeze |

### Component B: Demo Provisioner

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `demo-provisioner/` | New service directory |
| Create | `demo-provisioner/app/main.py` | FastAPI app, lifespan (startup reconciliation) |
| Create | `demo-provisioner/app/config.py` | Pydantic settings (capacity, rate limits, LLM keys) |
| Create | `demo-provisioner/app/provisioner.py` | Create/destroy demo instances via Docker Compose |
| Create | `demo-provisioner/app/reaper.py` | Background task: TTL enforcement, orphan cleanup |
| Create | `demo-provisioner/app/router.py` | API endpoints: POST/GET demos |
| Create | `demo-provisioner/app/rate_limiter.py` | Redis-backed IP rate limiting |
| Create | `demo-provisioner/Dockerfile` | Container image |
| Create | `demo-provisioner/requirements.txt` | Dependencies |
| Create | `docker-compose.demo.yml` | Slimmed Nova compose for demo instances |
| Create | `docker-compose.demo-host.yml` | Traefik + provisioner compose for the demo VPS |
| Create | `scripts/demo-seed.sql` | Pre-seeded demo data |

### Component C: Infrastructure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `infra/demo/setup.sh` | VPS bootstrap: Docker, pre-pull images, create traefik-public network |
| Create | `infra/demo/traefik.yml` | Traefik static config (Docker provider, Let's Encrypt DNS-01) |

---

## Task 1: LLM Gateway — Demo Config & Budget Tracker

**Files:**
- Modify: `llm-gateway/app/config.py:51-155`
- Create: `llm-gateway/app/budget.py`
- Create: `tests/test_demo_mode.py`

- [ ] **Step 1: Add demo settings to gateway config**

In `llm-gateway/app/config.py`, add to the `Settings` class:

```python
nova_demo: bool = False
demo_token_budget: int = 150_000
```

- [ ] **Step 2: Write the budget tracker module**

Create `llm-gateway/app/budget.py`.

Note: llm-gateway has no shared Redis client module. Each file manages its own connection (see `rate_limiter.py`, `response_cache.py`). Follow the same pattern here.

```python
"""Redis-backed token budget tracker for demo mode."""
import redis.asyncio as redis
from app.config import settings

BUDGET_KEY = "demo:budget:used"

_redis: redis.Redis | None = None

async def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis

async def get_budget_status() -> dict:
    """Return current budget usage."""
    if not settings.nova_demo:
        return {"demo": False}
    r = await _get_redis()
    used = int(await r.get(BUDGET_KEY) or 0)
    budget = settings.demo_token_budget
    return {
        "demo": True,
        "budget_total": budget,
        "budget_used": used,
        "budget_remaining": max(0, budget - used),
        "budget_exhausted": used >= budget,
    }

async def record_usage(input_tokens: int, output_tokens: int) -> bool:
    """Record token usage. Returns True if still within budget."""
    if not settings.nova_demo:
        return True
    r = await _get_redis()
    used = await r.incrby(BUDGET_KEY, input_tokens + output_tokens)
    return used < settings.demo_token_budget

async def check_budget() -> bool:
    """Check if budget is exhausted. Returns True if OK to proceed."""
    if not settings.nova_demo:
        return True
    r = await _get_redis()
    used = int(await r.get(BUDGET_KEY) or 0)
    return used < settings.demo_token_budget
```

- [ ] **Step 3: Write failing test for budget enforcement**

Create `tests/test_demo_mode.py`.

**Important:** Helper functions `_is_demo_mode()` and `_is_demo_expired()` must be defined at the TOP of the file, before any test class that references them in `@pytest.mark.skipif` decorators (evaluated at import time).

```python
"""Integration tests for demo mode features."""
import pytest
import httpx

BASE = "http://localhost:8001"
ORCH_BASE = "http://localhost:8000"

def _is_demo_mode():
    """Check if gateway is running in demo mode."""
    try:
        r = httpx.get(f"{BASE}/demo/budget", timeout=5)
        return r.status_code == 200 and r.json().get("demo", False)
    except Exception:
        return False

def _is_demo_expired():
    """Check if demo is in frozen state."""
    try:
        r = httpx.get(f"{ORCH_BASE}/api/v1/demo/status", timeout=5)
        return r.status_code == 200 and r.json().get("frozen", False)
    except Exception:
        return False

@pytest.fixture
def client():
    return httpx.AsyncClient(base_url=BASE, timeout=30)

class TestDemoBudget:
    """These tests only run when gateway is started with NOVA_DEMO=true."""

    @pytest.mark.skipif(
        not _is_demo_mode(),
        reason="Gateway not in demo mode"
    )
    @pytest.mark.asyncio
    async def test_complete_returns_budget_status(self, client):
        """Budget metadata should appear in demo mode responses."""
        resp = await client.post("/complete", json={
            "messages": [{"role": "user", "content": "say hello"}],
            "model": "auto",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "demo_budget" in data

    @pytest.mark.asyncio
    async def test_budget_status_endpoint(self, client):
        """Gateway should expose budget status."""
        resp = await client.get("/demo/budget")
        assert resp.status_code == 200
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_demo_mode.py -v`
Expected: FAIL (endpoint doesn't exist yet, demo mode not active)

- [ ] **Step 5: Wire budget enforcement into /complete and /stream**

In `llm-gateway/app/router.py`, add budget check before LLM call and usage recording after:

At the top of the `/complete` handler (~line 74):
```python
from app.budget import check_budget, record_usage, get_budget_status

# Inside the handler, before the LLM call:
if not await check_budget():
    raise HTTPException(
        status_code=429,
        detail={"error": "demo_limit_reached", "message": "Demo token budget exhausted."}
    )
```

After the LLM response is received (~line 108):
```python
await record_usage(response.input_tokens or 0, response.output_tokens or 0)
```

For `/stream`: add budget check before the `generate()` call. For usage recording, modify the `generate()` async generator to accumulate token counts from the provider's chunks, then call `record_usage()` after the loop ends (before yielding `data: [DONE]`). Also emit a Nova-specific SSE metadata event with the usage totals: `data: {"event":"usage","input_tokens":N,"output_tokens":N}\n\n` before `[DONE]` — the dashboard's `useDemoMode` hook can read this to update budget display in real time.

Add budget status endpoint:
```python
@router.get("/demo/budget")
async def demo_budget():
    return await get_budget_status()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_demo_mode.py::TestDemoBudget::test_budget_status_endpoint -v`
Expected: PASS (endpoint exists, returns budget info)

- [ ] **Step 7: Commit**

```bash
git add llm-gateway/app/config.py llm-gateway/app/budget.py llm-gateway/app/router.py tests/test_demo_mode.py
git commit -m "feat(llm-gateway): add demo mode budget tracking and enforcement"
```

---

## Task 2: Orchestrator — Demo Status & Write Blocking

**Files:**
- Modify: `orchestrator/app/config.py:5-100`
- Modify: `orchestrator/app/router.py:196-228` (demo status endpoint + write blocking)
- Modify: `tests/test_demo_mode.py`

**Note:** The demo status endpoint goes in `router.py` (not `health.py`), because `health_router` has a `/health` prefix which would produce `/health/api/v1/demo/status`. The main `router` in `router.py` has no prefix, giving the correct `/api/v1/demo/status` path.

- [ ] **Step 1: Add demo settings to orchestrator config**

In `orchestrator/app/config.py`, add to the `Settings` class:

```python
nova_demo: bool = False
demo_expires_at: str = ""  # ISO 8601 timestamp, empty if not a demo
```

- [ ] **Step 2: Write failing test for demo status endpoint**

Append to `tests/test_demo_mode.py` (helpers `_is_demo_mode()`, `_is_demo_expired()`, and `ORCH_BASE` are already defined at the top of the file from Task 1):

```python
class TestDemoStatus:
    @pytest.mark.asyncio
    async def test_demo_status_endpoint_exists(self):
        async with httpx.AsyncClient(base_url=ORCH_BASE, timeout=10) as client:
            resp = await client.get("/api/v1/demo/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "demo" in data

class TestDemoWriteBlock:
    """Verify that orchestrator blocks writes after demo expiry."""

    @pytest.mark.skipif(
        not _is_demo_expired(),
        reason="Demo not expired — run with DEMO_EXPIRES_AT in the past to test"
    )
    @pytest.mark.asyncio
    async def test_task_creation_blocked_when_expired(self):
        async with httpx.AsyncClient(base_url=ORCH_BASE, timeout=10) as client:
            resp = await client.post("/api/v1/tasks", json={
                "input": "nova-test-demo-blocked",
            })
            assert resp.status_code == 403
            assert "demo" in resp.json().get("detail", "").lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_demo_mode.py::TestDemoStatus -v`
Expected: FAIL (endpoint doesn't exist)

- [ ] **Step 4: Add demo status endpoint**

In `orchestrator/app/router.py`, add:

```python
from datetime import datetime, timezone
from app.config import settings

@router.get("/api/v1/demo/status")
async def demo_status():
    if not settings.nova_demo:
        return {"demo": False}

    expires_at = None
    frozen = False
    if settings.demo_expires_at:
        expires_at = datetime.fromisoformat(settings.demo_expires_at)
        frozen = datetime.now(timezone.utc) >= expires_at

    # Fetch budget from gateway
    budget_remaining = None
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{settings.llm_gateway_url}/demo/budget")
            if r.status_code == 200:
                budget_remaining = r.json().get("budget_remaining")
    except Exception:
        pass

    return {
        "demo": True,
        "expires_at": settings.demo_expires_at or None,
        "frozen": frozen,
        "budget_remaining": budget_remaining,
    }
```

- [ ] **Step 5: Add write-block guard to task creation**

In `orchestrator/app/router.py`, add a guard at the top of `submit_task()` (~line 196):

```python
from datetime import datetime, timezone

async def _check_demo_allowed():
    """Raise 403 if demo is expired."""
    if not settings.nova_demo or not settings.demo_expires_at:
        return
    # TODO: also check Redis key demo:expires_at (db2) for runtime session
    # extension support. See spec forward-compat note — env var is baked at
    # container start; Redis override enables future "extend 30 min" CTA.
    expires_at = datetime.fromisoformat(settings.demo_expires_at)
    if datetime.now(timezone.utc) >= expires_at:
        raise HTTPException(
            status_code=403,
            detail="Demo session expired. Start a new demo at arialabs.ai"
        )
```

Call `await _check_demo_allowed()` at the top of:
- `submit_task()` (POST /api/v1/tasks)
- `stream_task()` (POST /api/v1/tasks/stream)
- Any goal creation endpoints

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_demo_mode.py::TestDemoStatus -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add orchestrator/app/config.py orchestrator/app/router.py tests/test_demo_mode.py
git commit -m "feat(orchestrator): add demo status endpoint and write-block on expiry"
```

---

## Task 3: Dashboard — Demo Mode Hook & API

**Files:**
- Modify: `dashboard/src/api.ts`
- Create: `dashboard/src/hooks/useDemoMode.ts`

- [ ] **Step 1: Add demo status API call**

In `dashboard/src/api.ts`, add:

```typescript
export interface DemoStatus {
  demo: boolean;
  expires_at: string | null;
  frozen: boolean;
  budget_remaining: number | null;
}

export async function fetchDemoStatus(): Promise<DemoStatus> {
  return apiFetch<DemoStatus>('/api/v1/demo/status');
}
```

- [ ] **Step 2: Create useDemoMode hook**

Create `dashboard/src/hooks/useDemoMode.ts`:

```typescript
import { useQuery } from '@tanstack/react-query';
import { fetchDemoStatus, type DemoStatus } from '../api';

export function useDemoMode() {
  const { data } = useQuery({
    queryKey: ['demo-status'],
    queryFn: fetchDemoStatus,
    refetchInterval: 10_000, // poll every 10s for countdown
    staleTime: 5_000,
  });

  const isDemo = data?.demo ?? false;
  const frozen = data?.frozen ?? false;
  const budgetRemaining = data?.budget_remaining ?? null;
  const budgetExhausted = budgetRemaining !== null && budgetRemaining <= 0;

  let timeRemaining: number | null = null;
  if (data?.expires_at) {
    const expiresMs = new Date(data.expires_at).getTime();
    timeRemaining = Math.max(0, expiresMs - Date.now());
  }

  return {
    isDemo,
    frozen,
    budgetRemaining,
    budgetExhausted,
    timeRemaining,
    expiresAt: data?.expires_at ?? null,
  };
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd dashboard && npm run build`
Expected: PASS (no type errors)

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/api.ts dashboard/src/hooks/useDemoMode.ts
git commit -m "feat(dashboard): add useDemoMode hook and demo status API"
```

---

## Task 4: Dashboard — Demo Onboarding Overlay

**Files:**
- Create: `dashboard/src/components/demo/DemoOnboarding.tsx`
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Create onboarding overlay component**

Create `dashboard/src/components/demo/DemoOnboarding.tsx`:

A full-screen dismissible overlay shown on first load in demo mode. Content:
- "Welcome to Nova" heading
- 3-4 bullet points: what Nova is, what makes it different (pipeline, memory, autonomous goals), what to try
- "Got it, let me explore" dismiss button
- Dismiss state saved to `localStorage` key `demo-onboarding-dismissed`

Use existing Tailwind patterns from the codebase (stone/teal palette, Lucide icons).

- [ ] **Step 2: Mount in App.tsx**

Import `useDemoMode` and `DemoOnboarding` in `App.tsx`. Render `<DemoOnboarding />` when `isDemo` is true.

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/demo/DemoOnboarding.tsx dashboard/src/App.tsx
git commit -m "feat(dashboard): add demo onboarding overlay"
```

---

## Task 5: Dashboard — Demo Banner (Countdown, Badge, Freeze)

**Files:**
- Create: `dashboard/src/components/demo/DemoBanner.tsx`
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Create demo banner component**

Create `dashboard/src/components/demo/DemoBanner.tsx`:

A sticky top banner (below the main header) with three states:

**Active state:**
- Small "DEMO" badge on the left
- Countdown timer on the right: "42:17 remaining"
- "?" button to reopen onboarding
- Subtle background (stone-800 with teal accent border)

**Budget exhausted state:**
- Yellow/amber banner: "Demo token limit reached"
- CTAs: "Start new demo" | "Self-host Nova" | "GitHub"

**Frozen state:**
- Full-width banner: "Your demo has ended — browse your results for the next 30 minutes"
- CTAs: "Start new demo" | "Self-host Nova" | "GitHub"

Uses `useDemoMode()` hook for all state. Countdown updates every second via `useEffect` + `setInterval` using the `timeRemaining` value.

- [ ] **Step 2: Mount in App.tsx**

Render `<DemoBanner />` when `isDemo` is true, positioned above the main content area.

- [ ] **Step 3: Verify build**

Run: `cd dashboard && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/demo/DemoBanner.tsx dashboard/src/App.tsx
git commit -m "feat(dashboard): add demo countdown banner with freeze and budget states"
```

---

## Task 6: Dashboard — Hide Disabled Features in Demo Mode

**Files:**
- Modify: `dashboard/src/components/layout/Sidebar.tsx`
- Modify: `dashboard/src/pages/Settings.tsx`

- [ ] **Step 1: Hide dangerous nav items in demo mode**

In `Sidebar.tsx`, import `useDemoMode` and filter out nav items when `isDemo`:
- Remote Access
- Recovery
- Users / Keys (admin pages)

Follow the existing conditional rendering pattern (see how `isAuthenticated` already gates items in Settings.tsx ~line 185).

- [ ] **Step 2: Hide dangerous settings sections**

In `Settings.tsx`, gate sections behind `!isDemo`:
- API Keys section
- Remote Access section
- Auth / User Management section
- Recovery / Factory Reset section

- [ ] **Step 3: Disable chat input when frozen or budget exhausted**

In `dashboard/src/pages/chat/ChatInput.tsx`, import `useDemoMode()` — disable the input and show a message when `frozen` or `budgetExhausted`.

- [ ] **Step 4: Verify build**

Run: `cd dashboard && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/layout/Sidebar.tsx dashboard/src/pages/Settings.tsx dashboard/src/pages/chat/ChatInput.tsx
git commit -m "feat(dashboard): hide admin features and disable inputs in demo mode"
```

---

## Task 7: Demo Docker Compose File

**Files:**
- Create: `docker-compose.demo.yml`

- [ ] **Step 1: Create slimmed demo compose**

Create `docker-compose.demo.yml` — a standalone compose file (not an overlay) with only the essential services:

```yaml
# docker-compose.demo.yml
# Slimmed Nova stack for ephemeral demo instances.
# All services use expose: (no ports:) — Traefik routes via Docker labels.
# Usage: COMPOSE_PROJECT_NAME=demo-xxxx docker compose -f docker-compose.demo.yml up -d

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: nova
      POSTGRES_USER: nova
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    expose:
      - "5432"
    volumes:
      - demo-pgdata:/var/lib/postgresql/data
    deploy:
      resources:
        limits:
          memory: 256M
    networks:
      - internal

  redis:
    image: redis:7-alpine
    expose:
      - "6379"
    deploy:
      resources:
        limits:
          memory: 128M
    networks:
      - internal

  llm-gateway:
    image: nova-llm-gateway:latest
    env_file: .env
    expose:
      - "8001"
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"
    networks:
      - internal

  memory-service:
    image: nova-memory-service:latest
    env_file: .env
    expose:
      - "8002"
    depends_on:
      - postgres
      - redis
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"
    networks:
      - internal

  orchestrator:
    image: nova-orchestrator:latest
    env_file: .env
    expose:
      - "8000"
    depends_on:
      - postgres
      - redis
      - llm-gateway
      - memory-service
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"
    networks:
      - internal

  chat-api:
    image: nova-chat-api:latest
    env_file: .env
    expose:
      - "8080"
    depends_on:
      - orchestrator
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"
    networks:
      - internal

  dashboard:
    image: nova-dashboard:latest
    env_file: .env
    expose:
      - "3000"
    depends_on:
      - orchestrator
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.${COMPOSE_PROJECT_NAME}.rule=Host(`${COMPOSE_PROJECT_NAME}.demo.arialabs.ai`)"
      - "traefik.http.routers.${COMPOSE_PROJECT_NAME}.tls=true"
      - "traefik.http.routers.${COMPOSE_PROJECT_NAME}.tls.certresolver=letsencrypt"
      - "traefik.http.services.${COMPOSE_PROJECT_NAME}.loadbalancer.server.port=3000"
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "0.25"
    networks:
      - internal
      - traefik-public

volumes:
  demo-pgdata:

networks:
  internal:
    driver: bridge
  traefik-public:
    external: true
```

- [ ] **Step 2: Verify compose parses**

Run: `COMPOSE_PROJECT_NAME=demo-test docker compose -f docker-compose.demo.yml config --quiet`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add docker-compose.demo.yml
git commit -m "feat: add slimmed docker-compose.demo.yml for ephemeral demo instances"
```

---

## Task 8: Demo Seed Data

**Files:**
- Create: `scripts/demo-seed.sql`

- [ ] **Step 1: Curate demo data in a running Nova instance**

Start a local Nova instance (`make dev`). Interactively create the demo content:

- Chat with Nova to produce 3-5 engrams (different node types: fact, entity, self_model)
- Submit a goal and let the pipeline run to completion (produces task history + agent sessions)
- Verify the Brain page shows a small connected graph

This is manual curation, not scripted — the point is to produce realistic demo data.

- [ ] **Step 2: Dump the curated data to seed file**

```bash
docker compose exec -T postgres pg_dump -U nova --data-only \
  -t engrams -t engram_edges -t sources -t tasks -t agent_sessions \
  -t conversations -t conversation_messages \
  nova > scripts/demo-seed.sql
```

Wrap all INSERTs in `BEGIN; ... COMMIT;` and add `ON CONFLICT DO NOTHING` or make idempotent.

- [ ] **Step 3: Test seed loads against a fresh DB**

Reset local DB, restart services, then load the seed:
```bash
docker compose exec -T postgres psql -U nova nova < scripts/demo-seed.sql
```
Expected: Rows inserted, no errors. Verify engrams and tasks exist via dashboard.

- [ ] **Step 3: Commit**

```bash
git add scripts/demo-seed.sql
git commit -m "feat: add demo seed data for pre-populated demo instances"
```

---

## Task 9: Demo Provisioner — Core Service

**Files:**
- Create: `demo-provisioner/app/main.py`
- Create: `demo-provisioner/app/config.py`
- Create: `demo-provisioner/app/provisioner.py`
- Create: `demo-provisioner/app/reaper.py`
- Create: `demo-provisioner/app/router.py`
- Create: `demo-provisioner/app/rate_limiter.py`
- Create: `demo-provisioner/Dockerfile`
- Create: `demo-provisioner/requirements.txt`

This is the largest task. Break into sub-steps:

- [ ] **Step 1: Scaffold provisioner project**

Create `demo-provisioner/requirements.txt`:
```
fastapi>=0.111
uvicorn[standard]>=0.29
redis>=5.0
pydantic-settings>=2.0
httpx>=0.27
python-dotenv>=1.0
```

Create `demo-provisioner/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
```

- [ ] **Step 2: Write config.py**

Create `demo-provisioner/app/config.py`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    admin_secret: str = "change-me"
    max_concurrent_demos: int = 8
    demo_ttl_minutes: int = 60
    freeze_minutes: int = 30
    rate_limit_per_ip: int = 3
    rate_limit_window_minutes: int = 60
    min_free_disk_gb: int = 10
    nova_template_dir: str = "/opt/nova"
    demos_dir: str = "/opt/nova-demos"
    redis_url: str = "redis://localhost:6379/0"
    demo_domain: str = "demo.arialabs.ai"

    # LLM keys passed through to demo instances
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # Demo instance config
    demo_chat_model: str = "haiku"
    demo_token_budget: int = 150_000

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
```

- [ ] **Step 3: Write rate_limiter.py**

Create `demo-provisioner/app/rate_limiter.py`:

Redis-backed sliding window rate limiter. Key: `ratelimit:{ip}`. Uses sorted sets with timestamp scores. Check + record in one call. Returns `(allowed: bool, remaining: int, retry_after: int)`.

- [ ] **Step 4: Write provisioner.py**

Create `demo-provisioner/app/provisioner.py`:

Core functions:
- `create_demo(ip: str) -> DemoInstance` — generate ID, check capacity/disk/rate, create working dir, write .env, copy compose + `demo-seed.sql`, run `docker compose up -d`, poll health, then load seed data via `docker compose exec -T postgres psql -U nova nova < demo-seed.sql`. Return instance metadata.
- `destroy_demo(demo_id: str)` — `docker compose down -v`, remove working dir with verification/retry
- `get_demo_status(demo_id: str) -> str` — check container health, expiry state
- `list_demos() -> list[DemoInstance]` — scan demos dir, return all with status
- `reconcile()` — startup pass: find and reap orphaned instances

The `.env` template written per instance includes:
```
NOVA_DEMO=true
DEMO_TOKEN_BUDGET={budget}
DEMO_EXPIRES_AT={iso_timestamp}
DEFAULT_CHAT_MODEL={model}
COMPOSE_PROJECT_NAME={demo_id}
REQUIRE_AUTH=false
LLM_ROUTING_STRATEGY=cloud-only
POSTGRES_PASSWORD={random}
ANTHROPIC_API_KEY={from provisioner env}
...
```

- [ ] **Step 5: Write reaper.py**

Create `demo-provisioner/app/reaper.py`:

Background `asyncio.Task` that runs every 60 seconds:
- Scan all demo directories
- Parse `DEMO_EXPIRES_AT` from each `.env`
- If `now > expires_at + freeze_minutes`: call `destroy_demo()`
- If status is `provisioning` for >5 min: call `destroy_demo()`
- Check disk: if free disk < threshold, block new provisioning (set a flag)

- [ ] **Step 6: Write router.py**

Create `demo-provisioner/app/router.py`:

```python
@router.post("/api/v1/demos", status_code=202)
async def create_demo(request: Request):
    """Create a new demo instance. Returns 202 immediately."""
    ip = request.client.host
    # Rate limit, capacity, disk checks
    # Kick off provisioning in background task
    # Return { id, url, status: "provisioning", expires_at }

@router.get("/api/v1/demos/{demo_id}/status")
async def demo_status(demo_id: str):
    """Poll instance state."""
    # Return { id, status, url, expires_at }

@router.get("/api/v1/demos")
async def list_demos(request: Request):
    """Admin-only: list all active demos."""
    # Check admin secret header
    # Return list of all demos with status and resource info
```

- [ ] **Step 7: Write main.py with lifespan**

Create `demo-provisioner/app/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.provisioner import reconcile
from app.reaper import start_reaper, stop_reaper

@asynccontextmanager
async def lifespan(app: FastAPI):
    await reconcile()  # Clean up orphans from prior crash
    await start_reaper()
    yield
    await stop_reaper()

app = FastAPI(title="Nova Demo Provisioner", lifespan=lifespan)
# Mount router
```

- [ ] **Step 8: Verify provisioner builds**

Run: `cd demo-provisioner && docker build -t nova-demo-provisioner .`
Expected: Image builds successfully

- [ ] **Step 9: Commit**

```bash
git add demo-provisioner/
git commit -m "feat: add demo provisioner service for ephemeral Nova instances"
```

---

## Task 10: Demo Host Infrastructure

**Files:**
- Create: `docker-compose.demo-host.yml`
- Create: `infra/demo/traefik.yml`
- Create: `infra/demo/setup.sh`

- [ ] **Step 1: Create Traefik config**

Create `infra/demo/traefik.yml`:

```yaml
api:
  dashboard: false

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
  websecure:
    address: ":443"

providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false
    network: traefik-public

certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@arialabs.ai
      storage: /letsencrypt/acme.json
      dnsChallenge:
        provider: cloudflare
        resolvers:
          - "1.1.1.1:53"
```

- [ ] **Step 2: Create demo host compose**

Create `docker-compose.demo-host.yml` — runs on the demo VPS:

```yaml
services:
  traefik:
    image: traefik:v3.0
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./infra/demo/traefik.yml:/etc/traefik/traefik.yml:ro
      - letsencrypt:/letsencrypt
    environment:
      CF_DNS_API_TOKEN: ${CF_DNS_API_TOKEN}
    networks:
      - traefik-public
    restart: unless-stopped

  provisioner:
    build: ./demo-provisioner
    env_file: .env.demo
    ports:
      - "9000:9000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/nova-demos:/opt/nova-demos
    depends_on:
      - traefik
      - redis
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.provisioner.rule=Host(`demo.arialabs.ai`)"
      - "traefik.http.routers.provisioner.tls=true"
      - "traefik.http.routers.provisioner.tls.certresolver=letsencrypt"
      - "traefik.http.services.provisioner.loadbalancer.server.port=9000"
    networks:
      - traefik-public
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    networks:
      - traefik-public
    restart: unless-stopped

volumes:
  letsencrypt:
  redis-data:

networks:
  traefik-public:
    external: true
```

- [ ] **Step 3: Create VPS setup script**

Create `infra/demo/setup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== Nova Demo Host Setup ==="

# Install Docker
curl -fsSL https://get.docker.com | sh

# Create shared network
docker network create traefik-public 2>/dev/null || true

# Create demos directory
mkdir -p /opt/nova-demos

# Pre-pull Nova images
echo "Pre-pulling Nova images..."
docker compose -f docker-compose.demo.yml pull 2>/dev/null || echo "Build images first with: docker compose build"

echo "=== Setup complete ==="
echo "Next: create .env.demo with CF_DNS_API_TOKEN and LLM API keys, then:"
echo "  docker compose -f docker-compose.demo-host.yml up -d"
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.demo-host.yml infra/demo/
git commit -m "feat: add demo host infrastructure (Traefik + provisioner compose + VPS setup)"
```

---

## Task 11: Website — "Try Nova Free" Button & Interstitial

**Files:**
- Modify: `website/src/pages/index.astro` (hero CTA)
- Create: `website/src/pages/try.astro` (interstitial page)

- [ ] **Step 1: Add "Try Nova Free" CTA to hero**

In `website/src/pages/index.astro`, add a second CTA button alongside "Explore Nova":

```html
<a href="/try" class="...">Try Nova Free</a>
```

Style it as the primary CTA (teal/filled), make "Explore Nova" secondary.

- [ ] **Step 2: Create try.astro interstitial page**

Create `website/src/pages/try.astro`:

A simple page that:
1. On load, POSTs to `https://demo.arialabs.ai/api/v1/demos`
2. Shows "Spinning up your own Nova instance..." with a spinner
3. Polls `GET /api/v1/demos/{id}/status` every 2 seconds
4. When status is `ready`, redirects to the demo URL
5. Error states:
   - 503 (capacity): "All demo slots are taken. Try again in a few minutes." + retry
   - 429 (rate limit): "You've started a few demos recently. Try again in an hour."
   - Timeout (>90s): "Something went wrong. Try again." + retry

Vanilla JS — no framework needed, it's a one-page interstitial.

- [ ] **Step 3: Verify site builds**

Run: `cd website && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add website/src/pages/index.astro website/src/pages/try.astro
git commit -m "feat(website): add 'Try Nova Free' hero CTA and provisioning interstitial"
```

---

## Task 12: Integration Testing — Full Demo Lifecycle

**Files:**
- Modify: `tests/test_demo_mode.py`

- [ ] **Step 1: Add end-to-end demo lifecycle tests**

These tests validate the full flow when Nova is running with `NOVA_DEMO=true`:

```python
class TestDemoLifecycle:
    """End-to-end demo mode behavior.
    Run with NOVA_DEMO=true, DEMO_TOKEN_BUDGET=1000 (low for fast exhaustion),
    DEMO_EXPIRES_AT set to now + 5 minutes.
    """

    @pytest.mark.asyncio
    async def test_demo_status_reports_active(self, client):
        """Fresh demo should report active, not frozen."""
        resp = await client.get(f"{ORCH_BASE}/api/v1/demo/status")
        data = resp.json()
        assert data["demo"] is True
        assert data["frozen"] is False

    @pytest.mark.asyncio
    async def test_gateway_enforces_budget(self, client):
        """After exceeding budget, gateway should return 429."""
        # Send requests until budget is exhausted
        # Verify 429 with demo_limit_reached error

    @pytest.mark.asyncio
    async def test_settings_hidden_in_demo(self, client):
        """Dashboard build should include demo gating logic."""
        # This is validated by the TypeScript build, not an HTTP test
        pass

    @pytest.mark.asyncio
    async def test_task_creation_works_when_active(self, client):
        """Demo should allow task creation before expiry."""
        # Submit a task, verify it's accepted
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_demo_mode.py -v`
Expected: Tests that can run without demo mode are skipped; demo-specific tests pass when demo mode is active.

- [ ] **Step 3: Commit**

```bash
git add tests/test_demo_mode.py
git commit -m "test: add demo mode integration tests"
```

---

## Operational Checklist (post-implementation)

These are not code tasks — they're manual steps to deploy the demo platform:

- [ ] Provision Hetzner VPS (CPX41: 8 vCPU, 32GB RAM, 240GB disk)
- [ ] Run `infra/demo/setup.sh` on the VPS
- [ ] Configure Cloudflare DNS: `demo.arialabs.ai` A record (proxy ON), `*.demo.arialabs.ai` wildcard CNAME (proxy OFF)
- [ ] Create `.env.demo` on VPS with `CF_DNS_API_TOKEN`, LLM API keys (demo-only keys with provider spend caps), `ADMIN_SECRET`
- [ ] Build and push Nova images to the VPS (or build on-host)
- [ ] Start demo host: `docker compose -f docker-compose.demo-host.yml up -d`
- [ ] Test: click "Try Nova Free" on staging site, verify full lifecycle
- [ ] Set up monitoring: uptime check on `demo.arialabs.ai/health`, disk alert at 80%
- [ ] Deploy website with new CTA to production
