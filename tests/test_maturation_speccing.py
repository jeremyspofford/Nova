"""Tier 3 — speccing phase produces spec."""
import os
import time

import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def test_speccing_produces_spec_and_transitions_to_review():
    """Goal in speccing phase gets spec populated and transitions to review within ~90s."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-speccing",
            "description": "Add webhook delivery service with auth and dashboard",
            "priority": 5,
            "max_iterations": 10,
            "max_cost_usd": 1.00,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        scope_seed = {
            "affected_scopes": ["backend", "frontend", "security"],
            "estimated_files_changed": 6,
            "summary": "Adds a webhook service touching auth and dashboard.",
        }
        httpx.patch(
            f"{BASE}/goals/{gid}",
            json={"maturation_status": "speccing", "scope_analysis": scope_seed},
            headers=HEADERS,
        )
        detail: dict = {}
        for _ in range(8):
            time.sleep(15)
            detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
            if detail.get("spec"):
                break
        assert detail.get("spec"), "spec was never populated"
        assert len(detail["spec"]) > 100, "spec too short to be a real spec"
        assert detail.get("maturation_status") == "review"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
