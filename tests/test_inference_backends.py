"""Integration tests for managed inference backends."""
from __future__ import annotations

import httpx
import pytest


class TestHardwareDetection:
    """Tests for the hardware detection endpoint."""

    async def test_get_hardware_info_requires_auth(self, recovery: httpx.AsyncClient):
        """Hardware endpoint should reject unauthenticated requests."""
        r = await recovery.get("/api/v1/recovery/inference/hardware")
        assert r.status_code == 401

    async def test_get_hardware_info(self, recovery: httpx.AsyncClient, admin_headers: dict):
        """Recovery service should return detected hardware info."""
        r = await recovery.get("/api/v1/recovery/inference/hardware", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "gpus" in data
        assert "cpu_cores" in data
        assert "ram_gb" in data
        assert "disk_free_gb" in data
        assert isinstance(data["gpus"], list)
        assert data["cpu_cores"] > 0
        assert "recommended_backend" in data

    async def test_hardware_redetect(self, recovery: httpx.AsyncClient, admin_headers: dict):
        """Re-detection should refresh hardware info."""
        r = await recovery.post(
            "/api/v1/recovery/inference/hardware/detect",
            headers=admin_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert "detected_at" in data
        assert "recommended_backend" in data
