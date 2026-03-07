"""
Integration tests for the chat-bridge service.

Requires: docker compose --profile bridges up
Tests are skipped if chat-bridge is not running.
"""
import os

import httpx
import pytest

BRIDGE_URL = os.getenv("CHAT_BRIDGE_URL", "http://localhost:8090")


async def _bridge_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{BRIDGE_URL}/health/live")
            return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def skip_if_unavailable():
    if not await _bridge_available():
        pytest.skip("chat-bridge not running")


@pytest.mark.asyncio
async def test_bridge_health_live():
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{BRIDGE_URL}/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_bridge_health_ready():
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{BRIDGE_URL}/health/ready")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ready", "degraded")
    assert "orchestrator" in data["checks"]


@pytest.mark.asyncio
async def test_bridge_adapter_status():
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{BRIDGE_URL}/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "adapters" in data
    platforms = [a["platform"] for a in data["adapters"]]
    assert "telegram" in platforms
