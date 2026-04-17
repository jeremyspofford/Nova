# Nova Phase 0 Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a versioned, nine-axis audit of Nova plus a nova-suite feature inventory, synthesized into one prioritized backlog at `docs/audits/2026-04-16-phase0/BACKLOG.md`.

**Architecture:** Nine Opus subagents run in parallel, each owning one review axis. Each writes one markdown report to `docs/audits/2026-04-16-phase0/<axis>.md`. The main session then synthesizes a backlog from all nine reports.

**Tech Stack:** Claude Agent subagents (general-purpose type, Opus model), markdown output, git.

**Spec reference:** `docs/superpowers/specs/2026-04-16-nova-phase0-audit-design.md`

---

## A note on task shape

This plan is orchestration, not code. Traditional TDD ("write the failing test") does not apply — there is nothing to execute against. Each task is a bounded action: create a file, dispatch an agent, verify an output, commit. Quality gates are "report exists and contains findings that match the template," not "tests pass."

---

## Prerequisite artifacts

Before any task executes, verify the spec and gitignore entry are already committed:

- [ ] **Step 0.1: Verify prerequisite commit landed**

Run: `git log --oneline -3`
Expected: The most recent commit is `docs: Phase 0 audit design spec` (`b5410f5` or equivalent), and `.gitignore` contains `docs/audits/*/security.md`.

If not, stop and surface to the user — the brainstorming phase has not completed cleanly.

---

## Task 1: Create the audit folder and README

**Files:**
- Create: `docs/audits/2026-04-16-phase0/README.md`

- [ ] **Step 1.1: Create the audit directory**

Run: `mkdir -p docs/audits/2026-04-16-phase0`

- [ ] **Step 1.2: Write the README**

Create `docs/audits/2026-04-16-phase0/README.md`:

```markdown
# Nova Phase 0 Audit — 2026-04-16

Nine-axis audit of Nova (`arialabs/nova`) and a feature inventory of the prior iteration (`~/workspace/nova-suite/`). Drives Phase 1 daily-driver push planning.

## Files

| File | Axis | Status |
|---|---|---|
| `security.md` | Security & secrets | **Gitignored — local only** |
| `privacy.md` | Privacy & data custody | Public |
| `reliability.md` | Reliability & data integrity | Public |
| `agent-quality.md` | Agent behavior, tools, memory | Public |
| `feature-completeness.md` | Per-feature shipped vs. half-wired | Public |
| `ui-ux.md` | Dashboard, accessibility, mobile | Public |
| `performance.md` | Memory, CPU, queries, bundle | Public |
| `infra-ops.md` | Compose, startup, health, logs | Public |
| `nova-suite-inventory.md` | Port-or-skip per nova-suite feature | Public |
| `BACKLOG.md` | Prioritized synthesis | Public |

## Design spec

`docs/superpowers/specs/2026-04-16-nova-phase0-audit-design.md`

## How to read the backlog

Default sort: Severity (P0 first) → Daily-Driver Impact (H first) → Effort (S first). Top rows are the "obviously do these first" items.

Severity is measured against a neutral "daily driver" user. Daily-Driver Impact captures how much the finding blocks *this* user (Jeremy) specifically. The two can diverge: e.g., a P0 bug in voice is L impact for a user who doesn't use voice.
```

- [ ] **Step 1.3: Verify file contents**

Run: `ls docs/audits/2026-04-16-phase0/`
Expected: `README.md` present.

- [ ] **Step 1.4: Stage but do not commit yet**

Run: `git add docs/audits/2026-04-16-phase0/README.md`

The README commits together with the finished reports in Task 6.

---

## Task 2: Dispatch nine review agents in parallel

**Files:**
- Created by agents: `docs/audits/2026-04-16-phase0/{security,privacy,reliability,agent-quality,feature-completeness,ui-ux,performance,infra-ops,nova-suite-inventory}.md`

