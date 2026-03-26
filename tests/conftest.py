"""Integration test configuration — real services, no mocks."""
from __future__ import annotations

import asyncio
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
KNOWLEDGE_WORKER_URL = os.getenv("NOVA_KNOWLEDGE_WORKER_URL", "http://localhost:8120")

ADMIN_SECRET = os.getenv("NOVA_ADMIN_SECRET", "")
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "false").lower() == "true"

SERVICE_URLS = {
    "orchestrator": ORCHESTRATOR_URL,
    "llm-gateway": LLM_GATEWAY_URL,
    "memory-service": MEMORY_URL,
    "chat-api": CHAT_API_URL,
    "recovery": RECOVERY_URL,
}

# Optional services started via --profile flags; excluded from parametrized health tests
OPTIONAL_SERVICE_URLS = {
    "knowledge-worker": KNOWLEDGE_WORKER_URL,
}


# ---------------------------------------------------------------------------
# Markers & session-scoped event loop
# ---------------------------------------------------------------------------
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "requires_llm: skip unless an LLM provider is available")
    config.addinivalue_line("markers", "pipeline: full pipeline tests requiring LLM provider")


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


@pytest_asyncio.fixture
async def knowledge_worker():
    async with httpx.AsyncClient(base_url=KNOWLEDGE_WORKER_URL, timeout=30) as client:
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


@pytest_asyncio.fixture
async def create_test_pod(orchestrator: httpx.AsyncClient, admin_headers: dict):
    """Factory fixture — creates a pod with configurable agents, auto-deletes on teardown."""
    created_pod_ids = []

    async def _create(name: str, agents: list[dict], **pod_kwargs) -> dict:
        pod_name = f"nova-test-{name}"
        resp = await orchestrator.post(
            "/api/v1/pods",
            json={"name": pod_name, "description": f"Test pod: {name}", "enabled": True, **pod_kwargs},
            headers=admin_headers,
        )
        assert resp.status_code in (200, 201), f"Failed to create pod: {resp.text}"
        pod = resp.json()
        created_pod_ids.append(pod["id"])

        for agent_cfg in agents:
            resp = await orchestrator.post(
                f"/api/v1/pods/{pod['id']}/agents",
                json=agent_cfg,
                headers=admin_headers,
            )
            assert resp.status_code in (200, 201), f"Failed to create agent: {resp.text}"

        return pod

    yield _create

    for pod_id in created_pod_ids:
        await orchestrator.delete(f"/api/v1/pods/{pod_id}", headers=admin_headers)


@pytest_asyncio.fixture
async def force_cleanup_task(orchestrator: httpx.AsyncClient, admin_headers: dict):
    """Tracks task IDs and force-deletes them on teardown (even non-terminal tasks)."""
    task_ids = []

    def _track(task_id: str):
        task_ids.append(task_id)

    yield _track

    for task_id in task_ids:
        await orchestrator.post(
            f"/api/v1/pipeline/tasks/{task_id}/cancel",
            headers=admin_headers,
        )
        await orchestrator.delete(
            f"/api/v1/pipeline/tasks/{task_id}",
            headers=admin_headers,
        )


@pytest_asyncio.fixture
async def pipeline_task(orchestrator: httpx.AsyncClient, admin_headers: dict, force_cleanup_task):
    """Submit a pipeline task and poll until terminal state."""
    async def _submit(user_input: str, pod_name: str | None = None, timeout: int = 120, poll_interval: int = 3) -> dict:
        body = {"user_input": user_input}
        if pod_name:
            body["pod_name"] = pod_name
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json=body,
            headers=admin_headers,
        )
        assert resp.status_code == 202, resp.text
        task_id = resp.json().get("task_id") or resp.json().get("id")
        force_cleanup_task(task_id)

        data = {}
        for _ in range(timeout // poll_interval):
            await asyncio.sleep(poll_interval)
            resp = await orchestrator.get(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            if data["status"] in ("complete", "completed", "failed", "cancelled", "clarification_needed", "pending_human_review"):
                return data

        pytest.fail(f"Task {task_id} did not reach terminal state within {timeout}s (last: {data.get('status')})")

    yield _submit
