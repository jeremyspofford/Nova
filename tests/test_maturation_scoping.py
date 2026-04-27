"""Tier 2 — scoping phase produces scope_analysis."""
import os
import time

import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def test_scoping_produces_scope_analysis():
    """Goal entering scoping gets scope_analysis populated within ~60s."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-scoping",
            "description": "Add a webhook delivery service with auth, dashboard, and Redis queue",
            "priority": 5,
            "max_iterations": 10,
            "max_cost_usd": 1.00,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        httpx.patch(
            f"{BASE}/goals/{gid}",
            json={"maturation_status": "scoping"},
            headers=HEADERS,
        )
        scope: dict = {}
        for _ in range(8):
            time.sleep(15)
            scope = httpx.get(f"{BASE}/goals/{gid}/scope", headers=HEADERS).json()
            if scope:
                break
        assert scope, "scope_analysis was never populated"
        scopes_str = " ".join(str(scope.get(k, "")) for k in scope).lower()
        assert "backend" in scopes_str or "service" in scopes_str
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        assert detail.get("maturation_status") == "speccing"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
