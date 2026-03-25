# Knowledge Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a knowledge-worker service that autonomously crawls user-provided URLs (GitHub, portfolios, social media), stores credentials securely, and feeds content into Nova's engram memory system, with a unified Sources dashboard.

**Architecture:** New `knowledge-worker` FastAPI service (port 8120, Redis db8, `--profile knowledge`) with autonomous LLM-guided crawler, GitHub platform extractor, and built-in encrypted credential provider. Shared utilities extracted from intel-worker into `nova-worker-common` package. Orchestrator gets new `/api/v1/knowledge/*` endpoints. Dashboard Intelligence page becomes unified Sources page.

**Tech Stack:** Python 3.12, FastAPI, httpx, asyncio, cryptography (AES-256-GCM + HKDF), BeautifulSoup4, Redis, asyncpg (orchestrator), React/TypeScript/TanStack Query (dashboard), Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-25-knowledge-sources-design.md`

---

## File Map

### New Files

```
nova-worker-common/
├── pyproject.toml                          # Shared package definition (includes cryptography dep)
├── nova_worker_common/
│   ├── __init__.py                         # Package exports
│   ├── http_client.py                      # httpx AsyncClient singleton with retry/backoff + Nova User-Agent
│   ├── queue.py                            # Redis dual-queue push (engram + notification)
│   ├── content_hash.py                     # SHA256 content hashing + dedup
│   ├── url_validator.py                    # SSRF validation (consolidated, includes knowledge-worker in blocklist)
│   ├── rate_limiter.py                     # Per-domain rate limiting
│   └── credentials/
│       ├── __init__.py
│       ├── provider.py                     # CredentialProvider ABC + CredentialHealth
│       └── builtin.py                      # AES-256-GCM envelope encryption (encrypt/decrypt)
├── tests/
│   ├── test_url_validator.py               # SSRF blocklist tests
│   ├── test_content_hash.py                # Deterministic hashing tests
│   └── test_credentials.py                 # Encryption roundtrip, tenant isolation, tamper detection

knowledge-worker/
├── pyproject.toml                          # Service dependencies
├── Dockerfile                              # Python 3.12-slim, pip install nova-worker-common
├── app/
│   ├── main.py                             # FastAPI lifespan, health endpoints
│   ├── config.py                           # Settings via os.getenv()
│   ├── client.py                           # httpx client for orchestrator + llm-gateway
│   ├── scheduler.py                        # Crawl scheduling loop with global concurrency semaphore
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── engine.py                       # Autonomous crawl engine (fetch → score → follow)
│   │   ├── relevance.py                    # LLM relevance scoring with circuit breaker
│   │   ├── content_extractor.py            # HTML → text extraction (BeautifulSoup)
│   │   ├── link_extractor.py              # Link discovery + normalization
│   │   └── robots.py                       # robots.txt fetching and rule checking
│   ├── extractors/
│   │   ├── __init__.py                     # Extractor registry (URL pattern → extractor)
│   │   ├── base.py                         # BaseExtractor ABC
│   │   └── github.py                       # GitHub API extractor
│   ├── credentials/
│   │   ├── __init__.py
│   │   └── health.py                       # Credential health check background task
│   └── queue.py                            # Redis queue helpers (uses nova-worker-common)

orchestrator/app/knowledge_router.py        # /api/v1/knowledge/* endpoints
orchestrator/app/migrations/041_knowledge_schema.sql  # All knowledge tables

dashboard/src/pages/Sources.tsx             # Unified Sources page (replaces Intelligence)
dashboard/src/components/SourceCard.tsx      # Source card component
dashboard/src/components/AddSourceModal.tsx  # Add source flow with platform detection
dashboard/src/components/CredentialManager.tsx # Credential list + add/validate

