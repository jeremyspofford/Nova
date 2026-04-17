# Nova Phase 0 Audit & Inventory — Design Spec

> **Date:** 2026-04-16
> **Status:** Draft — awaiting user approval
> **Approach:** Nine parallel review agents produce per-axis reports; a synthesis pass produces a single prioritized backlog

---

## Problem

Nova has "many features, none feature complete" (Jeremy's framing). The intent is to promote this repo (`arialabs/nova`) to Jeremy's daily-driver AI assistant, replacing OpenClaw and every other harness. Before committing to a fix-it sequence, we don't have a map of what's actually broken, what's production-ready, and what's worth porting from the prior iteration at `~/workspace/nova-suite/`.

Without a map, any work on Nova is reactive — we'd fix whatever's visible this session and leave subtler problems (auth gaps, data-loss risks, agent-quality issues) untouched.

## Goals

1. Produce durable, versioned artifacts describing the current state of Nova across nine axes.
2. Produce a single prioritized backlog that drives Phase 1 planning.
3. Separately inventory `nova-suite` to inform a port-or-skip decision per feature.

## Non-Goals

- **Fixing anything in this phase.** This phase only observes and records.
- Dependency-health review — already handled by the existing agent-fleet cron.
- Code-quality-for-its-own-sake review — folded into reliability/agent-quality/infra axes where it matters; a freestanding pass generates churn without priority.
- Synthesizing a Phase 1 implementation plan. That comes after backlog review.

---

## The Nine Review Axes

Each axis becomes one dedicated review agent. Agents run in parallel. Each writes one markdown report to `docs/audits/2026-04-16-phase0/<axis>.md`.

| # | Axis | Scope |
|---|---|---|
| 1 | `security` | Auth model, admin secret handling, API key storage, credential leakage, injection surfaces, container privilege, Redis unauth exposure, CORS, CSRF, SSRF in tools |
| 2 | `privacy` | Data custody, what leaves the box (LLM providers, telemetry, logs), persistence locations, deletion/export paths, user isolation (even pre-multi-user) |
| 3 | `reliability` | Engram/source data integrity, migration safety, stale Redis state handling, backup/restore correctness, ingestion idempotency, heartbeat/reaper correctness |
| 4 | `agent-quality` | Quartet pipeline correctness, tool-calling reliability, memory retrieval quality, hallucination surfaces, prompt durability across model/provider swaps |
| 5 | `feature-completeness` | For each major feature (chat, memory, intel, knowledge, voice, cortex, skills/rules, triggers-if-exists): shipped vs. half-wired vs. UI-only |
| 6 | `ui-ux` | Dashboard vs. DESIGN.md conformance, accessibility, mobile/PWA readiness, error states, loading states, tab persistence, keyboard affordances |
| 7 | `performance` | Container memory/CPU footprint, DB query shape, engram activation cost, cold-start time, frontend bundle size, streaming latency |
| 8 | `infra-ops` | Compose topology, startup resilience (partial-failure recovery), health-rollup semantics, log-level correctness, observability gaps |
| 9 | `nova-suite-inventory` | Separate pass over `~/workspace/nova-suite/`: spec-first read, then code, then port-or-skip recommendation per feature |

### Why these axes, and not others

- **Agent quality (axis 4) is called out separately** because it's the single largest driver of daily-driver readiness for an AI assistant, and traditional code audits miss it entirely. A perfectly secure and reliable system that hallucinates half its tool calls is unusable.
- **Nova-suite inventory (axis 9) is its own agent** so the question "what does Nova need?" (axes 1–8) stays independent of "what's sitting next door that we already have?" (axis 9). Merging them biases the audit toward whatever nova-suite happened to solve.
- **Feature-completeness (axis 5)** exists as a discrete axis because "half-wired feature" is a category the other axes miss. A feature with a beautiful UI, no backend, and no tests reads as "fine" to a code-quality audit.

---

## Report Template

Every axis report follows this structure:

```markdown
# <Axis> Audit — 2026-04-16

## Scope
What was reviewed. What was deliberately out of scope.

## Findings

### [P0] Title of the finding
- **Evidence:** `path/to/file.py:123` + one-paragraph context
- **Impact:** who/what is affected; daily-driver implication
- **Recommendation:** specific remediation, not hand-waving
- **Effort:** S (≤1 day), M (2–5 days), L (>5 days or requires design)

(repeat per finding, grouped by severity P0 → P3)

## Summary
3–5 bullet key takeaways.
```

### Severity scale

| Level | Meaning |
|---|---|
| **P0** | Daily-driver blocker; security or data-loss risk; user trust damage |
| **P1** | Meaningful friction or hidden risk; blocks adoption of a dependent feature |
| **P2** | Cleanup or polish; affects quality but not function |
| **P3** | Nice-to-have |

### Effort scale

| Level | Meaning |
|---|---|
| **S** | ≤1 day of focused work |
| **M** | 2–5 days |
| **L** | >5 days or requires its own design spec first |

---

## Synthesis: `BACKLOG.md`

Once all 9 reports land, a synthesis pass produces `docs/audits/2026-04-16-phase0/BACKLOG.md`. One row per finding from all reports. Columns:

| Column | Content |
|---|---|
| # | Stable ID (e.g., `SEC-001`, `REL-004`) |
| Axis | security, privacy, reliability, … |
| Finding | Short title |
| Severity | P0–P3 |
| Effort | S/M/L |
| Daily-Driver Impact | H/M/L (separate from severity — a P0 that only affects a rarely-used feature is M or L impact) |
| Report Link | Relative path to the source report |
| Status | Open / In Progress / Done / Killed |

Default sort: Severity asc, then Daily-Driver Impact desc, then Effort asc. This pushes "P0 high-impact small-effort" to the top — the stuff that should obviously happen first.

Phase 1 planning is driven directly from this backlog.

---

## Security Report — Public Repo Handling

`arialabs/nova` is a public repo. The security report will contain specific findings about auth gaps, secret handling, and injection surfaces that must not leak publicly before remediation.

### Handling

1. `docs/audits/2026-04-16-phase0/security.md` is added to `.gitignore` before dispatch.
2. The gitignore entry is `docs/audits/*/security.md` — applies to all dated audit folders, current and future.
3. The `BACKLOG.md` synthesis is allowed to reference security findings at a non-actionable level (e.g., "SEC-003 — admin secret rotation missing, P0") but must not include exploit specifics, PoCs, or credential-exposure paths.
4. When a security finding is remediated, the fix is committed normally (the fix itself is public once shipped); the report file stays local-only until the user explicitly decides it's safe to publish.

### What gets committed in this phase

- The design spec (this file).
- The gitignore addition.
- After dispatch: 8 of the 9 reports (everything except `security.md`).
- The `BACKLOG.md`.

### What stays local-only

- `security.md`.

---

## Nova-Suite Inventory — Methodology

Axis 9's agent follows a different pattern than the others because the target is a separate codebase being evaluated for feature extraction, not defects.

**Order of reading:**
1. `~/workspace/nova-suite/docs/architecture/*.md` — design specs and intent
2. `~/workspace/nova-suite/services/{api,board,nova-lite}/` — actual implementation
3. `~/workspace/nova-suite/infra/docker-compose.yml` — deployment topology
4. Compare spec intent to implementation completeness

**Per-feature output:**

| Field | Content |
|---|---|
| Feature | Name |
| Spec quality | Is the design worth inheriting even if the code isn't? |
| Implementation state | Complete / Partial / Stub / Missing |
| Parity with current Nova | Does current Nova have an equivalent? Better or worse? |
| Recommendation | Port code / Port spec only / Rebuild fresh / Skip |
| Rationale | One paragraph |

**Triggers/scheduler is a called-out feature** — Jeremy specifically mentioned it ("create a task that runs at 9am every day"). The inventory agent must assess nova-suite's triggers implementation and recommend a path: port the code, port the design, or rebuild.

---

## Execution

- **9 agents dispatched in parallel.** Each runs with the Opus model — this is high-judgment review work where model quality matters more than throughput.
- **Agents write directly to disk.** Return messages back to the session are short summaries only, so the 9 reports don't overwhelm main context.
- **Synthesis pass** happens after all 9 agents return. Reads the reports from disk, produces `BACKLOG.md`.

### Prior art to reference

`docs/feature-audit-2026-03-25.md` — a prior feature audit from March. The `feature-completeness` agent must read it first and build on it (delta from then to now), not duplicate it.

---

## Success Criteria

Phase 0 is complete when:

1. All 9 reports exist at `docs/audits/2026-04-16-phase0/`.
2. `security.md` is gitignored and has not been committed.
3. `BACKLOG.md` exists, is sorted by severity × daily-driver-impact, and contains every finding from every report.
4. Jeremy has read the backlog and either approved it or requested adjustments.

At that point, we have a durable, versioned map of Nova's state and a single artifact to drive Phase 1 planning.

---

## Out-of-Scope Follow-ups (noted but not part of this spec)

- **Automated audit cadence.** A nightly or weekly re-run of the reliability/infra agents would catch regressions — design separately if the Phase 0 output proves valuable.
- **Continuous compliance.** Some of the security/privacy findings will likely warrant ongoing controls (secret scanning, dependency CVE gates). Those are Phase 1+ decisions.
- **Public-facing audit summary.** Once P0 security findings are remediated, publishing a public "security posture" doc is worth considering — out of scope here.
