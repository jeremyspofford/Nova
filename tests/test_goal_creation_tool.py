"""Tests for create_goal tool and creation autonomy setting."""
import os
import pytest
import httpx

BASE = "http://localhost:8000/api/v1"
HEADERS = {}


@pytest.fixture(autouse=True)
def admin_headers():
    secret = os.environ.get("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    HEADERS["X-Admin-Secret"] = secret


@pytest.fixture
def cleanup_goals():
    """Track and delete test goals after each test."""
    created: list[str] = []
    yield created
    for gid in created:
        httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)


class TestCreateGoalInCatalog:
    """Verify create_goal appears in the tool catalog."""

    def test_create_goal_in_tool_catalog(self):
        resp = httpx.get(f"{BASE}/tools", headers=HEADERS)
        assert resp.status_code == 200
        categories = resp.json()
        platform = next(
            c for c in categories if c["category"] == "Platform Tools"
        )
        tool_names = [t["name"] for t in platform["tools"]]
        assert "create_goal" in tool_names, f"create_goal not found in Platform Tools: {tool_names}"

    def test_create_task_in_tool_catalog(self):
        resp = httpx.get(f"{BASE}/tools", headers=HEADERS)
        assert resp.status_code == 200
        categories = resp.json()
        platform = next(
            c for c in categories if c["category"] == "Platform Tools"
        )
        tool_names = [t["name"] for t in platform["tools"]]
        assert "create_task" in tool_names, f"create_task not found in Platform Tools: {tool_names}"

    def test_create_goal_has_description(self):
        resp = httpx.get(f"{BASE}/tools", headers=HEADERS)
        categories = resp.json()
        platform = next(c for c in categories if c["category"] == "Platform Tools")
        goal_tool = next(t for t in platform["tools"] if t["name"] == "create_goal")
        assert "description" in goal_tool
        assert "ongoing goal" in goal_tool["description"].lower() or "autonomous" in goal_tool["description"].lower()


class TestGoalCreationAPI:
    """Verify goals can be created and cleaned up via the API."""

    def test_create_goal(self, cleanup_goals):
        resp = httpx.post(
            f"{BASE}/goals",
            headers=HEADERS,
            json={
                "title": "nova-test-mediated-goal",
                "description": "Integration test for mediated creation",
                "priority": 3,
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["title"] == "nova-test-mediated-goal"
        assert data["status"] == "active"
        assert "id" in data
        cleanup_goals.append(data["id"])

    def test_create_goal_with_success_criteria(self, cleanup_goals):
        resp = httpx.post(
            f"{BASE}/goals",
            headers=HEADERS,
            json={
                "title": "nova-test-goal-criteria",
                "description": "Test with success criteria",
                "success_criteria": "All tests pass and coverage > 80%",
                "priority": 2,
                "max_cost_usd": 1.50,
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["success_criteria"] == "All tests pass and coverage > 80%"
        cleanup_goals.append(data["id"])

    def test_delete_goal(self, cleanup_goals):
        # Create
        resp = httpx.post(
            f"{BASE}/goals",
            headers=HEADERS,
            json={
                "title": "nova-test-goal-delete",
                "description": "Will be deleted",
            },
        )
        assert resp.status_code in (200, 201)
        gid = resp.json()["id"]

        # Delete
        del_resp = httpx.delete(f"{BASE}/goals/{gid}", headers=HEADERS)
        assert del_resp.status_code in (200, 204)


class TestAutonomySetting:
    """Verify the creation autonomy Redis config key works."""

    def test_set_and_read_autonomy(self):
        # Set to confirm_all
        resp = httpx.patch(
            f"{BASE}/config/creation.autonomy",
            headers=HEADERS,
            json={"value": "confirm_all"},
        )
        assert resp.status_code in (200, 201), f"Failed to set: {resp.status_code} {resp.text}"

        # Read back
        resp = httpx.get(f"{BASE}/config/creation.autonomy", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["value"] == "confirm_all"

        # Reset to default
        httpx.patch(
            f"{BASE}/config/creation.autonomy",
            headers=HEADERS,
            json={"value": "auto_tasks"},
        )

    def test_autonomy_accepts_all_valid_values(self):
        for val in ("auto_all", "auto_tasks", "auto_goals", "confirm_all"):
            resp = httpx.patch(
                f"{BASE}/config/creation.autonomy",
                headers=HEADERS,
                json={"value": val},
            )
            assert resp.status_code in (200, 201), f"Failed for {val}: {resp.text}"

        # Reset
        httpx.patch(
            f"{BASE}/config/creation.autonomy",
            headers=HEADERS,
            json={"value": "auto_tasks"},
        )
