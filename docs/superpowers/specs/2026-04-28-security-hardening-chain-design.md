---
title: Security Hardening Chain (Audit Findings #1–#5)
date: 2026-04-28
status: approved
---

# Security Hardening Chain — Design

## Goals

Close the five interlocking security gaps surfaced by the 2026-04-28 audit:

1. **#5** — Strip silent admin-secret-as-user-token fallback from `require_user`
2. **#2** — Randomize admin secret on install; refuse to start with the literal default
3. **#1** — Recovery service: CORS allowlist, critical-service restart guards, exact container match
4. **#4** — Cortex service: CORS allowlist
5. **#3** — Google OAuth: `state` parameter (CSRF protection); strip user-supplied `redirect_uri` fallback

The fixes interlock — the cumulative effect is that the admin secret stops being a god-mode credential and becomes a system-admin credential with bounded blast radius.

## Non-goals

Each of these is intentionally deferred to a follow-up design:

- **Rotate admin secret button (dashboard)** — deferred to the future built-in secret manager. Rationale: building `.env`-writing infrastructure now would be throwaway code. CLI rotation remains the supported path until the secret manager exists.
- **Built-in secret manager** — separate brainstorm + design.
- **PKCE on OAuth** — `state` alone closes the CSRF hole. PKCE is a defense-in-depth follow-up.
- **Service-account JWTs for internal workers** — workers currently use `AdminDep` endpoints exclusively; admin secret is the correct credential for service-to-service calls until we have proper service-account tokens.
- **Retiring admin secret entirely in favor of `is_admin` JWT claim** — long-term direction; out of scope for this sprint.
- **Cortex config refactor (raw `os.getenv` → `BaseSettings`)** — flagged in the code-quality audit; touched lightly here (only adding `cors_allowed_origins`). Full refactor is its own change.

## Sequencing rationale

The order is structured so each fix cannot break the next:

| # | Fix | Why this position |
|---|---|---|
| 1 | #5 (strip fallback) | Smallest diff, biggest privilege reduction. All downstream fixes are safer because the admin secret is no longer god-mode. |
| 2 | #2 (randomize on install) | Now safe — even if the new strong secret leaks, blast radius is bounded. |
| 3 | #1 (recovery) | Defense-in-depth on the most privileged service. |
| 4 | #4 (cortex CORS) | Same pattern as #1, trivial. |
| 5 | #3 (OAuth state) | Independent; can land in parallel with #1/#4 if convenient. |

Each fix is its own commit. All commits are independently revertable.

---

## Fix #5 — Strip admin-secret-as-user-token fallback

### Current state

`orchestrator/app/auth.py:264-403` defines `require_user`. Lines 396–397:

```python
# Fallback: admin secret (backward compat for existing dashboard sessions)
if x_admin_secret and x_admin_secret == await get_admin_secret():
    return _SYNTHETIC_ADMIN
```

This means any request with the admin secret header is treated as the synthetic admin user (tenant `00000000-...0001`), even on tenant-scoped user endpoints. Combined with the default `nova-admin-secret-change-me` (#2), every fresh install is "log in as anyone" by header.

### Verified worker call paths

Workers using `X-Admin-Secret` to call orchestrator:

- `intel-worker/app/client.py:27` — only hits `AdminDep` endpoints (`/api/v1/intel/feeds/{id}/status`, `/api/v1/intel/content`, `/api/v1/intel/recommendations`)
- `knowledge-worker/app/client.py:28` — only hits `AdminDep` endpoints (`/api/v1/knowledge/sources/{id}/status`, `/api/v1/knowledge/crawl-log`)

The fallback is dead code for these callers. Stripping it does **not** break any internal service.

### Change

Remove lines 395–397 from `require_user` (`orchestrator/app/auth.py`). Update the module docstring at lines 7–11 to reflect that `UserDep` is JWT-only.

### Files touched

- `orchestrator/app/auth.py:7-11` — docstring
- `orchestrator/app/auth.py:264-267` — drop `x_admin_secret` parameter from `require_user` signature
- `orchestrator/app/auth.py:395-397` — delete fallback block

### Tests

`orchestrator/tests/test_auth.py` (extend existing):

- New negative test: request to a `UserDep`-protected endpoint with only `X-Admin-Secret` (no JWT) returns 401
- Confirm existing positive tests for `UserDep` (with valid JWT) still pass
- Confirm existing positive tests for `AdminDep` (with valid `X-Admin-Secret`) still pass

Integration test (`tests/test_auth_isolation.py`, new file):

- Call `/api/v1/knowledge/sources` (UserDep) with admin secret only → 401
- Call `/api/v1/knowledge/sources/{id}/status` (AdminDep) with admin secret only → 200
- Confirm worker-equivalent call patterns continue to function

---

## Fix #2 — Randomize admin secret on install

### Current state

`orchestrator/app/config.py:40`:
```python
nova_admin_secret: str = "nova-admin-secret-change-me"
```

`scripts/install.sh` does not generate a random value. Fresh installs ship with the literal default until manually changed.

### Change

**A. Install-time generation (`scripts/install.sh`)**

When materializing `.env`, after sourcing/copying `.env.example`:

```bash
# Generate strong admin secret if missing or default
if grep -qE '^NOVA_ADMIN_SECRET=(nova-admin-secret-change-me|)$' .env 2>/dev/null \
   || ! grep -q '^NOVA_ADMIN_SECRET=' .env; then
  NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  if grep -q '^NOVA_ADMIN_SECRET=' .env; then
    sed -i.bak "s|^NOVA_ADMIN_SECRET=.*|NOVA_ADMIN_SECRET=${NEW_SECRET}|" .env && rm -f .env.bak
  else
    echo "NOVA_ADMIN_SECRET=${NEW_SECRET}" >> .env
  fi
  GENERATED_ADMIN_SECRET="$NEW_SECRET"
fi
```

At end of install, if `GENERATED_ADMIN_SECRET` is set, print:

```
✓ Generated admin secret: <value>
  Save this to your password manager. It's also stored in .env as NOVA_ADMIN_SECRET.
  This is the only time it will be displayed.
```

Honor pre-set `NOVA_ADMIN_SECRET=...` env vars (CI/automation case): if the env var is already set when `install.sh` runs, write that value rather than generating.

**B. Startup guard (orchestrator, recovery, cortex)**

Add to each service's startup (in `lifespan` startup phase):

```python
if settings.nova_admin_secret == "nova-admin-secret-change-me":
    if os.getenv("NOVA_ALLOW_DEFAULT_ADMIN_SECRET") != "1":
        raise RuntimeError(
            "NOVA_ADMIN_SECRET is set to the literal default. "
            "Run scripts/install.sh to generate a strong secret, "
            "or set NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1 to bypass (dev/test only)."
        )
    log.warning("NOVA_ADMIN_SECRET is the literal default — bypass active. Do not use in production.")
```

The escape hatch `NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1` exists for the test suite (which uses the default value via fixtures).

### Files touched

- `scripts/install.sh` — generation + display logic
- `orchestrator/app/main.py` (or `config.py`) — startup guard
- `recovery-service/app/main.py` — startup guard
- `cortex/app/main.py` — startup guard
- `tests/conftest.py` (or wherever fixtures live) — set `NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1` for the test process

### Tests

- Shell test (`tests/test_install_secret.sh` or extend an existing setup test): run `install.sh` against a tmpdir, assert `.env` does not contain the literal default
- Integration smoke: services start successfully with `NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1` and the test default; services refuse to start without it

---

## Fix #1 — Recovery service: CORS, restart guards, exact match

### Current state

Three issues, same file:

- `recovery-service/app/main.py:54` — `allow_origins=["*"]`
- `recovery-service/app/docker_client.py:159` — `restart_service()` has no critical-service guard; also uses substring match (`if service_name in c.name`)
- `recovery-service/app/docker_client.py:197` — `get_container_logs()` has the same substring issue (read-only impact, but inconsistent)

### Change

**A. CORS allowlist** — replace `recovery-service/app/main.py:52-58` with the orchestrator pattern:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Add to `recovery-service/app/config.py`:
```python
cors_allowed_origins: str = "http://localhost:3000,http://localhost:5173"
```

**B. Critical-service guards** — at the top of `recovery-service/app/docker_client.py`:

```python
CRITICAL_SERVICES = frozenset({"postgres", "redis", "recovery"})
```

Wrap `restart_service`:

```python
def restart_service(service_name: str) -> dict:
    """Restart a Nova service container. Refuses critical services."""
    if service_name in CRITICAL_SERVICES:
        return {
            "service": service_name, "action": "rejected", "ok": False,
            "error": f"{service_name} is a critical service. Restart it via 'docker compose restart {service_name}' from the host.",
        }
    ...
```

**C. Exact container match** — replace `if service_name in c.name and ("nova" in c.name or service_name == c.name)` (line 163) with a Docker-label match:

```python
expected_label = service_name
for c in containers:
    if c.labels.get("com.docker.compose.service") == expected_label:
        c.restart(timeout=30)
        return {"service": service_name, "action": "restarted", "ok": True}
return {"service": service_name, "action": "not_found", "ok": False, ...}
```

Apply the same fix to `get_container_logs()` at line 197.

### Files touched

- `recovery-service/app/main.py:52-58`
- `recovery-service/app/config.py` — add `cors_allowed_origins`
- `recovery-service/app/docker_client.py:1-10` (add CRITICAL_SERVICES)
- `recovery-service/app/docker_client.py:159-170` (guard + label match)
- `recovery-service/app/docker_client.py:194-203` (label match in `get_container_logs`)

### Tests

`tests/test_recovery.py` (extend):

- `restart_service("postgres")` returns rejected with `ok: False`
- `restart_service("redis")` returns rejected
- `restart_service("recovery")` returns rejected
- `restart_service("post")` returns `not_found` (not "accidentally restarted postgres")
- Existing positive tests (restart valid service) still pass via label match

---

## Fix #4 — Cortex CORS allowlist

### Current state

`cortex/app/main.py:89` — `allow_origins=["*"]`. Cortex's config (`cortex/app/config.py`) uses raw `os.getenv()`, no `cors_allowed_origins` setting.

### Change

Add to `cortex/app/config.py`:
```python
cors_allowed_origins: str = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
```

Update `cortex/app/main.py:89`:
```python
allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
```

### Files touched

- `cortex/app/config.py` — add `cors_allowed_origins`
- `cortex/app/main.py:89`

### Tests

Integration test (`tests/test_cortex.py` or new): assert response from cortex `/health/live` does not include `Access-Control-Allow-Origin: *` for an unrecognized origin.

---

## Fix #3 — Google OAuth: state + redirect_uri allowlist

### Current state

- `orchestrator/app/oauth.py:22` — `get_google_auth_url(redirect_uri)` does not include a `state` query param
- `orchestrator/app/auth_router.py:379` — `redirect_uri = body.get("redirect_uri", str(request.url_for("google_callback")))` accepts client-supplied value

### Change

**A. State parameter (CSRF protection)**

`orchestrator/app/oauth.py`:

```python
def get_google_auth_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
```

`orchestrator/app/auth_router.py` — endpoint that returns the auth URL:

```python
@router.get("/api/v1/auth/google/url")
async def google_auth_url(request: Request):
    state = secrets.token_urlsafe(32)
    redirect_uri = str(request.url_for("google_callback"))
    redis = await get_redis()
    await redis.set(f"nova:oauth:state:{state}", redirect_uri, ex=600)
    return {"url": get_google_auth_url(redirect_uri, state), "state": state}
```

`google_callback` endpoint:

```python
@router.post("/api/v1/auth/google/callback", name="google_callback")
async def google_callback(request: Request, body: dict):
    state = body.get("state")
    if not state:
        raise HTTPException(400, "Missing state parameter")
    redis = await get_redis()
    stored_redirect_uri = await redis.getdel(f"nova:oauth:state:{state}")
    if not stored_redirect_uri:
        raise HTTPException(400, "Invalid or expired state token")
    redirect_uri = stored_redirect_uri.decode() if isinstance(stored_redirect_uri, bytes) else stored_redirect_uri
    code = body.get("code")
    google_user = await exchange_google_code(code, redirect_uri)
    ...
```

Single-use semantics enforced via `GETDEL`. 10-minute TTL.

**B. Strip user-supplied `redirect_uri` fallback** — done by the changes above (the callback no longer reads `redirect_uri` from the request body; it reads from Redis using the state token as the key).

### Files touched

- `orchestrator/app/oauth.py:22-31` — add `state` parameter
- `orchestrator/app/auth_router.py` — `google_auth_url` endpoint generates and stores state
- `orchestrator/app/auth_router.py:379-380` — `google_callback` validates state and uses stored `redirect_uri`
- Dashboard: `dashboard/src/pages/Login.tsx` (or wherever OAuth flow is initiated) — pass `state` from auth-url response into the callback request

### Tests

`tests/test_oauth_flow.py` (new file):

- State mismatch: callback with wrong state returns 400
- Replayed state: same state used twice returns 400 on second use (single-use enforcement)
- Expired state: simulate by waiting past TTL or manually `DEL`ing the key, returns 400
- Missing state: callback without state returns 400
- Happy path: state generated by `/url` endpoint validates correctly on callback (mocked Google exchange)
- User-supplied `redirect_uri` in callback body is ignored (no longer read)

---

## Cross-cutting

### TDD ordering per fix

For each fix:
1. Write the failing test
2. Make the minimal code change to pass
3. Run `make test-quick` (health endpoints) for fast feedback
4. Run `make test` (full integration suite) before commit
5. Commit (one fix per commit)

### Commit boundaries

Five commits, one per fix, in the sequence above. Each commit:
- Touches only the files listed in its section
- Includes its own tests
- Has a `fix(security):` prefix in the message
- Does not break existing tests

Push directly to `main` per the project workflow (no branches/PRs).

### Documentation updates

After all five fixes land, update:

- `website/src/content/docs/nova/docs/security.md` — note the new behaviors (state parameter on OAuth, restart guards on recovery, refusal to start with default secret)
- `website/src/content/changelog/2026-04-28-security-hardening.md` — new entry summarizing the chain
- `CLAUDE.md` — already mostly accurate; note the directory rename `recovery/` → `recovery-service/` if it isn't already

### Out-of-scope follow-ups (track separately)

- Built-in secret manager design (will absorb the deferred rotate-button feature)
- Service-account JWTs (replace `X-Admin-Secret` for internal worker calls)
- PKCE on OAuth flow
- Cortex config refactor (`os.getenv` → `BaseSettings`)
- Retire admin secret entirely in favor of `is_admin` JWT claim (long-term direction)
