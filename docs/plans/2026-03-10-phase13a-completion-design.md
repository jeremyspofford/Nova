# Phase 13a Completion — Design

> Closes out the remaining 4 gaps in RBAC & User Invitations.
> Prerequisite: Phase 13a core (already implemented).

---

## 1. Redis Token Deny-List (Immediate Revocation)

**Problem:** JWT access tokens live 15 minutes. When an admin deactivates a user or changes their role, the old token keeps working until expiry.

**Design:**
- Key pattern: `nova:auth:denied:{user_id}` → `{"reason": "...", "at": timestamp}`
- TTL: 900s (matches JWT lifetime — after that, the token is expired anyway)
- Check: single `redis.get()` in `require_user()` (auth.py), right after JWT signature verification
- Response: 403 with message "Your access has been updated. Please log in again."

**Write triggers (set the deny-list key):**
- User deactivation (`DELETE /api/v1/admin/users/{id}`)
- Role change (`PATCH /api/v1/admin/users/{id}` with `role`)
- Password change (`PATCH /api/v1/auth/password`)
- Expiry update (`PATCH /api/v1/admin/users/{id}` with `expires_at`)

**Files:**
- `orchestrator/app/auth.py` — add deny-list check in `require_user()`, fix `time.time()` → `_time.time()` bug (line 104)
- `orchestrator/app/auth_router.py` — add Redis deny-list write on deactivation, password change
- `orchestrator/app/users.py` — add Redis deny-list write on role change, expiry update

**Redis DB:** db2 (orchestrator's existing allocation)

---

## 2. Role-Based Nav Visibility

**Problem:** Guests can see all nav links (Tasks, Pods, Keys, MCP, Agents, Memory, Models, Settings). They can't use them, but they shouldn't see them.

**Design — role → visible links:**

| Role | Visible Nav Links |
|------|-------------------|
| **Guest** | Chat only |
| **Viewer** | Chat, Tasks (read-only), Pods (read-only), Usage, Models, About |
| **Member** | Everything except Users, Settings (admin sections hidden) |
| **Admin/Owner** | Everything |

**Implementation:**
- `dashboard/src/components/NavBar.tsx` — filter `mainLinks` and `systemLinks` by user role using `hasMinRole()`
- Each link gets a `minRole` property: `'guest'`, `'viewer'`, `'member'`, or `'admin'`
- Route-level guard not needed — nav filtering is sufficient since backend endpoints already enforce auth

**Settings page visibility:**
- Guests/Viewers: hidden entirely (nav link removed)
- Members: see Identity, Appearance only
- Admin/Owner: see everything

---

## 3. Invite Route UX

**Problem:** `/invite/{code}` redirects to `/login?invite=code`. The login page auto-switches to register mode, but there's no dedicated invite experience — no welcome message, no context about who invited them or what role they'll get.

**Design:**
- `/invite/{code}` renders a dedicated page (not a redirect) with:
  - Invite validation: `GET /api/v1/auth/invites/validate/{code}` (new endpoint)
  - Shows: inviter name, assigned role, expiry info (if guest)
  - Inline registration form (email, password, display name)
  - On success: auto-login and redirect to Chat
  - Invalid/expired invite: clear error message with no registration form

**New backend endpoint:**
```
GET /api/v1/auth/invites/validate/{code}
→ { valid: bool, role: str, created_by_name: str, expires_at: str | null, account_expires_in_hours: int | null }
```
No auth required (public endpoint — the code itself is the auth).

**Files:**
- `orchestrator/app/auth_router.py` — add validate endpoint
- `dashboard/src/pages/Invite.tsx` — replace redirect with full registration page

---

## 4. Expanded Audit Logging

**Problem:** Only 3 events logged (invite_created, role_change, user_deactivated). Security-relevant actions like login, logout, and password changes aren't tracked.

**Events to add:**

| Action | Trigger | Details |
|--------|---------|---------|
| `login_success` | POST /auth/login | `{email, provider}` |
| `login_failed` | POST /auth/login (bad creds) | `{email, reason}` |
| `logout` | POST /auth/logout | `{}` |
| `password_changed` | PATCH /auth/password | `{}` |
| `invite_accepted` | POST /auth/register (with invite) | `{invite_id, role}` |
| `invite_revoked` | DELETE /auth/invites/{id} | `{invite_id}` |
| `account_expired` | require_user() expiry check | `{user_id}` |
| `token_denied` | require_user() deny-list hit | `{user_id, reason}` |

**IP address:** Populate `ip_address` column (currently NULL everywhere) using `request.client.host`.

**Helper function:** Extract a reusable `audit_rbac(pool, actor_id, action, target_id, details, ip, tenant_id)` to reduce boilerplate.

**Files:**
- `orchestrator/app/auth_router.py` — add audit calls to login, logout, register, password change, invite revoke
- `orchestrator/app/auth.py` — add audit on expiry/deny-list enforcement
- New: `orchestrator/app/audit_rbac.py` — helper function (or add to existing `audit.py`)

---

## Implementation Order

1. **Audit helper** — needed by everything else
2. **Redis deny-list** — core auth change, test thoroughly
3. **Expanded audit logging** — wire up all events using the helper
4. **Invite route UX** — new endpoint + frontend page
5. **Role-based nav** — frontend-only, lowest risk

## Migration

Single migration file `021_audit_improvements.sql`:
- No schema changes needed (rbac_audit_log already has all columns)
- Possibly add index on `action` column if query patterns warrant it
