"""Recovery service integration tests — status, backups, services."""
from __future__ import annotations

import httpx
import pytest


class TestRecoveryStatus:
    async def test_status_overview(self, recovery: httpx.AsyncClient):
        resp = await recovery.get("/api/v1/recovery/status")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    async def test_list_services(self, recovery: httpx.AsyncClient):
        resp = await recovery.get("/api/v1/recovery/services")
        assert resp.status_code == 200
        services = resp.json()
        assert isinstance(services, list)
        # Should have at least a few Nova services
        if len(services) > 0:
            svc = services[0]
            assert "service" in svc or "name" in svc or "container_name" in svc


class TestBackups:
    async def test_list_backups(self, recovery: httpx.AsyncClient):
        resp = await recovery.get("/api/v1/recovery/backups")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_and_delete_backup(self, recovery: httpx.AsyncClient, admin_headers: dict):
        # Create
        resp = await recovery.post("/api/v1/recovery/backups", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        filename = data.get("filename") or data.get("name")
        assert filename is not None

        # Delete the test backup
        resp = await recovery.delete(
            f"/api/v1/recovery/backups/{filename}",
            headers=admin_headers,
        )
        assert resp.status_code == 200


class TestFactoryReset:
    async def test_list_categories(self, recovery: httpx.AsyncClient):
        resp = await recovery.get("/api/v1/recovery/factory-reset/categories")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
