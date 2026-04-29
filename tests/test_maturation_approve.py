"""Verify approve-spec routes directly to verifying (Phase 4 building deferred)."""
import os

import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def test_approve_spec_routes_to_verifying():
    """approve-spec sets maturation_status to 'verifying', not 'building'."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-approve-spec",
            "description": "Test approve-spec routing",
            "priority": 3, "max_iterations": 5, "max_cost_usd": 0.50,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        # Force into review state. UpdateGoalRequest already accepts maturation_status.
        httpx.patch(
            f"{BASE}/goals/{gid}",
            json={"maturation_status": "review"},
            headers=HEADERS,
        )
        resp = httpx.post(f"{BASE}/goals/{gid}/approve-spec", headers=HEADERS)
        assert resp.status_code == 200
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        assert detail["maturation_status"] == "verifying", \
            f"Expected verifying (Phase 4 deferred), got {detail['maturation_status']}"
        assert detail.get("spec_approved_at"), "spec_approved_at should be set"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
