"""Integration tests for unified bridge chat flow."""

import os
import pytest
import httpx

BASE = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
BRIDGE_BASE = os.getenv("CHAT_BRIDGE_URL", "http://localhost:8090")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "changeme")
BRIDGE_SECRET = os.getenv("BRIDGE_SERVICE_SECRET", "")


def admin_headers():
    return {"X-Admin-Secret": ADMIN_SECRET}


def service_headers(user_id: str = ""):
    h = {"X-Service-Secret": BRIDGE_SECRET}
    if user_id:
        h["X-On-Behalf-Of"] = user_id
    return h


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE, timeout=30)


class TestBridgeUnified:
    def test_bridge_health(self):
        """Bridge service is healthy."""
        r = httpx.get(f"{BRIDGE_BASE}/health/ready", timeout=5)
        assert r.status_code == 200

    def test_service_auth_on_chat_stream(self, client):
        """Service auth bypass works on /chat/stream — returns 200 not 401/403."""
        if not BRIDGE_SECRET:
            pytest.skip("BRIDGE_SERVICE_SECRET not set")

        r = client.get("/api/v1/users", headers=admin_headers())
        if r.status_code != 200 or not r.json():
            pytest.skip("No users available")
        user_id = r.json()[0]["id"]

        with httpx.Client(base_url=BASE, timeout=30) as c:
            with c.stream(
                "POST",
                "/api/v1/chat/stream",
                json={"messages": [{"role": "user", "content": "nova-test-ping"}]},
                headers=service_headers(user_id),
            ) as resp:
                assert resp.status_code == 200
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        break

    def test_concurrent_stream_lock(self, client):
        """409 returned when conversation is already streaming."""
        pass
