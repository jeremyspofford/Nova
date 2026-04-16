"""
Tool handler implementations for Phase 2 tools.

Each handler takes (input: dict, *deps) and returns a dict output.
The dispatch() function routes by tool name.
"""
import datetime
import os
import subprocess
import httpx
from sqlalchemy.orm import Session
from app import llm_client
from app.config import settings as _settings


def handle_debug_echo(input: dict) -> dict:
    """Returns its input unchanged. Used for testing the invocation loop."""
    return {"echo": input}


def handle_ha_light_turn_on(input: dict, cfg=None) -> dict:
    """Calls the Home Assistant light.turn_on service.

    input: {"entity_id": "light.xyz", "brightness": 0-255 (optional)}
    Raises RuntimeError if HA_BASE_URL or HA_TOKEN are not configured.
    """
    cfg = cfg or _settings
    if not cfg.ha_base_url or not cfg.ha_token:
        raise RuntimeError(
            "HA not configured: set HA_BASE_URL and HA_TOKEN environment variables"
        )
    payload: dict = {"entity_id": input["entity_id"]}
    if "brightness" in input:
        payload["brightness"] = input["brightness"]
    resp = httpx.post(
        f"{cfg.ha_base_url}/api/services/light/turn_on",
        headers={"Authorization": f"Bearer {cfg.ha_token}"},
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return {"status": "ok", "entity_id": input["entity_id"]}


def handle_ha_light_turn_off(input: dict, cfg=None) -> dict:
    """Calls the Home Assistant light.turn_off service.

    input: {"entity_id": "light.xyz"}
    Raises RuntimeError if HA_BASE_URL or HA_TOKEN are not configured.
    """
    cfg = cfg or _settings
    if not cfg.ha_base_url or not cfg.ha_token:
        raise RuntimeError(
            "HA not configured: set HA_BASE_URL and HA_TOKEN environment variables"
        )
    resp = httpx.post(
        f"{cfg.ha_base_url}/api/services/light/turn_off",
        headers={"Authorization": f"Bearer {cfg.ha_token}"},
        json={"entity_id": input["entity_id"]},
        timeout=10,
    )
    resp.raise_for_status()
    return {"status": "ok", "entity_id": input["entity_id"]}


def handle_http_request(input: dict, db=None, cfg=None) -> dict:
    """Makes an HTTP GET or POST request.

    input: {"method": "GET"|"POST", "url": "...", "headers"?: {...},
            "body"?: {...}, "timeout_seconds"?: 30}
    Returns {"status_code": int, "body": str} — body truncated to 2048 chars.
    """
    method = input["method"].upper()
    url = input["url"]
    headers = input.get("headers", {})
    body = input.get("body")
    timeout = input.get("timeout_seconds", 30)
    resp = httpx.request(method, url, headers=headers, json=body, timeout=timeout)
    return {"status_code": resp.status_code, "body": resp.text[:2048]}


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

    workspace_real = os.path.realpath(workspace)
    resolved = os.path.realpath(
        path if os.path.isabs(path) else os.path.join(workspace, path)
    )
    if not resolved.startswith(workspace_real + os.sep) and resolved != workspace_real:
        raise ValueError(f"Path escapes workspace: {path}")

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

    workspace_real = os.path.realpath(workspace)
    resolved = os.path.realpath(
        path if os.path.isabs(path) else os.path.join(workspace, path)
    )
    if not resolved.startswith(workspace_real + os.sep) and resolved != workspace_real:
        raise ValueError(f"Path escapes workspace: {path}")

    if not os.path.exists(resolved):
        raise FileNotFoundError(f"File not found: {resolved}")
    if os.path.isdir(resolved):
        raise ValueError(f"Path is a directory, not a file: {resolved}")

    size = os.path.getsize(resolved)
    with open(resolved, "rb") as f:
        raw = f.read(max_bytes)

    content = raw.decode("utf-8", errors="replace")
    return {"path": resolved, "content": content, "truncated": size > max_bytes, "size_bytes": size}


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

    # Use naive UTC to avoid SQLite timezone comparison issues (production uses PostgreSQL)
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=since_hours)

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


def handle_devops_summarize_ci_failure(input: dict, db: Session) -> dict:
    """Uses the LLM (via route_internal) to summarize a CI failure.

    input: {"url": "https://...", "log_snippet": "..."}
    """
    prompt = (
        f"Summarize this CI failure concisely (2-3 sentences):\n"
        f"URL: {input['url']}\n\n"
        f"Log:\n{input['log_snippet']}"
    )
    summary = llm_client.route_internal(
        db,
        purpose="summarize",
        messages=[{"role": "user", "content": prompt}],
    )
    return {"summary": summary}


# Registry: tool name → (handler callable, extra_deps: list["db"|"settings"])
_REGISTRY: dict[str, tuple] = {
    "debug.echo": (handle_debug_echo, []),
    "ha.light.turn_on": (handle_ha_light_turn_on, ["settings"]),
    "ha.light.turn_off": (handle_ha_light_turn_off, ["settings"]),
    "http.request": (handle_http_request, []),
    "devops.summarize_ci_failure": (handle_devops_summarize_ci_failure, ["db"]),
    "nova.query_activity": (handle_nova_query_activity, ["db"]),
    "shell.run": (handle_shell_run, ["settings"]),
    "fs.list": (handle_fs_list, ["settings"]),
    "fs.read": (handle_fs_read, ["settings"]),
}


def dispatch(tool_name: str, input: dict, db: Session, cfg=None) -> dict:
    """Dispatch to the correct handler by tool name.

    Raises KeyError if tool_name is not in the registry.
    """
    handler_fn, deps = _REGISTRY[tool_name]
    args = []
    for dep in deps:
        if dep == "db":
            args.append(db)
        elif dep == "settings":
            args.append(cfg or _settings)
    return handler_fn(input, *args)