Each prompt below is a complete, self-contained brief. The dispatcher (main session or subagent-driven executor) sends all nine in parallel in a single message (9 Agent tool calls in one response).

**Agent configuration for all nine:**
- `subagent_type`: `general-purpose`
- `model`: `opus`
- `run_in_background`: `false` (foreground parallel so all return before Task 3 begins)

**Shared context block** (prepend to every agent's prompt):

```
You are a specialist reviewer producing one report in a nine-axis audit of Nova.

Nova is a self-directed autonomous AI platform running as a 12-service Docker Compose stack at `/home/jeremy/workspace/arialabs/nova`. Architecture is documented in that repo's `CLAUDE.md` — read it first. The stack is currently running; you can query live services if useful, but your primary mode is code review.

The full audit design is at `docs/superpowers/specs/2026-04-16-nova-phase0-audit-design.md`. Read it before starting — it defines the report template, severity scale (P0–P3), effort scale (S/M/L), and your place in the larger audit.

**Severity vs. Impact — a worked example to anchor the distinction:**
- A finding can be P0 (severe issue, e.g., unencrypted credential storage) while having Daily-Driver Impact L (the user doesn't use that feature). Note severity by the defect, not by the audience.
- A finding can be P2 (minor) while having Daily-Driver Impact H (hits the user every single session, e.g., "chat input loses focus after send").
- Use P0–P3 for the *defect*, leave Daily-Driver Impact for the synthesis pass to assign.

**Your deliverable:** one markdown file at the exact path given below, following the report template in the design spec exactly.

**What not to do:**
- Do not fix anything. This is an observation phase.
- Do not write code changes. Recommendations only.
- Do not speculate about things you haven't verified. Evidence must be concrete file paths and line numbers.
- Do not pad with generic best-practice sections. Every finding must be grounded in what you actually saw.

**When in doubt on scope,** err toward fewer, higher-quality findings. A report with 8 crisp P0–P2 findings beats a report with 40 blurry ones.

End your returned message with a ≤150-word summary of the top 3 findings. The full report lives in the file.
```

### Agent 1: Security & secrets

Target path: `docs/audits/2026-04-16-phase0/security.md` (gitignored)

Axis-specific scope to append to the shared context:

```
**Your axis:** Security & secrets.

**Scope:**
- Admin secret and API key handling (how they're stored, rotated, transmitted)
- `REQUIRE_AUTH` and the auth flow (or lack thereof) for dashboard, chat-api, WebSocket endpoints
- API key authentication (`Authorization: Bearer sk-nova-*` and `X-API-Key` paths)
- Command injection, path traversal, SSRF surfaces — especially in tools (`orchestrator/app/tools/`), MCP dispatch, crawlers (`knowledge-worker/`), and any shell-out code
- Prompt injection surfaces exposed to the agent (untrusted text reaching tool parameters, untrusted tool output becoming agent context)
- Container privilege (root user, docker socket mounts, privileged: true anywhere)
- Redis/Postgres exposure — are listeners bound correctly? Are credentials hardcoded in compose?
- CORS, CSRF, WebSocket origin validation
- Secrets leakage in logs (LOG_LEVEL=DEBUG paths, error messages)
- Dashboard-side: `localStorage` of admin secret — is it XSS-safe?
- Credential storage in knowledge-worker (encrypted credential storage per CLAUDE.md — verify the encryption is real)

**Out of scope:**
- Dependency CVEs (handled by agent-fleet cron)
- Transport security above localhost (user runs locally; TLS is downstream for deployment)

**Write your report to:** `docs/audits/2026-04-16-phase0/security.md`

This file is gitignored and will not be committed. You may include specific PoC-grade detail on findings.
```

### Agent 2: Privacy & data custody

Target path: `docs/audits/2026-04-16-phase0/privacy.md`

```
**Your axis:** Privacy & data custody.

**Scope:**
- What data leaves the user's machine: LLM provider calls (which providers get what data), telemetry, error reporting, analytics
- What data is persisted locally and where: Postgres tables, Redis keys, filesystem paths (`data/postgres`, `data/redis`, `data/sources/`, backups)
- Data retention defaults — does anything grow unbounded (conversations, engrams, sources, intel items, logs)?
- User/workspace isolation: even pre-multi-user, are there assumptions that break under multi-user later? (Memory segregation, API key scoping, source ownership.)
- Deletion/export paths: can a user actually delete their data? Export it? Is "delete" soft-delete, hard-delete, or ignore?
- Third-party surfaces the user may not realize data reaches: GitHub API, RSS feeds, Telegram, Slack, Cloudflare Tunnel if configured
- Admin-secret visibility: who can see conversations/memory? Is there a privileged tier vs. user tier?
- Prompt content logging — are user prompts written to logs at any level?

**Out of scope:**
- GDPR compliance boilerplate (the user is the operator)
- Legal framework discussion

**Write your report to:** `docs/audits/2026-04-16-phase0/privacy.md`
```

### Agent 3: Reliability & data integrity

Target path: `docs/audits/2026-04-16-phase0/reliability.md`

```
**Your axis:** Reliability & data integrity.

**Prior art to read first:**
- `docs/superpowers/specs/2026-03-31-crash-recovery-context-design.md`
- `docs/superpowers/specs/2026-03-28-platform-health-analysis.md`

**Scope:**
- Engram/source corruption surfaces: ingestion race conditions, partial writes, foreign-key orphan potential
- DB migration safety: are `orchestrator/app/migrations/*.sql` genuinely idempotent? What breaks if one half-applies?
- Stale Redis state issues: we just hit one (stale `task_running` entries surviving restart, orphan Redis config like `inference.backend`). How pervasive is this class?
- Backup/restore correctness: does `make backup` actually produce a file that `make restore` can restore? Any silent exclusions?
- Heartbeat / stale-reaper logic: 30s heartbeat, 150s timeout — are edge cases (clock skew, long LLM calls) handled?
- Ingestion idempotency: the engram ingestion queue — is it safe to replay? What happens on worker crash mid-item?
- Consolidation cycle mutex — can it deadlock or get stuck? What happens if it crashes mid-phase?
- Partial startup failure handling: what state is left behind when `make dev` aborts mid-way? (We saw this today.)
- Redis connection leakage (CLAUDE.md calls this out — verify `close_redis()` is actually called in every lifespan)

**Out of scope:**
- Distributed deployment reliability (separate spec exists, not yet implemented)
- Multi-node consensus (single-host for now)

**Write your report to:** `docs/audits/2026-04-16-phase0/reliability.md`
```

### Agent 4: Agent quality

Target path: `docs/audits/2026-04-16-phase0/agent-quality.md`

```
**Your axis:** Agent quality — pipeline correctness, tool-calling, memory, prompts.

**Prior art to read first:**
- `docs/superpowers/specs/2026-04-03-ai-quality-measurement-design.md`
- `docs/feature-audit-2026-03-25.md` (prior feature audit)
- `orchestrator/app/pipeline/` (full directory — the quartet pipeline)
- `memory-service/app/engram/` (the retrieval/ingestion code paths)

**Scope:**
- Quartet pipeline correctness: Context → Task → Guardrail → Code Review → Decision. Are the state transitions well-defined? What happens on stage-failure? Are guardrail findings actually actionable downstream?
- Tool-calling reliability: MCP dispatch, built-in tools, memory tools (`what_do_i_know`, `search_memory`, `recall_topic`, `read_source`). Do tool schemas match actual behavior? Error-surface quality.
- Memory retrieval quality: spreading activation parameters (decay, seed count, hop limit), working memory slot logic, source trust scoring. Any obvious quality failure modes?
- Hallucination surfaces: where can the agent generate plausible-but-wrong tool calls or answers? Any protection against tool-result injection back into context?
- Prompt durability: are system prompts hardcoded or configurable? Do they work across Opus/Sonnet/Haiku and cross-provider swaps (OpenAI, Groq, Ollama)?
- Model-routing correctness: `llm.routing_strategy` edge cases. Does local-first degrade gracefully to cloud when Ollama is down? (We just saw "unreachable" cascading.)
- Outcome feedback loop: does `outcome_feedback.py` actually close the loop — do bad outcomes reduce future retrievals of bad engrams?
- Consolidation quality: are the six phases (replay, pattern extraction, Hebbian, contradiction, pruning, self-model) doing what they claim, or are some stubs?
- Cortex autonomy: the "thinking loop" — how often does it run, what does it produce, is the output actually useful or mostly noise?
- Skills/rules framework: is it plumbed end-to-end or UI-only?

**Out of scope:**
- Deep prompt-engineering-as-taste review (bikeshed territory)
- Model-family feature parity (handled at router layer)

**Write your report to:** `docs/audits/2026-04-16-phase0/agent-quality.md`
```

### Agent 5: Feature completeness

Target path: `docs/audits/2026-04-16-phase0/feature-completeness.md`

```
**Your axis:** Feature completeness — for each major feature, classify as Shipped / Partial / UI-only / Stub / Broken.

**Prior art to read first:**
- `docs/feature-audit-2026-03-25.md` — a prior feature audit. Your report should delta from this, not duplicate it.
- `docs/roadmap.md` — current roadmap.
- `CLAUDE.md` — the canonical architecture summary.

**Scope — classify each of the following features:**
- Chat (chat-api, dashboard chat pages, streaming, PWA)
- Engram memory system (ingestion, retrieval, working memory, consolidation, neural router, outcome feedback)
- Memory tools for agents
- Source provenance and re-decomposition
- Intel worker (feeds, page change detection, trending)
- Knowledge worker (crawling, credential storage)
- Voice service (STT/TTS, dashboard settings)
- Cortex (thinking loop, goals, drives, budget tracking)
- Dashboard (each page: Chat, Memory/Brain, Knowledge, Intel, Cortex, Settings, Recovery, Benchmarks, AI Quality, Skills/Rules)
- Recovery (backup, restore, factory reset, service management)
- Chat bridges (Telegram, Slack)
- Triggers / scheduler (Jeremy called this out specifically — does Nova have it in any form?)
- Auth (REQUIRE_AUTH, API keys, admin secret)
- MCP tool catalog
- Distributed deployment (design exists; implementation?)

**Per-feature report entry:**
- Status: Shipped / Partial / UI-only / Stub / Broken / Missing
- Evidence: specific files that show current state
- Daily-driver gap: what's missing for this to be trustworthy daily?
- Effort to close the gap: S/M/L

**Out of scope:**
- Individual bug-level detail (other agents handle that)
- Nova-suite features (axis 9 handles)

**Write your report to:** `docs/audits/2026-04-16-phase0/feature-completeness.md`
```

### Agent 6: UI/UX

Target path: `docs/audits/2026-04-16-phase0/ui-ux.md`

```
**Your axis:** UI/UX — dashboard quality, accessibility, mobile readiness.

**Prior art to read first:**
- `DESIGN.md` (at repo root) — the design system reference. All visual/UX decisions trace here.
- `docs/superpowers/specs/2026-03-16-dashboard-redesign-design.md`, `2026-03-28-dashboard-nav-restructure-design.md`, `2026-04-01-mobile-chat-ux-design.md`, `2026-04-02-chat-only-pwa-design.md` — prior dashboard/UX specs.

**Scope:**
- DESIGN.md conformance: which pages follow the design system, which drift? Specific violations with file:line evidence.
- Empty, loading, and error states: every data-fetching page — does each of the three states exist and look reasonable?
- Tab persistence: Jeremy has explicitly flagged this before (memory recall). Pages with tabs — do tabs survive refresh?
- Keyboard affordances: is anything keyboard-only-impossible? Submit-with-Enter vs. newline, shortcut consistency.
- Accessibility: alt text, ARIA, semantic HTML, color contrast (spot-check, not full WCAG audit).
- Mobile/PWA readiness: the chat-only-pwa spec exists — is it shipped? Does the dashboard work on phone-sized viewports? (You can't test this in-session, but you can grep for viewport/responsive CSS.)
- Error recovery UX: when a service is down, does the UI show a useful message or white-screen?
- First-run / onboarding: fresh install experience — what does the user see on first open?
- Unified chat PWA: there's a spec — is it shipped?
- Skills/Rules UI: spec exists — is it shipped?

**Out of scope:**
- Full WCAG 2.1 audit (spot-check only)
- Visual design critique beyond DESIGN.md conformance (you are not the taste agent)

**Write your report to:** `docs/audits/2026-04-16-phase0/ui-ux.md`
```

### Agent 7: Performance

Target path: `docs/audits/2026-04-16-phase0/performance.md`

```
**Your axis:** Performance.

**Prior art to read first:**
- `docs/superpowers/specs/2026-03-17-performance-optimization-design.md`
- `docs/superpowers/specs/2026-03-28-brain-instanced-rendering-design.md`

**Scope:**
- Container memory/CPU footprint: eyeball each service for obvious waste (duplicate models loaded in-process, Python interpreter count, idle memory)
- DB query shape: scan `orchestrator/app/`, `memory-service/app/`, `cortex/`, `knowledge-worker/` for N+1s, unbounded queries, missing indexes
- Engram spreading-activation cost: the recursive CTE is a hot path — any obvious scaling issues?
- Cold-start time: how long from `docker compose up` to "everything ready"? Which services dominate? (Infer from log timestamps or startup code.)
- Frontend bundle: `dashboard/dist/` or build output — size per route, obvious large deps.
- Streaming latency: SSE paths — anything buffering that shouldn't be?
- Consolidation cycle cost: how long does a consolidation take? Does it block anything?
- Neural router training: 200+ observations gate — does training actually terminate or drift?
- Brain visualization (3D graph): memory for large graphs, rendering cost. (Prior spec exists.)

**Out of scope:**
- Micro-optimization of hot loops (YAGNI at this stage)
- Distributed scaling (single-host)

**Write your report to:** `docs/audits/2026-04-16-phase0/performance.md`
```

### Agent 8: Infra & ops

Target path: `docs/audits/2026-04-16-phase0/infra-ops.md`

```
**Your axis:** Infra & ops.

**Prior art to read first:**
- `docs/superpowers/specs/2026-03-28-platform-health-analysis.md`
- `docker-compose.yml`, `docker-compose.gpu.yml`, `docker-compose.rocm.yml`, `Makefile`, `scripts/setup.sh`

**Scope:**
- Compose topology: service dependencies, healthcheck correctness, startup order, profile hygiene
- Startup resilience: what happens on partial failure? (We just saw the failure mode where postgres didn't attach to the network.) Pre-flight checks that could have caught it?
- Health-rollup semantics: orchestrator → llm-gateway → chat-api cascading "degraded" because of a 3-second timeout exactly matching inner probe latency (we just saw this). Is this a pattern — where else does it bite?
- Log levels: CLAUDE.md explicitly warns against critical failures at DEBUG level. Spot-check if this discipline holds.
- Log format: is it structured JSON everywhere, or mixed? Greppable by service and level?
- Observability gaps: no metrics endpoint? No tracing? What's missing for "why is this slow" to be answerable?
- Redis cleanup: CLAUDE.md calls out the `get_redis` / `close_redis` pattern — verify every service honors it in lifespan.
- Env var hygiene: `.env.example` completeness, defaults sanity, runtime-config overrides (Redis-backed settings) behavior when stale
- Volume/bind-mount correctness: `data/postgres`, `data/redis` survive prune. Are there implicit Docker volumes elsewhere that wouldn't survive?
- Ollama detection: `OLLAMA_BASE_URL=auto` probe logic — does it handle host/WSL/Mac correctly?
- `make` target correctness: `make backup` / `make restore` / `make prune` — do they do what they claim?

**Out of scope:**
- Kubernetes / production deployment (distributed-deployment spec handles future work)
- CI/CD (separate concern)

**Write your report to:** `docs/audits/2026-04-16-phase0/infra-ops.md`
```

### Agent 9: Nova-suite inventory

Target path: `docs/audits/2026-04-16-phase0/nova-suite-inventory.md`

```
**Your axis:** Nova-suite feature inventory (separate codebase).

**Target codebase:** `/home/jeremy/workspace/nova-suite/` — Jeremy's prior Nova iteration. Separate repo. You are NOT auditing this for defects; you are extracting which features are worth porting to the new Nova at `/home/jeremy/workspace/arialabs/nova/`.

**Order of reading (this matters):**
1. `/home/jeremy/workspace/nova-suite/CLAUDE.md`
2. `/home/jeremy/workspace/nova-suite/docs/architecture/` — all files, spec-first
3. `/home/jeremy/workspace/nova-suite/services/{api,board,nova-lite}/` — the actual code
4. `/home/jeremy/workspace/nova-suite/infra/docker-compose.yml`
5. Screenshots at repo root (`chat-list-triggers-success.png`, `settings-triggers-panel.png`, `final-settings.png`) for context on what the UI looked like

**Per-feature output** — for each discoverable feature in nova-suite:

| Field | Content |
|---|---|
| Feature | Name |
| Spec quality | Is the design worth inheriting even if the code isn't? (High / Medium / Low) |
| Implementation state | Complete / Partial / Stub / Missing |
| Parity with current Nova | Does current Nova have an equivalent? Is it Better / Same / Worse / Missing-in-Nova? |
| Recommendation | Port code / Port spec only / Rebuild fresh in Nova / Skip |
| Rationale | One paragraph — why |

**Jeremy-specific call-out:** Triggers / scheduler. He explicitly asked whether nova-suite's implementation could be pulled over ("create a task that runs at 9am every day"). Assess this feature in particular depth: how it's implemented, what the data model looks like, how the agent actually fires the trigger.

**Out of scope:**
- Defect-hunting in nova-suite code
- Porting recommendations for features current Nova clearly does better

**Write your report to:** `/home/jeremy/workspace/arialabs/nova/docs/audits/2026-04-16-phase0/nova-suite-inventory.md`
```

### Execution steps for Task 2

- [ ] **Step 2.1: Dispatch all nine agents in parallel in a single message**

Use one response containing 9 Agent tool calls. All calls use `subagent_type: general-purpose` and `model: opus`. Each prompt is the shared context block concatenated with that axis's specific brief. The `description` field is short and axis-specific (e.g., "Security & secrets audit").

- [ ] **Step 2.2: Wait for all nine to return**

All are foreground; the session blocks until the final one returns. Expected duration: 10–25 minutes total (parallel). Agents return short summaries; full reports are on disk.

- [ ] **Step 2.3: Record agent return summaries**

Capture each agent's ≤150-word summary for quick reference. Do not re-read full reports into context yet — they'll be read during synthesis (Task 4).

---

## Task 3: Verify all nine reports exist and are non-empty

**Files:**
- Check: `docs/audits/2026-04-16-phase0/*.md`

- [ ] **Step 3.1: Confirm all nine files exist**

Run:
```bash
for f in security privacy reliability agent-quality feature-completeness ui-ux performance infra-ops nova-suite-inventory; do
  path="docs/audits/2026-04-16-phase0/${f}.md"
  if [ -s "$path" ]; then
    echo "OK: $path ($(wc -l < "$path") lines)"
  else
    echo "MISSING OR EMPTY: $path"
  fi
done
```

Expected: 9 "OK" lines. If any shows "MISSING OR EMPTY", re-dispatch that specific agent with the same prompt.

- [ ] **Step 3.2: Spot-check each report has findings**

Run: `grep -c "^### \[P" docs/audits/2026-04-16-phase0/*.md`

Expected: each file returns ≥ 1. If any returns 0, the agent likely did not follow the template — re-dispatch with a stricter instruction.

- [ ] **Step 3.3: Confirm security.md is gitignored**

Run: `git check-ignore docs/audits/2026-04-16-phase0/security.md`

Expected: the file path is printed (meaning: matched by gitignore). If nothing prints, the gitignore entry is not working — stop and fix before continuing.

---

## Task 4: Synthesize BACKLOG.md

**Files:**
- Create: `docs/audits/2026-04-16-phase0/BACKLOG.md`

This task is performed inline by the main session (no subagent needed). The session reads all nine reports from disk, assigns Daily-Driver Impact to each finding, and writes the synthesized backlog.

- [ ] **Step 4.1: Read all nine reports from disk**

Read each file in `docs/audits/2026-04-16-phase0/*.md` (excluding README.md).

- [ ] **Step 4.2: Assign stable IDs**

Per axis, generate IDs in order of appearance:
- Security → `SEC-001`, `SEC-002`, ...
- Privacy → `PRIV-001`, ...
- Reliability → `REL-001`, ...
- Agent-quality → `AQ-001`, ...
- Feature-completeness → `FC-001`, ...
- UI-UX → `UX-001`, ...
- Performance → `PERF-001`, ...
- Infra-ops → `OPS-001`, ...
- Nova-suite inventory → `NSI-001`, ...

- [ ] **Step 4.3: Assign Daily-Driver Impact**

For each finding, assign H / M / L based on:
- **H** — Affects every session or a core workflow Jeremy uses daily (chat, memory, tool use, scheduling, voice).
- **M** — Affects a feature Jeremy uses sometimes, or a silent risk that accumulates over time.
- **L** — Feature Jeremy has flagged as not-his-use-case, or far-future concern.

If uncertain, default to M.

- [ ] **Step 4.4: Write BACKLOG.md**

Template:

```markdown
# Phase 0 Audit Backlog — 2026-04-16

Synthesized from the nine axis reports in this folder. Default sort: Severity (P0 first) → Daily-Driver Impact (H first) → Effort (S first).

## How to use this

Drive Phase 1 planning from this table. Rows at the top are the obvious "do these first" items (P0, high-impact, small-effort). Rows at the bottom are P3 nice-to-haves.

**Security findings reference** `security.md`, which is local-only. Security titles here are non-actionable (no exploit detail) — see the report for specifics.

## Backlog

| # | Axis | Finding | Sev | Impact | Effort | Report | Status |
|---|---|---|---|---|---|---|---|
| SEC-001 | security | <title> | P0 | H | S | `security.md` | Open |
| ... | | | | | | | |

All rows default to `Open` during Phase 0 synthesis. Phase 1 execution updates them to `In Progress`, `Done`, or `Killed`.

## Totals

- Total findings: N
- By severity: P0=n, P1=n, P2=n, P3=n
- By effort: S=n, M=n, L=n
- High-impact: n items

## Top 10 (drives Phase 1)

1. **SEC-001** — <title>
2. ...

## Killed / explicitly-skipped

Findings raised during the audit but intentionally deferred or rejected. Record here with reason so they don't surface again next audit.
```

- [ ] **Step 4.5: Verify the backlog**

Run: `wc -l docs/audits/2026-04-16-phase0/BACKLOG.md`
Expected: Plausible row count (dozens to low hundreds). If it's empty or has 3 rows, synthesis went wrong — re-read inputs.

---

## Task 5: Commit public artifacts

**Files:**
- Stage: `docs/audits/2026-04-16-phase0/README.md`
- Stage: `docs/audits/2026-04-16-phase0/privacy.md`, `reliability.md`, `agent-quality.md`, `feature-completeness.md`, `ui-ux.md`, `performance.md`, `infra-ops.md`, `nova-suite-inventory.md`
- Stage: `docs/audits/2026-04-16-phase0/BACKLOG.md`
- Do **NOT** stage: `docs/audits/2026-04-16-phase0/security.md` (gitignored anyway, but double-check)

- [ ] **Step 5.1: Verify gitignore is still working**

Run: `git status docs/audits/2026-04-16-phase0/`

Expected: all files listed *except* `security.md`.

If `security.md` appears in the git status, stop — the gitignore is not effective and committing would leak security findings on a public repo.

- [ ] **Step 5.2: Stage public artifacts only**

Run:
```bash
git add docs/audits/2026-04-16-phase0/README.md \
        docs/audits/2026-04-16-phase0/privacy.md \
        docs/audits/2026-04-16-phase0/reliability.md \
        docs/audits/2026-04-16-phase0/agent-quality.md \
        docs/audits/2026-04-16-phase0/feature-completeness.md \
        docs/audits/2026-04-16-phase0/ui-ux.md \
        docs/audits/2026-04-16-phase0/performance.md \
        docs/audits/2026-04-16-phase0/infra-ops.md \
        docs/audits/2026-04-16-phase0/nova-suite-inventory.md \
        docs/audits/2026-04-16-phase0/BACKLOG.md
```

- [ ] **Step 5.3: Verify staging excludes security.md**

Run: `git diff --cached --stat`

Expected: 10 files staged. `security.md` is NOT in the list.

- [ ] **Step 5.4: Commit**

Run:
```bash
git commit -m "$(cat <<'EOF'
docs: Phase 0 audit reports and backlog

Eight axis reports (privacy, reliability, agent-quality,
feature-completeness, ui-ux, performance, infra-ops,
nova-suite-inventory) plus the synthesized BACKLOG.md driving
Phase 1 planning. Security report is local-only (gitignored).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5.5: Verify commit landed and working tree matches expectation**

Run: `git status` and `git log --oneline -3`

Expected: clean working tree for audit folder (only `security.md` remaining as untracked-and-ignored). The newest commit is the audit commit.

---

## Task 6: Hand off to user

- [ ] **Step 6.1: Report completion to user**

Message to user:
- Path to `BACKLOG.md`
- Totals by severity / impact / effort
- Top 3 from the "Top 10" section
- Note that `security.md` exists locally and should be reviewed separately (not shareable as committed history)
- Next step: user reads the backlog, we jointly decide which rows drive Phase 1

Do **not** start any Phase 1 implementation work in this session. This plan ends at handoff. Phase 1 planning begins from a fresh brainstorming pass once the user has reviewed the backlog.

---

## Failure recovery

If any agent returns with an empty report, wrong template, or crashes:

1. Re-dispatch only that agent (single tool call). Reuse the exact same prompt from Task 2.
2. If re-dispatch fails twice: surface to the user. Do not fabricate content to fill the gap — an empty report is better than a hallucinated one.

If the synthesis step produces a BACKLOG with fewer than ~20 findings total across nine axes covering 12 services, assume the reports under-delivered. Sample-read 2–3 reports and re-dispatch the thin ones with a note that the first pass produced too few findings.

---

## Definition of done

- [ ] All nine reports exist at `docs/audits/2026-04-16-phase0/<axis>.md`
- [ ] `security.md` is gitignored (`git check-ignore` confirms)
- [ ] `BACKLOG.md` exists with every finding from every report, sorted correctly, with stable IDs
- [ ] A single commit is landed on main containing the public reports + backlog + README
- [ ] User has been handed the backlog path and summary stats
