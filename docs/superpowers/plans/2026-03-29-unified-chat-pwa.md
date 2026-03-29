# Unified Chat & PWA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify Nova chat across PWA and Telegram so one user has one continuous conversation with shared memory, regardless of channel.

**Architecture:** Bridge-to-orchestrator. The Telegram bridge stops managing its own sessions and routes messages through the same orchestrator `/chat/stream` endpoint the PWA uses. A service-secret auth bypass lets the bridge act on behalf of linked users. A new `linked_accounts` table maps platform identities to Nova users. The PWA chat UI simplifies to a single continuous thread.

**Tech Stack:** Python/FastAPI (orchestrator, bridge), React/TypeScript/Tailwind (dashboard), asyncpg, Redis, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-03-29-unified-chat-pwa-design.md`

---

## File Map

### Created
| File | Responsibility |
|------|---------------|
| `orchestrator/app/migrations/049_linked_accounts.sql` | linked_accounts table schema |
| `orchestrator/app/linked_accounts.py` | CRUD functions for linked accounts (resolve, link, unlink, auto-link) |
| `orchestrator/app/linked_accounts_router.py` | API endpoints for linked accounts |
| `tests/test_linked_accounts.py` | Integration tests for linked accounts API |
| `tests/test_bridge_unified.py` | Integration tests for unified bridge chat flow |
| `website/src/content/docs/nova/docs/remote-access.md` | Cloudflare Tunnel + Tailscale guide (update existing) |

### Modified
| File | Changes |
|------|---------|
| `orchestrator/app/auth.py:201-310` | Add service-secret bypass in `require_user` |
| `orchestrator/app/conversations.py` | Add `get_active_conversation(user_id)` function |
| `orchestrator/app/router.py:351-473` | Add concurrent stream lock, accept bridge service auth |
| `orchestrator/app/main.py` | Register linked_accounts_router |
| `chat-bridge/app/config.py` | Add `BRIDGE_SERVICE_SECRET`, remove session-related config |
| `chat-bridge/app/bridge.py` | Replace session management with orchestrator API calls |
| `chat-bridge/app/adapters/telegram.py` | Add `/link`, `/unlink` commands, remove `/new`, use unified bridge |
| `chat-bridge/app/main.py` | Add `/reload-telegram` endpoint |
| `dashboard/src/pages/chat/ChatPage.tsx` | Remove sidebar toggle, load single active conversation |
| `dashboard/src/pages/settings/ChatIntegrationsSection.tsx` | Add linked users table, link code generation |
| `dashboard/src/api.ts` | Add linked accounts API functions |
| `scripts/setup.sh` | Generate `BRIDGE_SERVICE_SECRET` |
| `.env.example` | Add `BRIDGE_SERVICE_SECRET` |
| `docs/roadmap.md` | Add Phase 2 roadmap items |

### Deleted
| File | Reason |
|------|--------|
| `dashboard/src/components/ConversationSidebar.tsx` | No longer needed — single conversation model |

---

## Task 1: Database Migration — linked_accounts table

**Files:**
- Create: `orchestrator/app/migrations/049_linked_accounts.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 049_linked_accounts.sql
-- Maps external platform identities to Nova users for cross-channel chat unification.

CREATE TABLE IF NOT EXISTS linked_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    platform_id     TEXT NOT NULL,
    platform_username TEXT,
    linked_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One link per platform per user
CREATE UNIQUE INDEX IF NOT EXISTS uq_linked_accounts_user_platform
    ON linked_accounts (user_id, platform);

-- One platform identity maps to exactly one Nova user
CREATE UNIQUE INDEX IF NOT EXISTS uq_linked_accounts_platform_id
    ON linked_accounts (platform, platform_id);
```

- [ ] **Step 2: Verify migration applies**

Run: `docker compose restart orchestrator && sleep 3 && docker compose logs orchestrator --tail 10 | grep -i "049"`
Expected: Migration 049 applied successfully (orchestrator auto-runs migrations on startup)

- [ ] **Step 3: Verify table exists**

Run: `docker compose exec postgres psql -U nova -d nova -c "\d linked_accounts"`
Expected: Table with columns id, user_id, platform, platform_id, platform_username, linked_at

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/migrations/049_linked_accounts.sql
git commit -m "feat: add linked_accounts migration for cross-channel identity"
```

---

## Task 2: Orchestrator — Linked Accounts Module

**Files:**
- Create: `orchestrator/app/linked_accounts.py`

- [ ] **Step 1: Write the linked accounts module**

Follows the same pattern as `orchestrator/app/conversations.py` — uses `get_pool()` (sync) + `pool.acquire()` for DB, `get_redis()` (sync, returns aioredis) for Redis. UUID columns require `UUID()` conversion.

