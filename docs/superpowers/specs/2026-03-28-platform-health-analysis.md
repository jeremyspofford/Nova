# Platform Health Analysis — 2026-03-28

Deep analysis of four systemic issues impacting Nova's autonomous operation.

## 1. Cortex Goal Execution Pipeline

### Problem
Cortex has run 6700+ thinking cycles but every cycle produces "Skipped — no meaningful action to take." All 4 goals are stuck at iteration 1/50 with no cost and no progress.

### Root Cause Chain
1. **Impoverished planning context.** The serve drive passes only `{id, title, priority, progress, maturation_status}` to the LLM planner. No `description`, `current_plan`, `iteration`, `max_iterations`, or history. The LLM cannot formulate a concrete plan from a bare title.
2. **Easy skip escape hatch.** The prompt says "If nothing meaningful can be done, say 'skip'" — combined with zero context, the LLM always takes this exit.
3. **No `last_checked_at` update on skip.** `_execute_serve()` updates `last_checked_at` on dispatch, but skips bypass `_execute_serve` entirely. The goal remains permanently stale, triggering the serve drive every cycle.
4. **Skips treated as activity.** `action_taken = "serve"` on skip drops the adaptive timeout to 30 seconds. Cortex burns ~120 LLM planning calls/hour producing nothing.
5. **No skip counter or escalation.** No mechanism to break the loop after N consecutive skips.

### Additional Gaps
- `max_iterations` is never enforced — goals can exceed their limit indefinitely
- `max_cost_usd` is never checked — budget enforcement is dead code
- Only `stale_goals[0]` is worked on — no round-robin across multiple stale goals
- Task polling blocks the entire thinking loop for up to 5 minutes
- Reflect drive is permanently suppressed (urgency capped at 0.5, serve always wins)

### Proposed Fixes
- Enrich serve.py query to include `description`, `current_plan`, `iteration`, `max_iterations`
- Restructure planning prompt to require a plan (not optional skip)
- Update `last_checked_at` on skip to prevent tight loop
- Treat skips as idle (long timeout, not 30s)
- Add skip counter — force action or escalate after 3 consecutive skips
- Enforce max_iterations and max_cost_usd in the stale goals query
- Decouple task polling from the cycle (fire-and-forget dispatch)

---

## 2. Intel Recommendation Pipeline

### Problem
14 active feeds produce 711 items/week but 0 recommendations. The "Suggested Goals" tab is permanently empty.

### Root Cause
**The grading/recommendation creation step is completely unimplemented.** No code anywhere in the codebase inserts into `intel_recommendations`. The schema exists, the API CRUD endpoints exist (GET, PATCH, DELETE), the dashboard UI exists, the stimulus constants exist — but the actual grading logic and the POST creation endpoint were never built.

### What IS Working
- Feed polling: 14 feeds, 5 fetcher types (RSS, Reddit, GitHub trending/releases, page change)
- Content ingestion: items are deduped by content_hash, stored in `intel_content_items`
- Engram ingestion: new items are pushed to Redis engram queue for memory decomposition
- Dashboard: full recommendation card UI with approve/defer/dismiss workflows
- Approve flow: approval correctly creates a linked goal with `[Intel]` prefix

### What IS NOT Working
- `POST /api/v1/intel/recommendations` does not exist (405 Method Not Allowed)
- `RECOMMENDATION_CREATED` stimulus is defined but never emitted
- `intel:new_items` Redis queue (db6) has no consumer — accumulates indefinitely
- System goals ("Daily Intelligence Sweep", etc.) have no intel-specific tools to read/write intel data

### Proposed Implementation
Option A (recommended): Add intel-specific MCP tools (`query_intel_content`, `create_recommendation`, `search_engrams_for_topic`, `get_dismissed_hashes`) so Cortex can grade content via the existing system goals.

Option B: Background batch worker in orchestrator with periodic grading cron job.

Also needed:
- POST endpoint for creating recommendations
- Consumer for the `intel:new_items` dead letter queue (or remove the push)
- Content archival job for items >30 days old

---

## 3. Sources Naming/UX Confusion

### Problem
Two fundamentally different concepts are both called "Sources" in the dashboard.

### Concept Map

| | Knowledge Sources | Engram Sources |
|---|---|---|
| **What** | Crawl target configs | Provenance records |
| **Where** | Orchestrator DB, `knowledge_sources` | Memory-service DB, `sources` |
| **Dashboard** | `/sources` sidebar link | `/engrams` > Sources tab |
| **API** | `/api/v1/knowledge/sources` | `/api/v1/engrams/sources` |
| **Analogy** | RSS feed subscription | Citation/footnote |
| **Direction** | Input — "what to learn from" | Output — "where this came from" |

