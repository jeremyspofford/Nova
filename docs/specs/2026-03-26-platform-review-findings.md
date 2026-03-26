# Nova Platform Review — 2026-03-26

> Comprehensive review across 5 disciplines: architecture/data engineering,
> backend reliability, frontend/UX, security, and test quality. Each finding
> is rated Critical/High/Medium with a spec-level remediation.

---

## SEC: Security Findings

### SEC-1: REQUIRE_AUTH defaults to false (Critical)
Fresh deployments run fully unauthenticated. `docker-compose.yml` defaults `REQUIRE_AUTH` to `false`, meaning all APIs — including shell execution, file access, and admin endpoints — are open to any caller.
**Fix:** Default to `true` in docker-compose. Ship `.env.example` with `REQUIRE_AUTH=true` and comment explaining dev bypass.

### SEC-2: Reindex endpoint has no auth (Critical)
`POST /api/v1/engrams/reindex` and `GET /api/v1/engrams/reindex/status` have no `AdminDep`. Any caller can flood the ingestion queue.
**Fix:** Add `_admin: AdminDep` to both handlers.

### SEC-3: SSRF in web_fetch tool (High)
`web_tools.py` `_execute_web_fetch` makes HTTP requests with no URL validation and `follow_redirects=True`. An LLM can be prompted to fetch internal service URLs or cloud metadata endpoints.
**Fix:** Apply `validate_url()` from `nova_worker_common.url_validator` before fetch. Switch to manual redirect following with SSRF validation per hop.

### SEC-4: Trusted proxy header forgeable (Critical)
When `TRUSTED_PROXY_HEADER` is set, the header value is trusted without verifying the direct connection IP is a known proxy. An attacker setting `X-Forwarded-For: 10.0.0.1` bypasses all auth.
**Fix:** Only trust the proxy header when `request.client.host` is itself in the trusted proxy list.

### SEC-5: Google OAuth bypasses invite-only registration (Medium)
`/api/v1/auth/google/callback` creates accounts for any Google user even when `registration_mode=invite`. The invite check only exists in the local registration path.
**Fix:** Apply invite verification in the OAuth callback when `registration_mode=invite`.

### SEC-6: No rate limiting on auth endpoints (Medium)
`/api/v1/auth/login`, `/register`, `/invites/validate/{code}` have no rate limiting. Brute force is possible.
**Fix:** Redis sliding-window rate limit (5 failures per IP per 15 min) on auth endpoints.

### SEC-7: WebSocket connection DoS (High)
No limit on concurrent WebSocket connections, connection rate, or per-connection memory. `conversation_history` grows unbounded.
**Fix:** Connection semaphore, IP-based rate limit on establishment, bound conversation history length.

### SEC-8: Default admin secret shipped (Medium)
`nova-admin-secret-change-me` is the literal default in both `.env.example` and docker-compose. Dashboard hardcodes same value in localStorage.
**Fix:** Auto-generate at setup or refuse to start when default is detected with `REQUIRE_AUTH=true`.

---

## ARCH: Architecture & Data Engineering Findings

### ARCH-1: Dead letter queue unbounded (Critical)
`nova:queue:dead_letter` grows without bound — no TTL, no cap, no cleanup, no alerting.
**Fix:** LTRIM after each LPUSH (cap 10k), add depth to `/health/ready` degraded signal, add periodic purge.

### ARCH-2: Non-atomic SADD+LPUSH race in enqueue_task (Critical)
Two separate Redis commands without MULTI/EXEC. Under concurrent reaper + retry, duplicate queue entries are possible.
**Fix:** Redis pipeline or Lua script for atomic SADD+LPUSH.

### ARCH-3: working_memory_slots never cleaned up (Critical)
No TTL, no DELETE, no background cleanup. Table grows monotonically per session.
**Fix:** Background cleanup for slots older than N days with no session activity. Add LIMIT to queries.

### ARCH-4: Embedding cache serves stale vectors from wrong model (Critical)
L2 Postgres cache lookup doesn't filter by model. After changing embedding model, old vectors with wrong dimensionality are silently returned.
**Fix:** Add `AND model = :m` to L2 SELECT. Periodic cleanup of old-model entries.

