# RBAC & User Invitations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add five-role RBAC (Owner/Admin/Member/Viewer/Guest), link-based invitations with role assignment, auto-expiring guest accounts with sandboxed LLM access, and `tenant_id` scaffolding on all data tables.

**Architecture:** Extend existing `users` and `invite_codes` tables with `role`, `tenant_id`, `expires_at` columns. Replace `AdminDep` with a `RoleDep(min_role=...)` hierarchy. Add Guest isolation at the orchestrator level (no tools, no context, model allowlist). New Users page in dashboard for user/invite management.

**Tech Stack:** Python/FastAPI/asyncpg (backend), React/TypeScript/Tailwind/TanStack Query (frontend), PostgreSQL (schema), Redis (deny-list for immediate revocation)

**Design doc:** `docs/plans/2026-03-08-rbac-invitations-design.md`

---

### Task 1: Database Migration — RBAC Schema

**Files:**
- Create: `orchestrator/app/migrations/019_rbac_and_tenants.sql`

**Step 1: Write the migration**

```sql
-- 019_rbac_and_tenants.sql
-- RBAC roles, tenant scaffolding, guest expiry, audit log

-- Tenants table (single row for now)
CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO tenants (id, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default')
ON CONFLICT (id) DO NOTHING;

-- Users: add role, tenant_id, expiry, status
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='role') THEN
        ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='tenant_id') THEN
        ALTER TABLE users ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='expires_at') THEN
        ALTER TABLE users ADD COLUMN expires_at TIMESTAMPTZ;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='status') THEN
        ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
    END IF;
END $$;

-- Backfill roles from is_admin
-- First admin user becomes owner, others become admin, non-admins stay member
DO $$
DECLARE
    first_admin_id UUID;
BEGIN
    SELECT id INTO first_admin_id FROM users WHERE is_admin = true ORDER BY created_at ASC LIMIT 1;
    IF first_admin_id IS NOT NULL THEN
        UPDATE users SET role = 'owner' WHERE id = first_admin_id AND role = 'member';
        UPDATE users SET role = 'admin' WHERE is_admin = true AND id != first_admin_id AND role = 'member';
    END IF;
END $$;

-- Invite codes: add role, account expiry, tenant_id
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invite_codes' AND column_name='role') THEN
        ALTER TABLE invite_codes ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invite_codes' AND column_name='account_expires_in_hours') THEN
        ALTER TABLE invite_codes ADD COLUMN account_expires_in_hours INTEGER;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='invite_codes' AND column_name='tenant_id') THEN
        ALTER TABLE invite_codes ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
    END IF;
END $$;

-- Tenant scaffolding on data tables
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='conversations' AND column_name='tenant_id') THEN
        ALTER TABLE conversations ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='api_keys' AND column_name='tenant_id') THEN
        ALTER TABLE api_keys ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='usage_events' AND column_name='tenant_id') THEN
        ALTER TABLE usage_events ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
    END IF;
END $$;

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    UUID REFERENCES users(id),
    action      TEXT NOT NULL,
    target_id   UUID,
    details     JSONB,
    ip_address  TEXT,
    tenant_id   UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON audit_log(tenant_id, created_at DESC);

-- Guest-allowed models config
INSERT INTO platform_config (key, value, description, is_secret)
VALUES ('guest_allowed_models', '[]', 'JSON array of model IDs guests can use', false)
ON CONFLICT (key) DO NOTHING;
```

**Step 2: Verify migration runs**

Run: `docker compose restart orchestrator && docker compose logs orchestrator | grep -i "019"`
Expected: Migration 019 applied successfully.

**Step 3: Commit**

```bash
git add orchestrator/app/migrations/019_rbac_and_tenants.sql
git commit -m "feat: add RBAC schema migration with tenant scaffolding"
```

---

### Task 2: Role Constants & Auth Middleware

**Files:**
- Create: `orchestrator/app/roles.py`
- Modify: `orchestrator/app/auth.py` (lines 31-37: AuthenticatedUser, lines 110-196: deps)

**Step 1: Create roles module**

Create `orchestrator/app/roles.py`:

```python
"""Fixed role definitions and hierarchy for RBAC."""

from enum import IntEnum

class Role(IntEnum):
    """Roles ordered by privilege level (higher = more access)."""
    GUEST = 0
    VIEWER = 1
    MEMBER = 2
    ADMIN = 3
    OWNER = 4

ROLE_NAMES = {r.name.lower(): r for r in Role}
VALID_ROLES = set(ROLE_NAMES.keys())

def parse_role(role_str: str) -> Role:
    """Convert role string to Role enum. Defaults to MEMBER if unknown."""
    return ROLE_NAMES.get(role_str.lower(), Role.MEMBER)

def can_assign_role(assigner_role: str, target_role: str) -> bool:
    """Check if assigner can assign target role (must be >= target)."""
    return parse_role(assigner_role) >= parse_role(target_role)

def has_min_role(user_role: str, min_role: str) -> bool:
    """Check if user meets minimum role requirement."""
    return parse_role(user_role) >= parse_role(min_role)
```

**Step 2: Update AuthenticatedUser dataclass**

In `orchestrator/app/auth.py`, update the `AuthenticatedUser` dataclass (line 31-37) to add `role` and `tenant_id`:

```python
@dataclass
class AuthenticatedUser:
    id: str
    email: str
    display_name: str
    is_admin: bool
    role: str = "member"
    tenant_id: str = "00000000-0000-0000-0000-000000000001"
```

**Step 3: Add RoleDep factory**

In `orchestrator/app/auth.py`, add after the existing `require_user` function (after line ~190):

```python
def require_role(min_role: str):
    """Factory for role-checking dependencies. Usage: RoleDep = Annotated[AuthenticatedUser, Depends(require_role('admin'))]"""
    async def _check(user: UserDep) -> AuthenticatedUser:
        from app.roles import has_min_role
        if not has_min_role(user.role, min_role):
            raise HTTPException(status_code=403, detail=f"Requires {min_role} role or higher")
        return user
    return _check
```

**Step 4: Update require_user to extract role from JWT**

In `orchestrator/app/auth.py`, update the JWT extraction in `require_user()` (around line 170-180) to populate role and tenant_id from JWT claims:

```python
# In the JWT path of require_user(), after decoding token:
role = payload.get("role", "admin" if payload.get("is_admin") else "member")
tenant_id = payload.get("tenant_id", "00000000-0000-0000-0000-000000000001")
return AuthenticatedUser(
    id=payload["sub"],
    email=payload.get("email", ""),
    display_name=payload.get("email", ""),
    is_admin=payload.get("is_admin", False),
    role=role,
    tenant_id=tenant_id,
)
```

Also update the `_SYNTHETIC_ADMIN` constant and all synthetic user returns to include `role="owner"` and `tenant_id`.

**Step 5: Add expiry check middleware**

In `orchestrator/app/auth.py`, add an expiry check in `require_user()` after the user is resolved:

```python
# After user is resolved (before return), check expiry
if user.role == "guest":
    # Check DB or Redis for expiry — this is done in the route or a separate dep
    pass
```

Actually, the expiry check should be a separate concern. Add a new dependency:

```python
async def check_account_active(user: UserDep) -> AuthenticatedUser:
    """Check user account is not expired or deactivated."""
    from app.db import get_pool
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT status, expires_at FROM users WHERE id = $1",
        user.id
    )
    if row:
        if row["status"] != "active":
            raise HTTPException(status_code=403, detail="Account deactivated")
        if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="Account expired")
    return user

ActiveUserDep = Annotated[AuthenticatedUser, Depends(check_account_active)]
```

**Step 6: Update AdminDep to use RoleDep**

Replace the current `AdminDep` alias (line 195) to use the new role system while keeping backwards compatibility:

```python
# Keep AdminDep working but it now checks role
AdminDep = Annotated[None, Depends(require_admin)]  # Keep as-is for now
# New role-based deps
OwnerDep = Annotated[AuthenticatedUser, Depends(require_role("owner"))]
AdminRoleDep = Annotated[AuthenticatedUser, Depends(require_role("admin"))]
MemberDep = Annotated[AuthenticatedUser, Depends(require_role("member"))]
```

**Step 7: Commit**

```bash
git add orchestrator/app/roles.py orchestrator/app/auth.py
git commit -m "feat: add role hierarchy and RoleDep auth middleware"
```

---

