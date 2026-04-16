# Nova Tools: shell.run, fs.list, fs.read, nova.query_activity — Design Spec

**Date:** 2026-04-15
**Status:** Approved

---

## Goal

Add four new tool handlers to Nova's tool registry: `shell.run`, `fs.list`, `fs.read`, and `nova.query_activity`. These make Nova meaningfully capable on the host machine — running commands, reading files, listing directories, and querying its own activity history. No new tables, routers, or services required.

---

## Context

Nova already has a tool handler registry (`_REGISTRY` in `services/api/app/tools/handlers.py`) with five tools. Adding a new tool means: implementing a handler function, registering it in `_REGISTRY`, and seeding a `Tool` DB record. The intent classifier in `conversations.py` can then invoke these tools from chat.

All four tools fire immediately — `requires_approval=False` — consistent with Nova's design as a trusted personal assistant.

---

## Architecture

```
NOVA_WORKSPACE_DIR (env var, default: ~)
        │
        ▼
config.py  ←  nova_workspace_dir: str field
        │
        ▼
handlers.py  ←  4 new handler functions
        │
        ▼
_REGISTRY  ←  4 new entries with correct deps
        │
        ▼
seed.py  ←  4 new Tool definitions (upserted on startup)
```

Priority chain for workspace dir: env var → code default (`~`). UI-based config editing is a separate spec.

---

## Config

One new field added to `services/api/app/config.py`:

```python
nova_workspace_dir: str = Field(default="~", env="NOVA_WORKSPACE_DIR")
```

Handlers that need the workspace path take `cfg` as a dependency (already the convention for `ha.*` tools). The field is expanded at call time via `os.path.expanduser(cfg.nova_workspace_dir)`.

---

## Tool Designs

### `shell.run`

Runs an arbitrary shell command and returns its output.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "command":          { "type": "string" },
    "cwd":              { "type": "string" },
    "timeout_seconds":  { "type": "integer", "default": 30 }
  },
  "required": ["command"]
}
```

**Handler:**
```python
def handle_shell_run(input: dict, cfg=None) -> dict:
    cfg = cfg or _settings
    workspace = os.path.expanduser(cfg.nova_workspace_dir)
    cwd = input.get("cwd") or workspace
    timeout = input.get("timeout_seconds", 30)
    timed_out = False
    try:
        # sandbox boundary — replace subprocess with container exec for Docker isolation
        proc = subprocess.run(
            ["sh", "-c", input["command"]],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout[:4096]
        stderr = proc.stderr[:4096]
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, exit_code, timed_out = "", "Command timed out.", -1, True
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr, "timed_out": timed_out}
```

**Output schema:**
```json
{
  "properties": {
    "exit_code":  { "type": "integer" },
    "stdout":     { "type": "string" },
    "stderr":     { "type": "string" },
    "timed_out":  { "type": "boolean" }
  }
}
```

**Seed definition:**
- `risk_class`: `"high"`
- `requires_approval`: `false`
- `timeout_seconds`: `35`
- `adapter_type`: `"internal"`
- `tags`: `["shell", "system"]`

**Registry entry:** `"shell.run": (handle_shell_run, ["settings"])`

---

### `fs.list`

Lists the contents of a directory.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "path":        { "type": "string", "default": "." },
    "show_hidden": { "type": "boolean", "default": false }
  }
}
```

**Handler behavior:**
- Resolves `path` relative to `NOVA_WORKSPACE_DIR` if not absolute (`os.path.join(workspace, path)`)
- Returns entries sorted: directories first (alphabetical), then files (alphabetical)
- Each entry: `{"name": str, "type": "file"|"dir", "size_bytes": int, "modified": str}` (ISO 8601 modified time)
- `show_hidden=false` filters entries starting with `.`
- Raises `ValueError` if resolved path does not exist or is not a directory

**Output schema:**
```json
{
  "properties": {
    "path":    { "type": "string" },
    "entries": { "type": "array", "items": { "type": "object" } }
  }
}
```

**Seed definition:**
- `risk_class`: `"low"`
- `requires_approval`: `false`
- `timeout_seconds`: `10`
- `adapter_type`: `"internal"`
- `tags`: `["filesystem"]`

**Registry entry:** `"fs.list": (handle_fs_list, ["settings"])`

---

### `fs.read`

