# Nova Tools: shell.run, fs.list, fs.read, nova.query_activity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four tool handlers (shell.run, fs.list, fs.read, nova.query_activity) to Nova's tool registry, seeding each as a Tool DB record so the chat agent can invoke them by name.

**Architecture:** Each handler is a plain Python function added to `services/api/app/tools/handlers.py`, registered in `_REGISTRY`, and upserted as a `Tool` row in `seed.py` on startup. The workspace root (`NOVA_WORKSPACE_DIR`) is added to `Settings` and injected via the `"settings"` dep key — the same pattern used by `ha.*` tools. `nova.query_activity` uses the `"db"` dep key, the same pattern as `devops.summarize_ci_failure`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, pydantic-settings, pytest, unittest.mock, subprocess, os

---

## File Map

| File | Change |
|------|--------|
| `services/api/app/config.py` | Add `nova_workspace_dir` field + `Field` import |
| `services/api/app/tools/handlers.py` | Add `import os, subprocess, datetime`; 4 new handler functions; 4 new `_REGISTRY` entries |
| `services/api/app/tools/seed.py` | Add 4 tool definitions to `tool_definitions` list in `seed_tools()` |
| `services/api/tests/test_tool_handlers.py` | Add tests for all 4 handlers + dispatch smoke tests |

No new files. No new tables. No new routers.

---

## Task 1: Config — `nova_workspace_dir`

**Files:**
- Modify: `services/api/app/config.py`

Context: `Settings` currently has no `nova_workspace_dir` field. We need to add it so handlers can access `cfg.nova_workspace_dir`. The existing fields use bare default values (no `Field()`). We follow the spec's explicit `Field()` form to document the env var name.

- [ ] **Step 1: Write the failing test**

Add to `services/api/tests/test_tool_handlers.py`:

```python
def test_settings_has_nova_workspace_dir():
    from app.config import settings
    # Field exists and defaults to "~" when NOVA_WORKSPACE_DIR is not set
    assert hasattr(settings, "nova_workspace_dir")
    assert settings.nova_workspace_dir == "~"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/api && python -m pytest tests/test_tool_handlers.py::test_settings_has_nova_workspace_dir -v
```

Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'nova_workspace_dir'`

- [ ] **Step 3: Add the field to Settings**

In `services/api/app/config.py`, add the `Field` import and the new field:

```python
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    deployment_mode: str = "local"
    service_name: str = "nova-api"
    version: str = "0.1.0"
    ollama_base_url: str = ""
    ollama_model: str = "gemma3:4b"
    ha_base_url: str = ""
    ha_token: str = ""
    nova_workspace_dir: str = Field(default="~", env="NOVA_WORKSPACE_DIR")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd services/api && python -m pytest tests/test_tool_handlers.py::test_settings_has_nova_workspace_dir -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite to check nothing broke**

```bash
cd services/api && python -m pytest -v
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add services/api/app/config.py services/api/tests/test_tool_handlers.py
git commit -m "feat(tools): add nova_workspace_dir config field"
```

---

## Task 2: `shell.run` handler

**Files:**
- Modify: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/tests/test_tool_handlers.py`

Context: The handler runs `["sh", "-c", command]` via `subprocess.run`. `TimeoutExpired` is caught and returned as `timed_out: true` (not raised). stdout and stderr are capped at 4096 chars each. A `# sandbox boundary` comment marks where Docker exec would go. The handler is registered with `["settings"]` as the dep.

- [ ] **Step 1: Write the failing tests**

Add to `services/api/tests/test_tool_handlers.py`:

