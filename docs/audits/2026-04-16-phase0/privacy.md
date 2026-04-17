# Privacy & Data Custody Audit — 2026-04-16

## Scope

Reviewed what data leaves the user's machine (LLM providers, bridges, intel/knowledge workers, voice, OAuth), what is persisted locally (Postgres tables, Redis DBs, filesystem blobs at `data/sources/`, backups, friction screenshots), data retention defaults across all growth surfaces, multi-user / workspace isolation assumptions, deletion/export paths, privileged-tier visibility, and whether prompt content is written to logs.

**Out of scope:** GDPR / legal compliance framing, dependency-CVE scanning, the security report's auth-model concerns (covered in `security.md`), and the synthesis pass's daily-driver-impact rating.

## Findings

### [P0] No deletion path for engrams — "forget this" is impossible

- **Evidence:** `memory-service/app/engram/router.py:48-1467` defines 30+ endpoints. The only `delete` is `@engram_router.delete("/sources/{source_id}")` (line 1467). No endpoint to delete an individual engram, an engram tied to a deleted conversation, engrams tagged with a topic, or engrams belonging to a user. `memory-service/app/engram/sources.py:193` `delete_source` nulls the FK on engrams (`ON DELETE SET NULL`, `schema.sql:125`) — the engrams themselves persist with `source_meta` intact. `orchestrator/app/conversations.py:105` deletes a conversation row (cascading to `messages`), but nothing propagates to engrams that were decomposed from those messages.
- **Impact:** Once an engram is written — from a private message, a crawled page, a voice transcript — there is no user-facing or admin-facing way to remove it. "Delete this conversation" removes the raw record but leaves the semantic memory intact. Consolidation (`consolidation.py`) can prune or merge but is opaque to the user. This is a trust-breaking gap for any daily-driver use.
- **Recommendation:** Add `DELETE /api/v1/engrams/{engram_id}` (hard-delete node + incident edges), `POST /api/v1/engrams/forget` accepting `{conversation_id? | source_id? | topic? | query?}` with a dry-run preview, and a dashboard "Forget" action on conversations and sources. Wire conversation-delete to enqueue an engram-forget job for any engram whose `source_type='chat' AND source_id=<conversation_id>`.
- **Effort:** M

### [P0] Orchestrator container mounts the entire host filesystem read-write

- **Evidence:** `docker-compose.yml:363-366` mounts `${NOVA_WORKSPACE}:/workspace:rw`, `.:/nova:rw`, `${HOME}:${HOME}:rw`, AND `/:/host-root:rw`. `orchestrator/app/tools/sandbox.py:69-70` exposes a `root` tier that returns `Path("/host-root")` — the full host filesystem is reachable by any agent execution that sets (or inherits) `SandboxTier.root`. `tools/code_tools.py`, `git_tools.py`, and LLM-driven tool calls are the entry points; tier enforcement is per-execution-context via a `ContextVar` (`sandbox.py:37`).
- **Impact:** Every LLM-generated tool call in the `root` tier has RW access to `~/.ssh/`, `~/.secrets`, `~/.1password/`, `~/.config/`, the user's entire git history, other projects' `.env` files, the Claude Code session data, and arbitrary system paths. A prompt-injection from a crawled page, RSS item, or MCP tool output that convinces an agent to run `cat ~/.ssh/id_*` exfiltrates the host. This is a privacy issue even without malicious intent — trust-boundary violations mean user data everywhere on the machine is in the agent's reach.
- **Recommendation:** Drop the bind mount `/:/host-root:rw` from the default compose; gate it behind an explicit `--profile dangerous-root` the user must opt in to. Replace the `root` tier with a narrow "allowed paths" allowlist. If self-modification needs broader access, confine it to `/nova:rw` only. Document clearly in `security.md` and on the Sandbox UI that `root` tier reveals everything on the host.
- **Effort:** M

### [P0] Factory reset ignores 90% of user data