tests/test_knowledge.py                     # Integration tests
```

### Modified Files

```
intel-worker/app/client.py                  # Replace inline HTTP client with nova-worker-common import
intel-worker/app/queue.py                   # Replace inline queue logic with nova-worker-common import
intel-worker/app/url_validator.py           # Replace with nova-worker-common import (or delete)
intel-worker/app/poller.py                  # Update imports from new locations
intel-worker/app/fetchers/*.py              # Update imports (content_hash)
intel-worker/Dockerfile                     # Add COPY + pip install for nova-worker-common
intel-worker/pyproject.toml                 # Add nova-worker-common dependency

orchestrator/app/intel_router.py            # Add 'knowledge-worker' to BLOCKED_HOSTS
orchestrator/app/router.py                  # Include knowledge_router
orchestrator/Dockerfile                     # Add COPY + pip install for nova-worker-common (credential encryption)

dashboard/src/App.tsx                       # Replace Intelligence route with Sources route
dashboard/src/pages/Goals.tsx               # Add "Suggested" recommendations section
dashboard/src/pages/EngramExplorer.tsx      # Add source attribution stats
dashboard/src/api.ts                        # Add knowledge source + credential API functions
dashboard/src/components/layout/Sidebar.tsx # Replace Intelligence nav item with Sources

docker-compose.yml                          # Add knowledge-worker service entry
.env.example                               # Add CREDENTIAL_MASTER_KEY and knowledge-worker vars
scripts/setup.sh                            # Auto-generate CREDENTIAL_MASTER_KEY
```

---

## Task 1: nova-worker-common — Shared Package

Extract shared utilities from intel-worker into a reusable package. **Includes credential encryption** so both orchestrator and knowledge-worker can encrypt/decrypt credentials without cross-service imports.

**Files:**
- Create: `nova-worker-common/pyproject.toml`
- Create: `nova-worker-common/nova_worker_common/__init__.py`
- Create: `nova-worker-common/nova_worker_common/http_client.py`
- Create: `nova-worker-common/nova_worker_common/queue.py`
- Create: `nova-worker-common/nova_worker_common/content_hash.py`
- Create: `nova-worker-common/nova_worker_common/url_validator.py`
- Create: `nova-worker-common/nova_worker_common/rate_limiter.py`
- Create: `nova-worker-common/nova_worker_common/credentials/__init__.py`
- Create: `nova-worker-common/nova_worker_common/credentials/provider.py`
- Create: `nova-worker-common/nova_worker_common/credentials/builtin.py`
- Create: `nova-worker-common/tests/test_url_validator.py`
- Create: `nova-worker-common/tests/test_content_hash.py`
- Create: `nova-worker-common/tests/test_credentials.py`

**Reference files:**
- Read: `intel-worker/app/client.py` (HTTP client pattern)
- Read: `intel-worker/app/queue.py` (dual-queue pattern)
- Read: `intel-worker/app/url_validator.py` (SSRF validation)
- Read: `orchestrator/app/intel_router.py` (SSRF validation — `_validate_feed_url` function and `BLOCKED_HOSTS`)

- [ ] **Step 1: Create package structure**

Create `nova-worker-common/pyproject.toml`:

```toml
[project]
name = "nova-worker-common"
version = "0.1.0"
description = "Shared utilities for Nova worker services (intel-worker, knowledge-worker, orchestrator)"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "redis>=5.0",
    "cryptography>=44.0",
]

[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-asyncio>=0.24"]

[tool.hatch.build.targets.wheel]
packages = ["nova_worker_common"]
```

Create `nova-worker-common/nova_worker_common/__init__.py` exporting all public functions.

- [ ] **Step 2: Extract URL validator**

Create `nova-worker-common/nova_worker_common/url_validator.py`.

Consolidate SSRF validation from both `intel-worker/app/url_validator.py` and `orchestrator/app/intel_router.py:_validate_feed_url`. The consolidated version must:
- Block all Nova service hostnames: orchestrator, llm-gateway, memory-service, chat-api, chat-bridge, postgres, redis, recovery, cortex, intel-worker, **knowledge-worker**, dashboard
- Block metadata endpoints: metadata.google.internal, host.docker.internal
- Block private IPs (10.x, 172.16-31.x, 192.168.x), loopback (127.x), link-local (169.254.x)
- Block non-http(s) schemes
- Accept an optional `extra_blocked_hosts` parameter for service-specific additions
- Return `None` if URL is safe, error message string if blocked

- [ ] **Step 3: Extract HTTP client**

Create `nova-worker-common/nova_worker_common/http_client.py`.

Extract from `intel-worker/app/client.py`. Provide a factory that creates an httpx.AsyncClient with:
- Configurable base_url and default headers (e.g., X-Admin-Secret)
- Default `User-Agent: Nova/1.0 (knowledge-worker)` header (configurable per service)
- Retry with exponential backoff (configurable max_retries, base_delay)
- Configurable timeout
- Global init/get/close lifecycle pattern matching intel-worker's existing pattern

- [ ] **Step 4: Extract queue helpers**

Create `nova-worker-common/nova_worker_common/queue.py`.

Extract from `intel-worker/app/queue.py`. Provide:
- `push_to_engram_queue(redis, raw_text, source_type, source_id, metadata)` — pushes to `engram:ingestion:queue` on db0
- `push_to_notification_queue(redis, queue_name, data)` — generic push to any Redis list
- Redis connection factory with configurable db number

- [ ] **Step 5: Extract content hashing**

Create `nova-worker-common/nova_worker_common/content_hash.py`.

Extract content hash computation (SHA256 of title+body) used for dedup. Simple utility, pulled from the pattern in intel-worker's fetchers.

- [ ] **Step 6: Create rate limiter**

Create `nova-worker-common/nova_worker_common/rate_limiter.py`.

New utility (not extracted — intel-worker doesn't have this). Async per-domain rate limiter:
- `RateLimiter` class with configurable default rate (1 req/sec)
- Per-domain override capability
- `async with limiter.acquire(domain):` context manager pattern
- Uses asyncio.Semaphore + sleep internally

- [ ] **Step 7: Implement credential provider ABC and built-in encryption**

Create `nova-worker-common/nova_worker_common/credentials/provider.py` — the `CredentialProvider` ABC and `CredentialHealth` dataclass (see Task 4 for interface definition).

Create `nova-worker-common/nova_worker_common/credentials/builtin.py` — the `BuiltinCredentialProvider` with:
- `encrypt(tenant_id: str, plaintext: str) -> bytes` — HKDF-SHA256 tenant subkey derivation, random 256-bit data key, AES-256-GCM encryption. Returns `nonce || encrypted_data_key || encrypted_credential || tag`.
- `decrypt(tenant_id: str, ciphertext: bytes) -> str` — reverse of encrypt.
- Uses `cryptography` library (`AESGCM`, `HKDF`).

This module contains **only the crypto logic** (no DB, no async). Orchestrator and knowledge-worker both import it and handle their own DB persistence.

- [ ] **Step 8: Write unit tests (in nova-worker-common/tests/)**

Create `nova-worker-common/tests/test_url_validator.py`:
- Test blocked hosts, private IPs, valid URLs, scheme validation, extra_blocked_hosts parameter

Create `nova-worker-common/tests/test_content_hash.py`:
- Test deterministic hashing, empty content handling

Create `nova-worker-common/tests/test_credentials.py`:
```python
from nova_worker_common.credentials.builtin import BuiltinCredentialProvider

TEST_MASTER_KEY = "a" * 64  # 32 bytes hex-encoded

class TestBuiltinCredentialProvider:
    def test_encrypt_decrypt_roundtrip(self):
        provider = BuiltinCredentialProvider(master_key_hex=TEST_MASTER_KEY)
        encrypted = provider.encrypt("tenant-1", "ghp_abc123secrettoken")
        decrypted = provider.decrypt("tenant-1", encrypted)
        assert decrypted == "ghp_abc123secrettoken"

    def test_different_tenants_different_ciphertext(self):
        provider = BuiltinCredentialProvider(master_key_hex=TEST_MASTER_KEY)
        enc1 = provider.encrypt("tenant-1", "secret")
        enc2 = provider.encrypt("tenant-2", "secret")
        assert enc1 != enc2

    def test_tampered_ciphertext_raises(self):
        provider = BuiltinCredentialProvider(master_key_hex=TEST_MASTER_KEY)
        encrypted = provider.encrypt("tenant-1", "secret")
        tampered = bytearray(encrypted)
        tampered[20] ^= 0xFF
        with pytest.raises(Exception):
            provider.decrypt("tenant-1", bytes(tampered))

    def test_wrong_tenant_fails(self):
        provider = BuiltinCredentialProvider(master_key_hex=TEST_MASTER_KEY)
        encrypted = provider.encrypt("tenant-1", "secret")
        with pytest.raises(Exception):
            provider.decrypt("tenant-2", encrypted)
```

Run: `cd nova-worker-common && pip install -e ".[test]" && pytest tests/ -v`

- [ ] **Step 9: Commit**

```bash
git add nova-worker-common/
git commit -m "feat: create nova-worker-common shared package with SSRF validator, credentials, and utilities"
```

---

## Task 2: Refactor Intel-Worker to Use nova-worker-common

Update intel-worker to import from the shared package instead of inline utilities.

**Files:**
- Modify: `intel-worker/pyproject.toml` (add nova-worker-common dependency)
- Modify: `intel-worker/Dockerfile` (COPY + install nova-worker-common)
- Modify: `intel-worker/app/client.py` (replace with nova-worker-common import)
- Modify: `intel-worker/app/queue.py` (replace with nova-worker-common import)
- Modify: `intel-worker/app/url_validator.py` (replace with nova-worker-common import or delete + update imports)
- Modify: `intel-worker/app/poller.py` (update imports)
- Modify: `intel-worker/app/fetchers/*.py` (update content_hash imports)

- [ ] **Step 1: Update intel-worker dependencies**

Add to `intel-worker/pyproject.toml`:
```toml
dependencies = [
    # ... existing deps ...
    "nova-worker-common",
]
```

- [ ] **Step 2: Update intel-worker Dockerfile**

The build context is the repo root (`.`), so paths are relative to that. nova-worker-common must be installed BEFORE `RUN pip install .` since intel-worker's pyproject.toml now depends on it. Updated Dockerfile order:

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y curl && apt-get clean
WORKDIR /app
COPY nova-worker-common /nova-worker-common
RUN pip install /nova-worker-common
COPY intel-worker/pyproject.toml .
RUN pip install .
COPY intel-worker/app/ app/
EXPOSE 8110
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8110"]
```

- [ ] **Step 3: Replace intel-worker inline modules**

Update `intel-worker/app/client.py` to re-export from `nova_worker_common.http_client`.
Update `intel-worker/app/queue.py` to re-export from `nova_worker_common.queue`.
Update `intel-worker/app/url_validator.py` to re-export from `nova_worker_common.url_validator`.

Keep the files as thin wrappers (re-exports) so existing imports in poller.py and fetchers don't break. This avoids a mass find-and-replace across all fetcher files.

- [ ] **Step 4: Verify intel-worker still works**

```bash
docker compose build intel-worker
docker compose up -d intel-worker
curl -sf http://localhost:8110/health/ready
```

- [ ] **Step 5: Run existing intel tests**

```bash
cd /home/jeremy/workspace/arialabs/nova && python -m pytest tests/test_intel.py -v
```

All existing intel tests must pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add intel-worker/ nova-worker-common/
git commit -m "refactor: migrate intel-worker to nova-worker-common shared package"
```

---

## Task 3: Database Migration — Knowledge Schema

Create the migration for all knowledge-related tables.

**Files:**
- Create: `orchestrator/app/migrations/041_knowledge_schema.sql`

**Reference:** `orchestrator/app/migrations/038_intel_schema.sql` for conventions.

- [ ] **Step 1: Write the migration**

Create `orchestrator/app/migrations/041_knowledge_schema.sql`:

```sql
-- Migration 041: Knowledge sources schema
-- Supports user-provided personal knowledge sources (GitHub, portfolios, social media)
-- with encrypted credential storage and crawl tracking.

-- Credentials table (must exist before sources, which reference it)
CREATE TABLE IF NOT EXISTS knowledge_credentials (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    provider          TEXT NOT NULL DEFAULT 'builtin'
                      CHECK (provider IN ('builtin', 'vault', 'onepassword', 'bitwarden')),
    label             TEXT NOT NULL,
    encrypted_data    BYTEA,
    external_ref      TEXT,
    key_version       INTEGER NOT NULL DEFAULT 1,
    scopes            JSONB,
    last_validated_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_credentials_tenant
    ON knowledge_credentials(tenant_id);

-- Sources table
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    name                TEXT NOT NULL,
    source_type         TEXT NOT NULL
                        CHECK (source_type IN (
                            'web_crawl', 'github_profile', 'gitlab_profile',
                            'twitter', 'mastodon', 'bluesky', 'reddit_profile',
                            'manual_import'
                        )),
    url                 TEXT NOT NULL,
    scope               TEXT NOT NULL DEFAULT 'personal'
                        CHECK (scope IN ('personal', 'shared')),
    crawl_config        JSONB NOT NULL DEFAULT '{}',
    credential_id       UUID REFERENCES knowledge_credentials(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'paused', 'error', 'restricted')),
    last_crawl_at       TIMESTAMPTZ,
    last_crawl_summary  JSONB,
    error_count         INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_sources_tenant ON knowledge_sources(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_status ON knowledge_sources(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_scope ON knowledge_sources(scope);

-- Crawl log
CREATE TABLE IF NOT EXISTS knowledge_crawl_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    source_id       UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    pages_visited   INTEGER NOT NULL DEFAULT 0,
    pages_skipped   INTEGER NOT NULL DEFAULT 0,
    engrams_created INTEGER NOT NULL DEFAULT 0,
    engrams_updated INTEGER NOT NULL DEFAULT 0,
    llm_calls_made  INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    error_detail    TEXT,
    crawl_tree      JSONB
);

CREATE INDEX IF NOT EXISTS idx_knowledge_crawl_log_source ON knowledge_crawl_log(source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_crawl_log_tenant ON knowledge_crawl_log(tenant_id);

-- Page cache (change detection for re-crawls)
CREATE TABLE IF NOT EXISTS knowledge_page_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    source_id       UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    content_hash    TEXT,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_id, url)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_page_cache_source ON knowledge_page_cache(source_id);

-- Credential audit log
CREATE TABLE IF NOT EXISTS knowledge_credential_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id   UUID NOT NULL REFERENCES knowledge_credentials(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL,
    action          TEXT NOT NULL
                    CHECK (action IN ('retrieve', 'store', 'rotate', 'delete', 'validate')),
    actor           TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    success         BOOLEAN NOT NULL DEFAULT true,
    detail          TEXT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_credential_audit_cred
    ON knowledge_credential_audit(credential_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_credential_audit_tenant
    ON knowledge_credential_audit(tenant_id);
```

- [ ] **Step 2: Verify migration runs**

```bash
docker compose restart orchestrator
docker compose logs orchestrator 2>&1 | grep -i "migration\|041"
```

Orchestrator runs migrations at startup. Verify 041 executes without errors.

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/migrations/041_knowledge_schema.sql
git commit -m "feat: add knowledge sources database schema (migration 041)"
```

---

## Task 4: Knowledge-Worker Credential Health Checks

The crypto (encrypt/decrypt) lives in `nova-worker-common` (Task 1). The DB-backed async operations (store/retrieve/rotate/delete) are handled inline by orchestrator's knowledge_router (Task 6). This task adds the **health check background task** in knowledge-worker that periodically validates stored credentials.

**Files:**
- Create: `knowledge-worker/app/credentials/__init__.py`
- Create: `knowledge-worker/app/credentials/health.py`

- [ ] **Step 1: Create credential health checker**

Create `knowledge-worker/app/credentials/health.py`:

Background task that runs every 6 hours:
1. Fetch all credentials from orchestrator: `GET /api/v1/knowledge/credentials`
2. For each credential with a known platform type (detected from associated sources):
   - GitHub PATs: test `GET https://api.github.com/user` with the token
   - GitLab PATs: test `GET https://gitlab.com/api/v4/user` with the token
   - Generic: skip validation (no way to test arbitrary tokens)
3. Report results back to orchestrator: `PATCH /api/v1/knowledge/credentials/{id}/health`
4. Detect: expired tokens (401), insufficient scopes (403), rate limited (429)
5. Log each validation to the audit table via orchestrator

The orchestrator decrypts the credential using `nova_worker_common.credentials.builtin` before sending to knowledge-worker for validation. Or alternatively, knowledge-worker fetches encrypted credentials and decrypts locally (it has `CREDENTIAL_MASTER_KEY`). The latter avoids sending plaintext over the network — prefer this approach.

- [ ] **Step 2: Wire into main.py lifespan**

Start health check as a background task in knowledge-worker's lifespan. Run on startup (with 60s delay) then every 6 hours.

- [ ] **Step 3: Commit**

```bash
git add knowledge-worker/app/credentials/
git commit -m "feat: add credential health check background task"
```

---

## Task 5: Knowledge-Worker Service Scaffold

Set up the FastAPI service with health endpoints, Docker config, and compose entry.

**Files:**
- Create: `knowledge-worker/pyproject.toml`
- Create: `knowledge-worker/Dockerfile`
- Create: `knowledge-worker/app/__init__.py`
- Create: `knowledge-worker/app/main.py`
- Create: `knowledge-worker/app/config.py`
- Create: `knowledge-worker/app/client.py`
- Create: `knowledge-worker/app/queue.py`
- Modify: `docker-compose.yml` (add knowledge-worker service)
- Modify: `.env.example` (add CREDENTIAL_MASTER_KEY)
- Modify: `scripts/setup.sh` (auto-generate CREDENTIAL_MASTER_KEY)

**Reference:** `intel-worker/` for exact patterns — follow the same structure.

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "knowledge-worker"
version = "0.1.0"
description = "Autonomous knowledge source crawler for Nova AI platform"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "httpx>=0.27",
    "redis>=5.0",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "cryptography>=44.0",
    "nova-worker-common",
]
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y curl && apt-get clean
WORKDIR /app
COPY nova-worker-common /nova-worker-common
RUN pip install /nova-worker-common
COPY knowledge-worker/pyproject.toml .
RUN pip install .
COPY knowledge-worker/app/ app/
EXPOSE 8120
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8120"]
```

- [ ] **Step 3: Create config.py**

Follow intel-worker pattern using `os.getenv()`:

```python
import os

class Settings:
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")
    llm_gateway_url: str = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8001")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/8")
    admin_secret: str = os.getenv("NOVA_ADMIN_SECRET", "")
    credential_master_key: str = os.getenv("CREDENTIAL_MASTER_KEY", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_crawl_pages: int = int(os.getenv("MAX_CRAWL_PAGES", "50"))
    max_llm_calls_per_crawl: int = int(os.getenv("MAX_LLM_CALLS_PER_CRAWL", "60"))
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "300"))
    port: int = int(os.getenv("PORT", "8120"))

settings = Settings()
```

- [ ] **Step 4: Create main.py with lifespan and health endpoints**

Follow intel-worker pattern: lifespan initializes client, Redis, credential provider, scheduler task. Health endpoints at `/health/live` and `/health/ready` (ready checks orchestrator reachability).

- [ ] **Step 5: Create client.py**

HTTP client setup using nova-worker-common. Two clients:
- `orchestrator_client` with X-Admin-Secret header
- `llm_client` for llm-gateway calls (relevance scoring)

Global init/get/close pattern matching intel-worker.

- [ ] **Step 6: Create queue.py**

Thin wrapper around nova-worker-common queue helpers. Configures Redis db8 for knowledge-worker's own state, and db0 for engram ingestion pushes.

- [ ] **Step 7: Add to docker-compose.yml**

Add knowledge-worker service entry after intel-worker. Use `profiles: ["knowledge"]` so it's opt-in. Follow the intel-worker pattern exactly:

```yaml
knowledge-worker:
  <<: *nova-common
  container_name: nova-knowledge-worker
  profiles: ["knowledge"]
  build:
    context: .
    dockerfile: knowledge-worker/Dockerfile
  command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8120", "--reload"]
  develop:
    watch:
      - action: sync
        path: ./knowledge-worker/app
        target: /app/app
        ignore:
          - __pycache__
          - "*.pyc"
  environment:
    ORCHESTRATOR_URL: http://orchestrator:8000
    LLM_GATEWAY_URL: http://llm-gateway:8001
    REDIS_URL: redis://redis:6379/8
    NOVA_ADMIN_SECRET: ${NOVA_ADMIN_SECRET}
    CREDENTIAL_MASTER_KEY: ${CREDENTIAL_MASTER_KEY:-}
    LOG_LEVEL: ${LOG_LEVEL:-INFO}
    MAX_CRAWL_PAGES: ${MAX_CRAWL_PAGES:-50}
    MAX_LLM_CALLS_PER_CRAWL: ${MAX_LLM_CALLS_PER_CRAWL:-60}
  ports:
    - "8120:8120"
  depends_on:
    orchestrator:
      condition: service_healthy
    redis:
      condition: service_healthy
  healthcheck:
    <<: *nova-healthcheck
    test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8120/health/live', timeout=3)"]
```

- [ ] **Step 8: Update .env.example**

Add:
```env
# Knowledge Worker — Master key for credential encryption (auto-generated by setup.sh if blank)
CREDENTIAL_MASTER_KEY=
MAX_CRAWL_PAGES=50
MAX_LLM_CALLS_PER_CRAWL=60
```

- [ ] **Step 9: Update setup.sh**

Add CREDENTIAL_MASTER_KEY auto-generation near the data directory creation section:

```bash
# Generate credential master key if not set
if grep -q "^CREDENTIAL_MASTER_KEY=$" .env 2>/dev/null; then
  CREDENTIAL_MASTER_KEY=$(openssl rand -hex 32)
  sed -i "s/^CREDENTIAL_MASTER_KEY=$/CREDENTIAL_MASTER_KEY=${CREDENTIAL_MASTER_KEY}/" .env
  echo "  Generated CREDENTIAL_MASTER_KEY"
fi
```

- [ ] **Step 10: Build and test health endpoints**

```bash
docker compose --profile knowledge build knowledge-worker
docker compose --profile knowledge up -d knowledge-worker
curl -sf http://localhost:8120/health/live | python3 -m json.tool
curl -sf http://localhost:8120/health/ready | python3 -m json.tool
```

- [ ] **Step 11: Commit**

```bash
git add knowledge-worker/ docker-compose.yml .env.example scripts/setup.sh
git commit -m "feat: scaffold knowledge-worker service with Docker and health endpoints"
```

---

## Task 6: Orchestrator — Knowledge Router

Add CRUD endpoints for knowledge sources and credentials to the orchestrator.

**Files:**
- Create: `orchestrator/app/knowledge_router.py`
- Modify: `orchestrator/app/router.py` (include knowledge_router)
- Modify: `orchestrator/app/intel_router.py` (add knowledge-worker to BLOCKED_HOSTS)
- Modify: `orchestrator/Dockerfile` (add COPY + pip install for nova-worker-common)
- Modify: `orchestrator/pyproject.toml` (add nova-worker-common dependency)

**Reference:** `orchestrator/app/intel_router.py` for endpoint patterns, auth (AdminDep), DB query style.

**Important:** The orchestrator needs `nova-worker-common` installed to use `BuiltinCredentialProvider` for encrypting credentials on storage and the shared `validate_url` for SSRF checking. Update the orchestrator Dockerfile to install it (same pattern as nova-contracts):

```dockerfile
COPY nova-worker-common /nova-worker-common
RUN pip install /nova-worker-common
```

- [ ] **Step 1: Write integration tests for knowledge endpoints**

Add to `tests/test_knowledge.py`:

```python
class TestKnowledgeSources:
    async def test_create_source(self, orchestrator, admin_headers):
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={
                "name": "nova-test-portfolio",
                "url": "https://example.com",
                "source_type": "web_crawl",
            }
        )
        assert resp.status_code == 201
        source = resp.json()
        assert source["name"] == "nova-test-portfolio"
        assert source["status"] == "active"
        # Cleanup
        await orchestrator.delete(
            f"/api/v1/knowledge/sources/{source['id']}",
            headers=admin_headers,
        )

    async def test_list_sources(self, orchestrator, admin_headers):
        resp = await orchestrator.get(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_ssrf_blocked(self, orchestrator, admin_headers):
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={
                "name": "nova-test-ssrf",
                "url": "http://localhost:8000/health",
                "source_type": "web_crawl",
            }
        )
        assert resp.status_code == 400

    async def test_create_credential(self, orchestrator, admin_headers):
        resp = await orchestrator.post(
            "/api/v1/knowledge/credentials",
            headers=admin_headers,
            json={
                "label": "nova-test-github-pat",
                "credential_data": "ghp_test123456789",
            }
        )
        assert resp.status_code == 201
        cred = resp.json()
        assert cred["label"] == "nova-test-github-pat"
        assert "encrypted_data" not in cred  # Never expose ciphertext
        assert "credential_data" not in cred  # Never echo plaintext
        # Cleanup
        await orchestrator.delete(
            f"/api/v1/knowledge/credentials/{cred['id']}",
            headers=admin_headers,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_knowledge.py -v
```

Expected: 404s — endpoints don't exist yet.

- [ ] **Step 3: Create knowledge_router.py**

Implement endpoints in `orchestrator/app/knowledge_router.py`:

**Source endpoints:**
- `GET /api/v1/knowledge/sources` — list sources, filter by tenant_id, scope, status
- `POST /api/v1/knowledge/sources` — create source (SSRF validate URL via `nova_worker_common.url_validator.validate_url`)
- `GET /api/v1/knowledge/sources/{id}` — get source with crawl history
- `PATCH /api/v1/knowledge/sources/{id}` — update source (name, status, crawl_config, credential_id)
- `DELETE /api/v1/knowledge/sources/{id}` — delete source
- `POST /api/v1/knowledge/sources/{id}/crawl` — trigger immediate crawl (push to Redis)

**Credential endpoints:**
- `GET /api/v1/knowledge/credentials` — list credentials (metadata only: id, label, provider, scopes, last_validated_at)
- `POST /api/v1/knowledge/credentials` — store credential (accepts plaintext, encrypts via `nova_worker_common.credentials.builtin.BuiltinCredentialProvider`, stores ciphertext in `knowledge_credentials` table)
- `DELETE /api/v1/knowledge/credentials/{id}` — delete credential + audit log entry
- `POST /api/v1/knowledge/credentials/{id}/validate` — trigger health check

**Import endpoints:**
- `POST /api/v1/knowledge/sources/{id}/paste` — accept raw text, push to engram ingestion queue with source_type='knowledge'

**Stats:**
- `GET /api/v1/knowledge/stats` — source counts by status, total engrams attributed to knowledge sources, last crawl times

**Crawl log endpoints (called by knowledge-worker):**
- `POST /api/v1/knowledge/crawl-log` — store crawl results
- `PATCH /api/v1/knowledge/sources/{id}/status` — update source status after crawl (AdminDep, used by knowledge-worker)

Use the same patterns as intel_router.py: asyncpg queries via `request.app.state.pool`, AdminDep for auth, UUID validation, error handling.

- [ ] **Step 4: Register the router**

In `orchestrator/app/router.py`, add:
```python
from app.knowledge_router import router as knowledge_router
app.include_router(knowledge_router)
```

- [ ] **Step 5: Update BLOCKED_HOSTS in intel_router.py**

Add `"knowledge-worker"` to the `BLOCKED_HOSTS` set in `orchestrator/app/intel_router.py`.

- [ ] **Step 6: Run tests**

```bash
docker compose restart orchestrator
pytest tests/test_knowledge.py -v
```

Expected: All knowledge endpoint tests pass.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/app/knowledge_router.py orchestrator/app/router.py orchestrator/app/intel_router.py tests/test_knowledge.py
git commit -m "feat: add knowledge source and credential CRUD endpoints to orchestrator"
```

---

## Task 7: Autonomous Crawler Engine

Build the core crawling engine with LLM-guided relevance scoring.

**Files:**
- Create: `knowledge-worker/app/crawler/__init__.py`
- Create: `knowledge-worker/app/crawler/engine.py`
- Create: `knowledge-worker/app/crawler/relevance.py`
- Create: `knowledge-worker/app/crawler/content_extractor.py`
- Create: `knowledge-worker/app/crawler/link_extractor.py`
- Create: `knowledge-worker/app/scheduler.py`

- [ ] **Step 1: Create content extractor**

Create `knowledge-worker/app/crawler/content_extractor.py`:
- `extract_text(html: str) -> str` — BeautifulSoup: strip scripts/styles/nav, extract main content text
- `extract_metadata(html: str) -> dict` — title, meta description, og:tags

- [ ] **Step 2: Create link extractor**

Create `knowledge-worker/app/crawler/link_extractor.py`:
- `extract_links(html: str, base_url: str) -> list[str]` — find all `<a href>`, resolve relative URLs against base, deduplicate, filter non-http(s)
- SSRF validate each link via `nova_worker_common.url_validator`

- [ ] **Step 3: Create robots.txt handler**

Create `knowledge-worker/app/crawler/robots.py`:
- `RobotsChecker` class that caches `robots.txt` per domain
- `async fetch_robots(domain: str) -> RobotsRules` — fetch and parse robots.txt, cache for 24h
- `is_allowed(url: str, user_agent: str = "Nova") -> bool` — check if URL is crawlable
- Configurable override list for user's own domains (bypass robots.txt)
- Graceful degradation: if robots.txt fetch fails, allow crawling (log warning)

- [ ] **Step 4: Write unit tests for extractors and robots**

Create `nova-worker-common/tests/test_crawler_utils.py` (or `knowledge-worker/tests/`):
- Content extractor: test script/style stripping, metadata extraction
- Link extractor: test relative URL resolution, dedup, SSRF filtering
- Robots checker: test allow/disallow rules, override list

```bash
pytest knowledge-worker/tests/ -v
```

- [ ] **Step 5: Create relevance scorer**

Create `knowledge-worker/app/crawler/relevance.py`:

- `RelevanceScorer` class with circuit breaker state
- `async score_links(links: list[str], page_content: str, source_context: str) -> list[tuple[str, float]]` — calls llm-gateway `/complete` with a prompt asking the LLM to score each link 0-1 for relevance given the source context. Uses haiku-class model. Returns list of (url, score) tuples.
- Circuit breaker: tracks consecutive failures. After 3 failures, `is_open` returns True and `score_links` returns all links with score 1.0 (follow everything).
- Resets on next successful call.

LLM prompt template:
```
You are evaluating URLs discovered on a personal knowledge source page.
Source context: {source_name} - {source_url}
Page content summary: {first_500_chars}

Score each URL 0.0-1.0 for how likely it contains meaningful information about this person/organization.
1.0 = definitely relevant (project page, repo, portfolio piece)
0.0 = definitely irrelevant (ads, unrelated external site)

URLs to score:
{urls_json}

Return JSON: [{"url": "...", "score": 0.0-1.0}]
```

- [ ] **Step 6: Create crawl engine**

Create `knowledge-worker/app/crawler/engine.py`:

- `CrawlEngine` class
- `async crawl(source: dict) -> CrawlResult` — the main entry point:
  1. Fetch entry URL (check robots.txt first via `RobotsChecker`)
  2. Extract content + links
  3. Score links via RelevanceScorer
  4. BFS loop: fetch high-scoring links (robots.txt checked per URL), extract, score new links, track visited
  5. Check stopping conditions each iteration (diminishing relevance, page cap, LLM call cap, depth limit)
  6. Push all extracted content to engram ingestion queue
  7. Update page cache (content hashes for re-crawl change detection)
  8. Return CrawlResult with stats (pages_visited, pages_skipped, engrams_created, llm_calls_made, crawl_tree)
- `async refresh_crawl(source: dict) -> CrawlResult` — re-crawl variant:
  1. Fetch pages from page_cache for this source
  2. Compare content_hash — skip unchanged
  3. Re-extract changed pages, discover new links
  4. Follow new high-relevance links
  5. Return CrawlResult

Uses `nova_worker_common.rate_limiter` for per-domain throttling.
Uses `nova_worker_common.url_validator` for SSRF on every fetch.
Uses `nova_worker_common.content_hash` for dedup.
Uses `RobotsChecker` for robots.txt compliance.

- [ ] **Step 7: Create scheduler**

Create `knowledge-worker/app/scheduler.py`:

- Global concurrency semaphore: `asyncio.Semaphore(3)` — max 3 concurrent crawls across all sources (spec requirement)
- `run_scheduling_loop()` — async loop that:
  1. Fetches active sources from orchestrator `GET /api/v1/knowledge/sources?status=active`
  2. Checks which sources are due for a crawl (based on last_crawl_at + adaptive interval)
  3. For due sources, acquires the concurrency semaphore, then:
     a. Checks if a platform extractor exists (Task 8) — if so, delegates to it
     b. Otherwise, runs the general crawler engine
  4. Posts crawl results to orchestrator
  5. Sleeps for `poll_interval` seconds

- [ ] **Step 8: Wire into main.py**

Update `knowledge-worker/app/main.py` lifespan to start the scheduling loop as a background task (same pattern as intel-worker's `run_polling_loop`).

- [ ] **Step 9: Test with a real URL**

With services running:
1. Create a knowledge source via orchestrator API pointing to a safe test URL
2. Verify knowledge-worker picks it up and crawls
3. Check engram ingestion queue received content
4. Check crawl log was created

```bash
# Create test source
curl -X POST http://localhost:8000/api/v1/knowledge/sources \
  -H "X-Admin-Secret: $NOVA_ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"name": "nova-test-crawl", "url": "https://example.com", "source_type": "web_crawl"}'

# Check crawl log after a minute
curl http://localhost:8000/api/v1/knowledge/sources -H "X-Admin-Secret: $NOVA_ADMIN_SECRET" | python3 -m json.tool
```

- [ ] **Step 10: Commit**

```bash
git add knowledge-worker/app/crawler/ knowledge-worker/app/scheduler.py
git commit -m "feat: implement autonomous LLM-guided crawler engine with circuit breaker and robots.txt"
```

---

## Task 8: GitHub Platform Extractor

Build the structured GitHub API extractor.

**Files:**
- Create: `knowledge-worker/app/extractors/__init__.py`
- Create: `knowledge-worker/app/extractors/base.py`
- Create: `knowledge-worker/app/extractors/github.py`

- [ ] **Step 1: Create base extractor ABC**

Create `knowledge-worker/app/extractors/base.py`:

```python
from abc import ABC, abstractmethod

class BaseExtractor(ABC):
    @staticmethod
    @abstractmethod
    def matches(url: str) -> bool:
        """Return True if this extractor handles the given URL."""

    @abstractmethod
    async def extract(self, url: str, credential: str | None = None) -> list[dict]:
        """Extract structured content items from the source.
        Returns list of dicts with: title, body, url, author, metadata."""
```

- [ ] **Step 2: Create extractor registry**

Create `knowledge-worker/app/extractors/__init__.py`:

```python
from .github import GitHubExtractor

EXTRACTORS = [GitHubExtractor]

def get_extractor(url: str):
    for ext_cls in EXTRACTORS:
        if ext_cls.matches(url):
            return ext_cls()
    return None
```

- [ ] **Step 3: Implement GitHub extractor**

Create `knowledge-worker/app/extractors/github.py`:

- `GitHubExtractor(BaseExtractor)`
- `matches(url)` — regex for `github.com/{username}` (not a repo URL)
- `extract(url, credential)` — using httpx against GitHub API:
  1. Parse username from URL
  2. `GET /users/{username}` — profile bio, name, company, blog, location
  3. `GET /users/{username}/repos?sort=updated&per_page=100` — all public repos
  4. For each repo: name, description, language, stars, topics
  5. For top 10 repos (by stars or recency): `GET /repos/{owner}/{repo}/readme` — decode base64 README content
  6. `GET /users/{username}/events/public?per_page=30` — recent activity summary
  7. If credential provided, use `Authorization: Bearer {pat}` header (gets private repos too)
  8. Return all extracted content as list of dicts ready for engram ingestion

Rate limit handling: check `X-RateLimit-Remaining` header, back off if low.

- [ ] **Step 4: Wire extractor into scheduler**

Update `knowledge-worker/app/scheduler.py` to check `get_extractor(source.url)` before falling back to the general crawler. If an extractor matches:
1. Retrieve credential if `credential_id` is set
2. Run the extractor
3. Push results to engram ingestion queue
4. Optionally: also run the general crawler to follow outbound links from the profile (e.g., blog URL from GitHub bio)

- [ ] **Step 5: Test with a real GitHub profile**

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/sources \
  -H "X-Admin-Secret: $NOVA_ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"name": "nova-test-github", "url": "https://github.com/octocat", "source_type": "github_profile"}'
```

Verify the extractor pulls profile data, repos, and READMEs.

- [ ] **Step 6: Commit**

```bash
git add knowledge-worker/app/extractors/
git commit -m "feat: add GitHub platform extractor with API-based profile and repo extraction"
```

---

## Task 9: Dashboard — Unified Sources Page

Replace the Intelligence page with a unified Sources page.

**Files:**
- Create: `dashboard/src/pages/Sources.tsx`
- Create: `dashboard/src/components/SourceCard.tsx`
- Create: `dashboard/src/components/AddSourceModal.tsx`
- Create: `dashboard/src/components/CredentialManager.tsx`
- Modify: `dashboard/src/App.tsx` (replace Intelligence route)
- Modify: `dashboard/src/api.ts` (add knowledge API functions)
- Modify: sidebar/nav component (replace Intelligence with Sources)

**Reference:**
- Read: `dashboard/src/pages/Intelligence.tsx` (existing page to replace/merge)
- Read: `dashboard/src/App.tsx` (routing structure)
- Read: `dashboard/src/api.ts` (API call patterns)
- Read: `dashboard/src/components/FeedManagerModal.tsx` (modal pattern for feed management)

- [ ] **Step 1: Add API functions**

Add to `dashboard/src/api.ts`:

```typescript
// Knowledge Sources
export async function getKnowledgeSources(): Promise<KnowledgeSource[]> {
  return apiFetch<KnowledgeSource[]>('/api/v1/knowledge/sources')
}

export async function createKnowledgeSource(data: CreateSourceRequest): Promise<KnowledgeSource> {
  return apiFetch<KnowledgeSource>('/api/v1/knowledge/sources', { method: 'POST', body: JSON.stringify(data) })
}

export async function deleteKnowledgeSource(id: string): Promise<void> {
  await apiFetch(`/api/v1/knowledge/sources/${id}`, { method: 'DELETE' })
}

export async function triggerCrawl(id: string): Promise<void> {
  await apiFetch(`/api/v1/knowledge/sources/${id}/crawl`, { method: 'POST' })
}

export async function pasteContent(id: string, content: string): Promise<void> {
  await apiFetch(`/api/v1/knowledge/sources/${id}/paste`, { method: 'POST', body: JSON.stringify({ content }) })
}

// Credentials
export async function getCredentials(): Promise<Credential[]> {
  return apiFetch<Credential[]>('/api/v1/knowledge/credentials')
}

export async function createCredential(data: CreateCredentialRequest): Promise<Credential> {
  return apiFetch<Credential>('/api/v1/knowledge/credentials', { method: 'POST', body: JSON.stringify(data) })
}

export async function deleteCredential(id: string): Promise<void> {
  await apiFetch(`/api/v1/knowledge/credentials/${id}`, { method: 'DELETE' })
}

export async function getKnowledgeStats(): Promise<KnowledgeStats> {
  return apiFetch<KnowledgeStats>('/api/v1/knowledge/stats')
}
```

Add TypeScript interfaces for `KnowledgeSource`, `Credential`, `KnowledgeStats`, etc.

- [ ] **Step 2: Create SourceCard component**

Create `dashboard/src/components/SourceCard.tsx`:
- Card displaying: source name, URL, source_type icon, status badge (active/paused/error/restricted), last crawl time, engram count
- Actions: pause/resume toggle, trigger crawl button, delete button
- Click expands to show crawl history and page tree
- Follow existing card patterns (stone/teal/amber palette, Lucide icons)

- [ ] **Step 3: Create AddSourceModal component**

Create `dashboard/src/components/AddSourceModal.tsx`:
- URL input field
- Auto-detect platform from URL (show detected type: "Detected: GitHub Profile")
- Name field (auto-populated from URL if possible)
- Optional credential selector (dropdown of existing credentials + "Add new" option)
- Submit triggers create source + initial crawl

- [ ] **Step 4: Create CredentialManager component**

Create `dashboard/src/components/CredentialManager.tsx`:
- List of credentials with: label, provider, health badge (green/yellow/red based on last_validated_at), sources using this credential
- Add credential form: label, credential type dropdown, paste token field
- Delete button per credential
- Validate button per credential

- [ ] **Step 5: Create Sources page**

Create `dashboard/src/pages/Sources.tsx`:

Three tabs:
- **Personal** — user's knowledge sources (query `getKnowledgeSources` with scope=personal). Uses SourceCard. "Add Source" button opens AddSourceModal.
- **Feeds** — existing intel feeds (reuse existing FeedManagerModal and feed components from Intelligence page). Migrate the feed listing from Intelligence.tsx.
- **Shared** — admin-only shared sources (scope=shared)

Top metrics bar: total sources, active crawls, total engrams from knowledge sources, credential health summary.

Credentials section at the bottom (or as a sub-tab): CredentialManager component.

- [ ] **Step 6: Update routing**

In `dashboard/src/App.tsx`:
- Replace the Intelligence page import and route with Sources
- Update the route path (e.g., `/sources` replacing `/intelligence`)

In `dashboard/src/components/layout/Sidebar.tsx`:
- Replace "Intelligence" menu item with "Sources"
- Update the icon (use Lucide `Globe` or `Link` icon)

- [ ] **Step 7: Verify dashboard builds**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

Must compile without TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/
git commit -m "feat(dashboard): add unified Sources page replacing Intelligence"
```

---

## Task 10: Dashboard — Goals Absorbs Recommendations

Move the recommendation feed from the Intelligence page to the Goals page.

**Files:**
- Modify: `dashboard/src/pages/Goals.tsx`

**Reference:** Read `dashboard/src/pages/Goals.tsx` and `dashboard/src/pages/Intelligence.tsx` to understand both pages' current structure.

- [ ] **Step 1: Add "Suggested" section to Goals page**

In `dashboard/src/pages/Goals.tsx`:
- Add a new section/tab: "Suggested" (or "Incoming")
- Query `getIntelRecommendations({ status: 'pending' })` (reuse existing API function)
- Display recommendation cards (reuse or adapt RecommendationCard from Intelligence page)
- Approve action creates a goal (existing behavior) and the new goal appears in the main Goals list
- Dismiss/defer actions work as before

- [ ] **Step 2: Verify Goals page works**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/Goals.tsx
git commit -m "feat(dashboard): move recommendations to Goals page as Suggested section"
```

---

## Task 11: Dashboard — Memory Source Attribution

Add source attribution stats to the Engram Explorer (Memory) page.

**Files:**
- Modify: `dashboard/src/pages/EngramExplorer.tsx`
- Modify: `dashboard/src/api.ts` (if new endpoint needed)

**Reference:** Read `dashboard/src/pages/EngramExplorer.tsx` to understand current structure.

- [ ] **Step 1: Add attribution stats query**

If `GET /api/v1/knowledge/stats` returns engram counts by source, use that. Otherwise, use `GET /api/v1/engrams/stats` (memory-service) which already returns counts by source_type.

- [ ] **Step 2: Add attribution section to Memory page**

Add a section showing: "Where Nova's knowledge comes from"
- Bar chart or stat cards: N engrams from chat, N from intel feeds, N from knowledge sources, N from consolidation
- If knowledge sources exist, break down further: "43 from GitHub, 12 from portfolio site"

- [ ] **Step 3: Verify build**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/
git commit -m "feat(dashboard): add source attribution stats to Memory page"
```

---

## Task 12: Integration Tests

Comprehensive integration tests for the full knowledge sources flow.

**Files:**
- Modify: `tests/test_knowledge.py` (extend from Task 6)
- Modify: `tests/conftest.py` (add knowledge-worker fixtures)

- [ ] **Step 1: Add knowledge-worker fixture to conftest.py**

```python
KNOWLEDGE_WORKER_URL = os.getenv("NOVA_KNOWLEDGE_WORKER_URL", "http://localhost:8120")

@pytest_asyncio.fixture
async def knowledge_worker():
    async with httpx.AsyncClient(base_url=KNOWLEDGE_WORKER_URL, timeout=30) as client:
        yield client
```

- [ ] **Step 2: Add health check test**

```python
class TestKnowledgeWorkerHealth:
    async def test_health_live(self, knowledge_worker):
        resp = await knowledge_worker.get("/health/live")
        assert resp.status_code == 200

    async def test_health_ready(self, knowledge_worker):
        resp = await knowledge_worker.get("/health/ready")
        assert resp.status_code == 200
```

- [ ] **Step 3: Add credential lifecycle test**

```python
class TestCredentialLifecycle:
    async def test_create_validate_delete_credential(self, orchestrator, admin_headers):
        # Create
        resp = await orchestrator.post(
            "/api/v1/knowledge/credentials",
            headers=admin_headers,
            json={"label": "nova-test-cred", "credential_data": "test-token-123"}
        )
        assert resp.status_code == 201
        cred_id = resp.json()["id"]

        # List (should appear, no plaintext)
        resp = await orchestrator.get("/api/v1/knowledge/credentials", headers=admin_headers)
        creds = resp.json()
        test_cred = next(c for c in creds if c["id"] == cred_id)
        assert "encrypted_data" not in test_cred
        assert test_cred["label"] == "nova-test-cred"

        # Delete
        resp = await orchestrator.delete(f"/api/v1/knowledge/credentials/{cred_id}", headers=admin_headers)
        assert resp.status_code == 204
```

- [ ] **Step 4: Add source lifecycle test**

```python
class TestSourceLifecycle:
    async def test_create_list_delete_source(self, orchestrator, admin_headers):
        # Create
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={"name": "nova-test-source", "url": "https://example.com", "source_type": "web_crawl"}
        )
        assert resp.status_code == 201
        source_id = resp.json()["id"]

        # List
        resp = await orchestrator.get("/api/v1/knowledge/sources", headers=admin_headers)
        sources = resp.json()
        assert any(s["id"] == source_id for s in sources)

        # Delete
        resp = await orchestrator.delete(f"/api/v1/knowledge/sources/{source_id}", headers=admin_headers)
        assert resp.status_code == 204

    async def test_manual_paste(self, orchestrator, admin_headers):
        # Create source
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={"name": "nova-test-paste", "url": "https://example.com", "source_type": "manual_import"}
        )
        source_id = resp.json()["id"]

        # Paste content
        resp = await orchestrator.post(
            f"/api/v1/knowledge/sources/{source_id}/paste",
            headers=admin_headers,
            json={"content": "Jeremy is a cloud engineer who builds infrastructure tools."}
        )
        assert resp.status_code == 200

        # Cleanup
        await orchestrator.delete(f"/api/v1/knowledge/sources/{source_id}", headers=admin_headers)
```

- [ ] **Step 5: Add SSRF protection tests**

```python
class TestKnowledgeSSRF:
    @pytest.mark.parametrize("url", [
        "http://localhost:8000/health",
        "http://redis:6379",
        "http://169.254.169.254/latest/meta-data/",
        "http://orchestrator:8000/api/v1/knowledge/sources",
        "http://knowledge-worker:8120/health/live",
        "ftp://example.com/file",
    ])
    async def test_ssrf_blocked(self, orchestrator, admin_headers, url):
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={"name": "nova-test-ssrf", "url": url, "source_type": "web_crawl"}
        )
        assert resp.status_code == 400
```

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/test_knowledge.py -v
```

All tests must pass.

- [ ] **Step 7: Run existing tests to verify no regressions**

```bash
make test
```

Full suite must pass (including existing intel tests).

- [ ] **Step 8: Commit**

```bash
git add tests/
git commit -m "test: add integration tests for knowledge sources, credentials, and SSRF protection"
```

---

## Task 13: Documentation Updates

Update CLAUDE.md and .env.example with knowledge-worker documentation.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.env.example` (already partially done in Task 5)

- [ ] **Step 1: Update CLAUDE.md**

Add knowledge-worker to:
- **Services and ports** section: `knowledge-worker (8120) — ...`
- **Inter-service communication** section: knowledge-worker calls orchestrator, llm-gateway, pushes to Redis db0/db8
- **Redis DB allocation** section: add knowledge-worker=db8
- **Debugging** section: add knowledge-worker health check to the for loop
- **Code-to-docs mapping** section: add knowledge-worker mapping

- [ ] **Step 2: Verify dashboard builds one final time**

```bash
cd /home/jeremy/workspace/arialabs/nova/dashboard && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add knowledge-worker service to CLAUDE.md"
```

---

## Dependency Graph

```
Task 1 (nova-worker-common, includes credential encryption)
    ├── Task 2 (refactor intel-worker) — depends on Task 1
    ├── Task 5 (knowledge-worker scaffold) — depends on Task 1
    │       ├── Task 7 (crawler engine) — depends on Task 5
    │       │       └── Task 8 (GitHub extractor) — depends on Task 7
    │       └── Task 4 (credential health checks) — depends on Task 5
    └── Task 6 (orchestrator router) — depends on Tasks 1 + 3

Task 3 (DB migration) — independent, can run in parallel with Tasks 1-2

Task 9 (dashboard Sources) — depends on Task 6 (needs endpoints)
Task 10 (dashboard Goals) — independent of Tasks 6-9
Task 11 (dashboard Memory) — independent of Tasks 9-10

Task 12 (integration tests) — depends on Tasks 5-8 (services must work)
Task 13 (docs) — last
```

**Parallelization opportunities:**
- Tasks 1 + 3 can run in parallel (shared package + migration are independent)
- Tasks 2 + 5 can run in parallel once Task 1 is done
- Tasks 4 + 7 can run in parallel once Task 5 is done
- Tasks 9 + 10 + 11 can run in parallel (independent dashboard changes)

**Note on migration numbering:** The plan uses migration 041, but check the highest existing migration number at implementation time — another branch may have landed a 041 first.
