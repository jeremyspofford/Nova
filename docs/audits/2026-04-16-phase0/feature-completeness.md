# Feature Completeness Audit — 2026-04-16

## Scope

Classifies each major Nova feature as **Shipped / Partial / UI-only / Stub / Broken / Missing** and
identifies the gap to daily-driver-readiness. Deltas from `docs/feature-audit-2026-03-25.md`.

**In scope:** Chat, Engram memory, memory tools, source provenance, intel, knowledge, voice,
cortex, dashboard pages, recovery, chat bridges, triggers/scheduler, auth, MCP tools, distributed
deployment.

**Out of scope:** Individual bug-level defects (other axes). Nova-suite features (axis 9). Deep
performance/security/UX analysis (other axes own those).

**Method:** Code walk across all service roots, live API probes against the running stack
(observed: 14 feeds → 201 items this week → 97 graded recommendations; 6,462 engrams / 79,117 edges;
neural router trained with 5,898 labeled observations), and a delta read against the March 2026
audit.

---

## Legend

| Status | Meaning |
|---|---|
| **Shipped** | Feature works end-to-end, wired UI-to-backend, acceptable daily-driver quality |
| **Partial** | Most of the feature works; meaningful daily-driver gaps remain |
| **UI-only** | Dashboard page renders but the backend is missing, stubbed, or disconnected |
| **Stub** | Scaffolding exists (tables, endpoints, classes) but no real behavior |
| **Broken** | Shipped but not currently functional |
| **Missing** | Not implemented — design may exist |

---

## Findings

### [P2] Chat (dashboard + chat-api + streaming + PWA)

- **Status:** Shipped
- **Evidence:**
  - `dashboard/src/pages/chat/ChatPage.tsx` (576 lines), `ChatInput.tsx`, `MessageBubble.tsx`,
    `DelegationCard.tsx`, `VoiceButton.tsx` — fully built multi-component chat UI.
  - `dashboard/src/pages/Chat.tsx:1` is a 1-line barrel re-export from `chat/ChatPage.tsx`
    (intentional; not a stub).
  - `chat-api/app/main.py`, `websocket.py`, `session.py`, `drain.py` — WebSocket streaming bridge
    works, service healthy on 8080.
  - `dashboard/public/manifest.json` + `dashboard/public/sw.js` — PWA manifest and service worker
    shipped. Installable.
- **Daily-driver gap:** Three uncommitted changes in `ChatInput.tsx` / `ChatPage.tsx` /
  `MessageBubble.tsx` per git status — Jeremy is in the middle of a tweak. Push notifications
  (VAPID) are still missing per roadmap. Offline message queue for flaky networks not implemented.
  For a trusted daily-driver, a chat that never loses input during a reconnect matters; the current
  WebSocket reconnect path silently drops in-flight messages.
- **Effort to close gap:** S for finishing the uncommitted work; M for push notifications +
  reconnect-safe queuing.

---

### [P1] Engram Memory System — ingestion, retrieval, consolidation

- **Status:** Shipped
- **Evidence:**
  - `memory-service/app/engram/ingestion.py` (507 lines), `activation.py` (315), `working_memory.py`
    (376), `consolidation.py` (739), `outcome_feedback.py` (176), `reconstruction.py` (371).
  - Live stats (probed 2026-04-16): 6,462 engrams, 79,117 edges, 8 node types represented,
    consolidation runs recorded (`/api/v1/engrams/consolidation-log` returns recent idle triggers,
    pruning 78,939 edges in last cycle).
  - Router `memory-service/app/engram/router.py:1473` lines — all endpoints live.
- **Daily-driver gap:** Consolidation is pruning engrams heavily (78,939 / 101,438 edges pruned per
  recent idle cycle) but `schemas_created=0`, `edges_strengthened=0`, `contradictions_resolved=0`
  in the last three runs. The sleep-cycle "intelligence" phases (pattern extraction, Hebbian
  learning, contradiction resolution) appear to run but produce nothing — this is invisible to the
  user but undermines the premise. Separately, no user-facing "what was consolidated last night?"
  surface exists in the dashboard.