- **Evidence:** `recovery-service/app/factory_reset.py:13-35` — the category map covers only `tasks`, `stage_results`, `messages`, `sessions`, `pod_agents`, `pods`, `api_keys`, `memories`, `usage_events`. It does NOT include: `engrams`, `engram_edges`, `engram_archive`, `sources` (table AND `/data/sources/*.txt` filesystem blobs), `intel_content_items`, `intel_content_items_archive`, `intel_recommendations`, `knowledge_sources`, `knowledge_credentials`, `knowledge_crawl_log`, `knowledge_page_cache`, `conversations`, `goals`, `cortex_*`, `friction_log` (+ `/data/friction-screenshots/`), `linked_accounts`, `platform_config`, `platform_config_audit`, `users`, `refresh_tokens`, `audit_log`. The `memories` table referenced in `CATEGORY_TABLES` no longer exists (replaced by engram tables in migration series).
- **Impact:** Users who click "Factory Reset" on the Recovery UI see a comforting list of categories but the operation leaves behind the bulk of their accumulated data — chat-derived engrams, knowledge-crawl results with potentially-sensitive credentials (encrypted but still present), intel feed content, conversation history, friction log screenshots, OAuth refresh tokens. The user believes they've wiped state; they haven't.
- **Recommendation:** Rewrite `CATEGORY_TABLES` to match the current schema. Add categories for `engrams` (with cascaded edges, archive, AND filesystem sources cleanup), `intel`, `knowledge_sources`, `knowledge_credentials`, `conversations_and_messages`, `cortex_state`, `friction_log_with_screenshots`, `linked_accounts`, `users_and_auth`, `platform_config`. Add a schema-drift test that fails CI when a new migration creates a table not assigned to any category.
- **Effort:** M

### [P1] Backups are unencrypted plaintext and contain every secret

