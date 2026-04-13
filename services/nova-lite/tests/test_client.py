import httpx
import pytest
from app.client import NovaClient, NovaClientError


class _OkTransport(httpx.BaseTransport):
    """Returns a fixed 200 JSON response."""
    def __init__(self, body: dict):
        self._body = body

    def handle_request(self, request):
        return httpx.Response(200, json=self._body)


class _ErrorTransport(httpx.BaseTransport):
    """Returns a fixed error response."""
    def __init__(self, status: int, text: str = "error"):
        self._status = status
        self._text = text

    def handle_request(self, request):
        return httpx.Response(self._status, text=self._text)


def test_raises_nova_client_error_on_non_2xx():
    client = NovaClient("http://test:8000", transport=_ErrorTransport(404, "Not Found"))
    with pytest.raises(NovaClientError) as exc:
        client.get_events(since="2026-01-01T00:00:00Z")
    assert exc.value.status_code == 404
    assert "Not Found" in str(exc.value)


def test_get_events_deserializes_list():
    events = [{"id": "e1", "type": "test", "timestamp": "2026-01-01T00:00:00Z"}]
    client = NovaClient("http://test:8000", transport=_OkTransport({"events": events}))
    result = client.get_events(since="2026-01-01T00:00:00Z")
    assert result == events


def test_get_tasks_deserializes_list():
    tasks = [{"id": "t1", "title": "Do thing", "status": "inbox"}]
    client = NovaClient("http://test:8000", transport=_OkTransport({"tasks": tasks}))
    result = client.get_tasks(status="inbox")
    assert result == tasks


def test_llm_route_returns_output_string():
    body = {"provider_id": "ollama-local", "model_ref": "gemma3:4b", "output": "hello"}
    client = NovaClient("http://test:8000", transport=_OkTransport(body))
    result = client.llm_route(
        purpose="triage", messages=[{"role": "user", "content": "hi"}]
    )
    assert result == "hello"


def test_client_closes_cleanly():
    client = NovaClient("http://test:8000", transport=_OkTransport({"events": []}))
    client.close()  # Should not raise
