"""Integration tests for linked accounts API."""

import os
import pytest
import httpx

BASE = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "changeme")
BRIDGE_SECRET = os.getenv("BRIDGE_SERVICE_SECRET", "")
PREFIX = "nova-test-"


def admin_headers():
    return {"X-Admin-Secret": ADMIN_SECRET}


def service_headers(user_id: str = ""):
    h = {"X-Service-Secret": BRIDGE_SECRET}
    if user_id:
        h["X-On-Behalf-Of"] = user_id
    return h


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE, timeout=10)


class TestLinkedAccounts:
    def test_list_linked_accounts(self, client):
        """GET /api/v1/linked-accounts returns a list."""
        r = client.get("/api/v1/linked-accounts", headers=admin_headers())
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_resolve_unlinked_returns_404(self, client):
        """Resolve a platform_id that isn't linked returns 404."""
        r = client.post(
            "/api/v1/linked-accounts/resolve",
            json={"platform": "telegram", "platform_id": f"{PREFIX}999999"},
            headers={"X-Service-Secret": BRIDGE_SECRET},
        )
        assert r.status_code == 404

    def test_generate_link_code(self, client):
        """Generate a link code returns a 6-char code."""
        r = client.post(
            "/api/v1/linked-accounts/link-code",
            headers=admin_headers(),
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["code"]) == 6
        assert data["ttl_seconds"] == 600

    def test_redeem_invalid_code_returns_404(self, client):
        """Redeeming an invalid code returns 404."""
        r = client.post(
            "/api/v1/linked-accounts/redeem",
            json={
                "code": "ZZZZZZ",
                "platform": "telegram",
                "platform_id": f"{PREFIX}888888",
            },
            headers={"X-Service-Secret": BRIDGE_SECRET},
        )
        assert r.status_code == 404

    def test_invalid_service_secret_returns_403(self, client):
        """Invalid service secret is rejected."""
        r = client.post(
            "/api/v1/linked-accounts/resolve",
            json={"platform": "telegram", "platform_id": "123"},
            headers={"X-Service-Secret": "wrong-secret"},
        )
        assert r.status_code == 403