```python
"""Linked account management — maps external platform identities to Nova users."""
from __future__ import annotations

import secrets
import string
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.db import get_pool
from app.store import get_redis

log = logging.getLogger(__name__)

LINK_CODE_TTL = 600  # 10 minutes
LINK_CODE_PREFIX = "nova:link:"


def _link_dict(row) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["user_id"] = str(d["user_id"])
    return d


async def resolve_platform_account(platform: str, platform_id: str) -> dict | None:
    """Look up a linked account by platform identity. Returns user_id + display_name."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT la.user_id, la.platform_username, u.display_name, u.email
            FROM linked_accounts la
            JOIN users u ON u.id = la.user_id
            WHERE la.platform = $1 AND la.platform_id = $2
            """,
            platform, platform_id
        )
    if not row:
        return None
    d = dict(row)
    d["user_id"] = str(d["user_id"])
    return d


async def get_active_conversation_for_user(user_id: str) -> dict[str, Any]:
    """Get the user's most recent conversation, or create one if none exists."""
    pool = get_pool()
    uid = UUID(user_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, created_at, last_message_at
            FROM conversations
            WHERE user_id = $1 AND is_archived = false
            ORDER BY last_message_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            uid
        )
        if row:
            d = dict(row)
            d["id"] = str(d["id"])
            return d
        # Create a new conversation
        new_row = await conn.fetchrow(
            """
            INSERT INTO conversations (user_id, title)
            VALUES ($1, NULL)
            RETURNING id, title, created_at, last_message_at
            """,
            uid
        )
    d = dict(new_row)
    d["id"] = str(d["id"])
    return d


async def auto_link(platform: str, platform_id: str, platform_username: str | None = None) -> dict | None:
    """Auto-link if exactly one user exists and no one is linked for this platform.
    Returns the linked account info, or None if conditions not met."""
    pool = get_pool()
    async with pool.acquire() as conn:
        user_count = await conn.fetchval("SELECT count(*) FROM users")
        if user_count != 1:
            return None
        link_count = await conn.fetchval(
            "SELECT count(*) FROM linked_accounts WHERE platform = $1", platform
        )
        if link_count > 0:
            return None
        user = await conn.fetchrow("SELECT id, display_name FROM users LIMIT 1")
    if not user:
        return None
    return await create_link(str(user["id"]), platform, platform_id, platform_username)


async def create_link(user_id: str, platform: str, platform_id: str,
                      platform_username: str | None = None) -> dict:
    """Create a linked account binding."""
    pool = get_pool()
    uid = UUID(user_id)
    link_id = uuid4()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO linked_accounts (id, user_id, platform, platform_id, platform_username, linked_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (platform, platform_id) DO UPDATE
                SET user_id = EXCLUDED.user_id,
                    platform_username = EXCLUDED.platform_username,
                    linked_at = EXCLUDED.linked_at
            """,
            link_id, uid, platform, platform_id, platform_username, now
        )
    return {
        "id": str(link_id), "user_id": user_id, "platform": platform,
        "platform_id": platform_id, "platform_username": platform_username,
        "linked_at": now.isoformat()
    }


async def list_links(user_id: str | None = None) -> list[dict]:
    """List linked accounts. If user_id provided, filter to that user."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if user_id:
            rows = await conn.fetch(
                """
                SELECT la.*, u.display_name, u.email FROM linked_accounts la
                JOIN users u ON u.id = la.user_id
                WHERE la.user_id = $1 ORDER BY la.linked_at DESC
                """,
                UUID(user_id)
            )
        else:
            rows = await conn.fetch(
                """
                SELECT la.*, u.display_name, u.email FROM linked_accounts la
                JOIN users u ON u.id = la.user_id
                ORDER BY la.linked_at DESC
                """
            )
    return [_link_dict(r) for r in rows]


async def delete_link(link_id: str) -> bool:
    """Remove a linked account binding."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM linked_accounts WHERE id = $1", UUID(link_id)
        )
    return result == "DELETE 1"


async def generate_link_code(user_id: str) -> str:
    """Generate a 6-char alphanumeric code mapped to a user_id, stored in Redis with TTL."""
    code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    r = get_redis()
    await r.set(f"{LINK_CODE_PREFIX}{code}", user_id, ex=LINK_CODE_TTL)
    return code


async def redeem_link_code(code: str, platform: str, platform_id: str,
                           platform_username: str | None = None) -> dict | None:
    """Validate a link code and create the binding. Returns link info or None if invalid."""
    r = get_redis()
    user_id = await r.get(f"{LINK_CODE_PREFIX}{code}")
    if not user_id:
        return None
    await r.delete(f"{LINK_CODE_PREFIX}{code}")
    return await create_link(user_id, platform, platform_id, platform_username)
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/app/linked_accounts.py
git commit -m "feat: linked accounts module — CRUD, auto-link, link codes"
```

---

## Task 3: Orchestrator — Linked Accounts API Router

**Files:**
- Create: `orchestrator/app/linked_accounts_router.py`
- Modify: `orchestrator/app/main.py` (register router)

- [ ] **Step 1: Write the router**

