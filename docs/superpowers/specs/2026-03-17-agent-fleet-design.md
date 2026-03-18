# Agent Fleet Design

**Date:** 2026-03-17
**Status:** Draft
**Repository:** jeremyspofford/nova

## Overview

An autonomous agent fleet — a set of AI agents that run via GitHub Actions on schedule, on push, and manually. Agents proactively analyze the Nova codebase and create GitHub issues with improvement suggestions. Seven agent categories cover security, performance, architecture, API quality, frontend quality, test coverage, and dependency health.

The system evolves through three phases: suggest-only (issues), draft PRs, and selective auto-merge — with manual promotion between phases controlled by a YAML config file.

## Agent Categories

Seven agents, ordered by priority:

| # | Agent | Slug | On Push | Weekly | Domain |
|---|-------|------|---------|--------|--------|
| 1 | Security | `security` | Yes (diff) | Yes (full) | CVEs in deps, secrets in code/config, injection vectors, auth bypasses, CORS/CSRF, Docker security, exposed ports |
| 2 | Performance | `performance` | Yes (diff) | Yes (full) | N+1 queries, missing indexes, unbounded loops, memory leaks, missing connection cleanup, Redis anti-patterns, blocking async |
| 3 | Architecture | `architecture` | No | Yes (full) | Circular deps, service boundary violations, contract drift, misplaced logic, God files, coupling |
| 4 | API Quality | `api-quality` | Yes (diff) | Yes (full) | Inconsistent response shapes, missing error codes, undocumented endpoints, breaking changes, missing validation |
| 5 | Frontend Quality | `frontend` | Yes (diff) | Yes (full) | Accessibility gaps, missing error states, stale query configs, bundle size, unused imports, component complexity |
| 6 | Test Coverage | `test-coverage` | No | Yes (full) | Untested endpoints, missing edge cases, uncovered error paths, new code without tests, integration gaps |
| 7 | Dependency Health | `dependencies` | No | Yes (full) | Outdated packages, deprecated APIs, license issues, unmaintained deps, version conflicts, missing lockfiles |

**Trigger modes:**
- **On push to main** — Diff-only analysis, restricted to agents with `on_push: true` whose `scan_paths` overlap with changed files
- **Weekly schedule** — Monday 6am UTC, full codebase analysis, all enabled agents
- **Manual** (`workflow_dispatch`) — Any agent(s), choice of deep or diff-only mode

## File Architecture

```
.claude/agents/
├── _fleet-base.md              # Shared protocol: output format, dedup, issue creation, safety rules
├── fleet-security.md           # Security domain expertise + severity rubric
├── fleet-performance.md        # Performance domain expertise
├── fleet-architecture.md       # Architecture domain expertise
├── fleet-api-quality.md        # API quality domain expertise
├── fleet-frontend.md           # Frontend quality domain expertise
├── fleet-test-coverage.md      # Test coverage domain expertise
├── fleet-dependencies.md       # Dependency health domain expertise
├── contract-reviewer.md        # (existing, unchanged)
└── security-reviewer.md        # (existing, unchanged)

.claude/skills/
└── review/
    └── SKILL.md                # /review skill — on-demand local use

.github/
├── workflows/
│   ├── agent-fleet.yml         # Unified workflow (all agents, all triggers)
│   └── deploy-website.yml      # (existing, unchanged)
└── agent-fleet.yml             # Fleet config: escalation flags, per-agent settings

scripts/
└── agent-fleet-run.sh          # Wrapper: resolves agent file, passes to claude CLI
```

### Prompt Layering

Each agent's runtime prompt is constructed by concatenating `_fleet-base.md` (shared protocol) with the agent-specific file (domain expertise). This keeps shared logic DRY while allowing each agent to define its own severity rubric, analysis patterns, and domain knowledge.

The `fleet-` prefix distinguishes fleet agents from existing manual review agents (`contract-reviewer.md`, `security-reviewer.md`).

## Fleet Config File

`.github/agent-fleet.yml` — the control plane for the fleet. Changes require human commits; agents cannot self-modify this file.

