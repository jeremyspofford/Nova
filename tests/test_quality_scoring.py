"""Integration tests for AI quality measurement system."""
import pytest
import httpx
import pytest_asyncio

MEMORY_BASE = "http://localhost:8002"
ORCH_BASE = "http://localhost:8000"


@pytest_asyncio.fixture
async def memory_client():
    async with httpx.AsyncClient(base_url=MEMORY_BASE, timeout=10) as client:
        yield client


@pytest_asyncio.fixture
async def orchestrator_client():
    async with httpx.AsyncClient(base_url=ORCH_BASE, timeout=10) as client:
        yield client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Secret": "nova-admin-secret-change-me"}


class TestEngramBatchEndpoint:
    """POST /api/v1/engrams/batch returns engram content by ID list."""

    async def test_batch_empty_ids(self, memory_client: httpx.AsyncClient):
        r = await memory_client.post("/api/v1/engrams/batch", json={"ids": []})
        assert r.status_code == 200
        assert r.json() == []

    async def test_batch_nonexistent_ids(self, memory_client: httpx.AsyncClient):
        fake_id = "00000000-0000-0000-0000-000000000099"
        r = await memory_client.post("/api/v1/engrams/batch", json={"ids": [fake_id]})
        assert r.status_code == 200
        assert r.json() == []

    async def test_batch_returns_content(self, memory_client: httpx.AsyncClient):
        """Ingest an engram, then fetch it via batch endpoint."""
        ingest_r = await memory_client.post("/api/v1/engrams/ingest", json={
            "raw_text": "nova-test-quality: Python is my favorite language",
            "source_type": "chat",
        })
        assert ingest_r.status_code == 201
        engram_ids = ingest_r.json().get("engram_ids", [])
        if not engram_ids:
            pytest.skip("Ingest did not return engram_ids (async decomposition)")

        r = await memory_client.post("/api/v1/engrams/batch", json={"ids": engram_ids})
        assert r.status_code == 200
        results = r.json()
        assert len(results) > 0
        assert "id" in results[0]
        assert "content" in results[0]
        assert "node_type" in results[0]