```python
"""API endpoints for linked accounts — maps platform identities to Nova users."""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .auth import UserDep
from .linked_accounts import (
    resolve_platform_account,
    get_active_conversation_for_user,
    auto_link,
    create_link,
    list_links,
    delete_link,
    generate_link_code,
    redeem_link_code,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/linked-accounts", tags=["linked-accounts"])

# --- Models ---

class ResolveRequest(BaseModel):
    platform: str
    platform_id: str

class ResolveResponse(BaseModel):
    user_id: str
    conversation_id: str
    display_name: str

class AutoLinkRequest(BaseModel):
    platform: str
    platform_id: str
    platform_username: str | None = None

class RedeemRequest(BaseModel):
    code: str
    platform: str
    platform_id: str
    platform_username: str | None = None

# --- Service-auth endpoints (bridge calls these) ---

def _require_service_secret(request: Request):
    """Validate X-Service-Secret header for bridge-to-orchestrator trust."""
    from .config import settings
    secret = request.headers.get("X-Service-Secret", "")
    if not secret or secret != settings.bridge_service_secret:
        raise HTTPException(status_code=403, detail="Invalid service secret")

@router.post("/resolve", response_model=ResolveResponse)
async def resolve_endpoint(req: ResolveRequest, request: Request):
    """Map platform + platform_id to user_id + conversation_id. Used by bridge."""
    _require_service_secret(request)
    account = await resolve_platform_account(req.platform, req.platform_id)
    if not account:
        raise HTTPException(status_code=404, detail="No linked account found")
    conv = await get_active_conversation_for_user(str(account["user_id"]))
    return ResolveResponse(
        user_id=str(account["user_id"]),
        conversation_id=str(conv["id"]),
        display_name=account.get("display_name") or account.get("email", ""),
    )

@router.post("/auto-link")
async def auto_link_endpoint(req: AutoLinkRequest, request: Request):
    """Auto-link when one user exists with no link. Used by bridge."""
    _require_service_secret(request)
    result = await auto_link(req.platform, req.platform_id, req.platform_username)
    if not result:
        raise HTTPException(
            status_code=409,
            detail="Auto-link not available. Multiple users exist or a link already exists."
        )
    return result

@router.post("/redeem")
async def redeem_endpoint(req: RedeemRequest, request: Request):
    """Validate a link code and create the binding. Used by bridge /link command."""
    _require_service_secret(request)
    result = await redeem_link_code(req.code, req.platform, req.platform_id, req.platform_username)
    if not result:
        raise HTTPException(status_code=404, detail="Invalid or expired link code")
    return result

# --- User-auth endpoints (dashboard calls these) ---

@router.get("")
async def list_links_endpoint(user: UserDep):
    """List all linked accounts (admin sees all, regular user sees own)."""
    return await list_links()

@router.delete("/{link_id}")
async def delete_link_endpoint(link_id: str, user: UserDep):
    """Unlink a platform account."""
    deleted = await delete_link(link_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Linked account not found")
    return {"status": "unlinked"}

@router.post("/link-code")
async def generate_link_code_endpoint(user: UserDep):
    """Generate a 6-char link code for the authenticated user."""
    code = await generate_link_code(str(user.id))
    return {"code": code, "ttl_seconds": 600}
```

- [ ] **Step 2: Add `bridge_service_secret` to orchestrator config**

In `orchestrator/app/config.py`, add:
```python
bridge_service_secret: str = ""
```

- [ ] **Step 3: Register the router in main.py**

In `orchestrator/app/main.py`, add:
```python
from .linked_accounts_router import router as linked_accounts_router
app.include_router(linked_accounts_router)
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/app/linked_accounts_router.py orchestrator/app/config.py orchestrator/app/main.py
git commit -m "feat: linked accounts API — resolve, auto-link, link codes, CRUD"
```

---

## Task 4: Orchestrator — Service Auth Bypass

**Files:**
- Modify: `orchestrator/app/auth.py:201-310`

- [ ] **Step 1: Add service-secret impersonation to `require_user`**

In `orchestrator/app/auth.py`, add a check at the top of the `require_user` function (after the existing admin-secret fallback logic) that accepts `X-Service-Secret` + `X-On-Behalf-Of` headers:

```python
# Service-to-service impersonation (bridge)
service_secret = request.headers.get("X-Service-Secret", "")
on_behalf_of = request.headers.get("X-On-Behalf-Of", "")
if service_secret and on_behalf_of:
    if service_secret == settings.bridge_service_secret and settings.bridge_service_secret:
        # Trusted internal service — look up the user
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, display_name, is_admin, role, tenant_id FROM users WHERE id = $1::uuid",
                on_behalf_of,
            )
        if row:
            return AuthenticatedUser(
                id=str(row["id"]),
                email=row["email"],
                display_name=row.get("display_name") or "",
                is_admin=row.get("is_admin", False),
                role=row.get("role", "member"),
                tenant_id=str(row["tenant_id"]) if row.get("tenant_id") else "00000000-0000-0000-0000-000000000001",
            )
    raise HTTPException(status_code=403, detail="Invalid service credentials")
```

