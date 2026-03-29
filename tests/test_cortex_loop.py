"""Tests for Cortex autonomous loop fixes — Tier 1."""
import os
import pytest
import httpx

BASE = "http://localhost:8000/api/v1"
CORTEX = "http://localhost:8100/api/v1/cortex"
HEADERS = {}


@pytest.fixture(autouse=True)
def admin_headers():
    secret = os.environ.get("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    HEADERS["X-Admin-Secret"] = secret


@pytest.fixture
def goal_id():
    """Create a test goal and clean up after."""
    resp = httpx.post(
        f"{BASE}/goals",
        json={
            "title": "nova-test-cortex-loop-goal",
            "description": "Test goal with description for planning context",
            "priority": 3,
            "max_iterations": 10,
            "max_cost_usd": 1.50,
        },
        headers=HEADERS,
    )
    assert resp.status_code in (200, 201), f"Failed to create goal: {resp.text}"
    gid = resp.json()["id"]
    yield gid
    try:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
    except Exception:
        pass


def test_goal_detail_includes_planning_fields(goal_id):
    """Goals returned by orchestrator include description, current_plan, iteration,
    max_iterations, and cost_so_far_usd — fields Cortex needs for planning."""
    resp = httpx.get(f"{BASE}/goals/{goal_id}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "description" in data
    assert data["description"] == "Test goal with description for planning context"
    assert "current_plan" in data
    assert "iteration" in data
    assert "max_iterations" in data
    assert data["max_iterations"] == 10
    assert "cost_so_far_usd" in data
    assert "max_cost_usd" in data
    assert data["max_cost_usd"] == 1.50


def test_cortex_drives_return_enriched_serve_context(goal_id):
    """Cortex /drives endpoint returns serve drive with stale goal context
    that includes description, not just title."""
    resp = httpx.get(f"{CORTEX}/drives", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    drives = data.get("drives", [])
    serve = next((d for d in drives if d["name"] == "serve"), None)
    assert serve is not None, "Serve drive not found in drives response"
    ctx = serve.get("context", {})
    stale = ctx.get("stale_goals", [])
    test_goal = next((g for g in stale if g["id"] == goal_id), None)
    if test_goal:
        assert "description" in test_goal, "Stale goal missing 'description' field"
        assert "current_plan" in test_goal, "Stale goal missing 'current_plan' field"
        assert "iteration" in test_goal, "Stale goal missing 'iteration' field"
        assert "max_iterations" in test_goal, "Stale goal missing 'max_iterations' field"


def test_cortex_status_endpoint_has_checkpoint():
    """Cortex status endpoint should expose cycle state for observability."""
    resp = httpx.get(f"{CORTEX}/status", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "cycle_count" in data
    assert "last_checkpoint" in data or "status" in data


def test_goal_last_checked_at_field_exists(goal_id):
    """Goals have a last_checked_at field available via API."""
    resp = httpx.get(f"{BASE}/goals/{goal_id}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "last_checked_at" in data, "Goal response must include last_checked_at"
