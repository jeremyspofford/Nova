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
├── fleet-base.md               # Shared protocol: output format, dedup, issue creation, safety rules
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

Each agent's runtime prompt is constructed by `scripts/agent-fleet-run.sh`, which reads `fleet-base.md` and the agent-specific file, concatenates them with a separator (`---`), and passes the result as the `--system-prompt` argument to the `claude` CLI. The analysis instructions (diff content or "analyze full codebase") are passed as the user `--prompt` argument.

Example invocation:
```bash
# agent-fleet-run.sh builds and runs:
claude --system-prompt "$(cat .claude/agents/fleet-base.md && echo '---' && cat .claude/agents/fleet-security.md)" \
       --prompt "Analyze the following diff for security issues: ..." \
       --output-format json \
       --max-turns 10 \
       --model sonnet
```

The `fleet-` prefix distinguishes fleet agents from existing manual review agents. `fleet-base.md` is a valid agent name (no underscore prefix needed) but is never invoked standalone — the workflow and script always pair it with a domain agent.

## Fleet Config File

`.github/agent-fleet.yml` — the control plane for the fleet. Changes require human commits; agents cannot self-modify this file.

```yaml
defaults:
  escalation: issues-only    # issues-only | draft-prs | auto-merge
  severity_threshold: medium  # low | medium | high | critical
  model: sonnet               # claude model to use
  max_turns: 10               # max conversation turns per agent run
  labels:
    - "agent-fleet"

agents:
  security:
    enabled: true
    on_push: true
    escalation: issues-only
    severity_threshold: low          # security gets everything
    scan_paths:
      - "orchestrator/"
      - "llm-gateway/"
      - "memory-service/"
      - "chat-api/"
      - "chat-bridge/"
      - "cortex/"
      - "recovery-service/"
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
      - "chat-bridge/"
      - "cortex/"
      - "recovery-service/"
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
      - "recovery-service/"
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
      - "memory-service/app/engram/"
      - "chat-api/"
      - "cortex/app/router*.py"
      - "recovery-service/app/routes.py"
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
      - "chat-api/"
      - "chat-bridge/"
      - "cortex/"
      - "recovery-service/"
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
- `model` and `max_turns` control cost per run
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

permissions:
  contents: read
  issues: write
  pull-requests: write

jobs:
  # Job 1: Determine which agents to run
  resolve-agents:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.resolve.outputs.matrix }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2  # need HEAD~1 for diff

      - name: Resolve agent matrix
        id: resolve
        run: |
          # Parse .github/agent-fleet.yml to get enabled agents
          # On push: filter to on_push=true agents whose scan_paths overlap with changed files
          # On schedule: all enabled agents
          # On workflow_dispatch: parse inputs.agents
          #
          # Changed files determined by: git diff --name-only HEAD~1..HEAD
          # Overlap check: for each agent, check if any changed file starts with
          # any of the agent's scan_paths prefixes (glob patterns expanded)
          #
          # Output: JSON array of agent slugs for the matrix
          python3 scripts/agent-fleet-resolve.py \
            --config .github/agent-fleet.yml \
            --trigger "${{ github.event_name }}" \
            --agents "${{ inputs.agents || 'auto' }}" \
            --mode "${{ inputs.mode || 'auto' }}" \
            >> "$GITHUB_OUTPUT"

  # Job 2: Run each agent in parallel
  run-agent:
    needs: resolve-agents
    if: needs.resolve-agents.outputs.matrix != '[]'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    strategy:
      fail-fast: false
      matrix:
        agent: ${{ fromJson(needs.resolve-agents.outputs.matrix) }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # full history for deep analysis

      - name: Install Claude CLI
        run: npm install -g @anthropic-ai/claude-code

      - name: Run fleet agent
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          bash scripts/agent-fleet-run.sh \
            --agent "${{ matrix.agent }}" \
            --config .github/agent-fleet.yml \
            --trigger "${{ github.event_name }}" \
            --mode "${{ inputs.mode || 'auto' }}"
```