- **Evidence:** `recovery-service/app/backup.py:38-82` creates `nova-backup-<ts>.tar.gz` as a plain `pg_dump` SQL text file inside a gzipped tar — no encryption, no passphrase. `backups/` has chmod 755 (`ls -l`). Existing backups range from 11 KB to 55+ MB and sit unencrypted next to the repo. The dump includes: `knowledge_credentials.encrypted_data` (envelope-encrypted under `CREDENTIAL_MASTER_KEY`, so those are safe IF the key is not also in the backup), `platform_config` (which stores `JWT_SECRET`, `OAUTH_CLIENT_SECRET`, and any runtime-set provider keys — `jwt_auth.py:55` writes `JWT_SECRET` here), `api_keys.key_hash` (bcrypt'd, OK), `refresh_tokens.token_hash`, the entire `messages.content` table with every prompt/response, `engrams.content` with decomposed memories, `sources.content`, `intel_content_items.body`.
- **Impact:** Any backup snapshot, if stolen, yields every conversation, every memory, and most stored secrets. `CREDENTIAL_MASTER_KEY` lives in `.env` — not in the backup — so knowledge credentials stay encrypted, but `JWT_SECRET` in `platform_config` means an attacker can forge admin tokens. Two different users sharing a machine, one with sudo, can read each other's backups at `0644`.
- **Recommendation:** Encrypt backups with a key derived from `NOVA_ADMIN_SECRET` or a dedicated `BACKUP_KEY` using age / gpg. Chmod `backups/` and files to `700` / `600`. At minimum, document that backups are plaintext before an export workflow is built. Include filesystem blobs (`data/sources/`, `data/friction-screenshots/`, `data/editor-config/`) in the archive so restore is actually complete.
- **Effort:** M

### [P1] Filesystem-stored sources are orphaned on source delete

- **Evidence:** `memory-service/app/engram/sources.py:134-142` writes sources >100 KB to `/data/sources/<first-2-hash>/<hash>.txt`. `sources.py:193-199` `delete_source` runs `DELETE FROM sources WHERE id = :id` — no filesystem cleanup, no reference to the `content_path` stored in the row. The orphaned `.txt` files live on disk indefinitely. Source content is often raw HTML or scraped article bodies that may contain PII surfaced from knowledge crawls.
- **Impact:** "Delete this source" gives the user false confidence — the blob is still on disk. Over time, the `/data/sources/` directory accumulates orphaned content that never appears in the dashboard and is never re-accessed. A forensic analysis of the volume recovers deleted source material.
- **Recommendation:** `delete_source` should `SELECT content_path` first, then `path.unlink()` the file (best-effort, log on failure), then execute the DB delete. Add a background `sources_gc` job that sweeps `data/sources/` for hashes not referenced by any `sources.content_path`.
- **Effort:** S

### [P1] All engrams, sources, and knowledge artifacts belong to a single hardcoded tenant

- **Evidence:** `memory-service/app/engram/ingestion.py:36,441` hardcodes `DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"` on every engram insert. `memory-service/app/engram/sources.py`, `activation.py:52`, `entity_resolution.py:28`, `retrieval_logger.py:29` all default to the same UUID. `orchestrator/app/knowledge_router.py:25,165,385,414,454,569` does the same for knowledge sources and credentials. `orchestrator/app/linked_accounts.py:80` auto-links Telegram/Slack platform IDs to "the single user" if `SELECT count(*) FROM users == 1`. The `tenant_id` column exists on `engrams`, `sources`, `knowledge_sources`, `knowledge_credentials`, but queries (`activation.py:100`, `entity_resolution.py:39`) filter by that default hardcoded UUID rather than by the caller's context.
- **Impact:** Today, single-user; tomorrow, the moment a second user is added, their memory, knowledge sources, and decrypted credentials flow into the same graph as the first user's. The "auto-link" logic in `linked_accounts.py:80` binds a Telegram message to whichever single user exists, not the right user. Any future multi-user deployment silently unifies per-user memory and reveals one user's private information to the other. The tenant plumbing looks done but is wired to one constant.
- **Recommendation:** Before shipping multi-user, thread `tenant_id` through the engram ingestion request path (orchestrator → memory-service `/context` and `/ingest`). Same for knowledge CRUD: stop defaulting to `DEFAULT_TENANT_ID`, derive from `UserDep.tenant_id`. Write a one-time migration that re-tags existing rows to the first user's tenant. Add a test that a second user cannot retrieve the first user's engrams.
- **Effort:** L

### [P1] No user-data export, no user deletion

- **Evidence:** Searched `orchestrator/` — no `/api/v1/users/{id}` DELETE endpoint, no `/api/v1/auth/me` DELETE, no `/export` endpoint for user data (`orchestrator/app/auth_router.py:300-310` only has `GET`/`PATCH` on `/me`). The dashboard (`dashboard/src/api/users.ts`) has `updateUser` but no `deleteUser`. The only export is `GET /api/v1/training-data/export` (`router.py:845`) — admin-only, exports fine-tune training data, not user-facing. Chat conversations can be deleted (`conversations.py:105`) and friction log entries (`friction_router.py:218-222`); nothing else.
- **Impact:** A user cannot delete their own account. Cascading deletes on `users` table (`ON DELETE CASCADE` on `conversations`, `refresh_tokens`, `linked_accounts`) would clean some state if a user row were deletable, but the UI doesn't expose that and engrams / sources / goals / cortex state would remain orphaned. Under any remote-sharing scenario (family, partner, inviting a friend as a guest) this is a meaningful gap.
- **Recommendation:** Add `DELETE /api/v1/users/me` (self-delete) and `DELETE /api/v1/users/{id}` (admin-delete) with cascading cleanup to all user-owned tables, including an engram-forget sweep. Add `GET /api/v1/users/me/export` returning a zip of conversations (NDJSON), messages, engrams filtered by their sources, knowledge sources, sessions, and usage events — one user, everything they own, in under a minute.
- **Effort:** M

### [P1] Unbounded growth on intel and knowledge tables; engrams grow forever

- **Evidence:** `orchestrator/app/migrations/038_intel_schema.sql` — `intel_content_items` has no retention policy, only an `intel_content_items_archive` sibling table. Examining `orchestrator/app/intel_router.py`: the archive is `LIKE intel_content_items INCLUDING ALL` but no code writes to it (confirmed by grep). `intel-worker/app/poller.py:54` polls feeds every `poll_interval` seconds; by default RSS/Reddit/page feeds check every 1–6 hours and insert new items indefinitely. `knowledge_page_cache` and `knowledge_crawl_log` have no retention. Engrams: `consolidation.py` prunes *some* based on activation/importance but there is no time-based aging and no user-facing "memories older than X days" policy. Task history has a configurable `task_history_retention_days` (`reaper.py:262-296`) — 0 = keep forever — and is the only retention setting surfaced in platform config.
- **Impact:** A year of daily-driver use accumulates: hundreds of thousands of intel items (many RSS-duplicated), every crawled page forever, every engram ever created. Postgres size grows monotonically, queries slow, the "Brain" graph visualization becomes unreadable, and backups balloon. The user has no knob to trim.
- **Recommendation:** Add platform-config retention keys for `intel.retention_days`, `knowledge_crawl_log.retention_days`, `engram.low_importance_retention_days`. Wire them into the existing reaper loop. Surface in Settings → Platform Defaults. Default to reasonable values (intel: 90 days, crawl log: 30 days, engrams: keep forever unless importance < 0.3 and age > 180 days).
- **Effort:** M

### [P2] Prompt-content leakage at DEBUG log level

- **Evidence:** `orchestrator/app/model_classifier.py:170` — `log.debug("Classifier (%s): '%s' → %s", model, user_message[:50], category)` logs the first 50 chars of the user message on every classifier call. `pipeline/complexity_classifier.py:100` — similar, first 50 chars of `task_input`. `chat_scorer.py:329` and `effectiveness.py:163` log truncated response bodies on failures. LiteLLM provider has `litellm.drop_params = True` but no explicit logging suppression; LiteLLM's internal debug logging can emit full request payloads when `LITELLM_LOG=DEBUG`.
- **Impact:** At the default `LOG_LEVEL=INFO` this is silent. But the setup scripts and `.env.example` leave `LOG_LEVEL` commented — a user debugging an issue who flips to `DEBUG` starts writing prompt fragments to `docker compose logs`. Docker logs are JSON files on disk at `/var/lib/docker/containers/<id>/*.log` — world-readable in many default installs. Anyone with shell access to the host can grep past prompts.
- **Recommendation:** Replace first-50-char prompt slices in classifier debug logs with a content hash or length-only summary. Document in `security.md` that `LOG_LEVEL=DEBUG` leaks prompt fragments; add a warning when flipping the setting from the dashboard. Optionally add a `NOVA_PROMPT_REDACTION=true` flag that hashes prompts in all debug logs.
- **Effort:** S

### [P2] Intel worker reveals Nova deployment to every site it polls

- **Evidence:** `intel-worker/app/fetchers/rss.py:15`, `page.py:14`, `reddit.py:10`, `github.py:12` all set `User-Agent: Nova-Intel/1.0 (AI ecosystem monitor)` or `Nova-Intel/1.0`. Every feed host sees a distinct Nova fingerprint in their logs — self-hosted blogs, Reddit, GitHub — enabling any operator with access to those logs to fingerprint Nova installs by their polling pattern.
- **Impact:** Low privacy impact for most users, but noteworthy: it's a stable identifier across deployments and a retention signal to third-party site operators. Not a browser UA — it stands out in logs.
- **Recommendation:** Either randomize with a standard browser UA, or expose a `INTEL_USER_AGENT` env var defaulting to a generic Mozilla string. The "AI ecosystem monitor" disclosure isn't load-bearing.
- **Effort:** S

### [P2] Friction-log screenshots persist after parent task deletion

- **Evidence:** `orchestrator/app/migrations/032_friction_log.sql:12` — `friction_log.task_id` has `ON DELETE SET NULL`. `friction_router.py:199-228` deletes screenshot files when a friction entry is deleted. But when the underlying task is deleted (via `pipeline_router.py:332`), the friction entry remains with `task_id=NULL` and the screenshot stays on disk. Screenshots are saved to `/data/friction-screenshots/<entry_id>.webp` (and thumb).
- **Impact:** Minor data growth; screenshots of dashboard UI can contain surfaced chat content in context panels. A user clearing task history expects related artifacts to go.
- **Recommendation:** On task delete, optionally cascade-delete associated friction entries (behind a flag) or at least offer that in the bulk-delete UI. Add a `friction.retention_days` policy similar to the task one.
- **Effort:** S

### [P2] Cloudflare Tunnel profile silently proxies all traffic through Cloudflare

- **Evidence:** `docker-compose.yml:839-850` defines `cloudflared` sidecar. `.env.example:101-106` documents it as the default "remote access" recommendation above Tailscale. When enabled, every request to the dashboard, every API call, every WebSocket chat stream, every SSE completion passes through Cloudflare's edge and is subject to Cloudflare's terms, logging, and potential MITM via TLS termination at their edge.
- **Impact:** Users enabling "Remote Access" from the Settings UI may not realize that "Cloudflare Tunnel" means "every byte of Nova traffic goes through Cloudflare's infrastructure unencrypted from their POV, unlike Tailscale which is end-to-end WireGuard." The phrasing in `.env.example` pitches Cloudflare first and Tailscale second — a user who picks the first listed option gets the less-private one.
- **Recommendation:** Rewrite the `.env.example` and dashboard Settings copy to lead with Tailscale (full privacy), and mark Cloudflare Tunnel as "public-but-authenticated (Cloudflare sees plaintext traffic)." No code change needed — this is a documentation / UX-copy issue that sets user expectation correctly.
- **Effort:** S

### [P3] Anthropic/OpenAI subscription OAuth tokens sent to cloud endpoints under user billing

- **Evidence:** `llm-gateway/app/providers/claude_subscription_provider.py:9-13` docs that `CLAUDE_CODE_OAUTH_TOKEN` is sent to `api.anthropic.com`. `chatgpt_subscription_provider.py` similar for OpenAI. This is expected and documented, but the dashboard has no per-request indicator showing which provider saw a given chat turn (the Routing Strategy setting controls it globally, but users can't see per-session which prompts reached Anthropic vs. stayed local).
- **Impact:** A user setting "cloud-first" routing and thinking "Groq handles my queries" may see some sensitive prompt go to Anthropic due to quota/tier routing. No per-turn provenance is shown.
- **Recommendation:** Add a per-message provider badge in the chat UI (or context panel) showing `local:ollama`, `cloud:anthropic`, etc. Already partly available via `usage_events.model`, just surface it.
- **Effort:** S

## Summary

- Nova has extensive memory infrastructure but **no way for a user to delete, export, or audit what the system remembers about them**. Engrams, sources, and filesystem blobs accumulate indefinitely; factory reset misses the majority of user data.
- The orchestrator container has **read-write access to the entire host filesystem** via `/:/host-root:rw` — any tool-calling agent can exfiltrate SSH keys, `.env` files, or unrelated project secrets. This is the single largest privacy-boundary violation in the repo.
- **Multi-tenancy plumbing is wired to one hardcoded UUID** across engrams, sources, knowledge sources, credentials. Current single-user deployments are fine; the first attempt to add a second user will silently merge their data with the existing user's graph.
- **Backups are unencrypted** and contain every message, every memory, `JWT_SECRET`, and OAuth tokens. Filesystem-stored sources (>100 KB) aren't even *in* the backup, so restore is partial.
- **Retention is absent everywhere** except task history (which defaults to "keep forever"). Intel, knowledge crawls, engrams, friction screenshots, conversations all grow unbounded.

The common theme: plumbing exists (tenant columns, source provenance, filesystem sharding, factory-reset categories) but the **control surface is missing** — no user-facing "forget," no per-tenant routing, no retention knobs, no encrypted export. Before Nova can be a daily-driver shared with family or anyone else, the "I want my data gone" path has to exist end-to-end.