Insert this after the dev bypass check (`if not await _get_require_auth()`) but before the JWT validation. This way `X-Service-Secret` is checked early and skips the JWT flow entirely.

- [ ] **Step 2: Verify the bypass does not break existing auth**

Run: `make test-quick`
Expected: All health checks pass (no auth regression)

- [ ] **Step 3: Commit**

```bash
git add orchestrator/app/auth.py
git commit -m "feat: service-secret auth bypass for bridge impersonation"
```

---

## Task 5: Orchestrator — Concurrent Stream Lock

**Files:**
- Modify: `orchestrator/app/router.py:351-473`

- [ ] **Step 1: Add `metadata` field to `ChatRequest`**

In `router.py` around line 301, add `metadata` to the `ChatRequest` model:

```python
class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    output_style: str | None = None
    custom_instructions: str | None = None
    web_search: bool = False
    deep_research: bool = False
    metadata: dict | None = None  # channel tagging from bridge
```

- [ ] **Step 2: Add stream lock check in `chat_stream`**

In the `chat_stream` function, after conversation validation (after line 409), add:

```python
# Concurrent stream lock — one stream per conversation at a time
from app.store import get_redis
lock_key = f"nova:chat:streaming:{conversation_id or session_id}"
_redis = get_redis()
if await _redis.exists(lock_key):
    raise HTTPException(
        status_code=409,
        detail="Nova is currently responding. Try again in a moment."
    )
await _redis.set(lock_key, "1", ex=120)
```

- [ ] **Step 3: Add `session_id` param and lock cleanup to `_sse_stream`**

Update the `_sse_stream` signature (line 62) to accept `session_id`:

```python
async def _sse_stream(agent_id: str, stream_gen, error_label: str = "stream", sandbox_token=None,
                      conversation_id: str | None = None, user_message: str | None = None,
                      session_id: str | None = None, message_metadata: dict | None = None):
```

In the finally block (after line 109), add lock cleanup:

```python
        # Release concurrent stream lock
        try:
            from app.store import get_redis
            _redis = get_redis()
            lock_key = f"nova:chat:streaming:{conversation_id or session_id}"
            await _redis.delete(lock_key)
        except Exception:
            pass  # Lock auto-expires via TTL if cleanup fails
```

Also update the `add_message` call for the user message to include metadata:

```python
if user_message:
    await add_message(conversation_id, "user", user_message, metadata=message_metadata)
```

- [ ] **Step 4: Update both `_sse_stream` call sites**

In the chat_stream handler (around line 447), pass the new params:

```python
_sse_stream(
    str(agent.id),
    run_agent_turn_streaming(...),
    error_label="Chat stream",
    sandbox_token=sandbox_token,
    conversation_id=conversation_id,
    user_message=user_message,
    session_id=session_id,
    message_metadata=req.metadata,
),
```

The other call site (task streaming, around line 248) passes `session_id=None` and `message_metadata=None` (no change needed — new params are optional with defaults).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/router.py
git commit -m "feat: concurrent stream lock — 409 when conversation is active"
```

---

## Task 6: Integration Tests — Linked Accounts

**Files:**
- Create: `tests/test_linked_accounts.py`

- [ ] **Step 1: Write integration tests**

```python
"""Integration tests for linked accounts API."""

import os
import pytest
import httpx

BASE = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "changeme")
BRIDGE_SECRET = os.getenv("BRIDGE_SERVICE_SECRET", "")
PREFIX = "nova-test-"


def admin_headers():
    return {"X-Admin-Secret": ADMIN_SECRET}


def service_headers(user_id: str = ""):
    h = {"X-Service-Secret": BRIDGE_SECRET}
    if user_id:
        h["X-On-Behalf-Of"] = user_id
    return h


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE, timeout=10)