### `scripts/agent-fleet-resolve.py`

A lightweight Python script (no dependencies beyond stdlib) that:
1. Reads `.github/agent-fleet.yml` (parsed as YAML via a simple parser or `pyyaml` installed in the workflow)
2. For push triggers: runs `git diff --name-only HEAD~1..HEAD`, then for each enabled agent with `on_push: true`, checks if any changed file matches any `scan_paths` entry using prefix matching (directories) or `fnmatch` (glob patterns)
3. For schedule triggers: returns all enabled agents
4. For workflow_dispatch: parses the `agents` input (comma-separated slugs or `"all"`)
5. Outputs `matrix=["security","performance",...]` as a JSON array

### `scripts/agent-fleet-run.sh`

The per-agent execution wrapper:
1. Reads agent config from `.github/agent-fleet.yml` (model, max_turns, escalation, labels, scan_paths)
2. Concatenates `fleet-base.md` + `fleet-{slug}.md` into a system prompt
3. Builds the user prompt: for diff-only mode, includes `git diff HEAD~1..HEAD -- <scan_paths>`; for deep mode, instructs the agent to analyze all files within its `scan_paths`
4. Runs `claude` CLI with `--system-prompt`, `--prompt`, `--output-format json`, `--model`, `--max-turns`
5. Parses the JSON output
6. For each finding above `severity_threshold`: calls `gh issue list --label "agent-fleet" --label "agent:{category}" --state open` and checks titles for duplicates (case-insensitive substring match). If duplicate found, `gh issue comment`. If new, `gh issue create` with labels from config.
7. If `escalation` is `draft-prs`: also creates a branch and PR (deferred — see Evolution Roadmap)

**Issue creation is handled by the shell script, not by Claude.** This keeps Claude focused on analysis and makes dedup deterministic rather than relying on LLM judgment. Title matching uses case-insensitive substring comparison (no fuzzy matching needed — agent-generated titles are consistent enough).

**Cost controls:**
- On-push runs skip agents whose `scan_paths` don't overlap with the diff (resolved in the matrix step — skipped agents never start)
- Each agent job has a `timeout-minutes: 10`
- `max_turns` defaults to 10 (configurable per agent)
- Model defaults to `sonnet` for cost efficiency; override to `opus` per-agent if quality requires it
- Weekly sweep runs at off-peak hours (Monday 6am UTC)
- `workflow_dispatch` allows running a single agent without the full fleet

**Estimated costs (Sonnet):** Each diff-only run uses ~20-50K input tokens + ~5K output. Each deep sweep uses ~100-200K input + ~10K output. Weekly full fleet (7 deep agents): ~$2-5. On-push (1-4 diff agents): ~$0.10-0.50.

## Base Prompt Protocol (`fleet-base.md`)

### Safety & Scoping

- Operate ONLY within the git repository root — never read, reference, or suggest changes to files outside the working tree
- Never modify fleet config (`.github/agent-fleet.yml`), workflow files, or agent prompts
- Never modify `.env` files or any file containing secrets
- Never execute destructive commands (`rm`, `drop`, `reset`)
- `scan_paths` in the config are the agent's universe — nothing outside them is in scope
- Never modify files in `.claude/agents/`, `.claude/skills/`, `.claude/hooks/`, `.github/`

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

### Confidence Definitions

| Level | Criteria |
|-------|----------|
| **High** | The code clearly exhibits this issue and the fix is unambiguous |
| **Medium** | The issue likely exists but additional context may change the assessment |
| **Low** | Possible issue that needs human judgment to confirm |

### Issue Deduplication

Handled by `scripts/agent-fleet-run.sh` (not by Claude). The script:

