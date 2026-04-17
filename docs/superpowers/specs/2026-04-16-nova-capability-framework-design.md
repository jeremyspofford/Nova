# Nova Capability Framework (Phase 1) — Primitives + MCP

**Date:** 2026-04-16
**Status:** Draft — pending review

---

## Goal

Move Nova from "hand-coded handler per feature" to a layered capability framework so it can grow without a human writing a new Python handler for every possible user intent. Phase 1 delivers the foundation of that framework:

1. **A small set of powerful native primitives** (`fs.write`, `sql.query`, `browser.fetch`) that close gaps in the existing tool set (`shell.run`, `http.request`, `fs.read`, `fs.list`).
2. **A Model Context Protocol (MCP) client** in nova-api that dynamically discovers and exposes tools from external MCP servers, letting the community ecosystem drive capability breadth instead of Nova's own codebase.

Phase 1 does NOT ship: code-generation sandbox (Phase 3), skill memory (Phase 2), or DB-encrypted secrets (future spec).

---

## User Stories

### Story 1 — adding a new capability without writing code

Jeremy says in chat: *"install the Reddit MCP server, auto-approve its tools."* Nova calls its `mcp.add_server` tool → intercepted for confirmation → Nova renders the proposed server entry + asks Confirm? → Jeremy says yes → row added to `mcp_servers`. Nova tells Jeremy to restart nova-api. After restart, Nova has ~10 new tools available (`reddit.search_posts`, `reddit.get_post`, etc.) with zero Nova code changes.

### Story 2 — asking Nova to use a newly-installed MCP

Jeremy: *"what's trending on r/localllama?"* Nova's LLM sees `reddit.search_posts` in its tool catalog → calls it → gets back titles → summarizes them. No handler written, no schema change.

### Story 3 — approval flow for destructive MCP tools

Jeremy adds the GitHub MCP with `auto_approve: false` and `sensitive_tools: ["create_issue", "push_commit"]`. He asks Nova: *"create an issue in my repo: Bug — feature X isn't working."* Nova's LLM picks `github.create_issue` → recognized as sensitive → Nova renders the confirmation prompt → Jeremy approves → issue created.

### Story 4 — failed MCP server degrades gracefully

The Reddit MCP subprocess crashes (dependency missing on fresh host, or ratelimit hit). Nova logs the failure, marks the server red in Settings, and continues serving every other request normally. A new chat request that needs Reddit produces a clear "Reddit MCP is not available right now" reply with no exceptions thrown.

### Story 5 — Nova writing to its own workspace

Jeremy: *"save a file called `notes.md` in my workspace with the bullet points you just gave me."* Nova calls `fs.write` with the content → writes to `NOVA_WORKSPACE_DIR/notes.md`. Previously impossible without a custom handler or `shell.run "cat > notes.md"` (fragile).

### Story 6 — Nova querying itself

Jeremy: *"how many failed runs have I had this week?"* Nova calls `sql.query` with a read-only SELECT against its own DB → counts rows → replies. Previously this required hand-coded analysis handlers; now any question answerable with a SELECT is one Nova can answer.

### Story 7 — fetching JS-rendered pages

