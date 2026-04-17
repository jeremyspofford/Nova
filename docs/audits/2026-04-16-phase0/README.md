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

## Implementation plan

`docs/superpowers/plans/2026-04-16-nova-phase0-audit.md`

## How to read the backlog

Default sort: Severity (P0 first) → Daily-Driver Impact (H first) → Effort (S first). Top rows are the "obviously do these first" items.

Severity is measured against a neutral "daily driver" user. Daily-Driver Impact captures how much the finding blocks *this* user (Jeremy) specifically. The two can diverge: e.g., a P0 bug in voice is L impact for a user who doesn't use voice.
