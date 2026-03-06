"""Memory service integration tests — store, search, delete, facts."""
from __future__ import annotations

import uuid

import httpx
import pytest

TEST_AGENT_ID = "nova-test-agent"


def _test_id() -> str:
    return f"nova-test-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------
class TestMemoryCRUD:
    async def test_store_get_delete(self, memory: httpx.AsyncClient):
        content = f"Integration test memory {_test_id()}"

        # Store
        resp = await memory.post(
            "/api/v1/memories",
            json={
                "agent_id": TEST_AGENT_ID,
                "content": content,
                "tier": "episodic",
                "metadata": {"source": "integration-test"},
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        memory_id = data["id"]

        try:
            # Get by ID
            resp = await memory.get(f"/api/v1/memories/{memory_id}")
            assert resp.status_code == 200
            assert content in resp.json()["content"]
        finally:
            # Delete
            resp = await memory.delete(f"/api/v1/memories/{memory_id}")
            assert resp.status_code == 204

    async def test_update(self, memory: httpx.AsyncClient):
        # Store
        resp = await memory.post(
            "/api/v1/memories",
            json={
                "agent_id": TEST_AGENT_ID,
                "content": f"Original content {_test_id()}",
                "tier": "episodic",
                "metadata": {"source": "integration-test"},
            },
        )
        assert resp.status_code == 201
        memory_id = resp.json()["id"]

        try:
            updated_content = f"Updated content {_test_id()}"
            resp = await memory.patch(
                f"/api/v1/memories/{memory_id}",
                json={"content": updated_content},
            )
            assert resp.status_code == 204

            # Verify update
            resp = await memory.get(f"/api/v1/memories/{memory_id}")
            assert resp.status_code == 200
            assert updated_content in resp.json()["content"]
        finally:
            await memory.delete(f"/api/v1/memories/{memory_id}")


# ---------------------------------------------------------------------------
# Bulk store
# ---------------------------------------------------------------------------
class TestBulkStore:
    async def test_bulk_store(self, memory: httpx.AsyncClient):
        tag = _test_id()
        memories = [
            {
                "agent_id": TEST_AGENT_ID,
                "content": f"Bulk memory {i} {tag}",
                "tier": "episodic",
                "metadata": {"source": "integration-test"},
            }
            for i in range(3)
        ]

        resp = await memory.post("/api/v1/memories/bulk", json={"memories": memories})
        assert resp.status_code == 201, resp.text
        data = resp.json()
        stored_ids = data.get("stored", [])
        assert len(stored_ids) >= 3

        # Cleanup
        for mid in stored_ids:
            await memory.delete(f"/api/v1/memories/{mid}")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class TestSearch:
    async def test_semantic_search_returns_results(self, memory: httpx.AsyncClient):
        tag = _test_id()
        content = f"The quick brown fox jumps over the lazy dog {tag}"

        # Store a memory
        resp = await memory.post(
            "/api/v1/memories",
            json={
                "agent_id": TEST_AGENT_ID,
                "content": content,
                "tier": "episodic",
                "metadata": {"source": "integration-test"},
            },
        )
        assert resp.status_code == 201
        memory_id = resp.json()["id"]

        try:
            # Search for it
            resp = await memory.post(
                "/api/v1/memories/search",
                json={
                    "agent_id": TEST_AGENT_ID,
                    "query": "fox jumping over dog",
                    "limit": 5,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            results = data.get("results", data) if isinstance(data, dict) else data
            assert len(results) > 0
        finally:
            await memory.delete(f"/api/v1/memories/{memory_id}")


# ---------------------------------------------------------------------------
# Semantic facts
# ---------------------------------------------------------------------------
class TestSemanticFacts:
    async def test_upsert_fact(self, memory: httpx.AsyncClient):
        tag = _test_id()
        fact = {
            "agent_id": TEST_AGENT_ID,
            "project_id": tag,
            "category": "test",
            "key": "test-fact",
            "content": "Nova is an AI platform",
        }

        # First upsert
        resp = await memory.post("/api/v1/memories/facts", json=fact)
        assert resp.status_code == 201, resp.text

        # Second upsert with same key — should dedup
        fact["content"] = "Nova is an autonomous AI platform"
        resp = await memory.post("/api/v1/memories/facts", json=fact)
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Browse
# ---------------------------------------------------------------------------
class TestBrowse:
    async def test_browse_memories(self, memory: httpx.AsyncClient):
        resp = await memory.get("/api/v1/memories/browse", params={"limit": 5})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (list, dict))
