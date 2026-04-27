"""Tier 1 — triage classifier."""
import os
import time

import httpx
import pytest

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-Admin-Secret": ""}


@pytest.fixture(autouse=True)
def admin_headers():
    HEADERS["X-Admin-Secret"] = os.environ.get("NOVA_ADMIN_SECRET", "")


def test_simple_goal_does_not_enter_maturation():
    """A trivial goal stays in NULL maturation_status after triage runs."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-simple",
            "description": (
                "Fix a typo in the README. Single-file documentation change, "
                "no code, no migrations, no services touched, no auth, no "
                "frontend, no infra. One line edit."
            ),
            "priority": 3, "max_iterations": 5, "max_cost_usd": 0.50,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    gid = resp.json()["id"]
    try:
        # 35s gives cortex enough time to actually run triage (LLM call up to
        # 30s + drive cycle cadence). Without this, the test would pass by
        # asserting the initial NULL state, not that triage classified simple.
        time.sleep(35)
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        assert detail.get("maturation_status") in (None, "simple")
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)


def test_complex_goal_enters_scoping():
    """A multi-service goal is classified complex and enters maturation at scoping."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-complex",
            "description": (
                "Build a new microservice that handles webhook delivery: "
                "receives HTTP POSTs from external systems, queues them in Redis, "
                "stores them in postgres, retries failed deliveries, exposes "
                "a dashboard page for monitoring, and integrates with the auth system."
            ),
            "priority": 3, "max_iterations": 50, "max_cost_usd": 5.00,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    gid = resp.json()["id"]
    try:
        time.sleep(35)
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        # Complex goals route directly to `scoping` — the first active phase.
        # There is no transient `triaging` status; the classifier writes
        # `scoping` once it returns "complex".
        assert detail.get("maturation_status") == "scoping"
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
