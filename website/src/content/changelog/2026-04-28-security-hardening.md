---
title: "Security hardening — admin secret, OAuth state, recovery guards"
date: 2026-04-28
---

Five interlocking security gaps closed in one chain:

- **Admin secret no longer impersonates users.** The `X-Admin-Secret` header used to silently authenticate user-context endpoints — every fresh install was effectively "log in as anyone" by header. Now `UserDep` is JWT-only; admin secret authenticates admin endpoints only. Worker services (intel-worker, knowledge-worker) were unaffected because they already hit admin endpoints exclusively.
- **Random admin secret on install.** `scripts/install.sh` generates a 32-byte URL-safe `NOVA_ADMIN_SECRET` when `.env` contains the literal default, an empty value, or no value at all. The generated secret is displayed once at the end of install with a "save this to your password manager" prompt. Orchestrator, recovery, and cortex now refuse to start with the literal default unless `NOVA_ALLOW_DEFAULT_ADMIN_SECRET=1` is set (escape hatch for tests/dev).
- **Recovery service hardened.** CORS allowlist replaces wildcard. Critical services (postgres, redis, recovery itself) cannot be restarted via the API — operators must use `docker compose restart` from the host where the consequences are obvious. Container matching switched from substring (`if name in c.name`) to exact `com.docker.compose.service` label, so `restart_service("post")` no longer accidentally matches `postgres`.
- **Cortex CORS allowlist.** Same wildcard → settings-driven allowlist fix as recovery; cortex now matches the orchestrator pattern.
- **OAuth CSRF protection.** Google OAuth flow now requires a `state` parameter. `/api/v1/auth/google` mints 32 bytes of URL-safe random state, stores it in Redis with a 10-minute TTL, and returns it alongside the consent URL. `/api/v1/auth/google/callback` validates state via `GETDEL` (single-use) and uses the Redis-stored `redirect_uri` rather than any client-supplied value — closing both CSRF and `redirect_uri`-tampering vectors. PKCE is a follow-up.

If you're upgrading: rerun `./scripts/install.sh` to regenerate your admin secret (or set a strong `NOVA_ADMIN_SECRET` manually). The Redis runtime override at `nova:config:auth.admin_secret` still wins at runtime — clear it with `docker compose exec redis redis-cli -n 1 DEL nova:config:auth.admin_secret` if it has drifted from `.env`.

A few intentionally-deferred items get their own future work: a built-in secret manager (which will absorb a "rotate from dashboard" feature), service-account JWTs to replace `X-Admin-Secret` for internal worker calls, OAuth PKCE, and retiring the admin secret entirely in favor of an `is_admin` JWT claim. The current chain shrinks blast radius enough that those become value-adds, not emergencies.
