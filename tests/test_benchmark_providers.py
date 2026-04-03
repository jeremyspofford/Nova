"""Integration tests for benchmark memory providers.

Tests hit real running services over HTTP -- no mocks.
Requires: docker compose --profile benchmark up

Provider services are optional. Tests are skipped if the provider is not running.
All test resources use the nova-test- prefix and are cleaned up via fixture teardown.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest
import pytest_asyncio

# ── Provider URLs ────────────────────────────────────────────────────────────

PGVECTOR_URL = os.getenv("NOVA_BASELINE_PGVECTOR_URL", "http://localhost:8003")
MEM0_URL = os.getenv("NOVA_BASELINE_MEM0_URL", "http://localhost:8004")
MARKDOWN_URL = os.getenv("NOVA_BASELINE_MARKDOWN_URL", "http://localhost:8005")
MEMORY_URL = os.getenv("NOVA_MEMORY_URL", "http://localhost:8002")


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _is_reachable(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{url}/health/live")
            return r.status_code == 200
    except Exception:
        return False


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def pgvector_client():
    if not await _is_reachable(PGVECTOR_URL):
        pytest.skip(f"pgvector baseline not running at {PGVECTOR_URL}")
    async with httpx.AsyncClient(base_url=PGVECTOR_URL, timeout=30) as client:
        yield client


@pytest_asyncio.fixture
async def mem0_client():
    if not await _is_reachable(MEM0_URL):
        pytest.skip(f"mem0 baseline not running at {MEM0_URL}")
    async with httpx.AsyncClient(base_url=MEM0_URL, timeout=30) as client:
        yield client


@pytest_asyncio.fixture
async def markdown_client():
    if not await _is_reachable(MARKDOWN_URL):
        pytest.skip(f"markdown baseline not running at {MARKDOWN_URL}")
    async with httpx.AsyncClient(base_url=MARKDOWN_URL, timeout=30) as client:
        yield client


# ── Health Endpoint Tests ────────────────────────────────────────────────────


class TestPgvectorHealth:
    async def test_health_live(self, pgvector_client):
        r = await pgvector_client.get("/health/live")
        assert r.status_code == 200

    async def test_health_ready(self, pgvector_client):
        r = await pgvector_client.get("/health/ready")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") in ("ok", "ready", "healthy")


class TestMem0Health:
    async def test_health_live(self, mem0_client):
        r = await mem0_client.get("/health/live")
        assert r.status_code == 200

    async def test_health_ready(self, mem0_client):
        r = await mem0_client.get("/health/ready")
        assert r.status_code == 200


class TestMarkdownHealth:
    async def test_health_live(self, markdown_client):
        r = await markdown_client.get("/health/live")
        assert r.status_code == 200

    async def test_health_ready(self, markdown_client):
        r = await markdown_client.get("/health/ready")
        assert r.status_code == 200


# ── Stats Endpoint Tests ─────────────────────────────────────────────────────


class TestProviderStats:
    async def test_pgvector_stats(self, pgvector_client):
        r = await pgvector_client.get("/api/v1/memory/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["provider_name"] == "pgvector-only"
        assert isinstance(data["total_items"], int)
        assert isinstance(data["capabilities"], list)

    async def test_mem0_stats(self, mem0_client):
        r = await mem0_client.get("/api/v1/memory/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["provider_name"] == "mem0"
        assert isinstance(data["total_items"], int)

    async def test_markdown_stats(self, markdown_client):
        r = await markdown_client.get("/api/v1/memory/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["provider_name"] == "markdown-context"
        assert isinstance(data["total_items"], int)


# ── Ingest Tests ─────────────────────────────────────────────────────────────


class TestPgvectorIngest:
    async def test_ingest_text(self, pgvector_client):
        r = await pgvector_client.post("/api/v1/memory/ingest", json={
            "raw_text": "nova-test-benchmark: Nova uses PostgreSQL 16 with pgvector for memory storage.",
            "source_type": "chat",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["items_created"] >= 1
        assert isinstance(data.get("item_ids", []), list)

    async def test_ingest_empty_text(self, pgvector_client):
        r = await pgvector_client.post("/api/v1/memory/ingest", json={
            "raw_text": "",
            "source_type": "chat",
        })
        assert r.status_code in (200, 422)


class TestMem0Ingest:
    async def test_ingest_text(self, mem0_client):
        r = await mem0_client.post("/api/v1/memory/ingest", json={
            "raw_text": "nova-test-benchmark: Jeremy prefers Terraform for infrastructure.",
            "source_type": "chat",
        })
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("items_created", 0), int)


class TestMarkdownIngest:
    async def test_ingest_text(self, markdown_client):
        r = await markdown_client.post("/api/v1/memory/ingest", json={
            "raw_text": "## nova-test-benchmark\n\nNova runs as a Docker Compose stack with 12+ services.",
            "source_type": "chat",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["items_created"] >= 1


# ── Context Retrieval Tests ──────────────────────────────────────────────────


class TestPgvectorContext:
    async def test_context_retrieval(self, pgvector_client):
        r = await pgvector_client.post("/api/v1/memory/context", json={
            "query": "What database does Nova use?",
        })
        assert r.status_code == 200
        data = r.json()
        assert "context" in data
        assert isinstance(data["total_tokens"], int)

    async def test_context_response_shape(self, pgvector_client):
        r = await pgvector_client.post("/api/v1/memory/context", json={
            "query": "nova-test-nonexistent-topic-" + uuid.uuid4().hex[:8],
        })
        assert r.status_code == 200
        data = r.json()
        assert "context" in data
        assert "total_tokens" in data


class TestMem0Context:
    async def test_context_retrieval(self, mem0_client):
        r = await mem0_client.post("/api/v1/memory/context", json={
            "query": "What does Jeremy prefer for infrastructure?",
        })
        assert r.status_code == 200
        data = r.json()
        assert "context" in data


class TestMarkdownContext:
    async def test_context_retrieval(self, markdown_client):
        r = await markdown_client.post("/api/v1/memory/context", json={
            "query": "How many services does Nova have?",
        })
        assert r.status_code == 200
        data = r.json()
        assert "context" in data

    async def test_no_results_returns_valid_response(self, markdown_client):
        r = await markdown_client.post("/api/v1/memory/context", json={
            "query": "nova-test-nonexistent-" + uuid.uuid4().hex[:8],
        })
        assert r.status_code == 200


# ── Mark-Used Tests ──────────────────────────────────────────────────────────


class TestMarkUsed:
    async def test_pgvector_mark_used(self, pgvector_client):
        r = await pgvector_client.post("/api/v1/memory/mark-used", json={
            "retrieval_log_id": str(uuid.uuid4()),
            "used_ids": [str(uuid.uuid4())],
        })
        assert r.status_code == 200

    async def test_mem0_mark_used(self, mem0_client):
        r = await mem0_client.post("/api/v1/memory/mark-used", json={
            "retrieval_log_id": str(uuid.uuid4()),
            "used_ids": [str(uuid.uuid4())],
        })
        assert r.status_code == 200

    async def test_markdown_mark_used(self, markdown_client):
        r = await markdown_client.post("/api/v1/memory/mark-used", json={
            "retrieval_log_id": str(uuid.uuid4()),
            "used_ids": [str(uuid.uuid4())],
        })
        assert r.status_code == 200