### ARCH-5: intel:new_items queue has no consumer (High)
Intel-worker pushes to `intel:new_items` on db6 but nothing BRPOPs it. Dead code or unfinished wiring to Cortex.
**Fix:** Either wire to Cortex stimulus system or remove the dead write.

### ARCH-6: Ingestion semaphore is effectively serial (High)
`_decomposition_semaphore` is held for the entire `_process_event()` duration, but the BRPOP loop is single-threaded. Semaphore(5) behaves as Semaphore(1).
**Fix:** Fire `asyncio.create_task(_process_event(...))` for each item; gate only the LLM call inside.

### ARCH-7: Orphaned references in comments and intel_recommendation_engrams (High)
Polymorphic `comments` table and cross-DB `engram_id` references have no FK cascade. Deleting goals/recommendations leaves orphans.
**Fix:** Application-level cascade on delete, or periodic sweep.

### ARCH-8: usage_events and messages need partition strategy (Medium)
Both tables grow monotonically with no retention policy. Will degrade at scale.
**Fix:** Range partition by month on `created_at`. Add retention policy (configurable).

---

## BE: Backend Engineering Findings

### BE-1: MCP registry _active_clients dict has no lock (Critical)
Module-level dict mutated by reload/disconnect/connect concurrently with tool execution and discovery. Race during hot-reload.
**Fix:** `asyncio.Lock` around all mutations and iterations.

### BE-2: Dead pass block in validate_invite (High)
`auth_router.py:489` — condition checks `used_by` which isn't in the SELECT. Always falls through. Dead code with misleading comment.
**Fix:** Remove dead block, include `used_by` in first query, remove redundant second query.

### BE-3: N+1 queries in list_recommendations (High)
3 sequential `fetchval` calls per recommendation row (60 queries for 20 results). Connection pool exhaustion under concurrent load.
**Fix:** Single SQL with COUNT subqueries.

### BE-4: Security bypasses logged at nothing (High)
`auth.py` — Redis/DB unavailable during deny-list and expiry checks silently allows deactivated users through with zero log output.
**Fix:** `log.warning()` on every security bypass path.

### BE-5: _get_sandbox_tier silently drops DB errors (High)
Bare `except Exception: pass` on every chat/task request. Persistent DB issues invisible in production.
**Fix:** `log.debug()` at minimum.

### BE-6: update_recommendation generic branch has no status validation (Medium)
Arbitrary status strings can be written. Empty `updates` dict causes SQL syntax error.
**Fix:** Validate status against allowed set. Guard against empty updates.

### BE-7: Corrupt agent entries silently dropped (Medium)
`store.py` — `except Exception: pass` when deserializing agents. If primary agent corrupts, all requests fail with no diagnostic.
**Fix:** `log.warning()` on corrupt entries.

---

## FE: Frontend & UX Findings

### FE-1: Conversation delete has no confirmation (Critical)
Single click permanently destroys conversation. No ConfirmDialog. Only destructive action in the app without confirmation.
**Fix:** Gate behind ConfirmDialog.

### FE-2: API key save fails silently (Critical)
`ProviderStatusSection` — save error is `console.error` only. User thinks key was saved.
**Fix:** Surface error in UI.

### FE-3: Service restart failures silently swallowed (Critical)
Recovery page — restart error handler is `catch { /* silently handled */ }`. Operators don't know restart failed.
**Fix:** Error state with feedback message.

### FE-4: Modal missing role="dialog" and focus trap (High)
Base Modal component has no ARIA attributes and no focus management. Propagates to every dialog in the app.
**Fix:** Add `role="dialog"`, `aria-modal`, `aria-labelledby`, focus trap.

### FE-5: Chat input has no accessible labels (High)
Send button, drawer toggle, textarea have no `aria-label` or associated label elements.
**Fix:** Add aria-labels to icon-only buttons and textarea.

### FE-6: MCP reload spinner shows on all cards (High)
`reloadMutation.isPending` is shared across all ServerCards. Wrong card shows loading.
**Fix:** Track reloading server ID separately.

### FE-7: Role change fires immediately without confirmation (High)
Users page — role dropdown triggers mutation on change. Accidental demotion with one misclick.
**Fix:** Confirmation step before role change.

### FE-8: Custom instructions persist forever with no indicator (Medium)
`outputStyle` and `customInstructions` in localStorage never cleared. No visible indicator they're active.
**Fix:** Visual indicator when active. Optional clear in resetConversation.