```yaml
defaults:
  escalation: issues-only    # issues-only | draft-prs | auto-merge
  severity_threshold: medium  # low | medium | high | critical
  labels:
    - "agent-fleet"

agents:
  security:
    enabled: true
    on_push: true
    escalation: issues-only
    severity_threshold: low
    scan_paths:
      - "orchestrator/"
      - "llm-gateway/"
      - "memory-service/"
      - "chat-api/"
      - "chat-bridge/"
      - "cortex/"
      - "recovery/"
      - "docker-compose*.yml"
      - "scripts/"
      - ".env.example"
    labels:
      - "agent:security"
      - "security"

  performance:
    enabled: true
    on_push: true
    scan_paths:
      - "orchestrator/"
      - "llm-gateway/"
      - "memory-service/"
      - "chat-api/"
      - "cortex/"
    labels:
      - "agent:performance"

  architecture:
    enabled: true
    on_push: false
    scan_paths:
      - "orchestrator/"
      - "llm-gateway/"
      - "memory-service/"
      - "chat-api/"
      - "chat-bridge/"
      - "cortex/"
      - "recovery/"
      - "nova-contracts/"
    labels:
      - "agent:architecture"

  api-quality:
    enabled: true
    on_push: true
    scan_paths:
      - "orchestrator/app/router*.py"
      - "orchestrator/app/auth*.py"
      - "llm-gateway/"
      - "memory-service/app/router*.py"
      - "chat-api/"
      - "cortex/app/router*.py"
      - "recovery/app/router*.py"
      - "nova-contracts/"
    labels:
      - "agent:api-quality"

  frontend:
    enabled: true
    on_push: true
    scan_paths:
      - "dashboard/src/"
      - "dashboard/package.json"
      - "dashboard/tsconfig.json"
    labels:
      - "agent:frontend"

  test-coverage:
    enabled: true
    on_push: false
    scan_paths:
      - "tests/"
      - "orchestrator/"
      - "llm-gateway/"
      - "memory-service/"
    labels:
      - "agent:test-coverage"

  dependencies:
    enabled: true
    on_push: false
    scan_paths:
      - "**/pyproject.toml"
      - "dashboard/package.json"
      - "dashboard/package-lock.json"
      - "docker-compose*.yml"
      - "**/*Dockerfile*"
    labels:
      - "agent:dependencies"
```

**Key properties:**
- `escalation` is per-agent — promote individually as trust is built
- `severity_threshold` filters findings below a minimum severity
- `scan_paths` are always repo-relative — enforces scoping boundary
- `defaults` reduce repetition — agents inherit unless they override
- `enabled: false` disables an agent entirely

## GitHub Actions Workflow

Single workflow file, matrix strategy for parallel agent execution:

```yaml
name: Agent Fleet

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 6 * * 1'   # Monday 6am UTC
  workflow_dispatch:
    inputs:
      agents:
        description: 'Comma-separated agent slugs (or "all")'
        default: 'all'
      mode:
        description: 'Analysis mode'
        type: choice
        options:
          - deep
          - diff-only
        default: deep
```

**Job flow per agent:**

1. Checkout repo
2. Install `claude` CLI
3. Read `.github/agent-fleet.yml` to determine agent config
4. Concatenate `_fleet-base.md` + agent-specific prompt
5. Run Claude with appropriate context (full repo or git diff)
6. Parse structured JSON output
7. Deduplicate against existing open issues
8. Create/update issues (or PRs, depending on escalation level)
9. Apply labels from config

**Cost controls:**
- On-push runs skip agents whose `scan_paths` don't overlap with the diff
- Each agent job has a 10-minute timeout
- Weekly sweep runs at off-peak hours
- `workflow_dispatch` allows running a single agent without the full fleet

## Base Prompt Protocol (`_fleet-base.md`)

### Safety & Scoping

- Operate ONLY within the git repository root — never read, reference, or suggest changes to files outside the working tree
- Never modify fleet config (`.github/agent-fleet.yml`), workflow files, or agent prompts
- Never modify `.env` files or any file containing secrets
- Never execute destructive commands (`rm`, `drop`, `reset`)
- `scan_paths` in the config are the agent's universe — nothing outside them is in scope

### Output Format

```json
{
  "findings": [
    {
      "id": "SEC-001",
      "severity": "high",
      "category": "security",
      "title": "Admin secret compared without constant-time equality",
      "file": "orchestrator/app/auth.py",
      "line": 42,
      "description": "String comparison with == is vulnerable to timing attacks. Use hmac.compare_digest() instead.",
      "suggestion": "Replace if secret == expected: with if hmac.compare_digest(secret, expected):",
      "confidence": "high"
    }
  ],
  "summary": {
    "total": 1,
    "critical": 0,
    "high": 1,
    "medium": 0,
    "low": 0
  }
}
```

### Severity Definitions

| Level | Meaning |
|-------|---------|
| **Critical** | Exploitable now, data loss risk, or production breakage |
| **High** | Significant risk, should fix before next release |
| **Medium** | Quality issue, fix when touching this code |
| **Low** | Suggestion, nice-to-have improvement |

### Issue Deduplication

1. Before creating an issue, search open issues with labels `agent-fleet` + `agent:<category>`
2. Normalize the title for comparison (lowercase, strip whitespace)
3. If a match is found with >80% title similarity, add a comment with updated findings instead of a new issue
4. If a finding no longer appears in a subsequent run, add a comment noting it may be resolved, but do NOT auto-close (human decides)

### Issue Template

