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
    """A trivial goal stays in NULL maturation_status."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-simple",
            "description": "Add a print statement to log.py",
            "priority": 3, "max_iterations": 5, "max_cost_usd": 0.50,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201)
    gid = resp.json()["id"]
    try:
        time.sleep(2)
        detail = httpx.get(f"{BASE}/goals/{gid}", headers=HEADERS).json()
        assert detail.get("maturation_status") in (None, "simple")
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)


def test_complex_goal_enters_triaging():
    """A multi-service goal is classified complex and enters maturation."""
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
        assert detail.get("maturation_status") in ("triaging", "scoping")
    finally:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
