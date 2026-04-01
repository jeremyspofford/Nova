# IDE Integration Onboarding — Design Spec

**Date:** 2026-04-01
**Status:** Approved
**Goal:** Make it trivially easy for users to connect their code editor to Nova as an AI backend, with zero-friction config generation, connection testing, and live monitoring.

---

## Problem

Nova exposes an OpenAI-compatible API at `localhost:8001/v1` that works with any editor that speaks that protocol (Continue.dev, Cline, Cursor, Aider, Windsurf, etc.). But users have no way to discover this from the dashboard. The docs exist at `/nova/docs/ide-integration` on the website, but nobody finds them during onboarding. The result: a powerful capability that goes unused because the last mile of configuration is invisible.

## Solution

Two touchpoints:

1. **Dashboard page** (`/editors`) — a dedicated "Connect Your Editor" page with config generation, connection testing, and live connection monitoring
2. **Onboarding card** — a non-blocking card on the onboarding wizard's "Ready" screen that links to the new page

---

## 1. Dashboard Page: `/editors`

### Navigation

- New top-level nav item "Editors" in the Infrastructure section (between Models and Integrations)
- Lucide icon: `Plug` or `Monitor`
- Minimum role: `member`

### Layout

Single page with three zones:

```
┌─────────────────────────────────────────────┐
│  Connect Your Editor                        │
│  Use Nova as your AI backend in any editor  │
├─────────────────────────────────────────────┤
│  CONNECTED EDITORS              Endpoint:   │
│  ● Continue.dev  3s ago     localhost:8001   │
│  ○ Cursor        —               [Copy]     │
│  ○ Cline         —                          │
├─────────────────────────────────────────────┤
│  [Continue] [Cline] [Cursor] [Aider]        │
│  [Windsurf] [Other]                         │
├─────────────────────────────────────────────┤
│  Step 1: Pick a model         [dropdown]    │
│                                             │
│  Step 2: Copy this config          [Copy]   │
│  ┌─────────────────────────────────┐        │
│  │ { "title": "Nova (Sonnet)", ... │        │
│  └─────────────────────────────────┘        │
│                                             │
│  Step 3: Paste in your editor               │
│  Cmd+Shift+P → "Continue: Open config.json" │
│  → paste into models array                  │
│                                             │
│  [Test Connection]  ● Connected!            │
└─────────────────────────────────────────────┘
```

**Zone 1 — Connection monitor bar:**
- Shows all known editors with status dots
- Green = last seen < 60s, yellow = last seen < 5m, gray = never/stale
- Shows the endpoint URL (`http://localhost:8001/v1`) with a copy button

**Zone 2 — Editor tabs:**
- Tabs: Continue.dev, Cline, Cursor, Aider, Windsurf, Other/Generic
- Each tab contains editor-specific config generation and paste instructions
- Active tab persisted in URL hash (`#editor=continue`)

**Zone 3 — Config content (per editor tab):**
- Model selector dropdown (populated from `GET /v1/models`)
- Generated config block with copy-to-clipboard button
- Editor-specific paste instructions (where to open, what menu, etc.)
- "Test Connection" button with success/failure feedback

### Supported Editors

| Editor | Config format | Generated output |
|---|---|---|
| Continue.dev | JSON (`config.json` models array entry) | `{ title, provider, model, apiBase, apiKey }` |
| Cline | JSON (Cline settings) | `{ apiBase, model, apiKey }` |
| Cursor | Step-by-step instructions | Settings > Models > Add model (base URL, key, model) |
| Aider | CLI command | `aider --openai-api-base ... --openai-api-key ... --model ...` |
| Windsurf | JSON (similar to Continue format) | `{ title, provider, model, apiBase, apiKey }` |
| Other / Generic | Raw endpoint + curl example | URL, model list, auth header format |

### Config Generation Logic

On tab selection, the page:

1. Queries `GET /v1/models` for available model IDs
2. Checks auth status from platform config (`REQUIRE_AUTH`)
3. If auth enabled: creates or reuses an API key named `editor-{slug}` (e.g., `editor-continue`) via `POST /api/v1/keys` with `rate_limit_rpm: 120`
4. If auth disabled: sets `apiKey` to `"unused"` in the generated config
5. Populates the config template with selected model, endpoint URL, and key
6. Config updates live when user changes the model dropdown

