"""Tier 4 — verifying phase runs health checks, transitions to completed."""
import os
import time

import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def test_verifying_completes_goal_when_services_healthy():
    """Goal in verifying transitions to status='completed' once health checks pass."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-verifying",
            "description": "Test verifying phase",
            "priority": 3, "max_iterations": 5, "max_cost_usd": 0.50,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        httpx.patch(
            f"{BASE}/goals/{gid}",
            json={"maturation_status": "verifying"},
            headers=HEADERS,
        )
        # Wait for cortex cycle
        detail = None
        for _ in range(6):
            time.sleep(15)
            detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
            if detail.get("status") == "completed":
                break
        assert detail is not None, "Goal lookup failed"
        assert detail.get("status") == "completed", \
            f"Goal should be completed after verifying, got status={detail.get('status')}"
        assert detail.get("maturation_status") is None, \
            "maturation_status should be cleared after completion"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
