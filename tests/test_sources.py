"""Integration tests for source provenance system."""
import httpx
import pytest
import pytest_asyncio

BASE = "http://localhost:8002/api/v1/engrams"


@pytest_asyncio.fixture
async def created_source():
    """Create a test source and clean up after."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(f"{BASE}/sources", json={
            "source_kind": "manual_paste",
            "title": "nova-test-source-provenance",
            "content": "Nova is an autonomous AI platform built by Aria Labs.",
            "trust_score": 0.9,
        })
        assert resp.status_code == 200
        data = resp.json()
        yield data
        await c.delete(f"{BASE}/sources/{data['id']}")


@pytest.mark.asyncio
async def test_create_source():
    """POST /sources creates a source record."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(f"{BASE}/sources", json={
            "source_kind": "intel_feed",
            "title": "nova-test-intel-source",
            "uri": "https://example.com/nova-test-article",
            "trust_score": 0.8,
            "author": "Test Author",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_kind"] == "intel_feed"
        assert data["title"] == "nova-test-intel-source"
        assert data["trust_score"] == 0.8
        await c.delete(f"{BASE}/sources/{data['id']}")


@pytest.mark.asyncio
async def test_list_sources():
    """GET /sources returns source list."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{BASE}/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_source_detail(created_source):
    """GET /sources/{id} returns full source detail."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{BASE}/sources/{created_source['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "nova-test-source-provenance"
        assert data["trust_score"] == 0.9


@pytest.mark.asyncio
async def test_source_dedup_by_hash():
    """Creating a source with identical content returns existing source."""
    content = "nova-test-dedup-content-identical"
    async with httpx.AsyncClient(timeout=10) as c:
        r1 = await c.post(f"{BASE}/sources", json={
            "source_kind": "manual_paste",
            "title": "nova-test-dedup-1",
            "content": content,
        })
        r2 = await c.post(f"{BASE}/sources", json={
            "source_kind": "manual_paste",
            "title": "nova-test-dedup-2",
            "content": content,
        })
        assert r1.json()["id"] == r2.json()["id"]
        await c.delete(f"{BASE}/sources/{r1.json()['id']}")


@pytest.mark.asyncio
async def test_domain_summary():
    """GET /sources/domain-summary returns knowledge domain overview."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{BASE}/sources/domain-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "source_count" in data
        assert "domains" in data
        assert "by_kind" in data