Reads the contents of a file.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "path":      { "type": "string" },
    "max_bytes": { "type": "integer", "default": 8192 }
  },
  "required": ["path"]
}
```

**Handler behavior:**
- Resolves `path` relative to `NOVA_WORKSPACE_DIR` if not absolute
- Reads up to `max_bytes` bytes, decodes as UTF-8 (with `errors="replace"` for binary files)
- Returns `truncated: true` if file is larger than `max_bytes`
- Raises `FileNotFoundError` (surfaced as tool error) if path does not exist

**Output schema:**
```json
{
  "properties": {
    "path":       { "type": "string" },
    "content":    { "type": "string" },
    "truncated":  { "type": "boolean" },
    "size_bytes": { "type": "integer" }
  }
}
```

**Seed definition:**
- `risk_class`: `"low"`
- `requires_approval`: `false`
- `timeout_seconds`: `10`
- `adapter_type`: `"internal"`
- `tags`: `["filesystem"]`

**Registry entry:** `"fs.read": (handle_fs_read, ["settings"])`

---

### `nova.query_activity`

Queries Nova's own run history from the `Run` table.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "limit":       { "type": "integer", "default": 10 },
    "since_hours": { "type": "integer", "default": 24 },
    "status":      { "type": "string", "enum": ["succeeded", "failed", "running"], "nullable": true },
    "tool_name":   { "type": "string", "nullable": true }
  }
}
```

**Handler behavior:**
- Queries `Run` table with optional `status` and `tool_name` filters
- Always filters to `started_at >= now - since_hours`
- Orders by `started_at DESC`, returns up to `limit` records
- `total` is the count of all matching rows before the limit is applied (requires a separate COUNT query — same pattern as the `/activity` endpoint)
- Needs `db` dependency (same pattern as `devops.summarize_ci_failure`)

**Output schema:**
```json
{
  "properties": {
    "runs": {
      "type": "array",
      "items": {
        "properties": {
          "id":          { "type": "string" },
          "tool_name":   { "type": "string" },
          "status":      { "type": "string" },
          "summary":     { "type": "string" },
          "started_at":  { "type": "string" },
          "finished_at": { "type": "string" }
        }
      }
    },
    "total": { "type": "integer" }
  }
}
```

**Seed definition:**
- `risk_class`: `"low"`
- `requires_approval`: `false`
- `timeout_seconds`: `10`
- `adapter_type`: `"internal"`
- `tags`: `["nova", "activity"]`

**Registry entry:** `"nova.query_activity": (handle_nova_query_activity, ["db"])`

---

## Error Handling

Each handler raises a Python exception on failure (consistent with existing handlers). The `dispatch()` caller in `conversations.py` catches all exceptions, sets `run.status = "failed"`, `run.error = str(exc)`, and injects the error into the LLM context so Nova can explain what went wrong.

- `shell.run`: `TimeoutExpired` caught internally, returned as `timed_out: true` rather than raised (the command output is still useful)
- `fs.list`: raises `ValueError` for missing/non-directory path
- `fs.read`: raises `FileNotFoundError` for missing path
- `nova.query_activity`: no expected errors (DB query, empty result is valid)

---

## Files Changed

| File | Change |
|------|--------|
| `services/api/app/config.py` | Add `nova_workspace_dir` field |
| `services/api/app/tools/handlers.py` | Add 4 handler functions + `import os, subprocess, datetime` |
| `services/api/app/tools/seed.py` | Add 4 tool definitions to `tool_definitions` list |
| `services/api/tests/test_tool_handlers.py` | Add tests for all 4 handlers |

---

## Testing

All handlers tested in `tests/test_tool_handlers.py` using `unittest.mock` and `monkeypatch`, consistent with existing handler tests.

**`shell.run` tests:**
- Happy path: command exits 0, stdout returned correctly
- Non-zero exit code: returned in result, no exception raised
- Timeout: `timed_out: true`, no exception raised
- Custom `cwd`: passed through to subprocess
- stdout/stderr truncation at 4096 chars

**`fs.list` tests:**
- Lists files and dirs in workspace root (mocked `os.scandir`)
- Hidden files filtered when `show_hidden=false`
- Hidden files included when `show_hidden=true`
- Raises on missing path

**`fs.read` tests:**
- Reads file content correctly
- Truncates at `max_bytes` with `truncated: true`
- Relative path resolved against workspace dir
- Raises on missing file

**`nova.query_activity` tests:**
- Returns runs from DB with correct field mapping
- `since_hours` filter applied correctly
- `status` and `tool_name` filters work independently
- Empty result returns `{"runs": [], "total": 0}`

---

## Future: Docker Sandbox

The `subprocess.run` call in `handle_shell_run` is marked with a `# sandbox boundary` comment. To containerize:
1. Replace the `subprocess.run` block with `docker exec <container> sh -c <command>`
2. Mount `NOVA_WORKSPACE_DIR` as a volume into the container
3. No other handler code changes required

`fs.read` and `fs.list` may also need to route through the container's filesystem in that mode — same boundary applies.
