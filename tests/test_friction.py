"""Integration tests for friction log CRUD endpoints."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

PREFIX = "nova-test-"


@pytest_asyncio.fixture
async def friction_entry(orchestrator: httpx.AsyncClient, admin_headers: dict):
    """Create a friction entry for tests, clean up after."""
    resp = await orchestrator.post(
        "/api/v1/friction",
        json={"description": f"{PREFIX}chat input resets on navigation", "severity": "blocker"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    entry = resp.json()
    yield entry
    # Cleanup
    await orchestrator.delete(f"/api/v1/friction/{entry['id']}", headers=admin_headers)


class TestFrictionCRUD:
    """Test friction log CRUD endpoints."""

    async def test_create_entry(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.post(
            "/api/v1/friction",
            json={"description": f"{PREFIX}pipeline timeout on large tasks", "severity": "annoyance"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["description"].startswith(PREFIX)
        assert data["severity"] == "annoyance"
        assert data["status"] == "open"
        assert data["source"] == "manual"
        assert data["id"]
        # Cleanup
        await orchestrator.delete(f"/api/v1/friction/{data['id']}", headers=admin_headers)

    async def test_create_entry_missing_description(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.post(
            "/api/v1/friction",
            json={"severity": "blocker"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_create_entry_invalid_severity(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.post(
            "/api/v1/friction",
            json={"description": f"{PREFIX}test", "severity": "invalid"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_list_entries(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        ids = [e["id"] for e in data]
        assert friction_entry["id"] in ids

    async def test_list_filter_severity(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction?severity=blocker", headers=admin_headers)
        assert resp.status_code == 200
        for entry in resp.json():
            assert entry["severity"] == "blocker"

    async def test_list_filter_status(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction?status=open", headers=admin_headers)
        assert resp.status_code == 200
        for entry in resp.json():
            assert entry["status"] == "open"

    async def test_list_pagination(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction?limit=1&offset=0", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) <= 1

    async def test_get_entry(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get(f"/api/v1/friction/{friction_entry['id']}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == friction_entry["id"]

    async def test_get_entry_not_found(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.get("/api/v1/friction/00000000-0000-0000-0000-000000000000", headers=admin_headers)
        assert resp.status_code == 404

    async def test_update_status(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.patch(
            f"/api/v1/friction/{friction_entry['id']}",
            json={"status": "fixed"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "fixed"

    async def test_update_invalid_status(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.patch(
            f"/api/v1/friction/{friction_entry['id']}",
            json={"status": "nonexistent"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_delete_entry(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        # Create one to delete
        create_resp = await orchestrator.post(
            "/api/v1/friction",
            json={"description": f"{PREFIX}delete-me", "severity": "idea"},
            headers=admin_headers,
        )
        entry_id = create_resp.json()["id"]
        resp = await orchestrator.delete(f"/api/v1/friction/{entry_id}", headers=admin_headers)
        assert resp.status_code == 204
        # Verify gone
        get_resp = await orchestrator.get(f"/api/v1/friction/{entry_id}", headers=admin_headers)
        assert get_resp.status_code == 404

    async def test_stats(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.get("/api/v1/friction/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "open_count" in data
        assert "total_count" in data
        assert "blocker_count" in data

    async def test_requires_admin_auth(self, orchestrator: httpx.AsyncClient):
        resp = await orchestrator.get("/api/v1/friction")
        assert resp.status_code in (401, 403)

        resp = await orchestrator.post(
            "/api/v1/friction",
            json={"description": "test"},
        )
        assert resp.status_code in (401, 403)


class TestFrictionFixThis:
    """Test the 'Fix This' action that creates a pipeline task."""

    async def test_fix_creates_task(self, orchestrator: httpx.AsyncClient, admin_headers: dict, friction_entry: dict):
        resp = await orchestrator.post(
            f"/api/v1/friction/{friction_entry['id']}/fix",
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "task_id" in data
        # Verify friction entry now has task_id and is in_progress
        entry_resp = await orchestrator.get(f"/api/v1/friction/{friction_entry['id']}", headers=admin_headers)
        assert entry_resp.json()["task_id"] == data["task_id"]
        assert entry_resp.json()["status"] == "in_progress"

    async def test_fix_not_found(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.post(
            "/api/v1/friction/00000000-0000-0000-0000-000000000000/fix",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_fix_already_fixed(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        # Create and mark as fixed
        create_resp = await orchestrator.post(
            "/api/v1/friction",
            json={"description": f"{PREFIX}already-fixed-test", "severity": "annoyance"},
            headers=admin_headers,
        )
        entry_id = create_resp.json()["id"]
        await orchestrator.patch(
            f"/api/v1/friction/{entry_id}",
            json={"status": "fixed"},
            headers=admin_headers,
        )
        # Try to fix
        resp = await orchestrator.post(f"/api/v1/friction/{entry_id}/fix", headers=admin_headers)
        assert resp.status_code == 422
        # Cleanup
        await orchestrator.delete(f"/api/v1/friction/{entry_id}", headers=admin_headers)


class TestPipelineStatsExtension:
    """Test the extended pipeline stats fields."""

    async def test_stats_include_new_fields(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.get("/api/v1/pipeline/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "failed_this_week" in data
        assert "submitted_today" in data
        assert isinstance(data["failed_this_week"], int)
        assert isinstance(data["submitted_today"], int)