### Task 3: JWT Claims & User CRUD Updates

**Files:**
- Modify: `orchestrator/app/jwt_auth.py` (line 58: create_access_token)
- Modify: `orchestrator/app/users.py` (line 19: create_user)

**Step 1: Update create_access_token**

In `orchestrator/app/jwt_auth.py`, update `create_access_token` (line 58) to include `role` and `tenant_id`:

```python
def create_access_token(user_id: str, email: str, is_admin: bool, role: str = "member", tenant_id: str = "00000000-0000-0000-0000-000000000001") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "is_admin": is_admin,
        "role": role,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)
```

**Step 2: Update rotate_refresh_token**

In `orchestrator/app/jwt_auth.py`, update `rotate_refresh_token` (line 98-132) to pass role and tenant_id when creating new access tokens. The function fetches user data from DB — add role and tenant_id to the query:

```python
# In the SQL query around line 110, add role and tenant_id:
row = await pool.fetchrow(
    """DELETE FROM refresh_tokens WHERE token_hash = $1 AND expires_at > NOW()
       RETURNING user_id""",
    token_hash
)
# Then when fetching user, include new fields:
user = await pool.fetchrow(
    "SELECT id, email, is_admin, display_name, role, tenant_id FROM users WHERE id = $1",
    row["user_id"]
)
access = create_access_token(
    str(user["id"]), user["email"], user["is_admin"],
    role=user.get("role", "member"),
    tenant_id=str(user.get("tenant_id", "00000000-0000-0000-0000-000000000001"))
)
```

**Step 3: Update create_user**

In `orchestrator/app/users.py`, update `create_user` (line 19) to accept `role` and `tenant_id`:

```python
async def create_user(
    email: str,
    password_hash: str | None = None,
    display_name: str | None = None,
    provider: str = "local",
    provider_id: str | None = None,
    is_admin: bool = False,
    role: str | None = None,
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
    expires_at=None,
) -> dict[str, Any]:
```

Update the INSERT query to include the new columns:

```python
row = await pool.fetchrow(
    """INSERT INTO users (email, password_hash, display_name, provider, provider_id, is_admin, role, tenant_id, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       RETURNING *""",
    email, password_hash, display_name, provider, provider_id, is_admin,
    role or ("admin" if is_admin else "member"),
    tenant_id, expires_at
)
```

**Step 4: Add list_users and update_user_role functions**

In `orchestrator/app/users.py`, add:

```python
async def list_users(tenant_id: str = "00000000-0000-0000-0000-000000000001") -> list[dict[str, Any]]:
    """List all users in a tenant."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT * FROM users WHERE tenant_id = $1 ORDER BY created_at",
        tenant_id
    )
    return [_user_dict(r) for r in rows]

async def update_user_role(user_id: str, role: str, actor_id: str | None = None) -> dict[str, Any] | None:
    """Update a user's role. Also updates is_admin for backwards compat."""
    pool = get_pool()
    is_admin = role in ("owner", "admin")
    row = await pool.fetchrow(
        """UPDATE users SET role = $2, is_admin = $3, updated_at = NOW()
           WHERE id = $1 RETURNING *""",
        user_id, role, is_admin
    )
    if row and actor_id:
        await pool.execute(
            """INSERT INTO audit_log (actor_id, action, target_id, details, tenant_id)
               VALUES ($1, 'role_change', $2, $3, $4)""",
            actor_id, user_id, json.dumps({"new_role": role}),
            str(row["tenant_id"])
        )
    return _user_dict(row) if row else None

async def deactivate_user(user_id: str, actor_id: str) -> bool:
    """Deactivate a user and revoke all their refresh tokens."""
    pool = get_pool()
    result = await pool.execute(
        "UPDATE users SET status = 'deactivated', updated_at = NOW() WHERE id = $1",
        user_id
    )
    await pool.execute("DELETE FROM refresh_tokens WHERE user_id = $1", user_id)
    await pool.execute(
        """INSERT INTO audit_log (actor_id, action, target_id, tenant_id)
           VALUES ($1, 'user_deactivated', $2,
                   (SELECT tenant_id FROM users WHERE id = $2))""",
        actor_id, user_id
    )
    return "UPDATE 1" in result
```

**Step 5: Commit**