**API key lifecycle:**
- Auto-created with name `editor-{slug}` on first tab visit (if auth enabled)
- Reused if an `editor-{slug}` key already exists (checked via `GET /api/v1/keys`)
- "Regenerate Key" button available for rotation
- Revoking via Settings > Keys shows the editor as disconnected on this page

### Test Connection

- Fires `POST /v1/chat/completions` through the dashboard's existing proxy using the editor's API key and selected model, with a trivial prompt (e.g., `"ping"`, `max_tokens: 1`)
- Success: green checkmark + "Connected! Nova received the request using {model}."
- Failure: red X + specific error message with hint:
  - Key invalid → "API key was revoked. Click Regenerate Key."
  - Gateway down → "LLM Gateway is not responding. Check service status."
  - Model not found → "Model {id} is not available. Try a different model."

---

## 2. Connection Monitor (Backend)

### Request Tracking in LLM Gateway

The gateway's `/v1/chat/completions` handler adds lightweight tracking after each request:

- Write to Redis hash `nova:editor:connections` (in gateway's db1)
- Key: API key name (e.g., `editor-continue`) or detected User-Agent slug
- Value: JSON `{ "last_seen": <unix_ts>, "user_agent": "<raw>", "request_count": <int> }`
- Each entry has a 5-minute TTL (auto-cleanup of stale connections)

### User-Agent Fallback Detection

When the API key is not one of the named `editor-*` keys, attempt to identify the editor from the User-Agent header:

```python
UA_PATTERNS = {
    "continue": "continue",
    "cline": "cline",
    "cursor": "cursor",
    "aider": "aider",
}
```

Only used as a fallback — key-based detection is primary and more reliable.

### New Endpoint

`GET /v1/editor-connections` on the LLM Gateway:

```json
{
  "connections": {
    "editor-continue": {
      "editor": "continue",
      "last_seen": "2026-04-01T12:34:56Z",
      "request_count": 42,
      "status": "connected"
    },
    "editor-cursor": {
      "editor": "cursor",
      "last_seen": null,
      "request_count": 0,
      "status": "never"
    }
  },
  "endpoint": "http://localhost:8001/v1",
  "auth_required": true
}
```

Status values: `"connected"` (< 60s), `"idle"` (< 5m), `"disconnected"` (> 5m), `"never"` (no record).

Dashboard polls this endpoint every 5 seconds via TanStack Query.

---

## 3. Onboarding Integration

### Ready Screen Card

The onboarding wizard's final "Ready" step (step 6) gains a second card alongside the existing "Open Chat" action:

```
┌──────────────────┐  ┌──────────────────┐
│  [MessageSquare] │  │  [Plug]          │
│  Open Chat       │  │  Connect Your    │
│                  │  │  Editor          │
│  Start talking   │  │  Use Nova in     │
│  to Nova         │  │  VS Code, Cursor │
│                  │  │  or terminal     │
│  [Go to Chat →]  │  │  [Set Up →]      │
└──────────────────┘  └──────────────────┘
```

- Not a new wizard step — zero friction added to the existing 6-step flow
- "Set Up" navigates to `/editors`
- Card uses Lucide `Plug` icon
- Styled consistently with the existing Ready screen

---

## 4. Files to Create/Modify

### New Files

| File | Purpose |
|---|---|
| `dashboard/src/pages/Editors.tsx` | Main "Connect Your Editor" page |
| `dashboard/src/pages/editors/editorConfigs.ts` | Per-editor config templates and metadata |

### Modified Files

| File | Change |
|---|---|
| `dashboard/src/App.tsx` | Add `/editors` route |
| `dashboard/src/components/layout/Sidebar.tsx` | Add "Editors" nav item in Infrastructure section |
| `dashboard/src/pages/onboarding/Ready.tsx` | Add "Connect Your Editor" card |
| `llm-gateway/app/openai_router.py` | Add request tracking + `GET /v1/editor-connections` endpoint |

### No New Database Tables

Connection state is ephemeral — Redis hash with TTL. API keys use the existing `api_keys` table.

---

## 5. Non-Goals

- Auto-installing editor extensions (too invasive, platform-dependent)
- MCP server integration for editors (future work — would let editors use Nova's memory/tools natively)
- CLI tool (`nova` command) — different scope entirely
- Detecting editor version or extension version