---

## TEST: Test Quality Findings

### Current State
- **152 passed, 2 failed (resource contention), 16 skipped**
- 18 test files, ~170 tests total
- 2 pipeline tests failed due to reindex queue saturation (not code bugs)

### TEST-1: No memory/engram tests (Critical gap)
Zero integration tests for the Engram Network — ingest, context retrieval, activation, stats, graph. Every pipeline run touches memory.

### TEST-2: No MCP server CRUD tests (High gap)
MCP server management endpoints untested. Introspect tools untested. Tool dispatch untested.

### TEST-3: No auth flow tests (High gap)
JWT login/register/refresh/logout cycle completely untested. Only admin-secret and API-key paths tested.

### TEST-4: No cortex tests (High gap)
Autonomous brain has zero test coverage — no health, no goals, no thinking loop.

### TEST-5: Weak/fake test patterns
- `test_pipeline_behavior.py` — artifacts test passes even when no artifacts exist (assertion inside `if` block)
- `test_rbac.py` — 75% skip in default config, hardcoded URL, soft asserts
- `test_chat_api.py` — 2 smoke tests, no actual message send/receive
- `test_llm_gateway.py` — 5 smoke tests, no actual completion/embedding calls
- `test_knowledge.py:219-230` — hardcoded `skipif(True)`, never runs regardless of service state

### TEST-6: Test isolation issues
- `test_orchestrator.py::test_bulk_delete` deletes ALL terminal tasks, not just test-created ones
- `test_tool_permissions.py::test_disable_multiple_groups` leaves groups disabled on mid-test failure
- `test_rbac.py` hardcodes `localhost:8000`, ignoring `NOVA_ORCHESTRATOR_URL`

---

## Priority Ranking (Recommended Execution Order)

### P0 — Fix immediately (security + data integrity)
| ID | Finding | Effort |
|---|---|---|
| SEC-2 | Reindex endpoint auth | 10 min |
| SEC-3 | SSRF in web_fetch | 30 min |
| SEC-4 | Trusted proxy header | 1 hour |
| ARCH-4 | Embedding cache wrong-model hits | 30 min |
| BE-1 | MCP registry lock | 30 min |

### P1 — Fix this week (reliability + UX)
| ID | Finding | Effort |
|---|---|---|
| SEC-1 | REQUIRE_AUTH default | 15 min |
| SEC-7 | WebSocket DoS limits | 2 hours |
| ARCH-1 | Dead letter cap + alerting | 1 hour |
| ARCH-2 | Atomic enqueue | 1 hour |
| ARCH-6 | Ingestion concurrency | 2 hours |
| BE-2 | Dead code in validate_invite | 30 min |
| BE-3 | N+1 in list_recommendations | 30 min |
| BE-4 | Security bypass logging | 30 min |
| FE-1 | Conversation delete confirm | 30 min |
| FE-2 | API key save error feedback | 15 min |
| FE-3 | Restart failure feedback | 15 min |

### P2 — Fix this sprint (quality + observability)
| ID | Finding | Effort |
|---|---|---|
| ARCH-3 | Working memory cleanup | 2 hours |
| ARCH-5 | intel:new_items dead queue | 1 hour |
| ARCH-7 | Orphan cleanup | 2 hours |
| SEC-5 | Google OAuth invite bypass | 1 hour |
| SEC-6 | Auth rate limiting | 2 hours |
| FE-4 | Modal accessibility | 2 hours |
| FE-6 | MCP reload spinner | 15 min |
| FE-7 | Role change confirm | 30 min |
| TEST-1 | Memory/engram test suite | 4 hours |
| TEST-2 | MCP + introspect tool tests | 2 hours |
| TEST-3 | Auth flow tests | 3 hours |

### P3 — Schedule for next cycle
| ID | Finding | Effort |
|---|---|---|
| ARCH-8 | Table partitioning | 1 day |
| SEC-8 | Auto-generate admin secret | 2 hours |
| FE-5 | Chat accessibility | 1 hour |
| FE-8 | Custom instructions indicator | 1 hour |
| TEST-4 | Cortex tests | 4 hours |
| TEST-5 | Fix weak/fake tests | 3 hours |
| TEST-6 | Test isolation fixes | 2 hours |
| BE-5-7 | Logging + validation gaps | 2 hours |