Jeremy: *"summarize https://some-spa.example/blog/post"* (page won't render server-side). Nova's existing `http.request` returns useless skeleton HTML. `browser.fetch` launches Playwright, waits for JS, returns rendered text. Nova summarizes.

---

## Architecture

### High-level

```
┌─── nova-api container ──────────────────────────────────────┐
│                                                             │
│   FastAPI                                                   │
│   ├─ chat tool-calling loop (route_with_tools)              │
│   │     ↓                                                   │
│   ├─ tool_handlers.dispatch(name, args, db, cfg)            │
│   │     ├─ native path (existing _REGISTRY)                 │
│   │     └─ mcp path (new, routes on server-id prefix)       │
│   │           ↓                                             │
│   └─ MCPRegistry (singleton)                                │
│         ├─ per-server MCPServerConnection                   │
│         │    ├─ stdio: subprocess                           │
│         │    │    ↓                                         │
│         │    │   e.g. `npx @modelcontextprotocol/server-X`  │
│         │    └─ http: HTTPX client                          │
│         └─ live tool catalog (merged into LLM tool catalog) │
│                                                             │
│   baked into image: node 20, python 3.12, uv                │
└─────────────────────────────────────────────────────────────┘
```

### Components

| Component | Responsibility |
|---|---|
| `app/mcp/client.py` | MCP protocol client — speaks JSON-RPC 2.0 over stdio or HTTP/SSE per MCP spec |
| `app/mcp/registry.py` | Singleton that starts/stops MCP connections, maintains live tool catalog, routes invocations |
| `app/mcp/lifecycle.py` | Startup/shutdown hooks integrated with FastAPI `lifespan` |
| `app/mcp/env_resolver.py` | Resolves `${VAR}` references in config `env` field against host environment |
| `app/tools/native_primitives.py` | New handlers for `fs.write`, `sql.query`, `browser.fetch` |
| `app/tools/mcp_management.py` | `mcp.list_servers`, `mcp.add_server`, `mcp.update_server`, `mcp.remove_server` handlers |
| `app/models/mcp_server.py` | SQLAlchemy model |
| `app/schemas/mcp_server.py` | Pydantic schemas + validators |
| `app/routers/mcp.py` | `GET /mcp/servers`, `GET /mcp/servers/{id}/health` — read-only endpoints for the Settings panel |
| `services/board/src/components/Settings/MCPServersPanel.tsx` | Read-only Settings UI |

### Data model

New migration `0010_mcp_servers.py`. Single new table:

```python
class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id = Column(String, primary_key=True)               # kebab-case, used as tool prefix
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    transport = Column(String, nullable=False)          # "stdio" | "http"

    # stdio transport:
    command = Column(String, nullable=True)
    args = Column(JSON, nullable=False, default=list)

    # http transport:
    url = Column(String, nullable=True)

    # auth: values are "${VAR_NAME}" references, not bare secrets
    env = Column(JSON, nullable=False, default=dict)

    # approval policy:
    auto_approve = Column(Boolean, nullable=False, default=False)
    sensitive_tools = Column(JSON, nullable=False, default=list)

    # runtime state:
    enabled = Column(Boolean, nullable=False, default=True)
    last_error = Column(String, nullable=True)
    last_connected_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

**Pydantic validation on save:**
- `id` matches `^[a-z0-9][a-z0-9-]{0,63}$`
- If `transport == "stdio"`: `command` required, `url` must be null
- If `transport == "http"`: `url` required, `command` must be null, URL must be `http(s)://...`
- All `env` values match `^\$\{[A-Z_][A-Z0-9_]*\}$` — bare secrets rejected
- `sensitive_tools` entries are bare tool names (no dots)

**MCP tools are NOT persisted as rows in the existing `tools` table.** They're discovered dynamically at MCP startup from the live connection. `tools` table stays native-only. The tool catalog visible to the LLM is built at runtime from `_REGISTRY ∪ MCPRegistry.tools()`.

---

## Native primitives (new)

### `fs.write`

**Purpose:** create or overwrite a file within `NOVA_WORKSPACE_DIR`.

**Input schema:**
```json
{
  "path": "relative path inside workspace; parent dirs created if missing",
  "content": "file content, UTF-8 string",
  "mode": "append | overwrite (default overwrite)"
}
```

**Safety:**
- All paths resolved relative to `NOVA_WORKSPACE_DIR`; attempts to escape via `..` or absolute paths → 400.
- 10 MB max content size; larger → 413.
- No binary handling in v1 (text-only via UTF-8). Binary writes could be added in Phase 3 alongside code-gen.

**Seed:** `risk_class="medium"`, `requires_approval=False`, `adapter_type="internal"`, `timeout_seconds=10`.

### `sql.query`

**Purpose:** execute a read-only SELECT against Nova's own Postgres DB.

**Input schema:**
```json
{
  "sql": "SELECT ... statement",
  "limit": "max rows returned (default 100, max 1000)"
}
```

**Safety:**
- SQL parsed with `sqlparse`; reject unless first token is `SELECT` AND no `INSERT`/`UPDATE`/`DELETE`/`DROP`/`CREATE`/`ALTER`/`TRUNCATE`/`GRANT` tokens present anywhere in the statement.
- Uses the existing `nova` DB role (already read-mostly — writes happen via ORM with different connection).
- Result truncated to `limit` rows.
- Timeout: 30s via `statement_timeout` SET LOCAL.

**Seed:** `risk_class="low"`, `requires_approval=False`, `adapter_type="internal"`, `timeout_seconds=30`.

### `browser.fetch`

**Purpose:** fetch and return the rendered text of a page that needs JS to render correctly (SPAs, Reddit's new UI, Twitter, etc.).

**Input schema:**
```json
{
  "url": "https://...",
  "wait_for_selector": "optional CSS selector to wait for before returning",
  "timeout_seconds": "default 30, max 60"
}
```

**Implementation:**
- Playwright with Chromium, headless, new context per request (isolated).
- Returns `{"url": "final after redirects", "title": "...", "text": "rendered body text", "status": 200}`.
- Max response: 2MB text; truncate if larger.

**Dockerfile impact:** `playwright install chromium` during nova-api image build. Adds ~300MB to image. Acceptable.

**Seed:** `risk_class="low"`, `requires_approval=False`, `adapter_type="internal"`, `timeout_seconds=65`.

---

## MCP client

### Transport support

Both transports per the MCP spec:
- **stdio:** `nova-api` spawns the MCP server as a subprocess, communicates via stdin/stdout with line-delimited JSON-RPC. Standard for community MCPs published to npm/PyPI.
- **HTTP/SSE:** `nova-api` connects to a long-running MCP server via HTTP. Standard for remote MCPs or MCPs deployed as their own services.

### Runtime image

`services/api/Dockerfile` updated to include:
- `node:20` + `npx`
- `python:3.12` stays (already there)
- `uv` (for `uvx`-based Python MCPs)

These cover ~95% of stdio MCPs. ~200MB image growth. Alternative base image (`python:3.12-slim` + manual node install) keeps size down; accepted.

### Client library

Use the official `mcp` Python package (`pip install mcp`) where possible. Falls back to a hand-rolled JSON-RPC 2.0 client if the package doesn't cover a transport cleanly. (Initial survey: the `mcp` package covers stdio well; HTTP support is newer and may need our own layer.)

### Tool namespace

MCP tool names in Nova's catalog: `{server_id}.{tool_name}`. Example:
- Server configured with `id: "reddit"` publishing tool `search_posts` → appears as `reddit.search_posts` in Nova's tool catalog visible to the LLM.
- Matches Nova's existing dotted-prefix convention (`scheduler.list_triggers`, `fs.read`).

**Collision rule:** native tools always win. If an MCP server publishes a tool whose prefixed name matches a native tool, the MCP tool is hidden from the catalog and a warning logs on startup.

### Tool catalog merging

The existing `_tool_catalog(db)` function in `conversations.py` (builds the OpenAI-format tools list for the LLM) is extended:

```python
def _tool_catalog(db: Session) -> list[dict]:
    # Existing: enabled native tools from DB
    tools_list = db.query(Tool).filter(Tool.enabled == True).all()
    catalog = [_openai_tool_spec(t) for t in tools_list]

    # New: MCP tools from live registry
    from app.mcp.registry import MCPRegistry
    for mcp_tool in MCPRegistry.current_tools():  # skips disabled/disconnected servers
        # Check for collision with native; native wins.
        if any(t["function"]["name"] == mcp_tool.prefixed_name for t in catalog):
            log.warning("MCP tool %s collides with native; MCP version hidden", mcp_tool.prefixed_name)
            continue
        catalog.append(mcp_tool.to_openai_spec())
    return catalog
```

### Dispatch routing

`tool_handlers.dispatch(name, args, db, cfg)` gains a new check at the top:

```python
def dispatch(tool_name, input, db, cfg):
    # 1. Native registry (existing)
    if tool_name in _REGISTRY:
        handler_fn, deps = _REGISTRY[tool_name]
        return handler_fn(input, *_resolve_deps(deps, db, cfg))

    # 2. MCP registry (new)
    from app.mcp.registry import MCPRegistry
    if MCPRegistry.has_tool(tool_name):
        return MCPRegistry.invoke(tool_name, input)

    raise KeyError(f"Tool not found: {tool_name}")
```

Native takes precedence; MCP only matches if native has no such entry.

### Environment variable resolution

At MCP server startup, the `env` field (stored as `{"GITHUB_TOKEN": "${GITHUB_TOKEN}"}`) is resolved against the host environment via `app/mcp/env_resolver.py`:

```python
def resolve_env(template: dict[str, str]) -> dict[str, str]:
    resolved = {}
    for k, v in template.items():
        m = re.fullmatch(r"\$\{([A-Z_][A-Z0-9_]*)\}", v)
        if not m:
            raise ValueError(f"invalid env reference for {k}: {v!r}")
        varname = m.group(1)
        value = os.environ.get(varname)
        if value is None:
            raise MissingEnvVar(varname)
        resolved[varname] = value
    return resolved
```

If a required env var is missing, the server fails to start with a clear error in `mcp_servers.last_error`. Settings panel shows "required env var NOT set."

### Connection lifecycle

- `lifespan` startup hook iterates enabled `mcp_servers` rows, starts each in parallel, caches handles in `MCPRegistry`.
- Each server has a max-10s startup timeout. Failures land in `last_error` and the server is marked unhealthy; other servers keep loading.
- `lifespan` shutdown hook sends `shutdown` JSON-RPC request to each MCP, then terminates subprocesses with SIGTERM → SIGKILL after 5s.
- Runtime crash handling: if an MCP stdio subprocess exits unexpectedly, the registry marks that server's tools as disconnected, updates `last_error`, and does NOT auto-reconnect in v1 (restart nova-api to reconnect — logged as future improvement).

### No hot-reload in v1

Adding an MCP server via chat writes the DB row but does NOT start the connection live. User must restart nova-api. Reason: hot-reload adds complexity (signal handling, state cleanup) that's not critical for v1. Clearly messaged in chat after `mcp.add_server` succeeds. Hot-reload is a future improvement — the MCPRegistry is built to allow it.

---

## Management tools (chat-driven)

Four new native tools, seeded alongside the scheduler management tools. All take `(input, db)` and follow the existing `SENSITIVE_TOOLS` convention.

| Tool | Risk | Sensitive? | Description |
|---|---|---|---|
| `mcp.list_servers` | low | no | Returns all configured servers with status, tools exposed, env var check |
| `mcp.add_server` | medium | **yes** | Inserts a new `mcp_servers` row after confirmation |
| `mcp.update_server` | medium | **yes** | Updates `auto_approve` / `sensitive_tools` / `enabled` on a server |
| `mcp.remove_server` | high | **yes** | Deletes a row (server entry) after confirmation |

`SENSITIVE_TOOLS` set in `conversations.py` extended with `mcp.add_server`, `mcp.update_server`, `mcp.remove_server`.

### Example: `mcp.add_server` input shape

```json
{
  "id": "reddit",
  "name": "Reddit MCP",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-reddit"],
  "env": {},
  "auto_approve": true,
  "sensitive_tools": []
}
```

### Chat flow for sensitive MCP tools (extension of existing pattern)

When the chat tool-calling loop inspects a tool call's sensitivity:

```python
def _is_sensitive(tool_name: str, db: Session) -> bool:
    if tool_name in SENSITIVE_TOOLS:
        return True

    # New: MCP per-server policy
    if "." in tool_name:
        server_id, bare_name = tool_name.split(".", 1)
        server = db.query(MCPServer).filter_by(id=server_id).first()
        if server:
            if not server.auto_approve:
                return True
            if bare_name in (server.sensitive_tools or []):
                return True
    return False
```

Existing `_render_confirmation` is extended to handle MCP tool calls — pulls server name + tool name + args summary from the runtime catalog.

---

## Settings UI — read-only MCP panel

New section in the existing Settings page (after Scheduled Triggers), component `<MCPServersPanel />`.

**Layout:**
```
┌ MCP Servers ─────────────────────────────────────────────────┐
│                                                              │
│  🟢  Reddit MCP                             8 tools exposed  │
│      npx @modelcontextprotocol/server-reddit                 │
│      Auto-approve: yes                                       │
│      Last connected: 3m ago                                  │
│                                                              │
│  🔴  GitHub MCP                             Connection error │
│      npx @modelcontextprotocol/server-github                 │
│      Required env: GITHUB_TOKEN ⚠ not set                    │
│      Last error: "Missing GITHUB_TOKEN"                      │
│                                                              │
│  To add, edit, or remove servers, ask Nova in chat.          │
└──────────────────────────────────────────────────────────────┘
```

Backed by `GET /mcp/servers` which returns per-server: id, name, transport, health (computed from last_connected_at + last_error), tool count (from live registry), required env vars + which are set.

React Query refetches on tab focus and every 30s for live-ish health.

---

## Error handling

| Failure | Behavior |
|---|---|
| MCP stdio subprocess fails to start | Server marked `enabled=True` but unhealthy; `last_error` populated; Settings shows red. Other servers unaffected. |
| MCP HTTP server unreachable | Connection retry (exponential backoff, 3 attempts). If all fail, mark unhealthy. |
| Missing env var for a server | Server fails to start with clear error; Settings shows "env var NOT set". |
| MCP server crashes mid-session | Tools become unavailable until nova-api restart. Nova's LLM gets a clear error when trying to call them: "MCP server X is not responding." |
| Individual tool call times out | 30s default timeout, Run recorded as failed, error surfaced to LLM, other tools unaffected. |
| Tool name collision with native | MCP tool hidden, warning logged on startup. |
| User removes an MCP that's currently connected | Row deleted, but live connection stays until nova-api restart. Settings shows stale until restart (acceptable for v1 — hot-reload is future work). |
| `fs.write` escapes workspace | 400 with clear "path must be relative to workspace" message. |
| `sql.query` contains write-statement keywords | 400 with "only SELECT queries are allowed." |
| `browser.fetch` times out | 30s max; returns timeout error; Run marked failed. |

---

## Testing Strategy

**API tests:**
- `test_mcp_server_crud` — CRUD via management handlers (add/list/update/remove)
- `test_mcp_server_validation` — reject bare-secret env values, collision with malformed transports, bad id patterns
- `test_fs_write_restricts_to_workspace` — path traversal attempts rejected
- `test_fs_write_creates_parent_dirs` — nested paths work
- `test_sql_query_accepts_select` — simple SELECT returns rows
- `test_sql_query_rejects_write_keywords` — INSERT/UPDATE/DELETE/DROP all blocked
- `test_sql_query_respects_limit` — returns ≤ limit rows
- `test_browser_fetch_returns_rendered_text` — simple static page works (SPA test deferred to manual)
- `test_env_resolver_substitutes` — `${VAR}` correctly resolved against host env
- `test_env_resolver_rejects_bare_values` — validator catches bare secrets

**MCP client unit tests** (mock transports):
- `test_mcp_client_stdio_init_handshake` — JSON-RPC init + tools/list response
- `test_mcp_client_tool_invocation` — tools/call round-trip
- `test_mcp_registry_collision_prefers_native` — native tool shadows MCP tool
- `test_mcp_server_crash_marks_unhealthy` — simulated subprocess exit updates state

**Integration test with a real tiny MCP** (in CI):
- Ship a minimal "echo" MCP server fixture (Python, stdio) that publishes one `say_hello` tool
- Seed it in `mcp_servers`; start nova-api; verify `echo.say_hello` appears in `/mcp/servers`; dispatch it via `POST /tools/echo.say_hello/invoke`; assert result

**E2E smoke (manual or scripted):**
- Install Reddit MCP via chat; confirm "restart required" message; restart; verify tools appear in catalog
- Ask Nova to search a subreddit; verify it calls `reddit.search_posts` and renders results
- Manually kill the Reddit subprocess; verify graceful degradation

---

## Rollout / Migration

- **Migration 0010** — creates `mcp_servers` table. Downgrade drops it.
- **No data migration needed** — starts empty.
- **Dockerfile change** — adds node + uv + playwright. Image rebuild required (expected for any code change).
- **Backward compatibility:** all existing tool calls continue to work unchanged. MCP is purely additive.

---

## Roadmap / Deferred Work

Explicitly tracked so they don't get lost:

### Phase 2 — Skill memory
Nova remembers successful compositions of primitives + MCP tools as named reusable "skills". When a similar request arrives, retrieves the skill instead of re-reasoning from scratch. Triggered when Phase 1 has enough usage data to identify patterns worth remembering.

### Phase 3 — Code-generation sandbox
`python.exec` handler + Pyodide or Docker-per-call sandbox. Lets Nova write novel code when primitives don't compose cleanly (e.g., the "build a PoC" step in Jeremy's subreddit → GitHub → Cloudflare ambition). Ships as its own spec with security review.

### MCP hot-reload
Starting/stopping MCP servers without a nova-api restart. Requires lifecycle signal handling and state cleanup. Nice UX improvement; not critical for Phase 1.

### Secret-manager integration
Replace `${VAR}` env-var resolution with a pluggable resolver supporting `${op://vault/item/field}` (1Password CLI), AWS Secrets Manager, HashiCorp Vault, or similar. Natural fit given Jeremy's existing 1Password setup. Secrets stay out of the DB either way.

### DB field-level encryption
If we ever decide some secrets should persist in DB (e.g., for multi-user scenarios), add encryption-at-rest with a KMS-backed key. Not needed for single-user Phase 1.

### MCP tool auto-discovery polish
Periodically refresh tool catalogs from connected servers (in case an MCP adds tools without restarting). v1 fetches once on connection.

---

## Risks & Tradeoffs

**Risk: MCP ecosystem quality varies.** Some community MCPs are excellent; some are rough. User-installed MCPs inherit their quality. Mitigation: per-server approval policy means a shoddy MCP can at worst leak data through a tool call — destructive actions are gated by confirmation. Jeremy chooses which servers to trust.

**Risk: subprocess-based MCPs consume resources.** 10 stdio MCPs = 10 extra processes. On an 8GB host already running a 9B model, resource pressure is real. Mitigation: `enabled` flag per server; unused servers should be disabled. Monitor via `nova.system_health` (future refinement: include MCP process memory/CPU in the health check).

**Risk: image size bloat.** node + uv + chromium adds ~500MB. Mitigation: single-stage Dockerfile, clean caches. If size becomes a problem, split into a "nova-api-base" vs "nova-api-mcp" image variants.

**Risk: `sql.query` leaks sensitive data.** A user asking "show me all conversations" gets every chat message dumped. Mitigation: acceptable in single-user setup — user is asking about their own data. Multi-user would require row-level security, out of scope for Phase 1.

**Risk: `fs.write` clobbers existing files.** User could ask Nova to overwrite a file without realizing. Mitigation: `mode: "overwrite"` is the default but the tool is `risk_class="medium"` — future refinement could add auto-confirmation for overwrites when an existing file is detected.

**Risk: MCP tool descriptions are LLM-untrustworthy.** A malicious MCP could describe a destructive tool as innocuous to bypass confirmation. Mitigation: `sensitive_tools` list is the user's final call; MCP-provided description is advisory only.

**Risk: no hot-reload means friction.** Every MCP add/remove needs a restart. Mitigation: documented clearly in chat replies; hot-reload is an explicit follow-up. For an engineer's personal tool, "restart after configuration change" is a familiar pattern.

---

## Implementation Order (for the follow-on plan)

1. **Migration 0010** + `MCPServer` model + Pydantic schemas with validators.
2. **Environment variable resolver** (`app/mcp/env_resolver.py`) + unit tests.
3. **Native primitive: `fs.write`** — handler + workspace-relative-path safety + tests + seed + registry entry.
4. **Native primitive: `sql.query`** — handler + SELECT-only parser + tests + seed + registry entry.
5. **Native primitive: `browser.fetch`** — Playwright dependency + handler + timeout handling + tests + seed + registry entry.
6. **Dockerfile** — add node 20, uv, Playwright chromium.
7. **MCP protocol client** (`app/mcp/client.py`) — stdio transport first, then HTTP.
8. **MCPRegistry singleton** — server lifecycle, tool catalog, invocation routing.
9. **Lifespan integration** — start all enabled servers on nova-api startup, stop on shutdown.
10. **Tool catalog + dispatch extension** — merge MCP tools into `_tool_catalog`, add MCP branch to `tool_handlers.dispatch`.
11. **MCP management tools** — four handlers + registry entries + seed + tests.
12. **Approval flow integration** — `_is_sensitive` helper + `_render_confirmation` updates for MCP.
13. **`/mcp/servers` read-only router** + tests.
14. **Settings UI: `<MCPServersPanel />`** + fetch helper + CSS.
15. **Integration smoke test** — tiny echo MCP fixture + full dispatch test.
16. **End-to-end smoke** — install Reddit MCP, restart, ask a question, assert expected tool call.
17. **Push.**

Each step self-contained. Typical TDD cycle per step. Frequent commits.