### Data Flow
Knowledge Source config → knowledge-worker crawl → Redis engram queue → memory-service ingestion → Engram Source provenance record → Engrams

### Gaps
- No cross-database FK — `engrams.source_id` stores knowledge_sources UUID but can't be joined in memory-service
- Deleting a knowledge source leaves orphaned engrams/provenance with dangling UUIDs
- Trust scores are independent and unsynchronized between systems
- EngramExplorer Sources tab uses raw `fetch()` instead of `apiFetch()`, bypassing auth headers
- No navigation path from a knowledge source to its derived engrams, or vice versa

### Proposed Fix
Rename to eliminate ambiguity:
- Knowledge Sources → **"Knowledge Feeds"** or **"Watch List"**
- Engram Sources → **"Provenance"** or **"Origins"**
- Sidebar: "Sources" → "Knowledge"
- EngramExplorer tab: "Sources" → "Provenance"

Long-term: add provenance drill-down from knowledge source cards, formalize cross-service linking.

---

## 4. Chat Agent Self-Awareness

### Problem
Chat agent claims consolidation isn't working (it is), claims it can't "do things" (it has 30 tools), and lacks visibility into its own system state.

### Agent Has 30 Tools in 7 Groups

| Group | Tools | In Catalog API? |
|---|---|---|
| Code (5) | list_dir, read_file, write_file, run_shell, search_codebase | Yes |
| Git (4) | git_status, git_diff, git_log, git_commit | Yes |
| Platform (6) | list_agents, get_agent_info, create_agent, list_available_models, send_message_to_agent, create_task | Yes |
| Web (2) | web_search, web_fetch | Yes |
| Diagnosis (5) | diagnose_task, check_service_health, get_recent_errors, get_stage_output, get_task_timeline | NO |
| Introspect (4) | get_platform_config, list_knowledge_sources, list_mcp_servers, get_user_profile | NO |
| Memory (4) | what_do_i_know, search_memory, recall_topic, read_source | NO |

### Why the Agent Makes False Claims

1. **No consolidation visibility tool.** Memory-service has `GET /consolidation-log` and `POST /consolidate` but no tool wraps them. The agent literally cannot verify consolidation status.
2. **Self-knowledge only describes 5 tools** (the 5 diagnosis tools). The other 25 are in the tool list but never described in the narrative.
3. **Self-knowledge is hardcoded and stale.** Missing voice-service, chat-bridge, Redis, Postgres. No auto-update mechanism.
4. **Tool catalog API missing 13 tools.** Diagnosis, Introspect, and Memory groups are available to agents internally but not exposed in `/api/v1/tools`.
5. **No "verify my assumptions" pattern.** The system prompt doesn't teach the agent to check before asserting.

### Proposed Fixes
- Add `get_consolidation_status` tool (wraps `/consolidation-log`)
- Add `get_memory_stats` tool (wraps `/stats`)
- Add `trigger_consolidation` tool (wraps `/consolidate`)
- Expand self-knowledge "What I Can Do" section to describe all tool groups
- Add all tool groups to `/api/v1/tools` catalog
- Add metacognition guidance: "verify before asserting" pattern

---

## Tests Written

4 new test files covering these gaps:

| File | Tests | Pass | XFail | Notes |
|---|---|---|---|---|
| `test_cortex_goals.py` | 6 | 5 | 0 | 1 fails until service rebuild (cost field) |
| `test_model_discovery.py` | 8 | 8 | 0 | Validates vLLM availability fix |
| `test_consolidation.py` | 6 | 6 | 0 | Verifies consolidation is actually running |
| `test_agent_capabilities.py` | 8 | 5 | 2 | XFails document known gaps |

XFail tests that document known gaps:
- `test_recommendation_create_endpoint_exists` — POST endpoint missing
- `test_tool_catalog_includes_diagnosis_and_memory` — 13 tools not in catalog

---

## Bug Fixes Applied (This Session)

| Fix | Files Changed |
|---|---|
| Friction UI debug gate | `dashboard/src/pages/Overview.tsx` |
| vLLM discovery `available: false` | `llm-gateway/app/discovery.py` |
| Goal cost tracking (3-gap pipeline) | `orchestrator/app/pipeline/executor.py`, `orchestrator/app/pipeline_router.py`, `cortex/app/task_tracker.py`, `cortex/app/cycle.py` |
