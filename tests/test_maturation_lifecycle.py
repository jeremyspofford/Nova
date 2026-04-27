"""End-to-end goal maturation lifecycle: create → triage → scope → spec → review → verify → complete.

Skips Phase 4 (building) — handled separately when goal decomposition lands.
"""
import os
import time

import httpx
import pytest

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": os.environ.get("NOVA_ADMIN_SECRET", "")}


def _wait_for_status(gid: str, predicate, timeout: int = 180) -> dict:
    """Poll goal until predicate(detail) is true or timeout."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        if predicate(last):
            return last
        time.sleep(15)
    raise AssertionError(
        f"Timed out waiting for goal {gid}; last state: maturation_status="
        f"{last.get('maturation_status')}, status={last.get('status')}"
    )


@pytest.mark.slow
def test_full_maturation_lifecycle():
    """A complex goal flows triaging → scoping → speccing → review → verifying → complete."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-lifecycle",
            "description": (
                "Build a webhook delivery microservice with auth, dashboard page, "
                "Redis queue, postgres storage, retry policy, and security review."
            ),
            "priority": 5,
            "max_iterations": 10,
            "max_cost_usd": 2.00,
        },
        headers=HEADERS,
    )
    gid = resp.json()["id"]
    try:
        d = _wait_for_status(gid, lambda x: x.get("maturation_status") in ("scoping", "speccing", "review"))
        assert d.get("maturation_status") in ("scoping", "speccing", "review")

        d = _wait_for_status(gid, lambda x: x.get("maturation_status") in ("speccing", "review"))
        scope = httpx.get(f"{BASE}/goals/{gid}/scope", headers=HEADERS).json()
        assert scope, "scope_analysis should be populated by now"

        d = _wait_for_status(gid, lambda x: x.get("maturation_status") == "review")
        assert d.get("spec"), "spec should be populated"
        assert len(d["spec"]) > 100

        resp = httpx.post(f"{BASE}/goals/{gid}/approve-spec", headers=HEADERS)
        assert resp.status_code == 200

        d = _wait_for_status(gid, lambda x: x.get("status") == "completed", timeout=120)
        assert d.get("status") == "completed"
        assert d.get("maturation_status") is None
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