```python
def test_shell_run_happy_path():
    from app.tools.handlers import handle_shell_run
    from unittest.mock import patch, MagicMock
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = "/tmp"
    mock_proc = MagicMock()
    mock_proc.stdout = "hello\n"
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("app.tools.handlers.subprocess.run", return_value=mock_proc):
        result = handle_shell_run({"command": "echo hello"}, mock_cfg)
    assert result == {"exit_code": 0, "stdout": "hello\n", "stderr": "", "timed_out": False}


def test_shell_run_nonzero_exit():
    from app.tools.handlers import handle_shell_run
    from unittest.mock import patch, MagicMock
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = "/tmp"
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = "command not found"
    mock_proc.returncode = 127
    with patch("app.tools.handlers.subprocess.run", return_value=mock_proc):
        result = handle_shell_run({"command": "badcommand"}, mock_cfg)
    assert result["exit_code"] == 127
    assert result["timed_out"] is False


def test_shell_run_timeout():
    import subprocess as _subprocess
    from app.tools.handlers import handle_shell_run
    from unittest.mock import patch, MagicMock
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = "/tmp"
    with patch(
        "app.tools.handlers.subprocess.run",
        side_effect=_subprocess.TimeoutExpired("cmd", 1),
    ):
        result = handle_shell_run({"command": "sleep 100", "timeout_seconds": 1}, mock_cfg)
    assert result["timed_out"] is True
    assert result["exit_code"] == -1
    assert result["stderr"] == "Command timed out."


def test_shell_run_custom_cwd():
    from app.tools.handlers import handle_shell_run
    from unittest.mock import patch, MagicMock
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = "/tmp"
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("app.tools.handlers.subprocess.run", return_value=mock_proc) as mock_run:
        handle_shell_run({"command": "ls", "cwd": "/var"}, mock_cfg)
    assert mock_run.call_args.kwargs["cwd"] == "/var"


def test_shell_run_truncates_stdout():
    from app.tools.handlers import handle_shell_run
    from unittest.mock import patch, MagicMock
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = "/tmp"
    mock_proc = MagicMock()
    mock_proc.stdout = "x" * 6000
    mock_proc.stderr = "e" * 6000
    mock_proc.returncode = 0
    with patch("app.tools.handlers.subprocess.run", return_value=mock_proc):
        result = handle_shell_run({"command": "cat bigfile"}, mock_cfg)
    assert len(result["stdout"]) == 4096
    assert len(result["stderr"]) == 4096


def test_dispatch_shell_run():
    """Smoke test: dispatch routes shell.run to correct handler."""
    from app.tools.handlers import dispatch
    from unittest.mock import patch, MagicMock
    mock_proc = MagicMock()
    mock_proc.stdout = "hi"
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("app.tools.handlers.subprocess.run", return_value=mock_proc):
        result = dispatch("shell.run", {"command": "echo hi"}, None, None)
    assert result["exit_code"] == 0
    assert result["stdout"] == "hi"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/api && python -m pytest tests/test_tool_handlers.py -k "shell_run" -v
```

Expected: FAIL — `ImportError: cannot import name 'handle_shell_run'`

- [ ] **Step 3: Add `import os, subprocess` and the handler to handlers.py**

At the top of `services/api/app/tools/handlers.py`, add to the existing imports:

```python
import os
import subprocess
```

Then add the handler function after `handle_http_request` and before `handle_devops_summarize_ci_failure`:

```python
def handle_shell_run(input: dict, cfg=None) -> dict:
    """Runs an arbitrary shell command and returns its output.

    input: {"command": str, "cwd"?: str, "timeout_seconds"?: int}
    Returns {"exit_code": int, "stdout": str, "stderr": str, "timed_out": bool}.
    stdout and stderr are each capped at 4096 chars.
    """
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

Add to `_REGISTRY`:

```python
"shell.run": (handle_shell_run, ["settings"]),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/api && python -m pytest tests/test_tool_handlers.py -k "shell_run" -v
```

Expected: all 6 shell.run tests PASS

- [ ] **Step 5: Add seed definition**

In `services/api/app/tools/seed.py`, add to the `tool_definitions` list in `seed_tools()`:

```python
dict(
    name="shell.run",
    display_name="Shell: Run Command",
    description=(
        "Runs an arbitrary shell command and returns its output. "
        "Uses NOVA_WORKSPACE_DIR as the default working directory."
    ),
    adapter_type="internal",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 30},
        },
        "required": ["command"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "exit_code": {"type": "integer"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "timed_out": {"type": "boolean"},
        },
    },
    risk_class="high",
    requires_approval=False,
    timeout_seconds=35,
    enabled=True,
    tags=["shell", "system"],
),
```

- [ ] **Step 6: Run full test suite**

```bash
cd services/api && python -m pytest -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add services/api/app/tools/handlers.py services/api/app/tools/seed.py services/api/tests/test_tool_handlers.py
git commit -m "feat(tools): add shell.run handler, registry entry, and seed definition"
```

---

## Task 3: `fs.list` and `fs.read` handlers

**Files:**
- Modify: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/tests/test_tool_handlers.py`