1. Lists open issues with labels `agent-fleet` + `agent:<category>` via `gh issue list`
2. For each finding, checks if any open issue title contains the finding's title as a case-insensitive substring (or vice versa)
3. If a match is found: `gh issue comment` with updated findings and the current run link
4. If no match: `gh issue create` with the issue template and configured labels
5. Findings that no longer appear in a run are NOT auto-closed — the script does not track resolved findings (human decides when to close)

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
Found by Nova Agent Fleet | `fleet-<category>` | [Run #N](link)
```

### Escalation Behavior

| Level | Behavior |
|-------|----------|
| `issues-only` | Create/update GitHub issues (Phase 1 — the only level implemented at launch) |
| `draft-prs` | Future Phase 2 — will be specified in a separate design document when any agent is promoted |
| `auto-merge` | Future Phase 3 — will be specified in a separate design document when any agent is promoted |

**Phase 1 implements `issues-only` only.** The config file accepts `draft-prs` and `auto-merge` as values so the schema is forward-compatible, but `agent-fleet-run.sh` treats any non-`issues-only` value as `issues-only` until the Phase 2 design is complete. This prevents premature implementation of PR automation.

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
3. **Execution** — Sequential (one agent at a time for readable terminal output). Each agent is dispatched as a subagent.
4. **No side effects** — Never creates issues, PRs, or branches. Purely informational.

### Configuration Reading

The `/review` skill prompt instructs Claude to read `.github/agent-fleet.yml` using the `Read` tool at the start of execution, extracting `scan_paths` for the relevant agent categories. This ensures the skill and CI use the same path configuration — single source of truth.

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

Same safety rules as CI agents. Only analyzes files within the `scan_paths` defined in `.github/agent-fleet.yml` for each category. Never reads, references, or suggests changes to files outside the repository root.

## Evolution Roadmap

### Phase 1: Suggest-Only (launch state, fully specified above)

- All agents set to `escalation: issues-only`
- Run for 2-4 weeks to calibrate signal quality
- Triage issues, close false positives, tune `severity_threshold` per agent
- `agent-fleet-run.sh` only implements issue creation

### Phase 2: Draft PRs (future, per-agent opt-in)

- Will be specified in a separate design document when the first agent is promoted
- High-level intent: change `escalation` to `draft-prs` for trusted agents; PRs on `fleet/<category>/<finding-id>` branches; all draft PRs require human review
- Likely first candidates: `dependencies` (version bumps are mechanical) and `security` (CVE fixes are well-defined)

### Phase 3: Selective Auto-Merge (future, per-agent opt-in)

- Will be specified in a separate design document when the first agent is promoted
- High-level intent: `auto-merge` for highly trusted agents, gated on high confidence + CI passing
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
- `.claude/agents/fleet-base.md` — shared protocol prompt
- `.claude/agents/fleet-security.md` — security agent prompt
- `.claude/agents/fleet-performance.md` — performance agent prompt
- `.claude/agents/fleet-architecture.md` — architecture agent prompt
- `.claude/agents/fleet-api-quality.md` — API quality agent prompt
- `.claude/agents/fleet-frontend.md` — frontend quality agent prompt
- `.claude/agents/fleet-test-coverage.md` — test coverage agent prompt
- `.claude/agents/fleet-dependencies.md` — dependency health agent prompt
- `.claude/skills/review/SKILL.md` — `/review` skill prompt
- `.github/agent-fleet.yml` — fleet config
- `.github/workflows/agent-fleet.yml` — GitHub Actions workflow
- `scripts/agent-fleet-run.sh` — per-agent execution wrapper
- `scripts/agent-fleet-resolve.py` — matrix resolution script

### Files to Modify
- `.claude/settings.json` — Register the `/review` skill (if needed by skill discovery)

### Files Unchanged
- `.claude/agents/contract-reviewer.md`
- `.claude/agents/security-reviewer.md`
- `.github/workflows/deploy-website.yml`
- All existing hooks, skills, and commands
