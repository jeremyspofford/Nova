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