Context: Both handlers resolve relative paths against `NOVA_WORKSPACE_DIR`. `fs.list` uses `os.scandir`, returns entries sorted dirs-first then files alphabetical, optionally filters dotfiles. `fs.read` reads up to `max_bytes` bytes with UTF-8 + `errors="replace"` fallback. Both raise (not return) on missing paths. Both registered with `["settings"]`.

Note on `fs.list` directory `size_bytes`: `os.scandir` entry stat returns the raw `st_size` for directories. This is platform-dependent (typically 4096 on Linux). Return the raw value — don't special-case it.

- [ ] **Step 1: Write the failing tests**

Add to `services/api/tests/test_tool_handlers.py`:

```python
# --- fs.list ---

def test_fs_list_entries_dirs_first(tmp_path):
    from app.tools.handlers import handle_fs_list
    from unittest.mock import MagicMock
    (tmp_path / "subdir").mkdir()
    (tmp_path / "aaa.txt").write_text("hi")
    (tmp_path / "zzz.txt").write_text("bye")
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    result = handle_fs_list({}, mock_cfg)
    assert result["entries"][0]["type"] == "dir"
    assert result["entries"][0]["name"] == "subdir"
    file_names = [e["name"] for e in result["entries"] if e["type"] == "file"]
    assert file_names == sorted(file_names)


def test_fs_list_hides_dotfiles_by_default(tmp_path):
    from app.tools.handlers import handle_fs_list
    from unittest.mock import MagicMock
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "visible.txt").write_text("y")
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    result = handle_fs_list({}, mock_cfg)
    names = [e["name"] for e in result["entries"]]
    assert ".hidden" not in names
    assert "visible.txt" in names


def test_fs_list_shows_dotfiles_when_requested(tmp_path):
    from app.tools.handlers import handle_fs_list
    from unittest.mock import MagicMock
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "visible.txt").write_text("y")
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    result = handle_fs_list({"show_hidden": True}, mock_cfg)
    names = [e["name"] for e in result["entries"]]
    assert ".hidden" in names


def test_fs_list_raises_on_missing_path(tmp_path):
    from app.tools.handlers import handle_fs_list
    from unittest.mock import MagicMock
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    with pytest.raises(ValueError):
        handle_fs_list({"path": "does_not_exist"}, mock_cfg)


# --- fs.read ---

def test_fs_read_returns_content(tmp_path):
    from app.tools.handlers import handle_fs_read
    from unittest.mock import MagicMock
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    result = handle_fs_read({"path": "hello.txt"}, mock_cfg)
    assert result["content"] == "hello world"
    assert result["truncated"] is False
    assert result["size_bytes"] == len(b"hello world")


def test_fs_read_truncates_large_file(tmp_path):
    from app.tools.handlers import handle_fs_read
    from unittest.mock import MagicMock
    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * 10000)
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    result = handle_fs_read({"path": "big.txt", "max_bytes": 8192}, mock_cfg)
    assert result["truncated"] is True
    assert len(result["content"]) == 8192


def test_fs_read_resolves_relative_path(tmp_path):
    from app.tools.handlers import handle_fs_read
    from unittest.mock import MagicMock
    f = tmp_path / "notes.txt"
    f.write_text("note content")
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    result = handle_fs_read({"path": "notes.txt"}, mock_cfg)
    assert result["path"] == str(tmp_path / "notes.txt")
    assert result["content"] == "note content"


def test_fs_read_raises_on_missing_file(tmp_path):
    from app.tools.handlers import handle_fs_read
    from unittest.mock import MagicMock
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    with pytest.raises(FileNotFoundError):
        handle_fs_read({"path": "ghost.txt"}, mock_cfg)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/api && python -m pytest tests/test_tool_handlers.py -k "fs_list or fs_read" -v
```