```markdown
## [SEVERITY] Title

**Agent:** `fleet-<category>` | **Confidence:** high/medium/low
**File:** `path/to/file.py:42`

### Description
What was found and why it matters.

### Suggestion
Concrete fix or approach.

### Context
Relevant code snippet (max 20 lines).

---
<bot-emoji> Found by Nova Agent Fleet · `fleet-<category>` · [Run #N](link)
```

### Escalation Behavior

| Level | Behavior |
|-------|----------|
| `issues-only` | Create/update GitHub issues |
| `draft-prs` | Create issue AND a draft PR with the fix on a `fleet/<category>/<finding-id>` branch |
| `auto-merge` | Same as `draft-prs`, but enable auto-merge if CI passes. Only for `high` confidence findings |

## `/review` Skill

On-demand local review for in-session use.

### Usage

```
/review                    # All categories, working tree changes
/review security           # Single category
/review security,perf,api  # Multiple categories
/review #123               # Review a specific PR by number
```

### Behavior

1. **Scope** — No args: `git diff` (unstaged + staged). PR number: `gh pr diff`. No diff: falls back to full `scan_paths` analysis.
2. **Categories** — No category: all 7. Short aliases: `security`, `perf`, `arch`, `api`, `frontend`, `tests`, `deps`.
3. **Execution** — Sequential (one agent at a time for readable terminal output).
4. **No side effects** — Never creates issues, PRs, or branches. Purely informational.

### Output Format

Terminal-friendly, grouped by severity:

```
--- Security -----------------------------------------------
  HIGH  orchestrator/app/auth.py:42
        Admin secret compared without constant-time equality
        -> Use hmac.compare_digest() instead of ==

  MED   docker-compose.yml:89
        Redis exposed on 0.0.0.0 without requirepass
        -> Bind to 127.0.0.1 or set a password

--- Performance --------------------------------------------
  No issues found

--- Summary ------------------------------------------------
  2 findings: 1 high, 1 medium
```

### Scoping

Same safety rules as CI agents. Reads `.github/agent-fleet.yml` for `scan_paths` so there's a single source of truth for what each agent can see.

## Evolution Roadmap

### Phase 1: Suggest-Only (launch state)

- All agents set to `escalation: issues-only`
- Run for 2-4 weeks to calibrate signal quality
- Triage issues, close false positives, tune `severity_threshold` per agent

### Phase 2: Draft PRs (per-agent opt-in)

- Change `escalation` to `draft-prs` for trusted agents
- Likely first candidates: `dependencies` (version bumps are mechanical) and `security` (CVE fixes are well-defined)
- PRs on `fleet/<category>/<finding-id>` branches
- All draft PRs require human review

### Phase 3: Selective Auto-Merge (per-agent opt-in)

- Change `escalation` to `auto-merge` for highly trusted agents
- Gated: only `high` confidence findings, only if CI passes
- Likely limited to `dependencies` (patch bumps with passing tests)
- `fleet-auto-merge` label applied for auditability

### Safety Invariants Across All Phases

- No automatic promotion between phases — always a human decision via config commit
- No auto-merge without CI passing
- No agent can modify the fleet config, workflow files, or other agent prompts
- Rollback is a one-line YAML edit (`escalation: issues-only` or `enabled: false`)

## Relationship to Existing Infrastructure

| Existing | Fleet | Relationship |
|----------|-------|-------------|
| `contract-reviewer.md` | `fleet-api-quality.md` | Complementary. Contract reviewer is manual, triggered during code review. Fleet API quality agent runs automatically and covers broader API concerns. |
| `security-reviewer.md` | `fleet-security.md` | Complementary. Existing agent is manual, focused on auth changes. Fleet security agent runs automatically and covers the full security surface. |
| Ruff hook | `fleet-performance.md` | Non-overlapping. Ruff checks style; fleet checks runtime performance. |
| TypeScript hook | `fleet-frontend.md` | Non-overlapping. TS hook checks compilation; fleet checks UX quality, accessibility, component patterns. |
| `run-tests` skill | `fleet-test-coverage.md` | Complementary. Skill runs tests; fleet identifies what's NOT tested. |

## Implementation Scope

### Files to Create
- `.claude/agents/_fleet-base.md`
- `.claude/agents/fleet-security.md`
- `.claude/agents/fleet-performance.md`
- `.claude/agents/fleet-architecture.md`
- `.claude/agents/fleet-api-quality.md`
- `.claude/agents/fleet-frontend.md`
- `.claude/agents/fleet-test-coverage.md`
- `.claude/agents/fleet-dependencies.md`
- `.claude/skills/review/SKILL.md`
- `.github/agent-fleet.yml`
- `.github/workflows/agent-fleet.yml`
- `scripts/agent-fleet-run.sh`

### Files to Modify
- `.claude/settings.json` — Register the `/review` skill (if needed)

### Files Unchanged
- `.claude/agents/contract-reviewer.md`
- `.claude/agents/security-reviewer.md`
- `.github/workflows/deploy-website.yml`
- All existing hooks, skills, and commands
