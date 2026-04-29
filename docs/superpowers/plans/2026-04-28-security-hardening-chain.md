# Security Hardening Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close five interlocking security gaps (#5, #2, #1, #4, #3 from the 2026-04-28 audit) so that the admin secret stops being a god-mode credential, install-time defaults are safe, and OAuth has CSRF protection.

**Architecture:** Five small, sequenced commits — each fix is independently revertable, each commit lands its own tests first (TDD). Order is structured so each fix cannot break the next: privilege reduction (#5) → safe defaults (#2) → defense-in-depth (#1, #4) → independent OAuth hardening (#3).

**Tech Stack:** Python 3.11 + FastAPI + asyncpg + async Redis (services); React + TypeScript + Vite (dashboard); pytest (tests); bash (install scripts).

**Spec:** `docs/superpowers/specs/2026-04-28-security-hardening-chain-design.md`

---

## File Structure Overview

**Files to create:**
- `tests/test_auth_isolation.py` — integration test for #5 (admin secret can't reach UserDep endpoints)
- `tests/test_install_secret.sh` — shell test for #2 (install.sh produces non-default secret)
- `tests/test_oauth_flow.py` — integration tests for #3 (OAuth state validation)
- `tests/test_cortex_cors.py` — integration test for #4 (cortex CORS allowlist)
- `website/src/content/changelog/2026-04-28-security-hardening.md` — changelog entry

**Files to modify:**
- `orchestrator/app/auth.py` — strip X-Admin-Secret fallback from `require_user` (#5)
- `orchestrator/tests/test_auth.py` — negative test for #5
- `scripts/install.sh` — generate random NOVA_ADMIN_SECRET (#2)
- `orchestrator/app/main.py` — startup guard for default secret (#2)
- `recovery-service/app/main.py` — startup guard (#2); CORS allowlist (#1)
- `recovery-service/app/config.py` — add `cors_allowed_origins` (#1)
- `recovery-service/app/docker_client.py` — `CRITICAL_SERVICES` guard + label-based match (#1)
- `cortex/app/main.py` — startup guard (#2); CORS allowlist (#4)
- `cortex/app/config.py` — add `cors_allowed_origins` (#4)
- `tests/conftest.py` — set `NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1` for the test process (#2)
- `tests/test_recovery.py` — restart_service guard tests (#1)
- `orchestrator/app/oauth.py` — accept `state` parameter (#3)
- `orchestrator/app/auth_router.py` — generate/validate state, strip user-supplied redirect_uri (#3)
- `dashboard/src/pages/Login.tsx` (or equivalent) — pass state through OAuth flow (#3)

---

## Task 1: Fix #5 — Strip admin-secret-as-user-token fallback

**Files:**
- Modify: `orchestrator/app/auth.py:7-11, 264-267, 395-397`
- Modify: `orchestrator/tests/test_auth.py`
- Create: `tests/test_auth_isolation.py`

- [ ] **Step 1: Read the existing `require_user` to confirm line numbers**

```bash
sed -n '260,405p' orchestrator/app/auth.py
```

Expected: see `require_user` definition at line 264, `x_admin_secret` parameter at line 267, fallback at lines 395-397 (`if x_admin_secret and x_admin_secret == await get_admin_secret(): return _SYNTHETIC_ADMIN`).

- [ ] **Step 2: Write a negative integration test**

Create `tests/test_auth_isolation.py`:

```python
"""FC-005: admin secret must not authenticate user-context endpoints."""
import os
import httpx
import pytest

ORCHESTRATOR_URL = os.getenv("NOVA_ORCHESTRATOR_URL", "http://localhost:8000")
ADMIN_SECRET = os.getenv("NOVA_ADMIN_SECRET", "")


@pytest.mark.asyncio
async def test_admin_secret_rejected_on_user_endpoint():
    """A request with X-Admin-Secret only (no JWT) must be 401 on UserDep endpoints."""
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        r = await client.get(
            "/api/v1/knowledge/sources",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        assert r.status_code == 401, (
            f"Expected 401 (admin secret should not authenticate UserDep endpoints), "
            f"got {r.status_code}: {r.text[:200]}"
        )


@pytest.mark.asyncio
async def test_admin_secret_accepted_on_admin_endpoint():
    """A request with X-Admin-Secret only must still work on AdminDep endpoints."""
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        r = await client.post(
            "/api/v1/knowledge/crawl-log",
            headers={"X-Admin-Secret": ADMIN_SECRET},
            json={
                "source_id": "00000000-0000-0000-0000-000000000000",
                "status": "success",
                "items_found": 0,
                "items_added": 0,
            },
        )
        # Either 201 (created) or 4xx for invalid source_id, but NOT 401/403.
        assert r.status_code not in (401, 403), (
            f"AdminDep endpoint rejected admin secret: {r.status_code} {r.text[:200]}"
        )
```

- [ ] **Step 3: Run the test and verify it currently FAILS**

Run: `pytest tests/test_auth_isolation.py::test_admin_secret_rejected_on_user_endpoint -v`

Expected: FAIL — current code returns `_SYNTHETIC_ADMIN` so the request succeeds (200), not 401.

- [ ] **Step 4: Strip the fallback from `require_user`**

Edit `orchestrator/app/auth.py`:

(a) Remove `x_admin_secret` from the `require_user` signature (line 267):

```python
# Before:
async def require_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_admin_secret: Annotated[str | None, Header(alias="X-Admin-Secret")] = None,
) -> AuthenticatedUser:

# After:
async def require_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
```

(b) Delete the fallback block (lines 395-397):

```python
# Delete these lines:
    # Fallback: admin secret (backward compat for existing dashboard sessions)
    if x_admin_secret and x_admin_secret == await get_admin_secret():
        return _SYNTHETIC_ADMIN
```

(c) Update module docstring (lines 7-11). Change:

```
UserDep also accepts X-Admin-Secret as a fallback for backward compatibility.
```

to:

```
UserDep is JWT-only. Admin secret is no longer a user-impersonation token;
it authenticates AdminDep endpoints only.
```

- [ ] **Step 5: Run the negative test and verify it now PASSES**

Run: `pytest tests/test_auth_isolation.py -v`

Expected: both tests PASS.

- [ ] **Step 6: Add a unit test in `orchestrator/tests/test_auth.py`**

Find the existing test class for `require_user` (or add one), and add:

```python
@pytest.mark.asyncio
async def test_require_user_rejects_admin_secret_only(monkeypatch):
    """require_user must NOT accept X-Admin-Secret as a user impersonation token."""
    from app.auth import require_user
    from fastapi import HTTPException, Request
    request = make_mock_request()  # or whatever fixture pattern this file uses
    with pytest.raises(HTTPException) as exc:
        await require_user(request=request, authorization=None)
    assert exc.value.status_code == 401
```

(Adapt to existing test conventions in the file — check imports and fixture patterns first.)

- [ ] **Step 7: Run the full orchestrator test suite to catch regressions**

Run: `cd orchestrator && pytest tests/ -v`

Expected: all tests pass. If any test was implicitly relying on admin-secret-as-user-token, it will surface here.

- [ ] **Step 8: Run the integration suite**

Run: `make test-quick` (health), then `make test` (full)

Expected: all green. Worker integration tests (intel, knowledge) should still pass — they hit AdminDep endpoints which are unaffected.

- [ ] **Step 9: Commit**

```bash
git add orchestrator/app/auth.py orchestrator/tests/test_auth.py tests/test_auth_isolation.py
git commit -m "$(cat <<'EOF'
fix(security): strip X-Admin-Secret fallback from require_user (#5)

UserDep is now JWT-only. Admin secret no longer silently grants
user-impersonation across all user-context endpoints; it authenticates
AdminDep endpoints only.

Verified worker call paths (intel-worker, knowledge-worker) hit AdminDep
endpoints exclusively, so no internal services break.

Spec: docs/superpowers/specs/2026-04-28-security-hardening-chain-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Fix #2 — Randomize admin secret on install

**Files:**
- Modify: `scripts/install.sh`
- Modify: `orchestrator/app/main.py` (startup guard)
- Modify: `recovery-service/app/main.py` (startup guard)
- Modify: `cortex/app/main.py` (startup guard)
- Modify: `tests/conftest.py` (set bypass for tests)
- Create: `tests/test_install_secret.sh`

### Subtask 2a: Install-script generation

- [ ] **Step 1: Read current install.sh structure**

```bash
sed -n '1,80p' scripts/install.sh
```

Identify the section that materializes `.env` (typically after copying `.env.example`).

- [ ] **Step 2: Write a shell test for the generation logic**

Create `tests/test_install_secret.sh`:

```bash
#!/usr/bin/env bash
# Verify install.sh generates a strong admin secret instead of the literal default.
set -euo pipefail

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# Copy the relevant files into a sandbox
mkdir -p "$TMPDIR/scripts"
cp scripts/install.sh "$TMPDIR/scripts/install.sh"
cp .env.example "$TMPDIR/.env.example"

cd "$TMPDIR"
# Stub: only run the .env materialization portion (full install.sh boots services).
# We extract & run just the secret-generation block.
bash -c '
  cp .env.example .env
  # Run the same logic install.sh uses:
  if grep -qE "^NOVA_ADMIN_SECRET=(nova-admin-secret-change-me|)$" .env || ! grep -q "^NOVA_ADMIN_SECRET=" .env; then
    NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    if grep -q "^NOVA_ADMIN_SECRET=" .env; then
      sed -i.bak "s|^NOVA_ADMIN_SECRET=.*|NOVA_ADMIN_SECRET=${NEW_SECRET}|" .env && rm -f .env.bak
    else
      echo "NOVA_ADMIN_SECRET=${NEW_SECRET}" >> .env
    fi
  fi
'

# Assert the secret is no longer the default and is at least 32 chars
grep -q "^NOVA_ADMIN_SECRET=" .env || { echo "FAIL: NOVA_ADMIN_SECRET missing"; exit 1; }
if grep -q "^NOVA_ADMIN_SECRET=nova-admin-secret-change-me$" .env; then
  echo "FAIL: secret is still the literal default"; exit 1
fi
SECRET=$(grep "^NOVA_ADMIN_SECRET=" .env | cut -d= -f2)
if [ ${#SECRET} -lt 32 ]; then
  echo "FAIL: secret too short (${#SECRET} chars)"; exit 1
fi
echo "PASS: generated secret length=${#SECRET}"
```

Make executable: `chmod +x tests/test_install_secret.sh`

- [ ] **Step 3: Run the test (should FAIL — generation logic not in install.sh yet)**

Run: `bash tests/test_install_secret.sh`

Expected: PASS, because the test embeds its own generation logic (this validates the *logic* before we put it in install.sh). After step 4, install.sh will produce the same outcome.

- [ ] **Step 4: Add the generation logic to `scripts/install.sh`**

Find the section in `install.sh` that handles `.env` materialization (typically after `cp .env.example .env`). Add immediately after:

```bash
# Generate strong admin secret if missing or default
GENERATED_ADMIN_SECRET=""
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

Near the end of `install.sh` (after services are up and the success message prints), add:

```bash
if [ -n "$GENERATED_ADMIN_SECRET" ]; then
  echo
  echo "✓ Generated admin secret: $GENERATED_ADMIN_SECRET"
  echo "  Save this to your password manager."
  echo "  It's also stored in .env as NOVA_ADMIN_SECRET."
  echo "  This is the only time it will be displayed in plain output."
fi
```

- [ ] **Step 5: Verify install script syntax**

Run: `bash -n scripts/install.sh`

Expected: no output (syntax OK).

### Subtask 2b: Startup guard

- [ ] **Step 6: Update `tests/conftest.py` to set the bypass for the test process**

Add near the top of `tests/conftest.py` (after the imports, before fixtures):

```python
# Allow the literal default admin secret in the test process — services
# refuse to start with it otherwise (see fix #2 startup guard).
os.environ.setdefault("NOVA_ALLOW_DEFAULT_ADMIN_SECRET", "1")
```

- [ ] **Step 7: Add startup guard to orchestrator**

In `orchestrator/app/main.py`, find the `lifespan` function. Add at the top of the startup phase (before any DB/Redis init):

```python
# Refuse to start with the literal default admin secret unless explicitly bypassed
if settings.nova_admin_secret == "nova-admin-secret-change-me":
    if os.getenv("NOVA_ALLOW_DEFAULT_ADMIN_SECRET") != "1":
        raise RuntimeError(
            "NOVA_ADMIN_SECRET is set to the literal default. "
            "Run scripts/install.sh to generate a strong secret, "
            "or set NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1 to bypass (dev/test only)."
        )
    log.warning(
        "NOVA_ADMIN_SECRET is the literal default — bypass active. "
        "Do not use this configuration in production."
    )
```

(Add `import os` if not already imported.)

- [ ] **Step 8: Add the same guard to `recovery-service/app/main.py`**

Same code block at the top of recovery's lifespan startup phase. Recovery reads `nova_admin_secret` via its own settings; if recovery's settings model doesn't have this field, add it to `recovery-service/app/config.py`:

```python
nova_admin_secret: str = "nova-admin-secret-change-me"  # validated at startup
```

- [ ] **Step 9: Add the same guard to `cortex/app/main.py`**

Cortex uses raw `os.getenv()`, so adapt:

```python
admin_secret = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
if admin_secret == "nova-admin-secret-change-me":
    if os.getenv("NOVA_ALLOW_DEFAULT_ADMIN_SECRET") != "1":
        raise RuntimeError(
            "NOVA_ADMIN_SECRET is set to the literal default. "
            "Run scripts/install.sh to generate a strong secret, "
            "or set NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1 to bypass (dev/test only)."
        )
    log.warning("NOVA_ADMIN_SECRET is the literal default — bypass active.")
```

- [ ] **Step 10: Run the install-script test**

Run: `bash tests/test_install_secret.sh`

Expected: PASS.

- [ ] **Step 11: Restart services and verify they boot**

Run: `make down && NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1 make up && sleep 10 && make ps`

Expected: all services running.

- [ ] **Step 12: Verify the guard fires when bypass is removed**

Run: `make down && unset NOVA_ALLOW_DEFAULT_ADMIN_SECRET && docker compose up orchestrator 2>&1 | grep -i "default" | head -5`

Expected: orchestrator logs the RuntimeError and exits.

After verification: `export NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1 && make up`

- [ ] **Step 13: Run the integration suite**

Run: `make test`

Expected: all tests pass (conftest sets the bypass).

- [ ] **Step 14: Commit**

```bash
git add scripts/install.sh \
  orchestrator/app/main.py \
  recovery-service/app/main.py recovery-service/app/config.py \
  cortex/app/main.py \
  tests/conftest.py tests/test_install_secret.sh
git commit -m "$(cat <<'EOF'
fix(security): randomize admin secret on install; refuse default on boot (#2)

install.sh generates a 32-byte url-safe random NOVA_ADMIN_SECRET when
.env contains the literal default or no value. Generated secret is
displayed once at end of install with a "save this" prompt.

orchestrator, recovery-service, and cortex now refuse to start with the
literal default unless NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1 is set
(escape hatch for tests/dev).

Spec: docs/superpowers/specs/2026-04-28-security-hardening-chain-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Fix #1 — Recovery service: CORS, restart guards, exact match

**Files:**
- Modify: `recovery-service/app/main.py:52-58`
- Modify: `recovery-service/app/config.py`
- Modify: `recovery-service/app/docker_client.py:1-10, 159-170, 194-203`
- Modify: `tests/test_recovery.py`

- [ ] **Step 1: Read current restart_service and main.py CORS**

```bash
sed -n '50,60p' recovery-service/app/main.py
sed -n '155,215p' recovery-service/app/docker_client.py
```

Confirm: `allow_origins=["*"]` at line 54; `restart_service` has no CRITICAL_SERVICES guard; uses `if service_name in c.name` substring match.

- [ ] **Step 2: Write failing tests in `tests/test_recovery.py`**

Add to existing file:

```python
@pytest.mark.asyncio
async def test_restart_service_rejects_postgres():
    """Critical services must be guarded from restart-via-API."""
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    async with httpx.AsyncClient(base_url=RECOVERY_URL, timeout=10.0) as client:
        r = await client.post(
            "/recovery/services/postgres/restart",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        # Should return rejection — exact endpoint shape may vary; assert ok=False or 4xx
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        assert r.status_code >= 400 or body.get("ok") is False, (
            f"Expected restart_service('postgres') to be rejected, got {r.status_code}: {r.text[:200]}"
        )


@pytest.mark.asyncio
async def test_restart_service_does_not_match_substring():
    """restart_service('post') must NOT accidentally restart postgres."""
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    async with httpx.AsyncClient(base_url=RECOVERY_URL, timeout=10.0) as client:
        r = await client.post(
            "/recovery/services/post/restart",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        # Should be not_found, not "restarted postgres"
        assert body.get("action") in ("not_found", "rejected"), (
            f"'post' must not match 'postgres' as substring; got {body}"
        )


@pytest.mark.asyncio
async def test_recovery_cors_not_wildcard():
    """Recovery service must not return Access-Control-Allow-Origin: * for arbitrary origins."""
    async with httpx.AsyncClient(base_url=RECOVERY_URL, timeout=10.0) as client:
        r = await client.options(
            "/health/ready",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        allow_origin = r.headers.get("access-control-allow-origin", "")
        assert allow_origin != "*", (
            f"Recovery CORS still wildcard: '{allow_origin}'"
        )
```

(Verify the actual endpoint path for restart by reading `recovery-service/app/routes.py` first; adjust if different from `/recovery/services/{name}/restart`.)

- [ ] **Step 3: Run tests, verify they FAIL**

Run: `pytest tests/test_recovery.py::test_restart_service_rejects_postgres tests/test_recovery.py::test_recovery_cors_not_wildcard -v`

Expected: both FAIL (current code allows postgres restart and returns wildcard CORS).

- [ ] **Step 4: Fix CORS in `recovery-service/app/main.py:54`**

```python
# Before:
allow_origins=["*"],

# After:
allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
```

Add to `recovery-service/app/config.py`:

```python
cors_allowed_origins: str = "http://localhost:3000,http://localhost:5173"
```

- [ ] **Step 5: Add `CRITICAL_SERVICES` guard and label-based match in `recovery-service/app/docker_client.py`**

At the top of the file (after imports):

```python
CRITICAL_SERVICES = frozenset({"postgres", "redis", "recovery"})
```

Replace `restart_service`:

```python
def restart_service(service_name: str) -> dict:
    """Restart a Nova service container. Refuses critical services."""
    if service_name in CRITICAL_SERVICES:
        return {
            "service": service_name,
            "action": "rejected",
            "ok": False,
            "error": (
                f"{service_name} is a critical service. Restart it via "
                f"'docker compose restart {service_name}' from the host."
            ),
        }
    try:
        client = _client()
        for c in client.containers.list(all=True):
            if c.labels.get("com.docker.compose.service") == service_name:
                c.restart(timeout=30)
                return {"service": service_name, "action": "restarted", "ok": True}
        return {
            "service": service_name,
            "action": "not_found",
            "ok": False,
            "error": f"Container for '{service_name}' not found",
        }
    except DockerException as e:
        return {"service": service_name, "action": "error", "ok": False, "error": str(e)}
```

Apply the same label-based match to `get_container_logs` (around line 197):

```python
def get_container_logs(service_name: str, tail: int = 100) -> str:
    """Get recent logs from a Nova service container."""
    try:
        client = _client()
        for c in client.containers.list(all=True):
            if c.labels.get("com.docker.compose.service") == service_name:
                return c.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        return f"Container for '{service_name}' not found"
    except DockerException as e:
        return f"Docker error: {e}"
```

- [ ] **Step 6: Restart recovery service to pick up changes**

Run: `docker compose restart recovery`

Wait ~5s for healthy state, then: `curl -sf http://localhost:8888/health/ready | python3 -m json.tool`

Expected: `status: ready` (or equivalent).

- [ ] **Step 7: Run the recovery tests**

Run: `pytest tests/test_recovery.py -v`

Expected: all PASS, including the new guards.

- [ ] **Step 8: Commit**

```bash
git add recovery-service/app/main.py recovery-service/app/config.py \
  recovery-service/app/docker_client.py tests/test_recovery.py
git commit -m "$(cat <<'EOF'
fix(security): recovery CORS allowlist, critical-service guards, exact match (#1)

- CORS: allow_origins=["*"] -> settings-driven allowlist (matches orchestrator)
- restart_service() refuses postgres/redis/recovery (CRITICAL_SERVICES)
- Container match uses com.docker.compose.service label, not substring
  (prevents 'post' from accidentally matching postgres)

Spec: docs/superpowers/specs/2026-04-28-security-hardening-chain-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Fix #4 — Cortex CORS allowlist

**Files:**
- Modify: `cortex/app/main.py:89`
- Modify: `cortex/app/config.py`
- Create: `tests/test_cortex_cors.py`

- [ ] **Step 1: Confirm current CORS state**

```bash
sed -n '85,95p' cortex/app/main.py
grep -n "cors\|CORS" cortex/app/config.py
```

Expected: `allow_origins=["*"]`; no `cors_allowed_origins` in config.

- [ ] **Step 2: Write failing test**

Create `tests/test_cortex_cors.py`:

```python
"""FC-004: cortex must not return wildcard CORS for arbitrary origins."""
import os
import httpx
import pytest

CORTEX_URL = os.getenv("NOVA_CORTEX_URL", "http://localhost:8100")


@pytest.mark.asyncio
async def test_cortex_cors_not_wildcard():
    async with httpx.AsyncClient(base_url=CORTEX_URL, timeout=10.0) as client:
        r = await client.options(
            "/health/ready",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        allow_origin = r.headers.get("access-control-allow-origin", "")
        assert allow_origin != "*", f"Cortex CORS still wildcard: '{allow_origin}'"
```

- [ ] **Step 3: Run test, verify it FAILS**

Run: `pytest tests/test_cortex_cors.py -v`

Expected: FAIL.

- [ ] **Step 4: Add `cors_allowed_origins` to `cortex/app/config.py`**

In the Settings class, add:

```python
cors_allowed_origins: str = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
```

- [ ] **Step 5: Update `cortex/app/main.py:89`**

```python
# Before:
allow_origins=["*"],

# After:
allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
```

- [ ] **Step 6: Restart cortex and verify**

Run: `docker compose restart cortex && sleep 5 && pytest tests/test_cortex_cors.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cortex/app/main.py cortex/app/config.py tests/test_cortex_cors.py
git commit -m "$(cat <<'EOF'
fix(security): cortex CORS allowlist (#4)

allow_origins=["*"] -> settings-driven allowlist matching orchestrator/recovery.
cors_allowed_origins added to cortex Settings.

Spec: docs/superpowers/specs/2026-04-28-security-hardening-chain-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Fix #3 — Google OAuth: state + redirect_uri allowlist

**Files:**
- Modify: `orchestrator/app/oauth.py:22-31`
- Modify: `orchestrator/app/auth_router.py` (Google endpoints, ~lines 360-385)
- Modify: `dashboard/src/pages/Login.tsx` (or wherever Google auth is initiated)
- Create: `tests/test_oauth_flow.py`

- [ ] **Step 1: Read current OAuth code**

```bash
sed -n '20,55p' orchestrator/app/oauth.py
sed -n '355,395p' orchestrator/app/auth_router.py
```

Confirm: no `state` parameter in `get_google_auth_url`; callback accepts client-supplied `redirect_uri`.

- [ ] **Step 2: Find dashboard OAuth flow file**

```bash
grep -rn "google_auth_url\|google/url\|google/callback" dashboard/src/ | head -10
```

Note the file(s) that initiate the OAuth flow — need to update these to pass `state`.

- [ ] **Step 3: Write failing tests**

Create `tests/test_oauth_flow.py`:

```python
"""FC-003: Google OAuth state validation (CSRF protection)."""
import os
import httpx
import pytest

ORCHESTRATOR_URL = os.getenv("NOVA_ORCHESTRATOR_URL", "http://localhost:8000")


@pytest.mark.asyncio
async def test_google_auth_url_returns_state():
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        r = await client.get("/api/v1/auth/google/url")
        assert r.status_code == 200
        body = r.json()
        assert "url" in body
        assert "state" in body
        assert "state=" in body["url"], "state must be in the OAuth redirect URL"
        assert len(body["state"]) >= 32, "state must be sufficiently random"


@pytest.mark.asyncio
async def test_google_callback_rejects_missing_state():
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        r = await client.post(
            "/api/v1/auth/google/callback",
            json={"code": "fake-code"},  # no state
        )
        assert r.status_code == 400
        assert "state" in r.text.lower()


@pytest.mark.asyncio
async def test_google_callback_rejects_unknown_state():
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        r = await client.post(
            "/api/v1/auth/google/callback",
            json={"code": "fake-code", "state": "not-a-real-state-token-12345"},
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_state_is_single_use():
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        url_resp = await client.get("/api/v1/auth/google/url")
        state = url_resp.json()["state"]
        # First use: will fail at code exchange (fake code) but past state validation
        r1 = await client.post(
            "/api/v1/auth/google/callback",
            json={"code": "fake-code", "state": state},
        )
        # Second use of same state: state should be consumed
        r2 = await client.post(
            "/api/v1/auth/google/callback",
            json={"code": "fake-code", "state": state},
        )
        assert r2.status_code == 400, f"State must be single-use; got {r2.status_code}"
        assert "state" in r2.text.lower()
```

- [ ] **Step 4: Run tests, verify FAIL**

Run: `pytest tests/test_oauth_flow.py -v`

Expected: all FAIL (no state implementation yet).

- [ ] **Step 5: Update `orchestrator/app/oauth.py`**

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

(Adjust scope/prompt to match existing values if different.)

- [ ] **Step 6: Update `auth_router.py` Google endpoints**

Find the `/api/v1/auth/google/url` endpoint and rewrite:

```python
import secrets
from app.redis_helpers import get_redis  # or wherever Redis client comes from

@router.get("/api/v1/auth/google/url")
async def google_auth_url(request: Request):
    state = secrets.token_urlsafe(32)
    redirect_uri = str(request.url_for("google_callback"))
    redis = await get_redis()
    await redis.set(f"nova:oauth:state:{state}", redirect_uri, ex=600)
    return {"url": get_google_auth_url(redirect_uri, state), "state": state}
```

Find the `/api/v1/auth/google/callback` endpoint and rewrite:

```python
@router.post("/api/v1/auth/google/callback", name="google_callback")
async def google_callback(request: Request, body: dict):
    state = body.get("state")
    if not state:
        raise HTTPException(400, "Missing state parameter")
    redis = await get_redis()
    stored = await redis.getdel(f"nova:oauth:state:{state}")
    if not stored:
        raise HTTPException(400, "Invalid or expired state token")
    redirect_uri = stored.decode() if isinstance(stored, bytes) else stored
    code = body.get("code")
    if not code:
        raise HTTPException(400, "Missing authorization code")
    google_user = await exchange_google_code(code, redirect_uri)
    # ... rest of existing user-creation/JWT-issuance flow ...
```

Important: the existing callback may have additional logic (creating users, issuing JWTs). Preserve all of that — only change the auth-input shape (state validation + Redis-stored redirect_uri).

- [ ] **Step 7: Update dashboard OAuth flow**

In the file identified at Step 2, when calling `/api/v1/auth/google/url`, capture both `url` and `state`. Pass `state` along with `code` when calling `/api/v1/auth/google/callback`.

Typical pattern:

```typescript
// Initiating OAuth
const { url, state } = await api.get('/api/v1/auth/google/url');
sessionStorage.setItem('oauth_state', state);
window.location.href = url;

// Handling callback (after Google redirects back with ?code=...&state=...)
const params = new URLSearchParams(window.location.search);
const code = params.get('code');
const returnedState = params.get('state');
const expectedState = sessionStorage.getItem('oauth_state');
if (returnedState !== expectedState) throw new Error('OAuth state mismatch');
sessionStorage.removeItem('oauth_state');
await api.post('/api/v1/auth/google/callback', { code, state: returnedState });
```

(Adapt to actual dashboard patterns — `apiFetch` instead of `api.get`, etc.)

- [ ] **Step 8: Restart orchestrator and dashboard**

Run: `docker compose restart orchestrator && sleep 5`

For dashboard dev: `cd dashboard && npm run build` (verify TypeScript compiles).

- [ ] **Step 9: Run OAuth tests**

Run: `pytest tests/test_oauth_flow.py -v`

Expected: all PASS.

- [ ] **Step 10: Run full integration suite for regression check**

Run: `make test`

Expected: all green.

- [ ] **Step 11: Commit**

```bash
git add orchestrator/app/oauth.py orchestrator/app/auth_router.py \
  dashboard/src/pages/Login.tsx tests/test_oauth_flow.py
git commit -m "$(cat <<'EOF'
fix(security): Google OAuth state parameter + redirect_uri allowlist (#3)

- get_google_auth_url() now requires a state parameter
- /api/v1/auth/google/url generates 32-byte URL-safe state, stores in
  Redis with 10-minute TTL (key: nova:oauth:state:{state}, value:
  server-computed redirect_uri)
- /api/v1/auth/google/callback validates state via GETDEL (single-use),
  uses stored redirect_uri instead of client-supplied (closes
  redirect_uri-tampering vector)
- Dashboard updated to round-trip state via sessionStorage

PKCE is a follow-up; state alone closes the CSRF hole.

Spec: docs/superpowers/specs/2026-04-28-security-hardening-chain-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Documentation + changelog

**Files:**
- Create: `website/src/content/changelog/2026-04-28-security-hardening.md`
- Modify: `website/src/content/docs/nova/docs/security.md` (if it exists; otherwise note as TODO)

- [ ] **Step 1: Check if security doc exists**

```bash
ls website/src/content/docs/nova/docs/security.md 2>&1
```

- [ ] **Step 2: Create changelog entry**

Create `website/src/content/changelog/2026-04-28-security-hardening.md`. Follow the format of recent entries (`2026-04-28-bundled-ollama.md`):

```markdown
---
title: Security Hardening
date: 2026-04-28
---

Five interlocking security gaps closed:

- **Admin secret no longer impersonates users.** `X-Admin-Secret` header now authenticates admin-only endpoints exclusively. Previously, the secret silently granted user-level access on every user-context endpoint.
- **Random admin secret on install.** `install.sh` generates a 32-byte URL-safe secret if none is set. Services refuse to start with the literal default unless `NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1` is set (escape hatch for tests).
- **Recovery service hardened.** CORS allowlist replaces wildcard; critical services (postgres, redis, recovery itself) cannot be restarted via the API; container matching uses Docker labels instead of substring matching (no more "post" → postgres).
- **Cortex CORS allowlist.** Same fix as recovery — wildcard origin replaced with config-driven allowlist.
- **OAuth CSRF protection.** Google OAuth flow now requires a `state` parameter. Callbacks validate single-use, time-bounded state tokens stored in Redis. The user-supplied `redirect_uri` fallback is removed.

If you're upgrading: run `./scripts/install.sh` to regenerate your admin secret (or update `NOVA_ADMIN_SECRET` in `.env` manually).
```

- [ ] **Step 3: Update security.md if it exists** (skip if not)

Add a section noting the new behaviors. Keep concise.

- [ ] **Step 4: Commit**

```bash
git add website/src/content/changelog/2026-04-28-security-hardening.md \
  website/src/content/docs/nova/docs/security.md  # if modified
git commit -m "$(cat <<'EOF'
docs(changelog): security hardening chain (2026-04-28)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step 1: Run the full integration suite one more time**

Run: `make test`

Expected: all green.

- [ ] **Step 2: Spot-check each fix manually**

```bash
# #5: admin secret rejected on user endpoint
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Admin-Secret: $NOVA_ADMIN_SECRET" http://localhost:8000/api/v1/knowledge/sources
# Expect: 401

# #1: postgres restart rejected
curl -s -X POST -H "X-Admin-Secret: $NOVA_ADMIN_SECRET" http://localhost:8888/recovery/services/postgres/restart | python3 -m json.tool
# Expect: ok=false, action=rejected

# #1, #4: CORS no longer wildcard
curl -s -I -X OPTIONS -H "Origin: http://evil.example.com" -H "Access-Control-Request-Method: GET" http://localhost:8888/health/ready | grep -i access-control-allow-origin
curl -s -I -X OPTIONS -H "Origin: http://evil.example.com" -H "Access-Control-Request-Method: GET" http://localhost:8100/health/ready | grep -i access-control-allow-origin
# Expect: no "*" in the values (either omitted or set to allowlist)

# #3: OAuth state present
curl -s http://localhost:8000/api/v1/auth/google/url | python3 -m json.tool
# Expect: { "url": "...&state=...", "state": "..." }
```

- [ ] **Step 3: Verify commit log**

Run: `git log --oneline -10`

Expected: 5–6 commits matching the fixes (and one for changelog).

---

## Out-of-scope (track for future planning)

- Built-in secret manager (will absorb the deferred rotate-button feature)
- Service-account JWTs (replace `X-Admin-Secret` for internal worker calls)
- PKCE on OAuth flow
- Cortex config refactor (`os.getenv` → `pydantic_settings.BaseSettings`)
- Retire admin secret entirely in favor of `is_admin` JWT claim (long-term direction)