Expected: FAIL — `ImportError: cannot import name 'handle_fs_list'`

- [ ] **Step 3: Add `import datetime` and the two handlers to handlers.py**

At the top of `services/api/app/tools/handlers.py`, add to the existing imports:

```python
import datetime
```

Then add both handlers after `handle_shell_run`:

```python
def handle_fs_list(input: dict, cfg=None) -> dict:
    """Lists the contents of a directory.

    input: {"path"?: str (default "."), "show_hidden"?: bool (default false)}
    Resolves relative paths against NOVA_WORKSPACE_DIR.
    Returns {"path": str, "entries": list} — dirs first (alpha), then files (alpha).
    Raises ValueError if path does not exist or is not a directory.
    """
    cfg = cfg or _settings
    workspace = os.path.expanduser(cfg.nova_workspace_dir)
    path = input.get("path", ".")
    show_hidden = input.get("show_hidden", False)

    resolved = path if os.path.isabs(path) else os.path.join(workspace, path)

    if not os.path.exists(resolved):
        raise ValueError(f"Path does not exist: {resolved}")
    if not os.path.isdir(resolved):
        raise ValueError(f"Path is not a directory: {resolved}")

    entries = []
    for entry in os.scandir(resolved):
        if not show_hidden and entry.name.startswith("."):
            continue
        stat = entry.stat()
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat()
        entries.append({
            "name": entry.name,
            "type": "dir" if entry.is_dir() else "file",
            "size_bytes": stat.st_size,
            "modified": mtime,
        })

    dirs = sorted([e for e in entries if e["type"] == "dir"], key=lambda e: e["name"])
    files = sorted([e for e in entries if e["type"] == "file"], key=lambda e: e["name"])
    return {"path": resolved, "entries": dirs + files}


def handle_fs_read(input: dict, cfg=None) -> dict:
    """Reads the contents of a file.

    input: {"path": str, "max_bytes"?: int (default 8192)}
    Resolves relative paths against NOVA_WORKSPACE_DIR.
    Returns {"path": str, "content": str, "truncated": bool, "size_bytes": int}.
    Raises FileNotFoundError if path does not exist.
    """
    cfg = cfg or _settings
    workspace = os.path.expanduser(cfg.nova_workspace_dir)
    path = input["path"]
    max_bytes = input.get("max_bytes", 8192)

    resolved = path if os.path.isabs(path) else os.path.join(workspace, path)

    if not os.path.exists(resolved):
        raise FileNotFoundError(f"File not found: {resolved}")

    size = os.path.getsize(resolved)
    with open(resolved, "rb") as f:
        raw = f.read(max_bytes)

    content = raw.decode("utf-8", errors="replace")
    return {"path": resolved, "content": content, "truncated": size > max_bytes, "size_bytes": size}
```

Add to `_REGISTRY`:

```python
"fs.list": (handle_fs_list, ["settings"]),
"fs.read": (handle_fs_read, ["settings"]),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/api && python -m pytest tests/test_tool_handlers.py -k "fs_list or fs_read" -v
```

Expected: all 8 fs tests PASS

- [ ] **Step 5: Add seed definitions**

In `services/api/app/tools/seed.py`, add to the `tool_definitions` list:

