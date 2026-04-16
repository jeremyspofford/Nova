import pytest
from unittest.mock import MagicMock, patch


def test_echo_returns_input():
    from app.tools.handlers import handle_debug_echo
    result = handle_debug_echo({"hello": "world"})
    assert result == {"echo": {"hello": "world"}}


def test_echo_with_empty_input():
    from app.tools.handlers import handle_debug_echo
    result = handle_debug_echo({})
    assert result == {"echo": {}}


def test_ha_light_turn_on_raises_when_not_configured(monkeypatch):
    from app.tools import handlers
    from app.config import settings
    # Ensure HA is not configured
    monkeypatch.setattr(settings, "ha_base_url", "")
    with pytest.raises(RuntimeError, match="HA not configured"):
        handlers.handle_ha_light_turn_on({"entity_id": "light.test"}, settings)


def test_ha_light_turn_on_calls_ha_api(monkeypatch):
    """Test HA tool makes the correct HTTP call."""
    from app.tools import handlers
    from app.config import settings
    import httpx

    monkeypatch.setattr(settings, "ha_base_url", "http://fake-ha:8123")
    monkeypatch.setattr(settings, "ha_token", "fake-token")

    # Mock httpx.post
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("app.tools.handlers.httpx.post", return_value=mock_response) as mock_post:
        result = handlers.handle_ha_light_turn_on(
            {"entity_id": "light.living_room", "brightness": 200}, settings
        )

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "light.living_room" in str(call_kwargs)
    assert result == {"status": "ok", "entity_id": "light.living_room"}


def test_summarize_ci_failure_calls_llm(db_session):
    from app.tools.handlers import handle_devops_summarize_ci_failure
    from unittest.mock import patch

    with patch("app.llm_client.route_internal", return_value="The build failed due to a timeout."):
        result = handle_devops_summarize_ci_failure(
            {"url": "https://ci.example.com/build/123", "log_snippet": "Error: timeout"},
            db_session,
        )
    assert result == {"summary": "The build failed due to a timeout."}


def test_dispatch_unknown_tool_raises():
    from app.tools.handlers import dispatch
    with pytest.raises(KeyError):
        dispatch("nonexistent.tool", {}, None, None)


def test_ha_light_turn_off_raises_when_not_configured(monkeypatch):
    from app.tools import handlers
    from app.config import settings
    monkeypatch.setattr(settings, "ha_base_url", "")
    with pytest.raises(RuntimeError, match="HA not configured"):
        handlers.handle_ha_light_turn_off({"entity_id": "light.test"}, settings)


def test_ha_light_turn_off_calls_ha_api(monkeypatch):
    from app.tools import handlers
    from app.config import settings
    monkeypatch.setattr(settings, "ha_base_url", "http://fake-ha:8123")
    monkeypatch.setattr(settings, "ha_token", "fake-token")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    with patch("app.tools.handlers.httpx.post", return_value=mock_response):
        result = handlers.handle_ha_light_turn_off({"entity_id": "light.office"}, settings)
    assert result == {"status": "ok", "entity_id": "light.office"}


def test_http_request_get_success():
    from app.tools.handlers import handle_http_request
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "Hello World"
    with patch("app.tools.handlers.httpx.request", return_value=mock_resp):
        result = handle_http_request({"method": "GET", "url": "http://example.com"}, None, None)
    assert result == {"status_code": 200, "body": "Hello World"}


def test_http_request_truncates_large_body():
    from app.tools.handlers import handle_http_request
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "x" * 3000
    with patch("app.tools.handlers.httpx.request", return_value=mock_resp):
        result = handle_http_request({"method": "GET", "url": "http://example.com"}, None, None)
    assert len(result["body"]) == 2048


def test_http_request_post_passes_headers_and_body():
    from app.tools.handlers import handle_http_request
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.text = '{"ok": true}'
    with patch("app.tools.handlers.httpx.request", return_value=mock_resp) as mock_req:
        handle_http_request(
            {
                "method": "POST",
                "url": "http://api.example.com/items",
                "headers": {"Authorization": "Bearer tok"},
                "body": {"name": "test"},
                "timeout_seconds": 15,
            },
            None, None,
        )
    call = mock_req.call_args
    assert call.args[0] == "POST"
    assert call.kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert call.kwargs["timeout"] == 15


def test_dispatch_ha_light_turn_off(monkeypatch):
    """Smoke test: dispatch routes ha.light.turn_off to correct handler."""
    from app.tools.handlers import dispatch
    from app.config import settings
    monkeypatch.setattr(settings, "ha_base_url", "http://fake-ha:8123")
    monkeypatch.setattr(settings, "ha_token", "fake-token")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    with patch("app.tools.handlers.httpx.post", return_value=mock_response):
        result = dispatch("ha.light.turn_off", {"entity_id": "light.kitchen"}, None, settings)
    assert result == {"status": "ok", "entity_id": "light.kitchen"}


def test_dispatch_http_request():
    """Smoke test: dispatch routes http.request to correct handler."""
    from app.tools.handlers import dispatch
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    with patch("app.tools.handlers.httpx.request", return_value=mock_resp):
        result = dispatch("http.request", {"method": "GET", "url": "http://example.com"}, None, None)
    assert result == {"status_code": 200, "body": "ok"}


def test_settings_has_nova_workspace_dir():
    from app.config import settings
    # Field exists and defaults to "~" when NOVA_WORKSPACE_DIR is not set
    assert hasattr(settings, "nova_workspace_dir")
    assert settings.nova_workspace_dir == "~"


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


def test_shell_run_rejects_cwd_outside_workspace():
    from app.tools.handlers import handle_shell_run
    from unittest.mock import MagicMock
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = "/tmp"
    with pytest.raises(ValueError, match="escapes workspace"):
        handle_shell_run({"command": "ls", "cwd": "/etc"}, mock_cfg)


def test_shell_run_custom_cwd(tmp_path):
    from app.tools.handlers import handle_shell_run
    from unittest.mock import patch, MagicMock
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    with patch("app.tools.handlers.subprocess.run", return_value=mock_proc) as mock_run:
        handle_shell_run({"command": "ls", "cwd": str(subdir)}, mock_cfg)
    assert mock_run.call_args.kwargs["cwd"] == str(subdir)


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


def test_fs_list_rejects_path_outside_workspace(tmp_path):
    from app.tools.handlers import handle_fs_list
    from unittest.mock import MagicMock
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(workspace)
    with pytest.raises(ValueError, match="escapes workspace"):
        handle_fs_list({"path": "/etc"}, mock_cfg)


def test_fs_list_rejects_dotdot_traversal(tmp_path):
    from app.tools.handlers import handle_fs_list
    from unittest.mock import MagicMock
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(workspace)
    with pytest.raises(ValueError):
        handle_fs_list({"path": "../outside"}, mock_cfg)


def test_fs_read_rejects_path_outside_workspace(tmp_path):
    from app.tools.handlers import handle_fs_read
    from unittest.mock import MagicMock
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(workspace)
    with pytest.raises(ValueError, match="escapes workspace"):
        handle_fs_read({"path": "/etc/passwd"}, mock_cfg)


def test_fs_read_raises_on_directory(tmp_path):
    from app.tools.handlers import handle_fs_read
    from unittest.mock import MagicMock
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    mock_cfg = MagicMock()
    mock_cfg.nova_workspace_dir = str(tmp_path)
    with pytest.raises(ValueError, match="directory"):
        handle_fs_read({"path": "subdir"}, mock_cfg)


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
