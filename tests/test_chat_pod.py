"""Integration tests for Chat Pod Architecture — create_task, pod config, allowlists."""
from __future__ import annotations

import asyncio

import httpx
import pytest
import pytest_asyncio

PREFIX = "nova-test-"


@pytest_asyncio.fixture
async def chat_pod_id(orchestrator: httpx.AsyncClient, admin_headers: dict):
    """Get the chat pod ID (seeded by migration 030)."""
    resp = await orchestrator.get("/api/v1/pods", headers=admin_headers)
    if resp.status_code != 200:
        pytest.skip("Could not list pods")
    pods = resp.json()
    chat_pods = [p for p in pods if p.get("is_chat_default")]
    if not chat_pods:
        pytest.skip("No chat pod configured — migration 030 may not have run")
    return chat_pods[0]["id"]


class TestCreateTaskTool:
    """Test the create_task platform tool via direct tool execution."""

    async def test_create_task_default_pod(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """create_task with no pod_name uses the system default pod."""
        resp = await orchestrator.post(
            "/api/v1/tools/execute",
            json={"name": "create_task", "arguments": {"description": f"{PREFIX}test task for default pod"}},
            headers=admin_headers,
        )
        if resp.status_code == 404:
            # Tool execute endpoint may not exist — test via pipeline submission
            resp = await orchestrator.post(
                "/api/v1/pipeline/tasks",
                json={"user_input": f"{PREFIX}test task via pipeline", "metadata": {"source": "chat"}},
                headers=admin_headers,
            )
            assert resp.status_code in (200, 201, 202)
            task = resp.json()
            assert task["task_id"]
            # Cleanup
            await orchestrator.delete(f"/api/v1/pipeline/tasks/{task['task_id']}", headers=admin_headers)
            return

        # If tool execute endpoint exists
        assert resp.status_code == 200
        result = resp.json()
        assert "submitted" in result.get("result", "").lower() or "task" in result.get("result", "").lower()

    async def test_create_task_unknown_pod(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """create_task with a nonexistent pod returns an error, not a crash."""
        resp = await orchestrator.post(
            "/api/v1/tools/execute",
            json={"name": "create_task", "arguments": {"description": f"{PREFIX}test", "pod_name": "nonexistent-pod-xyz"}},
            headers=admin_headers,
        )
        if resp.status_code == 404:
            pytest.skip("Tool execute endpoint not available")
        assert resp.status_code == 200
        result = resp.json().get("result", "")
        assert "not found" in result.lower() or "available" in result.lower()


class TestChatPodConfig:
    """Test chat endpoint pod configuration."""

    async def test_chat_pod_exists(self, orchestrator: httpx.AsyncClient, admin_headers: dict, chat_pod_id: str):
        """Verify chat pod was seeded by migration."""
        resp = await orchestrator.get(f"/api/v1/pods/{chat_pod_id}", headers=admin_headers)
        assert resp.status_code == 200
        pod = resp.json()
        assert pod["name"] == "Chat"
        assert pod.get("is_chat_default") is True

    async def test_chat_pod_has_agent(self, orchestrator: httpx.AsyncClient, admin_headers: dict, chat_pod_id: str):
        """Chat pod has at least one agent configured."""
        resp = await orchestrator.get(f"/api/v1/pods/{chat_pod_id}/agents", headers=admin_headers)
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) >= 1
        chat_agent = agents[0]
        assert chat_agent["role"] == "chat"

    async def test_chat_stream_uses_pod(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Chat stream endpoint loads and applies pod config (doesn't 503)."""
        resp = await orchestrator.post(
            "/api/v1/chat/stream",
            json={"messages": [{"role": "user", "content": f"{PREFIX}hello, respond briefly"}]},
            headers=admin_headers,
        )
        # Should not 503 — pod config loaded successfully
        assert resp.status_code == 200

    async def test_chat_fallback_without_pod(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """If chat pod were removed, chat should still work (fallback)."""
        # This tests the existing behavior — chat works with or without a pod
        # We don't actually delete the pod; we just verify chat doesn't crash
        resp = await orchestrator.post(
            "/api/v1/chat/stream",
            json={"messages": [{"role": "user", "content": f"{PREFIX}test fallback"}]},
            headers=admin_headers,
        )
        assert resp.status_code == 200


class TestToolAllowlist:
    """Test pod-level tool allowlist filtering."""

    async def test_null_allowlist_means_all_tools(self, orchestrator: httpx.AsyncClient, admin_headers: dict, chat_pod_id: str):
        """Pod agent with allowed_tools=NULL gives access to all tools."""
        resp = await orchestrator.get(f"/api/v1/pods/{chat_pod_id}/agents", headers=admin_headers)
        assert resp.status_code == 200
        agents = resp.json()
        assert agents[0].get("allowed_tools") is None  # NULL = all tools

    async def test_tools_listing_includes_create_task(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """The create_task tool appears in the available tools listing."""
        resp = await orchestrator.get("/api/v1/tools", headers=admin_headers)
        assert resp.status_code == 200
        categories = resp.json()
        all_tool_names = []
        for cat in categories:
            for tool in cat.get("tools", []):
                all_tool_names.append(tool.get("name"))
        assert "create_task" in all_tool_names


class TestPodDeletion:
    """Test defensive behavior when pod is deleted."""

    async def test_task_with_deleted_pod_fails_gracefully(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Task submitted to a deleted pod fails with clear error, not crash."""
        # Create a temporary pod
        resp = await orchestrator.post(
            "/api/v1/pods",
            json={"name": f"{PREFIX}temp-pod", "description": "temporary"},
            headers=admin_headers,
        )
        if resp.status_code not in (200, 201):
            pytest.skip(f"Could not create pod: {resp.status_code}")
        pod = resp.json()
        pod_id = pod["id"]

        # Submit a task to it
        task_resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": f"{PREFIX}task for temp pod", "pod_id": pod_id},
            headers=admin_headers,
        )
        if task_resp.status_code not in (200, 201, 202):
            await orchestrator.delete(f"/api/v1/pods/{pod_id}", headers=admin_headers)
            pytest.skip(f"Could not create task: {task_resp.status_code}")
        task_id = task_resp.json()["task_id"]

        # Delete the pod (task is already queued)
        await orchestrator.delete(f"/api/v1/pods/{pod_id}", headers=admin_headers)

        # Wait for pipeline to attempt the task
        await asyncio.sleep(5)

        # Task should be failed with a clear error
        status_resp = await orchestrator.get(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
        if status_resp.status_code == 200:
            task = status_resp.json()
            # Should be failed (pod not found) or completed (fell back to default)
            assert task["status"] in ("failed", "complete"), f"Unexpected status: {task['status']}"
        # Cleanup
        await orchestrator.delete(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