```python
dict(
    name="fs.list",
    display_name="FS: List Directory",
    description=(
        "Lists the contents of a directory. Resolves relative paths against "
        "NOVA_WORKSPACE_DIR. Returns entries sorted: directories first (alphabetical), "
        "then files (alphabetical)."
    ),
    adapter_type="internal",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
            "show_hidden": {"type": "boolean", "default": False},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "entries": {"type": "array", "items": {"type": "object"}},
        },
    },
    risk_class="low",
    requires_approval=False,
    timeout_seconds=10,
    enabled=True,
    tags=["filesystem"],
),
dict(
    name="fs.read",
    display_name="FS: Read File",
    description=(
        "Reads the contents of a file. Resolves relative paths against "
        "NOVA_WORKSPACE_DIR. Returns up to max_bytes (default 8192) bytes decoded as UTF-8."
    ),
    adapter_type="internal",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_bytes": {"type": "integer", "default": 8192},
        },
        "required": ["path"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "truncated": {"type": "boolean"},
            "size_bytes": {"type": "integer"},
        },
    },
    risk_class="low",
    requires_approval=False,
    timeout_seconds=10,
    enabled=True,
    tags=["filesystem"],
),
```

- [ ] **Step 6: Run full test suite**

```bash
cd services/api && python -m pytest -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add services/api/app/tools/handlers.py services/api/app/tools/seed.py services/api/tests/test_tool_handlers.py
git commit -m "feat(tools): add fs.list and fs.read handlers, registry entries, and seed definitions"
```

---

## Task 4: `nova.query_activity` handler

**Files:**
- Modify: `services/api/app/tools/handlers.py`
- Modify: `services/api/app/tools/seed.py`
- Modify: `services/api/tests/test_tool_handlers.py`

Context: Queries the `Run` table using the `db` SQLAlchemy session. `total` is the count of all matching rows BEFORE the limit is applied (requires a separate `.count()` call before `.limit()`). Uses the `"db"` dep key — same pattern as `devops.summarize_ci_failure`. The `Run` model is at `app.models.run`.

- [ ] **Step 1: Write the failing tests**

Add to `services/api/tests/test_tool_handlers.py`:

```python
# --- nova.query_activity ---

def test_query_activity_returns_runs(db_session):
    from app.tools.handlers import handle_nova_query_activity
    from app.models.run import Run
    from datetime import datetime, timezone
    run = Run(
        tool_name="debug.echo",
        status="succeeded",
        trigger_type="chat",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.commit()
    result = handle_nova_query_activity({}, db_session)
    assert result["total"] == 1
    assert result["runs"][0]["tool_name"] == "debug.echo"
    assert result["runs"][0]["status"] == "succeeded"


def test_query_activity_since_hours_excludes_old_runs(db_session):
    from app.tools.handlers import handle_nova_query_activity
    from app.models.run import Run
    from datetime import datetime, timezone, timedelta
    recent = Run(
        tool_name="debug.echo",
        status="succeeded",
        trigger_type="chat",
        started_at=datetime.now(timezone.utc),
    )
    old = Run(
        tool_name="debug.echo",
        status="succeeded",
        trigger_type="chat",
        started_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    db_session.add_all([recent, old])
    db_session.commit()
    result = handle_nova_query_activity({"since_hours": 1}, db_session)
    assert result["total"] == 1


def test_query_activity_status_filter(db_session):
    from app.tools.handlers import handle_nova_query_activity
    from app.models.run import Run
    from datetime import datetime, timezone
    db_session.add_all([
        Run(tool_name="debug.echo", status="failed", trigger_type="chat",
            started_at=datetime.now(timezone.utc)),
        Run(tool_name="debug.echo", status="succeeded", trigger_type="chat",
            started_at=datetime.now(timezone.utc)),
    ])
    db_session.commit()
    result = handle_nova_query_activity({"status": "failed"}, db_session)
    assert result["total"] == 1
    assert result["runs"][0]["status"] == "failed"


def test_query_activity_tool_name_filter(db_session):
    from app.tools.handlers import handle_nova_query_activity
    from app.models.run import Run
    from datetime import datetime, timezone
    db_session.add_all([
        Run(tool_name="shell.run", status="succeeded", trigger_type="chat",
            started_at=datetime.now(timezone.utc)),
        Run(tool_name="debug.echo", status="succeeded", trigger_type="chat",
            started_at=datetime.now(timezone.utc)),
    ])
    db_session.commit()
    result = handle_nova_query_activity({"tool_name": "shell.run"}, db_session)
    assert result["total"] == 1
    assert result["runs"][0]["tool_name"] == "shell.run"


def test_query_activity_empty_result(db_session):
    from app.tools.handlers import handle_nova_query_activity
    result = handle_nova_query_activity({"tool_name": "does.not.exist"}, db_session)
    assert result == {"runs": [], "total": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/api && python -m pytest tests/test_tool_handlers.py -k "query_activity" -v
```