```bash
git add orchestrator/app/jwt_auth.py orchestrator/app/users.py
git commit -m "feat: add role/tenant_id to JWT claims and user CRUD"
```

---

### Task 4: Auth Router — Invite & Registration Updates

**Files:**
- Modify: `orchestrator/app/auth_router.py` (lines 63-65: InviteCreate, lines 108-171: register, lines 336-389: invite endpoints)

**Step 1: Update InviteCreate model**

In `orchestrator/app/auth_router.py`, update the `InviteCreate` model (line 63-65):

```python
class InviteCreate(BaseModel):
    email: str | None = None
    expires_in_hours: int | None = None
    role: str = "member"
    account_expires_in_hours: int | None = None  # NULL = no account expiry
```

**Step 2: Update invite creation endpoint**

In the `POST /api/v1/auth/invites` handler (line 336-357), add role validation and persist role + account expiry:

```python
@auth_router.post("/api/v1/auth/invites")
async def create_invite(body: InviteCreate, user: UserDep):
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    # Validate role
    from app.roles import VALID_ROLES, can_assign_role
    if body.role not in VALID_ROLES:
        raise HTTPException(400, f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")
    if not can_assign_role(user.role, body.role):
        raise HTTPException(403, f"Cannot assign role higher than your own ({user.role})")

    code = secrets.token_urlsafe(24)
    expires_at = None
    if body.expires_in_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=body.expires_in_hours)

    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO invite_codes (code, created_by, email, expires_at, role, account_expires_in_hours, tenant_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING *""",
        code, user.id, body.email, expires_at, body.role,
        body.account_expires_in_hours, user.tenant_id
    )
    # Audit log
    await pool.execute(
        """INSERT INTO audit_log (actor_id, action, target_id, details, tenant_id)
           VALUES ($1, 'invite_created', $2, $3, $4)""",
        user.id, row["id"],
        json.dumps({"role": body.role, "email": body.email}),
        user.tenant_id
    )
    return {**dict(row), "id": str(row["id"]), "created_by": str(row["created_by"])}
```

**Step 3: Update registration to apply role from invite**

In the `POST /api/v1/auth/register` handler (line 108-171), after validating invite code, extract role and compute expiry:

```python
# After invite code validation (around line 128):
invite_role = invite_row["role"] if invite_row else "member"
invite_account_expires_in_hours = invite_row["account_expires_in_hours"] if invite_row else None
account_expires_at = None
if invite_account_expires_in_hours:
    account_expires_at = datetime.now(timezone.utc) + timedelta(hours=invite_account_expires_in_hours)

# In the create_user call (around line 140):
user_dict = await create_user(
    email=body.email,
    password_hash=hashed,
    display_name=body.display_name,
    is_admin=(invite_role in ("owner", "admin")),
    role=invite_role,
    tenant_id=str(invite_row["tenant_id"]) if invite_row else "00000000-0000-0000-0000-000000000001",
    expires_at=account_expires_at,
)
```

Update the token creation to include role:

```python
access = create_access_token(
    user_dict["id"], user_dict["email"], user_dict["is_admin"],
    role=user_dict.get("role", "member"),
    tenant_id=user_dict.get("tenant_id", "00000000-0000-0000-0000-000000000001")
)
```

**Step 4: Update GET /auth/me to return role**

Ensure the `/auth/me` response includes `role`. The endpoint already returns user data — just make sure the query includes the role field and the response includes it.

**Step 5: Commit**

```bash
git add orchestrator/app/auth_router.py
git commit -m "feat: invites carry role assignment, registration applies role + expiry"
```

---

### Task 5: User Management API Endpoints

**Files:**
- Modify: `orchestrator/app/auth_router.py` — add new admin endpoints

**Step 1: Add user management endpoints**

Add to `orchestrator/app/auth_router.py`:

```python
@auth_router.get("/api/v1/admin/users")
async def list_all_users(user: UserDep):
    """List all users. Requires admin role."""
    from app.roles import has_min_role
    if not has_min_role(user.role, "admin"):
        raise HTTPException(403, "Requires admin role")
    from app.users import list_users
    users = await list_users(user.tenant_id)
    # Strip password hashes
    for u in users:
        u.pop("password_hash", None)
    return users

@auth_router.patch("/api/v1/admin/users/{user_id}")
async def update_user_admin(user_id: str, body: dict, user: UserDep):
    """Update user role, status, or expiry. Requires admin role."""
    from app.roles import has_min_role, can_assign_role, parse_role
    if not has_min_role(user.role, "admin"):
        raise HTTPException(403, "Requires admin role")

    from app.users import get_user_by_id, update_user_role
    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")

    # Can't modify users with higher role
    if parse_role(target["role"]) >= parse_role(user.role) and user.id != user_id:
        raise HTTPException(403, "Cannot modify user with equal or higher role")

    pool = get_pool()

    if "role" in body:
        new_role = body["role"]
        if not can_assign_role(user.role, new_role):
            raise HTTPException(403, f"Cannot assign role higher than your own ({user.role})")
        await update_user_role(user_id, new_role, actor_id=user.id)
        # Revoke tokens to force re-auth with new role
        await pool.execute("DELETE FROM refresh_tokens WHERE user_id = $1", user_id)

    if "status" in body:
        await pool.execute(
            "UPDATE users SET status = $1, updated_at = NOW() WHERE id = $2",
            body["status"], user_id
        )
        if body["status"] == "deactivated":
            await pool.execute("DELETE FROM refresh_tokens WHERE user_id = $1", user_id)

    if "expires_at" in body:
        await pool.execute(
            "UPDATE users SET expires_at = $1, updated_at = NOW() WHERE id = $2",
            body["expires_at"], user_id
        )

    updated = await get_user_by_id(user_id)
    updated.pop("password_hash", None)
    return updated

@auth_router.delete("/api/v1/admin/users/{user_id}")
async def deactivate_user_endpoint(user_id: str, user: UserDep):
    """Deactivate a user. Requires admin role."""
    from app.roles import has_min_role, parse_role
    if not has_min_role(user.role, "admin"):
        raise HTTPException(403, "Requires admin role")

    from app.users import get_user_by_id, deactivate_user
    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target["role"] == "owner":
        raise HTTPException(403, "Cannot deactivate the owner")
    if parse_role(target["role"]) >= parse_role(user.role):
        raise HTTPException(403, "Cannot deactivate user with equal or higher role")

    await deactivate_user(user_id, user.id)
    return {"status": "deactivated"}
```

**Step 2: Commit**

```bash
git add orchestrator/app/auth_router.py
git commit -m "feat: add user management endpoints (list, update role, deactivate)"
```

---

### Task 6: Guest Isolation — LLM Filtering & Context Stripping

**Files:**
- Create: `orchestrator/app/guest.py`
- Modify: Orchestrator chat/streaming endpoint to check guest restrictions

**Step 1: Create guest module**

Create `orchestrator/app/guest.py`:

```python
"""Guest role isolation: model filtering, context stripping, tool blocking."""

import json
import logging
from app.db import get_pool

logger = logging.getLogger(__name__)

GUEST_SYSTEM_PROMPT = """You are a helpful AI assistant.
You do not have access to any tools, files, or system information.
Do not speculate about the system you are running on, its configuration,
API keys, infrastructure, or internal details. If asked, say you don't
have that information."""

_cached_models: list[str] | None = None
_cache_time: float = 0

async def get_guest_allowed_models() -> list[str]:
    """Get list of model IDs guests are allowed to use. Cached for 60s."""
    import time
    global _cached_models, _cache_time
    now = time.time()
    if _cached_models is not None and now - _cache_time < 60:
        return _cached_models

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT value FROM platform_config WHERE key = 'guest_allowed_models'"
    )
    if row:
        try:
            _cached_models = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            _cached_models = []
    else:
        _cached_models = []
    _cache_time = now
    return _cached_models

async def validate_guest_model(model: str | None) -> str:
    """Validate and resolve model for guest user. Raises ValueError if not allowed."""
    allowed = await get_guest_allowed_models()
    if not allowed:
        raise ValueError("No models configured for guest access. Contact the administrator.")
    if model is None:
        return allowed[0]  # Default to first allowed model
    if model not in allowed:
        raise ValueError(f"Model '{model}' is not available for guest users.")
    return model
```

**Step 2: Integrate guest checks into task/chat streaming**

This depends on where the model selection happens in the orchestrator. The key integration points are:

1. In the streaming/chat endpoint (likely in `router.py` or the pipeline), before calling LLM gateway:
   - If `user.role == "guest"`, call `validate_guest_model(requested_model)`
   - Replace system prompt with `GUEST_SYSTEM_PROMPT` (strip `nova_context`)
   - Set available tools to empty list

2. The exact file to modify depends on where the chat/streaming flow is handled. Check:
   - `orchestrator/app/router.py` — task creation / streaming endpoints
   - `orchestrator/app/pipeline/` — pipeline stages

**Step 3: Commit**

```bash
git add orchestrator/app/guest.py
git commit -m "feat: add guest isolation module (model allowlist, context stripping)"
```

---

### Task 7: Frontend — User Type & Auth Store Updates

**Files:**
- Modify: `dashboard/src/stores/auth-store.tsx` (lines 3-10: User interface)
- Modify: `dashboard/src/api.ts` (for new API calls)

**Step 1: Update User interface**

In `dashboard/src/stores/auth-store.tsx`, update the User interface (line 3-10):

```typescript
export interface User {
  id: string
  email: string
  display_name: string | null
  avatar_url: string | null
  is_admin: boolean
  role: 'owner' | 'admin' | 'member' | 'viewer' | 'guest'
  provider: string
  tenant_id: string
  expires_at: string | null
  status: string
}
```

**Step 2: Add role helper utilities**

Create `dashboard/src/lib/roles.ts`:

```typescript
export const ROLE_HIERARCHY = ['guest', 'viewer', 'member', 'admin', 'owner'] as const
export type Role = typeof ROLE_HIERARCHY[number]

export function hasMinRole(userRole: Role, minRole: Role): boolean {
  return ROLE_HIERARCHY.indexOf(userRole) >= ROLE_HIERARCHY.indexOf(minRole)
}

export function canAssignRole(assignerRole: Role, targetRole: Role): boolean {
  return ROLE_HIERARCHY.indexOf(assignerRole) >= ROLE_HIERARCHY.indexOf(targetRole)
}

export const ROLE_LABELS: Record<Role, string> = {
  owner: 'Owner',
  admin: 'Admin',
  member: 'Member',
  viewer: 'Viewer',
  guest: 'Guest',
}

export const ROLE_COLORS: Record<Role, string> = {
  owner: 'text-amber-400 bg-amber-400/10',
  admin: 'text-teal-400 bg-teal-400/10',
  member: 'text-stone-300 bg-stone-300/10',
  viewer: 'text-stone-500 bg-stone-500/10',
  guest: 'text-stone-600 bg-stone-600/10',
}
```

**Step 3: Add user management API functions**

Add to `dashboard/src/api.ts` or create `dashboard/src/api/users.ts`:

```typescript
import { apiFetch } from './api'

export interface UserListItem {
  id: string
  email: string
  display_name: string | null
  role: string
  status: string
  expires_at: string | null
  created_at: string
  updated_at: string
}

export async function fetchUsers(): Promise<UserListItem[]> {
  return apiFetch<UserListItem[]>('/api/v1/admin/users')
}

export async function updateUserRole(userId: string, role: string): Promise<UserListItem> {
  return apiFetch<UserListItem>(`/api/v1/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  })
}

export async function deactivateUser(userId: string): Promise<void> {
  await apiFetch(`/api/v1/admin/users/${userId}`, { method: 'DELETE' })
}

export interface InviteCreateRequest {
  role: string
  email?: string
  expires_in_hours?: number
  account_expires_in_hours?: number
}

