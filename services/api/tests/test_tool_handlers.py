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
