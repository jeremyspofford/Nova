"""Health endpoint tests — validates all services are alive and ready."""
from __future__ import annotations

import httpx
import pytest

from conftest import SERVICE_URLS


@pytest.mark.parametrize("service,url", SERVICE_URLS.items())
async def test_liveness(service: str, url: str):
    """Every service must respond to /health/live."""
    async with httpx.AsyncClient(base_url=url, timeout=10) as client:
        resp = await client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("alive", "ok")


@pytest.mark.parametrize("service,url", SERVICE_URLS.items())
async def test_readiness(service: str, url: str):
    """Every service must respond to /health/ready with status ready or degraded."""
    async with httpx.AsyncClient(base_url=url, timeout=10) as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ready", "degraded", "ok")