- **Effort to close gap:** M — investigate why the higher-order consolidation phases are no-ops;
  add a consolidation-result surface to Memory Health page.

---

### [P2] Neural Router (learned re-ranker)

- **Status:** Shipped (activated since March audit)
- **Evidence:**
  - `GET /api/v1/engrams/router-status` returns live: 8,282 observations, 5,898 labeled,
    `mode=embedding_reranker`, `model_loaded=true`.
  - `memory-service/app/engram/neural_router/{train.py (519), serve.py, model.py, features.py}`
    — full pipeline, including a dedicated `nova-neural-router-trainer-1` container.
  - March audit said "requires 200+ labeled observations" — now training on ~5.9k labeled, so this
    moved from "pending" to "shipped".
- **Daily-driver gap:** No dashboard surface to inspect router training runs, cross-validation
  scores, or feature importances. Training happens in a black box.
- **Effort to close gap:** S for a read-only router status page in Memory/Brain settings.

---

### [P2] Memory Tools for Agents

- **Status:** Shipped
- **Evidence:**
  - `orchestrator/app/tools/memory_tools.py` — `what_do_i_know`, `search_memory`, `recall_topic`,
    `read_source`, plus the newer `get_consolidation_status`, `get_memory_stats`,
    `trigger_consolidation` from Tier 2 of the autonomous-loop plan (confirmed in
    `runner.py:886-887` where skills resolution also lives).
  - Tool catalog (`GET /api/v1/tools`) currently exposes 11 categories / 65 tools including
    "Memory Tools", "Diagnosis Tools", "Introspection Tools", "Intel Tools".
- **Daily-driver gap:** `memory_retrieval_mode` still defaults to `inject` per CLAUDE.md. No
  dashboard toggle (roadmap item). For tool-mode to be the default, a feedback loop that confirms
  agents use tools correctly is missing — right now tools exist but usage is opaque.
- **Effort to close gap:** S for the toggle; M for tool-usage telemetry.

---

### [P2] Source Provenance & Re-decomposition

- **Status:** Shipped
- **Evidence:**
  - `memory-service/app/engram/sources.py` (365 lines) — full CRUD.
  - Router endpoints: `POST /sources`, `GET /sources`, `GET /sources/{id}/content`,
    `DELETE /sources/{id}`, `GET /sources/domain-summary`, `POST /sources/{id}/redecompose`.
  - Live stats show provenance by source type: intel=3,444 engrams, consolidation=2,595, chat=418,
    knowledge=3, external=2 — but the fact that knowledge=3 is striking given how many knowledge
    sources are configured.
  - `dashboard/src/pages/Sources.tsx` (452 lines) + Engram Explorer Provenance tab.
- **Daily-driver gap:** Only 3 engrams attributed to knowledge-worker despite sources being
  configured with URLs like `https://www.reddit.com/r/LocalLLaMA/` and `https://docs.openclaw.ai/`
  (both show `last_crawl_at=null`). Either no crawls have actually run, or they ran but didn't
  produce useful content. The "Shipped" sources subsystem is working; the "Partial" piece is
  whatever upstream produces sources (knowledge worker — see next finding).
- **Effort to close gap:** M — diagnose why knowledge sources never crawled.

---

### [P1] Intel Worker & Recommendation Pipeline — **MAJOR DELTA**

- **Status:** Shipped (was **Partial, critical gap** in March audit)
- **Evidence:**
  - `POST /api/v1/intel/recommendations` endpoint **exists and is live** (`intel_router.py:358`).
    This was missing in March.
  - Live stats: 14 active feeds, 201 items this week, **97 total recommendations** generated
    (22 grade-A, 46 grade-B, 29 grade-C).
  - Seeded system goals "Weekly Intelligence Synthesis" and "Daily Intelligence Sweep" now have
    concrete multi-step descriptions in DB. `current_plan` shows LLM-generated plans being
    dispatched, iteration 1 of 50.
  - `orchestrator/app/tools/intel_tools.py` — `query_intel_content`, `create_recommendation`,
    `get_dismissed_hashes` tools registered in the catalog.
  - Dead queue `intel:new_items` (db6) is empty (LLEN=0); test `tests/test_intel_recommendations.py`
    asserts the queue stays drained.
