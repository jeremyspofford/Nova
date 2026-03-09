# RBAC & Tenant Invitations Design

> **Date:** 2026-03-08
> **Status:** Approved
> **Scope:** Role-based access control, user invitation flow, guest sandboxing, tenant-aware schema scaffolding

---

## Summary

Add granular role-based access control to Nova with five fixed roles (Owner, Admin, Member, Viewer, Guest), a link-based invitation system with role assignment, auto-expiring Guest accounts with sandboxed LLM access, and `tenant_id` scaffolding on all data tables for future multi-tenancy.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Tenant model | Single-tenant now, tenant-aware schema | Avoid over-engineering; `tenant_id` columns ready for Phase 13 |
| Permission model | Fixed roles | Covers 95% of use cases, simple to build/audit, upgrade path to composable later |
| Invitation flow | Link-only (email delivery later) | No SMTP dependency; invite codes already built |
| Guest model access | Admin-configured allowlist | Flexible — admin decides what "free" means |
| Guest guardrails | Isolated context + guardrail prompt | Defense in depth — LLM never receives secrets |
| Guest expiry | Account-level auto-expiry | Real account (conversation history), auto-cleanup |
| Enforcement point for guest models | Orchestrator | Auth stays in orchestrator, gateway stays role-agnostic |

---

## Roles & Permissions

Five fixed roles, ordered by privilege:

| Role | Chat | Run Tasks | Own Data | Manage Users | System Config | Manage Tenant |
|---|---|---|---|---|---|---|
| **Owner** | All models | Yes | All users' data | Yes | Yes | Yes (transfer, delete) |
| **Admin** | All models | Yes | All users' data | Yes (can't remove Owner) | Yes | No |
| **Member** | All models | Yes | Own only | No | No | No |
| **Viewer** | No | No | Read-only own | No | No | No |
| **Guest** | Guest-allowed models only | No | Own only (isolated context) | No | No | No |

**Role hierarchy:** Owner > Admin > Member > Viewer > Guest. Users can only assign roles at or below their own level.

### Guest Restrictions

- No `nova_context` injection (no architecture/infra info in system prompt)
- No tool access (no shell, file I/O, git, search)
- No memory service access
- Guardrail system prompt prepended to every LLM call
- Auto-expires after admin-configured duration (default 24h)

### Guest System Prompt

```
You are a helpful AI assistant.
You do not have access to any tools, files, or system information.
Do not speculate about the system you are running on, its configuration,
API keys, infrastructure, or internal details. If asked, say you don't
have that information.
```

Replaces `nova_context` for Guest role.

---

## Database Schema

### Modified Tables

```sql
-- users: add role, tenant scaffolding, expiry
ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
ALTER TABLE users ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE users ADD COLUMN expires_at TIMESTAMPTZ;        -- NULL = never expires
ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active';  -- active | expired | deactivated

-- invite_codes: add role assignment and account expiry
ALTER TABLE invite_codes ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
ALTER TABLE invite_codes ADD COLUMN account_expires_in_hours INTEGER;  -- NULL = no expiry
ALTER TABLE invite_codes ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';

-- tenant_id scaffolding on data tables (all default to single tenant)
ALTER TABLE conversations ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE tasks ADD COLUMN tenant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001';
-- Same pattern for: memories, api_keys, usage_events, pods (where they exist)
```

### New Tables

```sql
-- Tenant table (one row for now, ready for multi-tenancy)
CREATE TABLE tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO tenants (id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'Default');

-- Audit log for security-sensitive actions
CREATE TABLE audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    UUID REFERENCES users(id),
    action      TEXT NOT NULL,          -- e.g. 'role_change', 'user_deactivated', 'invite_created'
    target_id   UUID,                   -- user/invite being acted on
    details     JSONB,                  -- before/after values, metadata
    ip_address  TEXT,
    tenant_id   UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_log_tenant ON audit_log(tenant_id, created_at DESC);
```

### Guest-Allowed Models

Stored in `platform_config` as key `guest_allowed_models`, value is a JSON array:
```json
["ollama/llama3", "groq/llama-3.1-8b-instant"]
```

### Migration Strategy

Single idempotent SQL migration file. Backfill logic:
- First user with `is_admin=true` → `role='owner'`
- Other `is_admin=true` users → `role='admin'`
- All `is_admin=false` users → `role='member'`
- `is_admin` column preserved, derived from `role IN ('owner', 'admin')` going forward

---

## API Changes

### Modified Endpoints