Expected: FAIL — `ImportError: cannot import name 'handle_nova_query_activity'`

- [ ] **Step 3: Add the handler to handlers.py**

Add the handler after `handle_fs_read`:

```python
def handle_nova_query_activity(input: dict, db: Session) -> dict:
    """Queries Nova's own run history from the Run table.

    input: {"limit"?: int (default 10), "since_hours"?: int (default 24),
            "status"?: str|null, "tool_name"?: str|null}
    Returns {"runs": list, "total": int} where total is the count before limit is applied.
    """
    from app.models.run import Run

    limit = input.get("limit", 10)
    since_hours = input.get("since_hours", 24)
    status = input.get("status")
    tool_name = input.get("tool_name")

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=since_hours)

    query = db.query(Run).filter(Run.started_at >= since)
    if status:
        query = query.filter(Run.status == status)
    if tool_name:
        query = query.filter(Run.tool_name == tool_name)

    total = query.count()
    runs = query.order_by(Run.started_at.desc()).limit(limit).all()

    return {
        "runs": [
            {
                "id": str(r.id),
                "tool_name": r.tool_name,
                "status": r.status,
                "summary": r.summary,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ],
        "total": total,
    }
```

Add to `_REGISTRY`:

```python
"nova.query_activity": (handle_nova_query_activity, ["db"]),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/api && python -m pytest tests/test_tool_handlers.py -k "query_activity" -v
```

Expected: all 5 query_activity tests PASS

- [ ] **Step 5: Add seed definition**

In `services/api/app/tools/seed.py`, add to the `tool_definitions` list:

```python
dict(
    name="nova.query_activity",
    display_name="Nova: Query Activity",
    description=(
        "Queries Nova's own run history. Filterable by status, tool name, "
        "and time window. Returns runs ordered newest-first."
    ),
    adapter_type="internal",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 10},
            "since_hours": {"type": "integer", "default": 24},
            "status": {"type": "string", "nullable": True},
            "tool_name": {"type": "string", "nullable": True},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "runs": {"type": "array", "items": {"type": "object"}},
            "total": {"type": "integer"},
        },
    },
    risk_class="low",
    requires_approval=False,
    timeout_seconds=10,
    enabled=True,
    tags=["nova", "activity"],
),
```

- [ ] **Step 6: Update `test_get_tools_returns_seeded_tools` in `tests/test_tools.py`**

The seed now has 9 tools (was 5). That test checks the seeded tool set by name — add the 4 new names:
`"shell.run"`, `"fs.list"`, `"fs.read"`, `"nova.query_activity"`.

Open `services/api/tests/test_tools.py`, find the set/list of expected tool names, and add those four.

```bash
cd services/api && python -m pytest tests/test_tools.py -v
```

Expected: PASS

- [ ] **Step 7: Run full test suite**

```bash
cd services/api && python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add services/api/app/tools/handlers.py services/api/app/tools/seed.py services/api/tests/test_tool_handlers.py services/api/tests/test_tools.py
git commit -m "feat(tools): add nova.query_activity handler, registry entry, and seed definition"
```

---

## Final Check

```bash
cd services/api && python -m pytest -v --tb=short
```

Expected: all tests pass. The registry now has 9 entries total (5 existing + 4 new). Seed has 9 tool definitions.
