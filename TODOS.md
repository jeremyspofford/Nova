# Nova — Deferred Work

> Items considered and explicitly deferred. Each has enough context to pick up cold.

## Friction Log Enhancements

### Docker Log Auto-Attach
**What:** When clicking "Fix This" on a friction entry, auto-capture recent service logs (last 10 min) and include them as context in the pipeline task input.
**Why:** Logs contain the actual error traces that caused the friction. Manual paste is a workaround but adds friction to the friction-reporting process.
**How:** Either mount Docker socket in orchestrator (security concern) or call the recovery service's existing Docker API access to pull logs. Recovery already has socket access.
**Blocked by:** Decision on whether orchestrator should have Docker socket access, or if recovery service should expose a log-retrieval endpoint.
**Added:** 2026-03-19

### Friction-to-Engram Pipeline
**What:** Feed friction log entries into the engram memory system so Nova "remembers" past friction and avoids repeating patterns.
**Why:** Friction entries represent hard-won learnings about what breaks. If the memory system knows "file uploads crash when disk is >90% full," future tasks can be warned.
**How:** On friction entry resolution (status → fixed), push a structured engram to `engram:ingestion:queue` with the friction description, resolution, and any associated task output.
**Blocked by:** Friction log feature must exist first. Engram ingestion must be stable.
**Added:** 2026-03-19

### GitHub Issue Export
**What:** One-click to create a GitHub issue from a friction entry. Pre-populates title, description, severity label.
**Why:** Bridges internal friction tracking to external visibility. Useful for open-source or when inviting external users.
**How:** GitHub API or `gh` CLI from orchestrator. Requires `GITHUB_TOKEN` in .env.
**Blocked by:** Friction log feature must exist first.
**Added:** 2026-03-19

### Screenshot File Cleanup Tooling
**What:** Orphan detection + disk usage monitoring for friction screenshot files.
**Why:** File-based storage can accumulate orphans after DB restores or manual deletes.
**How:** Script or endpoint that compares filesystem to DB, deletes orphaned files, reports disk usage.
**Blocked by:** Friction log with file-based screenshot storage.
**Added:** 2026-03-19

## Cloud LLM Providers

### Activate ChatGPT Subscription Provider
**What:** Run `codex login` to authenticate, then set `CHATGPT_TOKEN_DIR=~/.codex` in `.env`. Nova's `ChatGPTSubscriptionProvider` is already fully built — streaming, tool calls, auto-discovery from `~/.codex/auth.json`. Just needs the auth token.
**Why:** Gets GPT-4o and o3 on subscription (zero API cost) with full tool support. Currently the only working cloud provider with tool calls — Claude subscription OAuth is limited to Haiku 4.5.
**How:** `codex login` → add `CHATGPT_TOKEN_DIR=~/.codex` to `.env` → restart llm-gateway. Models available: `chatgpt/gpt-4o`, `chatgpt/o3`, `chatgpt/o4-mini`.
**Blocked by:** Nothing — codex CLI needs to be installed (`npm i -g @openai/codex`), then one login.
**Added:** 2026-03-19

### Re-test Claude 4.6 Subscription OAuth
**What:** Periodically test whether Anthropic has enabled Sonnet/Opus 4.6 for subscription OAuth on the public messages API.
**Why:** Currently `claude-sonnet-4-6` and `claude-opus-4-6` return `invalid_request_error: "Error"` via OAuth token on `api.anthropic.com/v1/messages`. Only `claude-haiku-4-5-20251001` works. Claude Code uses a different internal API path. When Anthropic fixes this, update `_MODEL_MAP` in `claude_subscription_provider.py`.
**How:** `curl -s https://api.anthropic.com/v1/messages -H "x-api-key: $TOKEN" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" -d '{"model":"claude-sonnet-4-6","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}'` — if it returns a message instead of "Error", it's fixed.
**Blocked by:** Anthropic API change (external).
**Added:** 2026-03-19

## Design System

### Create DESIGN.md via /design-consultation
**What:** Document the dashboard's implicit design system — palette (stone/teal/amber/emerald), typography, spacing scale, component patterns (cards, badges, activity feeds, toggles), icon library (Lucide), and responsive breakpoints.
**Why:** Every new UI element (delegation cards, pod indicators, tool pickers) makes design decisions without a reference. The system exists implicitly in code but isn't documented, increasing drift risk as more UI is added. The chat pod work adds 3+ new UI elements that need to be consistent.
**How:** Run `/design-consultation` to audit the existing dashboard, extract the implicit system, and produce a DESIGN.md as the project's design source of truth.
**Blocked by:** Nothing — can be done anytime. Recommended before the chat pod dashboard integration (Step 4).
**Added:** 2026-03-19