| Endpoint | Change |
|---|---|
| `POST /api/v1/auth/register` | Look up invite code → set `role`, `expires_at` from invite |
| `POST /api/v1/auth/invites` | Accept `role` (required), `account_expires_in_hours` (optional). Validate caller role ≤ own |
| `GET /api/v1/auth/me` | Return `role` field. Keep `is_admin` as derived for backwards compat |

### New Endpoints

| Endpoint | Min Role | Description |
|---|---|---|
| `GET /api/v1/admin/users` | Admin | List all users (role, status, last active, expiry) |
| `PATCH /api/v1/admin/users/{id}` | Admin | Change role, deactivate, extend expiry |
| `DELETE /api/v1/admin/users/{id}` | Admin | Soft-delete (deactivate, revoke tokens) |
| `GET /api/v1/admin/users/{id}/usage` | Admin | Per-user usage stats |

### JWT Claims

```python
{
    "sub": "user-uuid",
    "email": "...",
    "role": "member",
    "is_admin": true,               # derived, backwards compat
    "tenant_id": "00000000-...-01", # scaffolding
    "exp": ...,
    "type": "access"
}
```

### Auth Middleware

- `AuthenticatedUser` dataclass gains `role` and `tenant_id` fields
- New `RoleDep(min_role='admin')` — reusable FastAPI dependency checking role hierarchy
- `AdminDep` becomes `RoleDep(min_role='admin')` internally
- Guest expiry: every authenticated request checks `expires_at`, returns 403 if past

---

## Security Model

### Defense in Depth

1. **API layer (primary):** `RoleDep` middleware on every endpoint. Fail-closed — unknown role = deny.
2. **Data layer (secondary):** All queries include `WHERE tenant_id = $tenant`. Member/Viewer/Guest queries also include `AND user_id = $user`. Prevents horizontal privilege escalation.
3. **Token layer:** `role` and `tenant_id` in signed JWT. Server derives permissions from token, not request params.

### Guest Isolation

| Attack Vector | Mitigation |
|---|---|
| Prompt injection for secrets | Secrets never in Guest LLM context |
| Accessing other users' data | Queries scoped to `user_id` + `tenant_id` |
| Using non-allowed models | Orchestrator checks role against `guest_allowed_models` allowlist |
| Using tools (shell, files, git) | Tool dispatch checks role — Guest has empty tool set |
| Staying past expiry | Expiry checked on every request, not just login |
| Manipulating invite for higher role | Role stored server-side on `invite_codes` row |

### Role Change Propagation

- Role change or deactivation → revoke all user's refresh tokens immediately
- Add user ID to Redis deny-list (TTL=15min) for immediate access token invalidation
- Audit log entry created for every role change

---

## Dashboard UI

### New "Users" Page (Owner/Admin only)

**Users tab:**
- Table: avatar, name, email, role badge, status, last active, created date
- Row actions: change role (dropdown), deactivate, extend expiry
- Owner row visually distinct, not modifiable by Admins

**Invitations tab:**
- "Create Invite" button → modal with role selector, optional email restriction, expiry presets (1 day, 7 days, 30 days, never)
- Generates link with copy-to-clipboard
- Table of pending invites with revoke action

**Activity tab (future v2):**
- Audit log, per-user usage breakdown

### Role-Based Nav Visibility

- **Guest:** Chat only. No Settings, Tasks, sidebar admin sections.
- **Viewer:** Full nav, everything read-only (action buttons hidden/disabled).
- **Member:** Full nav, own data only.
- **Admin/Owner:** Full nav + Users page in sidebar.

### Invite Link Flow (Recipient)

1. Click `/invite/{code}` → registration form with invite pre-filled
2. If logged in → "Accept invite?" confirmation
3. Account created with role + expiry from invite
4. Redirect to Chat (Guest/Member) or Dashboard (Admin)

### Expired Guest Experience

Redirect to "Your access has expired" page with option to contact admin.

---

## Guest Model Filtering

**Enforcement:** Orchestrator (not LLM gateway — keep auth concerns out of the router).

1. Guest submits chat message
2. Orchestrator checks `role` from JWT
3. If Guest: fetch `guest_allowed_models` from `platform_config` (cached in Redis)
4. Requested model not in allowlist → 403
5. No model specified → default to first in Guest allowlist

---

## Out of Scope (Future)

- Email-based invitation delivery (requires SMTP setup)
- Custom/composable roles
- Multi-tenant with separate tenant creation
- Per-role rate limiting
- Activity tab with audit log UI
