"""Integration tests for agent-callable memory tools."""
import os
import httpx
import pytest

ORCH = os.getenv("NOVA_ORCHESTRATOR_URL", "http://localhost:8000")
MEM = os.getenv("NOVA_MEMORY_URL", "http://localhost:8002")
ADMIN_SECRET = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")


@pytest.mark.asyncio
async def test_what_do_i_know_tool():
    """what_do_i_know returns domain awareness summary."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{MEM}/api/v1/engrams/sources/domain-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "source_count" in data
        assert "domains" in data


@pytest.mark.asyncio
async def test_search_memory_endpoint():
    """search_memory hits the activate endpoint."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(
            f"{MEM}/api/v1/engrams/activate",
            params={"query": "nova-test-memory-search"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "engrams" in data


@pytest.mark.asyncio
async def test_memory_tools_registered():
    """Memory tools appear in the tool catalog."""
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(f"{ORCH}/api/v1/tools",
                           headers={"X-Admin-Secret": ADMIN_SECRET})
        if resp.status_code == 200:
            tools = resp.json()
            tool_names = [t["name"] if isinstance(t, dict) else t for t in tools]
            assert "search_memory" in tool_names
            assert "what_do_i_know" in tool_names
            assert "recall_topic" in tool_names
            assert "read_source" in tool_names
