"""Orchestrator integration tests — agent CRUD, tasks, keys, config, pods."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx
import pytest


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------
class TestAgentLifecycle:
    async def test_create_list_get_delete(self, orchestrator: httpx.AsyncClient, test_api_key: dict):
        headers = test_api_key["headers"]

        # Create — requires config with name and system_prompt
        resp = await orchestrator.post(
            "/api/v1/agents",
            json={
                "config": {
                    "name": "nova-test-agent",
                    "system_prompt": "You are a test agent.",
                }
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        agent = resp.json()
        agent_id = agent["id"]

        try:
            # List — our agent should appear
            resp = await orchestrator.get("/api/v1/agents", headers=headers)
            assert resp.status_code == 200
            ids = [a["id"] for a in resp.json()]
            assert agent_id in ids

            # Get by ID
            resp = await orchestrator.get(f"/api/v1/agents/{agent_id}", headers=headers)
            assert resp.status_code == 200
            assert resp.json()["id"] == agent_id
        finally:
            # Delete returns 204
            resp = await orchestrator.delete(f"/api/v1/agents/{agent_id}", headers=headers)
            assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Task submission — needs agent_id (UUID) and messages
# ---------------------------------------------------------------------------
class TestTaskSubmission:
    async def test_submit_returns_202(self, orchestrator: httpx.AsyncClient, test_api_key: dict):
        headers = test_api_key["headers"]

        # First create an agent to submit the task against
        resp = await orchestrator.post(
            "/api/v1/agents",
            json={
                "config": {
                    "name": "nova-test-task-agent",
                    "system_prompt": "You are a test agent.",
                }
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        agent_id = resp.json()["id"]

        try:
            resp = await orchestrator.post(
                "/api/v1/tasks",
                json={
                    "agent_id": agent_id,
                    "messages": [{"role": "user", "content": "nova-test: echo hello"}],
                },
                headers=headers,
            )
            assert resp.status_code == 202, resp.text
            data = resp.json()
            assert "id" in data or "task_id" in data
        finally:
            await orchestrator.delete(f"/api/v1/agents/{agent_id}", headers=headers)


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------
class TestApiKeyManagement:
    async def test_create_validate_revoke(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        # Create a throwaway key
        resp = await orchestrator.post(
            "/api/v1/keys",
            json={"name": "nova-test-throwaway-key"},
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        raw_key = data["raw_key"]
        key_id = data["id"]

        try:
            # Validate it works
            resp = await orchestrator.get(
                "/api/v1/keys/validate",
                headers={"X-API-Key": raw_key},
            )
            assert resp.status_code == 200

            # List keys — should appear
            resp = await orchestrator.get("/api/v1/keys", headers=admin_headers)
            assert resp.status_code == 200
            ids = [k["id"] for k in resp.json()]
            assert key_id in ids
        finally:
            # Revoke returns 204
            resp = await orchestrator.delete(f"/api/v1/keys/{key_id}", headers=admin_headers)
            assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Platform config
# ---------------------------------------------------------------------------
class TestPlatformConfig:
    async def test_get_config(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.get("/api/v1/config", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), (list, dict))


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------
class TestToolCatalog:
    async def test_list_tools(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        resp = await orchestrator.get("/api/v1/tools", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Pod lifecycle
# ---------------------------------------------------------------------------
class TestPodLifecycle:
    async def test_create_list_delete(self, orchestrator: httpx.AsyncClient, admin_headers: dict, test_api_key: dict):
        # Create — only name is required
        resp = await orchestrator.post(
            "/api/v1/pods",
            json={"name": "nova-test-pod"},
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        pod = resp.json()
        pod_id = pod["id"]

        try:
            # List
            resp = await orchestrator.get("/api/v1/pods", headers=test_api_key["headers"])
            assert resp.status_code == 200
            ids = [p["id"] for p in resp.json()]
            assert pod_id in ids

            # Get
            resp = await orchestrator.get(f"/api/v1/pods/{pod_id}", headers=test_api_key["headers"])
            assert resp.status_code == 200
            assert resp.json()["id"] == pod_id
        finally:
            # Delete returns 204
            resp = await orchestrator.delete(f"/api/v1/pods/{pod_id}", headers=admin_headers)
            assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Task deletion
# ---------------------------------------------------------------------------
class TestTaskDeletion:
    @staticmethod
    async def _wait_terminal(client: httpx.AsyncClient, task_id: str, headers: dict, timeout: float = 150):
        """Poll until task reaches a terminal state, trying cancel first."""
        await client.post(f"/api/v1/pipeline/tasks/{task_id}/cancel", headers=headers)
        for _ in range(int(timeout / 0.5)):
            resp = await client.get(f"/api/v1/pipeline/tasks/{task_id}", headers=headers)
            if resp.status_code == 200 and resp.json()["status"] in ("complete", "failed", "cancelled"):
                return resp.json()["status"]
            await asyncio.sleep(0.5)
        pytest.fail(f"Task {task_id} did not reach terminal state within {timeout}s")

    async def test_delete_single_task(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Delete a single terminal task."""
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "test task to delete"},
            headers=admin_headers,
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        # Wait for terminal state (cancel or let pipeline finish)
        await self._wait_terminal(orchestrator, task_id, admin_headers)

        # Delete — retry a few times in case of transient state transitions
        for attempt in range(5):
            resp = await orchestrator.delete(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
            if resp.status_code == 204:
                break
            await asyncio.sleep(1)
        assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"

        # Verify it's gone
        resp = await orchestrator.get(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_active_task_rejected(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Cannot delete a non-terminal task."""
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "active task for delete rejection test"},
            headers=admin_headers,
        )
        task_id = resp.json()["task_id"]

        # Immediately try delete — task should still be in a non-terminal state
        resp = await orchestrator.delete(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)
        # Should be 409 if still active, or 204 if it already finished (race)
        assert resp.status_code in (409, 204)

        # Cleanup if still around
        await self._wait_terminal(orchestrator, task_id, admin_headers)
        await orchestrator.delete(f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers)

    async def test_bulk_delete(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Bulk delete terminal tasks — verifies endpoint contract."""
        # Bulk delete whatever terminal tasks exist (previous tests may have left some)
        resp = await orchestrator.delete(
            "/api/v1/pipeline/tasks?status=complete,failed,cancelled",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "deleted" in body
        assert isinstance(body["deleted"], int)
        assert "statuses" in body

    async def test_bulk_delete_rejects_active_status(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Bulk delete rejects non-terminal statuses."""
        resp = await orchestrator.delete(
            "/api/v1/pipeline/tasks?status=queued",
            headers=admin_headers,
        )
        assert resp.status_code == 400


class TestSessionSummarization:
    @pytest.mark.requires_llm
    async def test_session_summarize(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """POST /api/v1/chat/sessions/{id}/summarize stores a session summary."""
        session_id = f"nova-test-summary-{uuid4().hex[:8]}"
        messages = [
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "The capital of France is Paris."},
            {"role": "user", "content": "What about Germany?"},
            {"role": "assistant", "content": "The capital of Germany is Berlin."},
        ]
        resp = await orchestrator.post(
            f"/api/v1/chat/sessions/{session_id}/summarize",
            json={"messages": messages},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["summary"]) > 10

    async def test_session_summarize_skips_short(self, orchestrator: httpx.AsyncClient, admin_headers: dict):
        """Sessions with fewer than 2 messages are skipped."""
        resp = await orchestrator.post(
            f"/api/v1/chat/sessions/nova-test-short/summarize",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