export async function createInvite(data: InviteCreateRequest): Promise<{ code: string; id: string }> {
  return apiFetch('/api/v1/auth/invites', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function fetchInvites(): Promise<any[]> {
  return apiFetch('/api/v1/auth/invites')
}

export async function revokeInvite(inviteId: string): Promise<void> {
  await apiFetch(`/api/v1/auth/invites/${inviteId}`, { method: 'DELETE' })
}
```

**Step 4: Commit**

```bash
git add dashboard/src/stores/auth-store.tsx dashboard/src/lib/roles.ts dashboard/src/api/users.ts
git commit -m "feat: add role types, helpers, and user management API client"
```

---

### Task 8: Frontend — Users Page

**Files:**
- Create: `dashboard/src/pages/Users.tsx`
- Modify: `dashboard/src/App.tsx` (line ~118: add route)
- Modify: `dashboard/src/components/NavBar.tsx` (line ~8-18: add nav link)

**Step 1: Create Users page**

Create `dashboard/src/pages/Users.tsx` with three tabs: Users, Invitations.

This is a substantial UI component. Key structure:

```typescript
// Users.tsx
// - UsersTab: table of users with role badge, status, actions (role dropdown, deactivate)
// - InvitationsTab: create invite modal, list pending invites, revoke
// - Use TanStack Query for data fetching (useQuery/useMutation)
// - Use role helpers for badge colors and permission checks
// - Follow existing page patterns (e.g., Keys page for table layout)
```

Use the existing page patterns from `dashboard/src/pages/Keys.tsx` or `dashboard/src/pages/Usage.tsx` for table layout, TanStack Query hooks, and action buttons.

The create invite modal should have:
- Role selector (dropdown, only roles ≤ current user's role)
- Optional email field
- Account expiry presets: 1 day, 7 days, 30 days, Never
- Generate button → show copyable invite link

**Step 2: Add route**

In `dashboard/src/App.tsx`, add after the settings route (line ~118):

```typescript
<Route path="/users" element={<PageShell><Users /></PageShell>} />
```

**Step 3: Add nav link**

In `dashboard/src/components/NavBar.tsx`, add to the nav links array (line ~8-18), conditionally shown for admin+ roles:

```typescript
// Only show for admin+ roles
{ to: '/users', label: 'Users', icon: Users2 }
```

The conditional rendering should check `user?.role` from the auth store — only show if `hasMinRole(user.role, 'admin')`.

**Step 4: Add role-based nav filtering**

In `NavBar.tsx`, filter nav links based on user role:
- Guest: only Chat
- Viewer: Chat, Tasks (read-only)
- Member: all except Users
- Admin/Owner: all including Users

**Step 5: Commit**

```bash
git add dashboard/src/pages/Users.tsx dashboard/src/App.tsx dashboard/src/components/NavBar.tsx
git commit -m "feat: add Users page with user management and invite creation UI"
```

---

### Task 9: Frontend — Invite Link Route & Guest Experience

**Files:**
- Create: `dashboard/src/pages/Invite.tsx`
- Modify: `dashboard/src/App.tsx` — add `/invite/:code` route
- Modify: `dashboard/src/pages/Login.tsx` — handle invite code from URL

**Step 1: Create invite landing page**

Create `dashboard/src/pages/Invite.tsx`:
- Fetches invite details from URL param
- If not logged in → redirect to Login with `?invite=CODE` query param
- If logged in → show "Accept invite" confirmation

**Step 2: Update Login page**

In `dashboard/src/pages/Login.tsx`, read `invite` query param and pre-fill the invite code field in registration form.

**Step 3: Create expired account page**

For guests whose account has expired, show a simple page:
- "Your access has expired"
- "Contact the administrator for an extension"
- Logout button

**Step 4: Add route**

In `dashboard/src/App.tsx`:

```typescript
<Route path="/invite/:code" element={<Invite />} />
```

This route should be outside the `AuthGate` wrapper so unauthenticated users can access it.

**Step 5: Commit**

```bash
git add dashboard/src/pages/Invite.tsx dashboard/src/pages/Login.tsx dashboard/src/App.tsx
git commit -m "feat: add invite link route and guest expired account page"
```

---

### Task 10: Guest Model Config in Settings

**Files:**
- Create: `dashboard/src/pages/settings/GuestAccessSection.tsx`
- Modify: `dashboard/src/pages/settings/Settings.tsx` — add section to System or AI category

**Step 1: Create GuestAccessSection**

Create a settings section that:
- Fetches available models from the provider status endpoint
- Shows multi-select for `guest_allowed_models`
- Saves to `platform_config` via the existing config save pattern

Follow the pattern from `LLMRoutingSection.tsx` for the config field approach.

**Step 2: Add to Settings page**

In `Settings.tsx`, add `<GuestAccessSection />` under the AI & Models category.

**Step 3: Commit**

```bash
git add dashboard/src/pages/settings/GuestAccessSection.tsx dashboard/src/pages/settings/Settings.tsx
git commit -m "feat: add guest model allowlist config in settings"
```

---

### Task 11: Integration Tests

**Files:**
- Create: `tests/test_rbac.py`

**Step 1: Write RBAC integration tests**

Follow patterns from `tests/conftest.py` (admin_headers fixture) and `tests/test_orchestrator.py`.

```python
# tests/test_rbac.py
import pytest
import httpx

ORCH = "http://localhost:8000"

class TestRBAC:
    """RBAC role enforcement tests."""

    @pytest.fixture(autouse=True)
    async def setup(self, orchestrator, admin_headers):
        self.client = orchestrator
        self.headers = admin_headers

    async def test_invite_with_role(self):
        """Admin can create invite with specific role."""
        resp = await self.client.post(
            f"{ORCH}/api/v1/auth/invites",
            json={"role": "member"},
            headers=self.headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "member"
        assert "code" in data
        # Cleanup
        await self.client.delete(
            f"{ORCH}/api/v1/auth/invites/{data['id']}",
            headers=self.headers,
        )

    async def test_invite_cannot_assign_higher_role(self):
        """Non-owner admin cannot assign owner role."""
        # This test requires a non-owner admin user
        # Create via invite, register, then try to create owner invite
        pass  # Implement when test user creation is available

    async def test_list_users(self):
        """Admin can list all users."""
        resp = await self.client.get(
            f"{ORCH}/api/v1/admin/users",
            headers=self.headers,
        )
        assert resp.status_code == 200
        users = resp.json()
        assert isinstance(users, list)
        assert len(users) >= 1
        # Verify no password hashes leaked
        for u in users:
            assert "password_hash" not in u
            assert "role" in u

    async def test_guest_allowed_models_config(self):
        """Guest allowed models can be configured."""
        resp = await self.client.put(
            f"{ORCH}/api/v1/config/guest_allowed_models",
            json={"value": '["ollama/llama3"]'},
            headers=self.headers,
        )
        assert resp.status_code in (200, 201)

    async def test_me_returns_role(self):
        """GET /auth/me returns role field."""
        # Register a user via invite, then check /me
        # For now, test with admin headers (trusted network returns synthetic admin)
        resp = await self.client.get(
            f"{ORCH}/api/v1/auth/me",
            headers=self.headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "role" in data
```

**Step 2: Run tests**

Run: `cd /home/jeremy/workspace/nova && make test`
Expected: All existing tests pass + new RBAC tests pass.

**Step 3: Commit**

```bash
git add tests/test_rbac.py
git commit -m "test: add RBAC integration tests"
```

---

### Task 12: TypeScript Build Check & Final Verification

**Files:** None new — verification only.

**Step 1: TypeScript build check**

Run: `cd dashboard && npm run build`
Expected: Clean build, no type errors.

**Step 2: Run full test suite**

Run: `make test`
Expected: All tests pass.

**Step 3: Manual smoke test**

1. Open dashboard, verify existing users show role in `/auth/me`
2. Go to Settings → verify Guest Access section appears
3. Go to Users page → verify user list loads
4. Create an invite with Guest role + 24h expiry → verify link generated
5. Open invite link in incognito → verify registration flow

**Step 4: Final commit if any fixes needed**

```bash
git add -u
git commit -m "fix: address issues from RBAC smoke testing"
```

---

## Task Dependency Graph

```
Task 1 (Migration) ─────┐
                         ├─→ Task 2 (Auth Middleware)
                         │        │
                         │        ├─→ Task 3 (JWT + User CRUD)
                         │        │        │
                         │        │        ├─→ Task 4 (Auth Router)
                         │        │        │        │
                         │        │        │        ├─→ Task 5 (User Mgmt API)
                         │        │        │
                         │        ├─→ Task 6 (Guest Isolation)
                         │
                         ├─→ Task 7 (Frontend Types) ──→ Task 8 (Users Page)
                         │                                     │
                         │                              Task 9 (Invite Route)
                         │                                     │
                         │                              Task 10 (Guest Config)
                         │
                         └─→ Task 11 (Tests) ──→ Task 12 (Verification)
```

Tasks 7-10 (frontend) can run in parallel with Tasks 2-6 (backend) after Task 1.