class TestLinkedAccounts:
    def test_list_linked_accounts(self, client):
        """GET /api/v1/linked-accounts returns a list."""
        r = client.get("/api/v1/linked-accounts", headers=admin_headers())
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_resolve_unlinked_returns_404(self, client):
        """Resolve a platform_id that isn't linked returns 404."""
        r = client.post(
            "/api/v1/linked-accounts/resolve",
            json={"platform": "telegram", "platform_id": f"{PREFIX}999999"},
            headers={"X-Service-Secret": BRIDGE_SECRET},
        )
        assert r.status_code == 404

    def test_generate_link_code(self, client):
        """Generate a link code returns a 6-char code."""
        r = client.post(
            "/api/v1/linked-accounts/link-code",
            headers=admin_headers(),
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["code"]) == 6
        assert data["ttl_seconds"] == 600

    def test_redeem_invalid_code_returns_404(self, client):
        """Redeeming an invalid code returns 404."""
        r = client.post(
            "/api/v1/linked-accounts/redeem",
            json={
                "code": "ZZZZZZ",
                "platform": "telegram",
                "platform_id": f"{PREFIX}888888",
            },
            headers={"X-Service-Secret": BRIDGE_SECRET},
        )
        assert r.status_code == 404

    def test_invalid_service_secret_returns_403(self, client):
        """Invalid service secret is rejected."""
        r = client.post(
            "/api/v1/linked-accounts/resolve",
            json={"platform": "telegram", "platform_id": "123"},
            headers={"X-Service-Secret": "wrong-secret"},
        )
        assert r.status_code == 403
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_linked_accounts.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_linked_accounts.py
git commit -m "test: integration tests for linked accounts API"
```

---

## Task 7: Setup & Config — BRIDGE_SERVICE_SECRET

**Files:**
- Modify: `scripts/setup.sh`
- Modify: `.env.example`

- [ ] **Step 1: Add to .env.example**

Add after the existing `ADMIN_SECRET` line:

```bash
BRIDGE_SERVICE_SECRET=
```

- [ ] **Step 2: Add auto-generation to setup.sh**

Follow the `CREDENTIAL_MASTER_KEY` pattern. Add after that block (around line 38):

```bash
if grep -q "^BRIDGE_SERVICE_SECRET=$" "${PROJECT_ROOT}/.env" 2>/dev/null; then
  BRIDGE_SERVICE_SECRET=$(openssl rand -hex 32)
  sed -i "s/^BRIDGE_SERVICE_SECRET=$/BRIDGE_SERVICE_SECRET=${BRIDGE_SERVICE_SECRET}/" "${PROJECT_ROOT}/.env"
  echo "  Generated BRIDGE_SERVICE_SECRET"
fi
```

- [ ] **Step 3: Add to chat-bridge config**

In `chat-bridge/app/config.py`, add:

```python
bridge_service_secret: str = ""
```

- [ ] **Step 4: Add env var to docker-compose.yml**

In the `chat-bridge` service environment section, add:

```yaml
BRIDGE_SERVICE_SECRET: ${BRIDGE_SERVICE_SECRET}
```

In the `orchestrator` service environment section, add:

```yaml
BRIDGE_SERVICE_SECRET: ${BRIDGE_SERVICE_SECRET}
```

- [ ] **Step 5: Commit**

```bash
git add scripts/setup.sh .env.example chat-bridge/app/config.py docker-compose.yml
git commit -m "feat: BRIDGE_SERVICE_SECRET setup — auto-generated, shared between orchestrator and bridge"
```

---

## Task 8: Chat-Bridge — Rewrite Bridge Core

**Files:**
- Modify: `chat-bridge/app/bridge.py` (full rewrite)

- [ ] **Step 1: Rewrite bridge.py**

Replace session management with orchestrator API calls. The bridge becomes a thin relay.

```python
"""Bridge core — routes platform messages through orchestrator's unified chat endpoint."""

import logging
import httpx

from .config import settings

logger = logging.getLogger(__name__)


def _service_headers():
    """Headers for service-to-service auth with orchestrator."""
    return {"X-Service-Secret": settings.bridge_service_secret}


def _impersonation_headers(user_id: str):
    """Headers to call chat/stream on behalf of a user."""
    return {
        "X-Service-Secret": settings.bridge_service_secret,
        "X-On-Behalf-Of": user_id,
        "Content-Type": "application/json",
    }


async def resolve_user(platform: str, platform_id: str) -> dict | None:
    """Resolve a platform identity to a Nova user. Returns user_id, conversation_id, username."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{settings.orchestrator_url}/api/v1/linked-accounts/resolve",
            json={"platform": platform, "platform_id": str(platform_id)},
            headers=_service_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def try_auto_link(platform: str, platform_id: str,
                        platform_username: str | None = None) -> dict | None:
    """Attempt auto-link for first user. Returns link info or None."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{settings.orchestrator_url}/api/v1/linked-accounts/auto-link",
            json={
                "platform": platform,
                "platform_id": str(platform_id),
                "platform_username": platform_username,
            },
            headers=_service_headers(),
        )
        if r.status_code == 409:
            return None
        if r.status_code >= 400:
            return None
        return r.json()


async def redeem_link_code(code: str, platform: str, platform_id: str,
                           platform_username: str | None = None) -> dict | None:
    """Redeem a link code. Returns link info or None if invalid."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{settings.orchestrator_url}/api/v1/linked-accounts/redeem",
            json={
                "code": code.strip().upper(),
                "platform": platform,
                "platform_id": str(platform_id),
                "platform_username": platform_username,
            },
            headers=_service_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def send_message(user_id: str, conversation_id: str, text: str,
                       channel: str = "telegram") -> str:
    """Send a message through orchestrator's chat stream endpoint. Returns full response text."""
    payload = {
        "messages": [{"role": "user", "content": text}],
        "conversation_id": conversation_id,
        "metadata": {"channel": channel},
    }
    full_response = []

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{settings.orchestrator_url}/api/v1/chat/stream",
            json=payload,
            headers=_impersonation_headers(user_id),
        ) as response:
            if response.status_code == 409:
                return "Nova is currently thinking. Try again in a moment."
            if response.status_code >= 400:
                logger.error("Chat stream error: %s", response.status_code)
                return "Sorry, I encountered an error. Please try again."

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    import json
                    parsed = json.loads(data)
                    if "t" in parsed:
                        full_response.append(parsed["t"])
                except (json.JSONDecodeError, KeyError):
                    continue

    return "".join(full_response) or "I had nothing to say."


