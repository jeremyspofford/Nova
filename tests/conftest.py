"""Integration test configuration — real services, no mocks."""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from dotenv import load_dotenv

# Load .env from repo root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# Service base URLs (override via env vars if services are on different hosts)
# ---------------------------------------------------------------------------
ORCHESTRATOR_URL = os.getenv("NOVA_ORCHESTRATOR_URL", "http://localhost:8000")
LLM_GATEWAY_URL = os.getenv("NOVA_LLM_GATEWAY_URL", "http://localhost:8001")
MEMORY_URL = os.getenv("NOVA_MEMORY_URL", "http://localhost:8002")
CHAT_API_URL = os.getenv("NOVA_CHAT_API_URL", "http://localhost:8080")
RECOVERY_URL = os.getenv("NOVA_RECOVERY_URL", "http://localhost:8888")

ADMIN_SECRET = os.getenv("NOVA_ADMIN_SECRET", "")

SERVICE_URLS = {
    "orchestrator": ORCHESTRATOR_URL,
    "llm-gateway": LLM_GATEWAY_URL,
    "memory-service": MEMORY_URL,
    "chat-api": CHAT_API_URL,
    "recovery": RECOVERY_URL,
}


# ---------------------------------------------------------------------------
# Markers & session-scoped event loop
# ---------------------------------------------------------------------------
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "requires_llm: skip unless an LLM provider is available")


# ---------------------------------------------------------------------------
# Session-scoped async clients (function-scoped to avoid event loop issues)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def orchestrator():
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=30) as client:
        yield client


@pytest_asyncio.fixture
async def llm_gateway():
    async with httpx.AsyncClient(base_url=LLM_GATEWAY_URL, timeout=30) as client:
        yield client


@pytest_asyncio.fixture
async def memory():
    async with httpx.AsyncClient(base_url=MEMORY_URL, timeout=30) as client:
        yield client


@pytest_asyncio.fixture
async def chat_api():
    async with httpx.AsyncClient(base_url=CHAT_API_URL, timeout=30) as client:
        yield client


@pytest_asyncio.fixture
async def recovery():
    async with httpx.AsyncClient(base_url=RECOVERY_URL, timeout=30) as client:
        yield client


# ---------------------------------------------------------------------------
# Admin headers helper
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Secret": ADMIN_SECRET}


# ---------------------------------------------------------------------------
# Test API key — created per test that needs it, revoked at teardown
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def test_api_key(orchestrator: httpx.AsyncClient, admin_headers: dict):
    resp = await orchestrator.post(
        "/api/v1/keys",
        json={"name": "nova-test-key", "rate_limit_rpm": 9999},
        headers=admin_headers,
    )
    if resp.status_code not in (200, 201):
        pytest.skip(f"Could not create test API key: {resp.status_code} {resp.text}")

    data = resp.json()
    raw_key = data["raw_key"]
    key_id = data["id"]

    yield {"raw_key": raw_key, "key_id": key_id, "headers": {"X-API-Key": raw_key}}

    # Teardown: revoke the test key
    if key_id:
        await orchestrator.delete(f"/api/v1/keys/{key_id}", headers=admin_headers)


# ---------------------------------------------------------------------------
# LLM availability check
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def llm_available(llm_gateway: httpx.AsyncClient) -> bool:
    try:
        resp = await llm_gateway.get("/models")
        if resp.status_code == 200:
            models = resp.json()
            return len(models) > 0
    except Exception:
        pass
    return False
