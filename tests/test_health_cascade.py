"""
OPS-001: health-rollup cascade regression test.

If an informational sub-check on llm-gateway (e.g. Ollama probe) is slow,
chat-api's /health/ready should still return "ready". Downstream probes
in rollups must call /health/live (self-only), not /health/ready (cascading).
"""

from __future__ import annotations

import httpx
import pytest


CHAT_API = "http://localhost:8080"
ORCHESTRATOR = "http://localhost:8000"
REDIS_HOST = "localhost"
REDIS_PORT = 6379


@pytest.fixture
def save_restore_ollama_url(redis_db1):
    """Save current Ollama URL, set unreachable URL for test, restore after."""
    original = redis_db1.get("nova:config:llm.ollama_url")
    # TEST-NET-1 (192.0.2.0/24) is reserved for documentation / blackholes —
    # packets to it are silently dropped, giving a slow timeout (not fast refuse).
    redis_db1.set("nova:config:llm.ollama_url", "http://192.0.2.1:11434")
    yield
    if original is not None:
        redis_db1.set("nova:config:llm.ollama_url", original)
    else:
        redis_db1.delete("nova:config:llm.ollama_url")


def test_chat_api_ready_when_ollama_unreachable(save_restore_ollama_url):
    """chat-api /health/ready must stay 'ready' when Ollama is unreachable."""
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{CHAT_API}/health/ready")
    assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
    body = resp.json()
    assert body.get("status") == "ready", (
        f"Expected status=ready, got {body.get('status')}. Full body: {body}"
    )


def test_orchestrator_ready_when_ollama_unreachable(save_restore_ollama_url):
    """orchestrator /health/ready must stay 'ready' when Ollama is unreachable."""
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{ORCHESTRATOR}/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ready", (
        f"Expected status=ready, got {body.get('status')}. Full body: {body}"
    )
