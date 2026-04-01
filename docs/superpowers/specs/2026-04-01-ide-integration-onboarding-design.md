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
- Lucide icon: `Code` (both `Plug` and `Monitor` are already used by Integrations and Models respectively)
- Minimum role: `member` — page renders for all members, but auto-key-creation requires admin. Non-admin users see the config with a placeholder key and a note: "Ask an admin to create an API key for you, or create one from Settings > Keys."

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
- Active tab persisted in URL hash via the existing `useTabHash` hook (`#tab=continue`)

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
- Auto-created with name `editor-{slug}` on first tab visit (if auth enabled, and user has admin role)
- To check for existing keys: fetch `GET /api/v1/keys`, filter client-side by name prefix `editor-`. There is no server-side filter endpoint.
- Guard against duplicate creation: check for existing key before creating. If a race creates a duplicate, it's harmless (two keys for the same editor both work).
- "Regenerate Key" = revoke the old key via `DELETE /api/v1/keys/{id}` + create a new one with the same name. After regeneration, the user must re-copy the config since the key value changed. The UI should show a warning: "Your editor will disconnect until you update the config."
- Revoking via Settings > Keys shows the editor as disconnected on this page
- Rate limit of 120 rpm (vs default 60) because editors make rapid sequential requests during autocomplete and inline suggestions

### Test Connection

The test proves the gateway endpoint is reachable and the selected model responds — the same path an external editor would take.

- Fires `POST /v1/chat/completions` through the dashboard's `/v1` proxy using the selected model with a trivial prompt (`"ping"`, `max_tokens: 1`)
- If auth is enabled, includes the editor's API key in the `Authorization: Bearer` header so the gateway's auth middleware validates it end-to-end
- If auth is disabled, sends without a key (same as the editor would)
- Success: green checkmark + "Connected! Nova received the request using {model}."
- Failure: red X + specific error message with hint:
  - 401/403 → "API key is invalid or revoked. Click Regenerate Key."
  - Gateway down → "LLM Gateway is not responding. Check service status."
  - Model not found → "Model {id} is not available. Try a different model."

---

## 2. Connection Monitor (Backend)

### Request Tracking in LLM Gateway

The gateway's `/v1/chat/completions` handler adds lightweight tracking **after a successful response** (not on request receipt — failed requests shouldn't count as "connected"):

- Write to separate Redis keys per editor: `nova:editor:connection:{slug}` (in gateway's db1)
- Value: JSON `{ "last_seen": <unix_ts>, "user_agent": "<raw>", "request_count": <int> }`
- Each key gets `EXPIRE 300` (5 minutes) — Redis per-field TTL doesn't exist on hashes, so separate keys are used instead
- The gateway's lifespan shutdown must include `close_redis()` for the connection tracking Redis client (per project convention: every `get_redis()` needs a corresponding `close_redis()`)

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
  "auth_required": false
}
```

Status values: `"connected"` (< 60s), `"idle"` (< 5m), `"disconnected"` (> 5m), `"never"` (no record).

The `endpoint` URL is read from `GATEWAY_PUBLIC_URL` env var (default: `http://localhost:8001/v1`). For remote access setups (Tailscale, Cloudflare tunnel), users should set this to their external URL. The `auth_required` field is read from the gateway's own `REQUIRE_AUTH` env var.

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
- "Set Up" navigates via `window.location.href = '/editors'` (full page navigation, consistent with the existing "Go to Chat" button which uses `window.location.href = '/chat'`)
- Card uses Lucide `Code` icon (matching the sidebar nav item)
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
| `dashboard/src/components/layout/MobileNav.tsx` | Add "Editors" nav item (mirrors sidebar) |
| `dashboard/src/pages/onboarding/Ready.tsx` | Add "Connect Your Editor" card |
| `llm-gateway/app/openai_router.py` | Add request tracking (post-response) + `GET /v1/editor-connections` endpoint |
| `llm-gateway/app/main.py` | Add `close_redis()` for connection tracking Redis in lifespan shutdown |

### No New Database Tables

Connection state is ephemeral — separate Redis keys per editor with 5-minute TTL. API keys use the existing `api_keys` table.

---

## 5. Non-Goals

- Auto-installing editor extensions (too invasive, platform-dependent)
- MCP server integration for editors (future work — would let editors use Nova's memory/tools natively)
- CLI tool (`nova` command) — different scope entirely
- Detecting editor version or extension version