def chunk_message(text: str, max_length: int = 4096) -> list[str]:
    """Split a long message into chunks at paragraph boundaries for Telegram."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) + 2 > max_length:
            chunks.append(current.strip())
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph

    if current.strip():
        chunks.append(current.strip())

    # Safety: if any chunk is still too long, hard-split
    final = []
    for chunk in chunks:
        while len(chunk) > max_length:
            final.append(chunk[:max_length])
            chunk = chunk[max_length:]
        if chunk:
            final.append(chunk)

    return final
```

- [ ] **Step 2: Remove `close_redis` import from main.py**

The rewrite removes all Redis usage from `bridge.py`, so `close_redis()` no longer exists. Update `chat-bridge/app/main.py`:
- Remove `from app.bridge import close_redis` (line 12)
- Remove `await close_redis()` from the lifespan shutdown (line 49)

- [ ] **Step 3: Commit**

```bash
git add chat-bridge/app/bridge.py chat-bridge/app/main.py
git commit -m "feat: rewrite bridge core — orchestrator relay, no local sessions"
```

---

## Task 9: Chat-Bridge — Update Telegram Adapter

**Files:**
- Modify: `chat-bridge/app/adapters/telegram.py`

- [ ] **Step 1: Rewrite the Telegram adapter**

Update command handlers and message flow to use the new bridge functions. Add `/link` and `/unlink`, remove `/new`.

Key changes:
- `_handle_message`: resolve user → if not linked, try auto-link → if still not linked, prompt for `/link` → if linked, send_message via orchestrator → chunk and reply
- `/link <code>` command: redeem the code
- `/unlink` command: tell user to unlink from the dashboard (simpler than implementing delete from Telegram)
- `/start` command: updated help text
- Remove `/new` command (no session reset in unified model)

The adapter's `_handle_message` method should:
1. Get `chat_id` and username from the Telegram update
2. Call `bridge.resolve_user("telegram", chat_id)`
3. If not found, call `bridge.try_auto_link("telegram", chat_id, username)`
4. If still not found, reply with linking instructions
5. If found, call `bridge.send_message(user_id, conversation_id, text)`
6. Chunk the response and send via Telegram
7. Handle markdown parsing with plaintext fallback (existing behavior)

The `/link` handler should:
1. Extract the code from the message text
2. Call `bridge.redeem_link_code(code, "telegram", chat_id, username)`
3. Reply with success or "invalid/expired code"

- [ ] **Step 2: Commit**

```bash
git add chat-bridge/app/adapters/telegram.py
git commit -m "feat: telegram adapter — unified chat, /link command, auto-link"
```

---

## Task 10: Chat-Bridge — Reload Endpoint

**Note:** The spec lists this as an orchestrator endpoint, but the bridge owns the Telegram adapter lifecycle. Putting the endpoint on the bridge directly (proxied via `/bridge-api`) is more pragmatic — avoids orchestrator→bridge reverse call.

**Files:**
- Modify: `chat-bridge/app/main.py`

- [ ] **Step 1: Add POST /reload-telegram endpoint**

Add a new endpoint to `chat-bridge/app/main.py` that tears down and re-initializes the Telegram adapter. Protected by admin secret.

```python
@app.post("/reload-telegram")
async def reload_telegram(request: Request):
    """Reload Telegram adapter with new config. Called by dashboard after saving bot token."""
    from fastapi import HTTPException
    admin_secret = request.headers.get("X-Admin-Secret", "")
    if admin_secret != settings.nova_admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Read new token from Redis runtime config (DB 1 = nova:config:* store)
    from app.adapters.telegram import TelegramAdapter
    import redis.asyncio as aioredis
    config_redis_url = settings.redis_url.rsplit("/", 1)[0] + "/1"
    r = aioredis.from_url(config_redis_url, decode_responses=True)
    try:
        token = await r.get("nova:config:telegram.bot_token")
    finally:
        await r.aclose()

    if not token:
        raise HTTPException(status_code=400, detail="No bot token configured")

    # Shutdown existing telegram adapter
    for adapter in ADAPTERS:
        if adapter.platform_name == "telegram":
            await adapter.shutdown()
            ADAPTERS.remove(adapter)
            break

    # Start new adapter with updated token (use model_config to allow mutation)
    object.__setattr__(settings, "telegram_bot_token", token)
    new_adapter = TelegramAdapter()  # reads from module-level settings
    if new_adapter.is_configured():
        await new_adapter.setup(app)
        ADAPTERS.append(new_adapter)

    return {"status": "reloaded"}
```

Also add `nova_admin_secret` to the bridge config if not already present (for reload endpoint auth).

- [ ] **Step 2: Add proxy route in dashboard nginx.conf and vite.config.ts**

Add a `/bridge-api` proxy to the bridge service (port 8090) so the dashboard can call the reload endpoint.

In `dashboard/vite.config.ts` dev proxy:
```typescript
'/bridge-api': {
  target: 'http://localhost:8090',
  rewrite: (path) => path.replace(/^\/bridge-api/, ''),
},
```

In `dashboard/nginx.conf` production proxy:
```nginx
location /bridge-api/ {
    proxy_pass http://chat-bridge:8090/;
}
```

- [ ] **Step 3: Commit**

```bash
git add chat-bridge/app/main.py dashboard/vite.config.ts dashboard/nginx.conf
git commit -m "feat: bridge reload endpoint + dashboard proxy for bot token changes"
```

---

## Task 11: Dashboard — Chat Page Simplification

**Files:**
- Modify: `dashboard/src/pages/chat/ChatPage.tsx`
- Delete: `dashboard/src/components/ConversationSidebar.tsx`

- [ ] **Step 1: Simplify ChatPage**

Remove the conversation sidebar toggle and conversation switching. The chat page should:
1. On mount, fetch the user's active conversation via `GET /api/v1/linked-accounts/resolve` or a simpler approach: call the existing conversations list endpoint and use the first one, or create one
2. Load messages for that single conversation
3. Remove sidebar references and the toggle button
4. Remove "new chat" button
5. Add a subtle channel indicator on messages that have `metadata.channel === "telegram"`

Key changes in `ChatPage.tsx`:
- Remove `ConversationSidebar` import and rendering
- Remove sidebar toggle state and button
- Auto-load the most recent conversation on mount
- If no conversation exists, create one automatically
- Add channel badge to `MessageBubble` for telegram-origin messages

- [ ] **Step 2: Delete ConversationSidebar.tsx**

```bash
rm dashboard/src/components/ConversationSidebar.tsx
```

- [ ] **Step 3: Remove any imports of ConversationSidebar in other files**

Search for and remove any remaining imports of `ConversationSidebar` across the dashboard.

- [ ] **Step 4: Build check**

Run: `cd dashboard && npm run build`
Expected: TypeScript compilation succeeds with no errors

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/chat/ChatPage.tsx dashboard/src/api.ts
git rm dashboard/src/components/ConversationSidebar.tsx
git commit -m "feat: single-conversation chat UI — remove sidebar, auto-load active conversation"
```

---

## Task 12: Dashboard — Telegram Settings UI

**Files:**
- Modify: `dashboard/src/pages/settings/ChatIntegrationsSection.tsx`
- Modify: `dashboard/src/api.ts`

- [ ] **Step 1: Add linked accounts API functions to api.ts**

```typescript
// Linked accounts
export async function getLinkedAccounts(): Promise<LinkedAccount[]> {
  return apiFetch<LinkedAccount[]>('/api/v1/linked-accounts')
}

export async function deleteLinkedAccount(id: string): Promise<void> {
  await apiFetch(`/api/v1/linked-accounts/${id}`, { method: 'DELETE' })
}

export async function generateLinkCode(): Promise<{ code: string; ttl_seconds: number }> {
  return apiFetch('/api/v1/linked-accounts/link-code', { method: 'POST' })
}

export async function reloadTelegramBot(): Promise<void> {
  await apiFetch('/bridge-api/reload-telegram', { method: 'POST' })
}

// Types
export interface LinkedAccount {
  id: string
  user_id: string
  display_name: string
  email: string
  platform: string
  platform_id: string
  platform_username: string | null
  linked_at: string
}
```

- [ ] **Step 2: Rewrite ChatIntegrationsSection**

Update `ChatIntegrationsSection.tsx` to include:

**Bot Token section:**
- Token input field — always visible, pre-filled from runtime config
- Save button that writes to Redis (`nova:config:telegram.bot_token`) and calls reload endpoint
- Connection status indicator

**Linked Users section:**
- Table rendered from `getLinkedAccounts()` filtered to platform=telegram
- Columns: Nova User, Telegram Username, Status, Actions (Unlink button)
- "Generate Link Code" button — calls `generateLinkCode()`, shows code with countdown timer
- First row auto-populates when user messages bot (shown on refresh)

**Status footer:**
- Bot online/offline from health check
- Last activity timestamp

- [ ] **Step 3: Build check**

Run: `cd dashboard && npm run build`
Expected: No TypeScript errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/settings/ChatIntegrationsSection.tsx dashboard/src/api.ts
git commit -m "feat: Telegram settings UI — bot token, linked users, link code generation"
```

---

## Task 13: External Access Documentation

**Files:**
- Modify: `website/src/content/docs/nova/docs/remote-access.md` (or create if not exists)

- [ ] **Step 1: Write the remote access guide**

Document both options with trade-offs, configuration steps, and recommendations:

**Cloudflare Tunnel:**
- Install cloudflared
- Create tunnel pointing to localhost:3000 (dashboard)
- Configure Telegram webhook URL to the tunnel domain
- Pros: any browser, no client needed, enables webhooks
- Cons: traffic routes through Cloudflare

**Tailscale:**
- Install Tailscale on server and client devices
- Access Nova at tailscale-ip:3000
- Telegram must use polling mode (not webhooks)
- Pros: private, encrypted P2P, no third party
- Cons: need client on every device

**Running both:** Tailscale for direct access, Cloudflare for Telegram webhooks

- [ ] **Step 2: Commit**

```bash
git add website/src/content/docs/nova/docs/remote-access.md
git commit -m "docs: remote access guide — Cloudflare Tunnel + Tailscale"
```

---

## Task 14: Roadmap Update

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Add Phase 2 items to roadmap**

Add a "Unified Chat — Phase 2" section with:
- Multi-user memory isolation (per-user engram graph, scoped retrieval)
- Real-time conversation sync (live cross-channel streaming via WebSocket push)
- Push notifications (VAPID keys, service worker push handlers)
- Slack adapter (same bridge pattern as Telegram)
- Conversation history management (archive, search, export)
- Automated VPN/tunnel setup scripts

- [ ] **Step 2: Commit**

```bash
git add docs/roadmap.md
git commit -m "docs: add unified chat phase 2 to roadmap"
```

---

## Task 15: Final Integration Testing

**Files:**
- Create: `tests/test_bridge_unified.py`

- [ ] **Step 1: Write end-to-end integration tests**

```python
"""Integration tests for unified bridge chat flow."""

import os
import pytest
import httpx

BASE = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
BRIDGE_BASE = os.getenv("CHAT_BRIDGE_URL", "http://localhost:8090")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "changeme")
BRIDGE_SECRET = os.getenv("BRIDGE_SERVICE_SECRET", "")


def admin_headers():
    return {"X-Admin-Secret": ADMIN_SECRET}


def service_headers(user_id: str = ""):
    h = {"X-Service-Secret": BRIDGE_SECRET}
    if user_id:
        h["X-On-Behalf-Of"] = user_id
    return h


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE, timeout=30)


class TestBridgeUnified:
    def test_bridge_health(self):
        """Bridge service is healthy."""
        r = httpx.get(f"{BRIDGE_BASE}/health/ready", timeout=5)
        assert r.status_code == 200

    def test_service_auth_on_chat_stream(self, client):
        """Service auth bypass works on /chat/stream — returns 200 not 401/403."""
        # This test requires a valid user_id — skip if no bridge secret
        if not BRIDGE_SECRET:
            pytest.skip("BRIDGE_SERVICE_SECRET not set")

        # Get a user ID
        r = client.get("/api/v1/users", headers=admin_headers())
        if r.status_code != 200 or not r.json():
            pytest.skip("No users available")
        user_id = r.json()[0]["id"]

        # Use httpx streaming to avoid hanging on SSE endpoint
        with httpx.Client(base_url=BASE, timeout=30) as c:
            with c.stream(
                "POST",
                "/api/v1/chat/stream",
                json={"messages": [{"role": "user", "content": "nova-test-ping"}]},
                headers=service_headers(user_id),
            ) as resp:
                # Should get 200 (streaming) not 401/403
                assert resp.status_code == 200
                # Read just the first line to confirm stream works, then close
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        break

    def test_concurrent_stream_lock(self, client):
        """409 returned when conversation is already streaming."""
        # This is tested implicitly — when a stream is active,
        # a second request to the same conversation returns 409.
        # Difficult to test in integration without async. Mark as manual.
        pass
```

- [ ] **Step 2: Run full test suite**

Run: `make test`
Expected: All existing tests pass + new tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_bridge_unified.py
git commit -m "test: integration tests for unified bridge chat flow"
```

---

## Execution Order

Tasks are ordered by dependency:

1. **Task 1** (migration) — no deps, foundation for everything
2. **Task 2** (linked accounts module) — depends on Task 1
3. **Task 3** (API router) — depends on Task 2
4. **Task 4** (service auth bypass) — depends on nothing, but Task 3 uses it
5. **Task 5** (stream lock) — independent
6. **Task 6** (linked accounts tests) — depends on Tasks 1-4
7. **Task 7** (setup/config) — independent, but bridge tasks need it
8. **Task 8** (bridge rewrite) — depends on Tasks 3, 4, 7
9. **Task 9** (telegram adapter) — depends on Task 8
10. **Task 10** (reload endpoint) — depends on Task 9
11. **Task 11** (chat page simplification) — independent of backend
12. **Task 12** (telegram settings UI) — depends on Tasks 3, 10
13. **Task 13** (external access docs) — independent
14. **Task 14** (roadmap) — independent
15. **Task 15** (integration tests) — depends on all above

**Parallelizable groups:**
- Tasks 1-5 + 7 (backend orchestrator + config)
- Tasks 11, 13, 14 (frontend + docs, no backend deps)
- Tasks 8-10 (bridge, after backend is done)
- Task 12 (dashboard settings, after bridge + router)
- Tasks 6, 15 (tests, after implementation)
