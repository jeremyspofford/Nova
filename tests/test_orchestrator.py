"""Orchestrator integration tests — agent CRUD, tasks, keys, config, pods."""
from __future__ import annotations

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