- **Daily-driver gap:** Recommendations accumulate but user workflow on them (approve → goal →
  task → PR) is not yet end-to-end. The Goals page shows pending recs but the "approve → create
  goal" handoff ergonomics need review. Cortex synthesis cycles are still `progress=0.02` and
  `cost_so_far_usd=0.0` — the goal runs but reports no cost, suggesting cost rollup is still
  broken for cortex-dispatched work.
- **Effort to close gap:** M — finish the approve-to-goal flow; fix cortex cost rollup.

---

### [P1] Knowledge Worker — Partial but Improved

- **Status:** Partial
- **Evidence:**
  - `knowledge-worker/app/scheduler.py` (228 lines), `crawler/engine.py` (269), `extractors/github.py`
    (246), `credentials/health.py` (157).
  - Credential retrieval is now wired: `knowledge-worker/app/credentials/__init__.py:11` calls
    orchestrator `/api/v1/knowledge/credentials/{id}/retrieve`, decrypts via
    `BuiltinCredentialProvider`. March audit listed this as a `scheduler.py:111` TODO — resolved.
  - Credential health checks hit real platform APIs: `credentials/health.py:PLATFORM_CHECKS` maps
    github_profile → `https://api.github.com/user`, gitlab_profile → gitlab.com — also resolved.
  - Knowledge-worker is **not running** in the current stack (`docker compose ps` shows no
    knowledge-worker container; it's gated behind `--profile knowledge`).
  - Only 3 engrams in the whole store have `by_source_type=knowledge` — most knowledge sources
    have `last_crawl_at=null`.
- **Daily-driver gap:** Not started by default. Jeremy won't benefit from autonomous personal
  knowledge crawling unless the profile is enabled. No GitLab/social extractors. No per-source
  crawl dedup (roadmap item, still open).
- **Effort to close gap:** S to enable by default; M to ship GitLab/social extractors.

---

### [P2] Voice Service — **Discrepancy with CLAUDE.md**

- **Status:** Partial
- **Evidence:**
  - `voice-service/app/providers/` — only `openai_stt.py` and `openai_tts.py` implemented.
  - `providers/__init__.py:89-91` and `:104-105` raise `ValueError("Unknown STT/TTS provider")`
    for anything other than `openai`. Deepgram and ElevenLabs are referenced in config/key
    resolution (`_resolve_api_key` at `providers/__init__.py:64-67`) but no provider class exists.
  - CLAUDE.md claims: "STT/TTS provider proxy: OpenAI Whisper, OpenAI TTS, Deepgram, ElevenLabs".
    **This is inaccurate** — only OpenAI works.
  - Service is running on 8130, healthy; `/health/ready` returns `stt_provider=openai`,
    `stt_available=true`, `tts_provider=openai`, `tts_available=true`.
  - Dashboard Settings has a Voice section (per Settings.tsx structure).
- **Daily-driver gap:** If Jeremy changes Settings to Deepgram or ElevenLabs (exposed in the UI
  per docs), voice will hard-fail at runtime. Either the UI must only offer OpenAI, or Deepgram/
  ElevenLabs providers must actually be implemented.
- **Effort to close gap:** S (hide non-OpenAI options until implemented) or M (implement the
  other two providers).

---

### [P1] Cortex (Autonomous Brain)

- **Status:** Shipped (major Tier-1 and Tier-2 fixes landed since March)
- **Evidence:**
  - `cortex/app/cycle.py` is now 1,143 lines (up from ~800 per prior reads) — includes:
    - Consecutive-skip tracking (`MAX_CONSECUTIVE_SKIPS=3` at line 38)
    - Scheduled-goal priority via `_select_goal()` (line 46)
    - Rich goal planning context: description, current_plan, iteration, max_iterations, cost
      (line 319–370 in `_plan_action`)
    - Reflection history query + format (line 373–381)
    - Force-action after 3 skips (line 333)
    - "Last attempt FAILED" context propagation with prior-checkpoint replay (line 342–360)
  - `cortex/app/drives/serve.py:42-44` enforces `iteration < max_iterations` and
    `cost_so_far_usd < max_cost_usd` in the stale-goal query — resolves March's "infinite skip
    loop" bug.
  - `cortex/app/scheduler.py` — croniter-based goal scheduling active (goals with `schedule_cron`
    fire via `goal.schedule_due` stimulus).
  - `cortex/app/task_tracker.py`, `task_monitor.py` — TRACK phase collects outcomes.
  - `cortex/app/reflections.py` referenced at `cycle.py:28` — reflection-learning is wired (the
    `feature/cortex-learning-from-experience` branch has landed).
  - Cycle count live: ~15,000 cycles. Actively running.
- **Daily-driver gap:** Cycle 14997 logs show `outcome=No stale goals to work on` even with active
  goals present — the stale-query filters may be over-exclusive, or goals are routinely freshly-
  checked from scheduled fires. Goal progress visible in DB is still 0.02 with `cost_so_far_usd=0.0`
  on an iteration-1 goal — cost rollup may still have a gap. Maturation pipeline (triaging →
  scoping → speccing → review → building → verifying) is present in schema and enforced as a filter
  in `serve.py` but **no drive implements the transitions**; the maturation stub from March
  remains.
- **Effort to close gap:** M — diagnose cost rollup, complete maturation drive logic.

---

### [P2] Dashboard — per page

All non-legacy pages resolve and fetch data. Delta is mostly consolidation (fewer, better pages)
since March.

| Page | Status | Notes |
|---|---|---|
| Chat (`chat/ChatPage.tsx`) | Shipped | See Chat finding above |
| Brain (`Brain.tsx`, 918 lines) | Partial | Instanced rendering shipped; lightweight API integration regressed per roadmap; settings persistence broken |
| Memory/Engram Explorer | Shipped | Sources tab exists; Provenance tab now named correctly |
| Sources (`Sources.tsx`, 452 lines) | Shipped | Unified knowledge + intel feeds; tabs correct |
| Intelligence | Shipped (redirects to `/sources#recommendations`) | No separate page |
| Goals (`Goals.tsx`, 1,173 lines) | Shipped | Maturation, schedules, suggested recommendations |
| Tasks | Shipped | Board + lifecycle per roadmap |
| Recovery (`Recovery.tsx`, 709 lines) | Shipped | All 20+ recovery endpoints wired |
| Settings (`Settings.tsx`, 821 lines) | Shipped | 30 section components including Voice, RemoteAccess, Vaultwarden, SelfMod |
| AI Quality (`AIQuality.tsx`, 766 lines) | Shipped | Benchmark runner, memory benchmark, dimension tracking |
| Skills (`Skills.tsx`, 441 lines) | Shipped | Full CRUD + category badges |
| Rules (`Rules.tsx`, 455 lines) | Shipped | Full CRUD; 3 system rules seeded |
| Pods / Models / Keys / Users | Shipped | Minor evolution since March |
| Friction | Shipped (debug-only flag) | Hidden from sidebar unless debug |
| Integrations | Shipped | MCP servers + Agent Endpoints consolidated |
| Editor | Shipped (lazy-loaded) | Neovim + VSCode configs |
| IDE Connections | Shipped | Continue, Cursor, Aider |
| Invite, Login, Onboarding, Expired | Shipped | Auth flows |
| UserProfile, About | Shipped | Straightforward |
| ComponentGallery (`/dev/components`) | Shipped | Developer-only |

Notably `Skills` and `Rules` pages are still in the codebase at top-level, but `App.tsx:230-232`
redirects `/skills` and `/rules` to `/settings#behavior`. The inline Settings sections
(`settings/SkillsSection.tsx`, `RulesSection.tsx`) are the canonical UI. The top-level pages exist
but are unreachable via nav — light dead code.

- **Daily-driver gap:** Dead-code Skills.tsx/Rules.tsx pages; Brain regressions per roadmap.
- **Effort to close gap:** S to remove dead pages; M for Brain regression fixes.

---

### [P3] Recovery Service

- **Status:** Shipped
- **Evidence:**
  - `recovery-service/app/routes.py` (407 lines) — 20 endpoints: services restart, backups,
    factory reset, env editor, compose-profiles, remote-access, chat-integrations, diagnostics,
    troubleshoot/chat.
  - `recovery-service/app/inference/` has hardware detection, model search, controller — all from
    managed-inference work.
  - Dashboard Recovery page (709 lines) wired to all endpoints.
- **Daily-driver gap:** None observed for core backup/restore. The newer chat-integrations
  `/recovery-api/chat-integrations/status` returned 404 in dev but that's because the test hit
  `/recovery-api/backups` which routes differently — `/api/v1/recovery/backups` is the actual
  path. Minor dashboard vs. backend path parity worth checking.
- **Effort to close gap:** S.

---

### [P1] Chat Bridges — **Discrepancy with CLAUDE.md + Roadmap**

- **Status:** Partial (Telegram only)
- **Evidence:**
  - `chat-bridge/app/adapters/` contains only `telegram.py` (194 lines) + `base.py` (38 lines).
  - `chat-bridge/app/main.py:36` warns "Set TELEGRAM_BOT_TOKEN or SLACK_BOT_TOKEN in .env" but
    **no Slack adapter implementation exists**. `chat-bridge/app/config.py` defines
    `slack_bot_token` / `slack_app_token` as settings but they are never read by an adapter class.
  - CLAUDE.md claims: "Multi-platform chat integration: Telegram, Slack". Roadmap also lists
    "Slack adapter done via chat-bridge" under Phase 8c. **Both overstate.**
  - Prior iteration's `feature/unified-chat-pwa` branch "Telegram integrations broken" per roadmap
    — so Telegram itself may be partially broken.
- **Daily-driver gap:** Multi-platform messaging is a material daily-driver feature (phone/laptop
  parity via Telegram is how Jeremy would chat mobile). Slack was promised but not built. Telegram
  is reported broken on a feature branch; main branch status uncertain.
- **Effort to close gap:** M to fix Telegram regressions; M to build Slack adapter.

---

### [P2] Triggers / Scheduler — Jeremy's explicit callout

- **Status:** Partial (goal-level cron only)
- **Evidence:**
  - Migration `024_goal_schedules.sql` adds `schedule_cron`, `schedule_next_at`,
    `schedule_last_ran_at`, `completion_count`, `max_completions` to `goals`.
  - `cortex/app/scheduler.py` — `check_schedules()` uses `croniter` to fire `goal.schedule_due`
    stimuli each cycle. Confirmed active in logs (feeds are polled).
  - `orchestrator/app/tools/platform_tools.py` — agent tool for creating goals validates cron
    expressions at creation time.
  - **This satisfies "create a task that runs at 9am every day" at the goal level** — create a
    goal with `schedule_cron='0 9 * * *'`, it fires daily.
- **Daily-driver gap:**
  1. **No user-facing UI for schedules.** The Goals page exposes creation but schedule_cron is
     buried in the DB schema; no "Schedule this goal" picker in the UI I could find.
  2. **No generalized "trigger" abstraction** beyond goals. There's no webhook receiver, file
     watcher, or event-stream trigger — roadmap Phase 9/9a ("Infrastructure + Triggers", "Reactive
     Event System") is still NOT STARTED per roadmap.
  3. **No ad-hoc scheduled chat prompts.** Jeremy can't say "ask me about my day at 6pm" without
     creating a full goal with description and success criteria.
  4. **Skip/miss semantics** — if cortex is down when a cron fires, the scheduled stimulus is
     never injected (no catch-up on missed runs).
- **Effort to close gap:** M for schedule picker in Goals UI; L for generalized triggers/reactive
  event system.

---

### [P0] Auth — Partial, has been tightened

- **Status:** Shipped (for built-in model; multi-user gaps remain)
- **Evidence:**
  - `orchestrator/app/auth.py` — API key auth (`ApiKeyDep`), admin auth (`AdminDep`), JWT user
    auth (`UserDep`) with dynamic `_get_require_auth()` reading `platform_config.auth.require_auth`
    (30s cache).
  - `.env.example:93` and `docker-compose.yml:343,415,462,713` all default to `REQUIRE_AUTH=true`
    (was false in March). This was a P1 fix in SEC-1 per the platform review.
  - RBAC columns on users, invite codes, tenants table, `RoleDep(min_role=...)`.
  - Neural-router trainer and synthetic admin user exist (migration 054).
- **Daily-driver gap:** Per roadmap, multi-tenancy is only partially shipped — engram retrieval is
  not tenant-scoped, Redis keys are not namespaced, audit logging for role changes is missing.
  For a single-user daily-driver, this is acceptable; for adding the family (stated future goal),
  it's a blocker.
- **Effort to close gap:** L (full multi-tenancy is its own design).

---

### [P2] MCP Tool Catalog

- **Status:** Shipped
- **Evidence:**
  - `GET /api/v1/tools` returns 11 categories, 65 tools including firecrawl (12 tools) and
    puppeteer (11 tools) as MCP-registered servers.
  - `GET /api/v1/mcp-servers` returns firecrawl and puppeteer both `connected=true` with full
    active tool lists.
  - `orchestrator/app/pipeline_router.py:877-982` — full MCP server CRUD + reload endpoint.
  - Integrations page in dashboard wires to all of it.
- **Daily-driver gap:** No "add MCP server from marketplace" experience (roadmap's MCP
  Integrations Hub is Future Vision). For daily use, the user must know the server command and
  env.
- **Effort to close gap:** M for a minimal marketplace UI.

---

### [P2] Distributed Deployment

- **Status:** Missing (design only)
- **Evidence:**
  - Design spec exists at `docs/superpowers/specs/2026-03-28-distributed-deployment-design.md`.
  - No implementation: no multi-host compose, no gateway service for multi-instance, no
    distributed Redis/pgvector config. Only `docker-compose.yml`, `docker-compose.gpu.yml`,
    `docker-compose.rocm.yml` exist.
  - Scripts directory has `backup.sh`, `detect_hardware.sh`, `resolve-ollama-url.sh`,
    `restore.sh`, `setup-remote-ollama.sh`, `setup.sh` — nothing distributed.
- **Daily-driver gap:** N/A for Jeremy's single-box daily-driver context. Strategic for the
  "multiple devices, shared brain" vision but not urgent.
- **Effort to close gap:** L (major design work before code).

---

### [P3] Skills Framework (extensibility)

- **Status:** Shipped (was NOT STARTED in March)
- **Evidence:**
  - Migration `047_skills_and_rules.sql` — both tables exist with CHECK constraints,
    category/scope/enforcement enums, seeded system rules (no-rm-rf, workspace-boundary,
    no-secret-in-output, no-direct-main-commit).
  - `orchestrator/app/skills.py` (108 lines), `rules.py` (157 lines) — full CRUD + regex
    compilation cache.
  - `orchestrator/app/tools/__init__.py:145` — `check_hard_rules(name, arguments)` enforced at
    tool execution time. Actually wired, not just declared.
  - `orchestrator/app/agents/runner.py:886-887` — `resolve_skills()` injected into agent system
    prompts.
  - Dashboard Skills/Rules sections in Settings.
  - Skills table is empty in current DB (`GET /api/v1/skills` returned `[]`), so **the framework
    is live but no skills are defined yet**.
- **Daily-driver gap:** Framework works; content is empty. No seeded skills means the system is
  effectively a no-op for skills. Seed a handful of starter skills (code-review checklist,
  TDD process, commit message format) to make this visible and valuable on day one.
- **Effort to close gap:** S to seed 5–10 starter skills.

---

### [P2] AI Quality Scoring + Benchmarks

- **Status:** Shipped (new since March)
- **Evidence:**
  - Migration `056_quality_scoring.sql` — `quality_scores` and `quality_benchmark_runs` tables.
  - `orchestrator/app/quality_router.py` — per-dimension scoring (memory_relevance,
    memory_recall, tool_accuracy, response_coherence, memory_usage, task_completion).
  - `orchestrator/app/quality_scorer.py` — LLM-graded scoring.
  - `benchmarks/quality/runner.py` (217 lines), `cases.py` (90) — benchmark harness.
  - Dashboard `AIQuality.tsx` (766 lines) — dimension tracking + benchmark runner + memory
    provider comparison (engram vs pgvector vs mem0 vs markdown).
- **Daily-driver gap:** No evidence scoring is running automatically in production — confidence
  and dimension columns exist but may not be populated. Worth checking if the scoring runs
  post-turn or is dashboard-triggered only.
- **Effort to close gap:** S — verify auto-scoring pipeline is active.

---

### [P2] Self-Modification (Nova writing code for itself)

- **Status:** Stub (new since March)
- **Evidence:**
  - Migration `055_selfmod.sql` — `selfmod_prs` table with PR audit trail columns, seeded safety
    rule "Nova must never merge its own PRs".
  - `orchestrator/app/router.py:1365-1408` — `/api/v1/selfmod/status`, `/selfmod/prs`,
    `/selfmod/prs/{pr_id}` endpoints.
  - Dashboard `SelfModSection.tsx` in Settings.
  - `cortex/app/drives/improve.py:70` — `selfmod_trigger` referenced, dispatched to orchestrator.
- **Daily-driver gap:** Scaffolding present; actual workflow (detect improvement → scope PR →
  execute on a branch → open PR → wait for human review) is not yet verified end-to-end. Needs
  integration testing and at least one successful self-modification PR before trusting.
- **Effort to close gap:** M — needs careful verification and probably a dedicated agent.

---

## Summary

1. **Delta since March is substantial.** Intel recommendation pipeline, Skills/Rules enforcement,
   neural router activation, goal cron scheduling, quality scoring, self-modification scaffolding,
   and knowledge credential retrieval all moved from partial/missing to shipped. The March audit's
   "most visible gap" (intel recommendation generation) is closed — 97 recommendations in the DB.
2. **Persistent daily-driver blockers not yet closed:**
   - Slack chat bridge is documented but not built (Telegram-only in code).
   - Voice service claims Deepgram/ElevenLabs support but only OpenAI providers exist — config
     resolver will raise `ValueError` if a user picks another provider in Settings.
   - Generalized triggers (webhook, file watch, reactive event) are still missing — goal-level
     cron exists but no schedule picker in the Goals UI.
   - Cortex maturation pipeline (triaging → scoping → speccing → review → building → verifying)
     is in schema but no drive executes it.
3. **Shipped features with quality concerns:**
   - Consolidation runs but higher-order phases (pattern extraction, Hebbian learning,
     contradiction resolution) report zeros — the sleep cycle may be degenerate.
   - Cortex cost tracking still shows `cost_so_far_usd=0.0` on goals with active work — rollup
     gap may not be fully fixed despite March's 3-gap patch.
   - Knowledge-worker is profile-gated (off by default) and only 3 engrams have knowledge
     provenance despite configured sources with `last_crawl_at=null`.
4. **Paper-gap vs. real gap:** The skills framework is technically shipped but the skills table
   is empty — from a user perspective, it doesn't exist until someone seeds content. Same for
   Self-Modification: the table exists but no real PR workflow has been exercised.
5. **Low-effort wins to bring Nova closer to daily-driver:**
   - Fix CLAUDE.md to match reality on voice providers and Slack.
   - Seed 5–10 starter skills.
   - Add a schedule picker to Goals UI (goal cron already works backend-side).
   - Remove dead top-level Skills.tsx / Rules.tsx pages now that Settings sections own them.
   - Expose consolidation summary on Memory Health page.
