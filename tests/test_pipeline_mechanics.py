"""Tier 1: Pipeline mechanics tests — no LLM required."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

# Add orchestrator to path so unit tests can import directly from app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))


class TestPipelineSubmission:
    """Task submission, queue, and basic lifecycle."""

    async def test_submit_returns_202(
        self, orchestrator: httpx.AsyncClient, admin_headers: dict, force_cleanup_task,
    ):
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-mechanics: hello"},
            headers=admin_headers,
        )
        assert resp.status_code == 202
        task_id = resp.json().get("task_id") or resp.json().get("id")
        assert task_id is not None
        force_cleanup_task(task_id)


class TestPodCRUD:
    """Pod create, list, update, delete — no LLM required."""

    async def test_create_and_list_pods(
        self,
        orchestrator: httpx.AsyncClient,
        admin_headers: dict,
        create_test_pod,
    ):
        pod = await create_test_pod("crud-list", agents=[])

        resp = await orchestrator.get("/api/v1/pods", headers=admin_headers)
        assert resp.status_code == 200
        pods = resp.json()
        assert isinstance(pods, list)
        pod_ids = [p["id"] for p in pods]
        assert pod["id"] in pod_ids

    async def test_update_pod(
        self,
        orchestrator: httpx.AsyncClient,
        admin_headers: dict,
        create_test_pod,
    ):
        pod = await create_test_pod("crud-update", agents=[])

        # PATCH requires name (it's a full PodRequest body, not a partial patch)
        resp = await orchestrator.patch(
            f"/api/v1/pods/{pod['id']}",
            json={"name": pod["name"], "description": "nova-test-updated-description"},
            headers=admin_headers,
        )
        assert resp.status_code in (200, 204)

    async def test_delete_pod(
        self,
        orchestrator: httpx.AsyncClient,
        admin_headers: dict,
    ):
        # Create a pod directly (not via fixture) so we can delete it ourselves
        resp = await orchestrator.post(
            "/api/v1/pods",
            json={"name": "nova-test-crud-delete", "description": "delete me", "enabled": True},
            headers=admin_headers,
        )
        assert resp.status_code in (200, 201), f"Failed to create pod: {resp.text}"
        pod_id = resp.json()["id"]

        del_resp = await orchestrator.delete(f"/api/v1/pods/{pod_id}", headers=admin_headers)
        assert del_resp.status_code in (200, 204)

        # Verify it's gone
        get_resp = await orchestrator.get(f"/api/v1/pods/{pod_id}", headers=admin_headers)
        assert get_resp.status_code == 404


class TestTaskLifecycle:
    """Task cancellation and pipeline operation endpoints."""

    async def test_cancel_queued_task(
        self,
        orchestrator: httpx.AsyncClient,
        admin_headers: dict,
        force_cleanup_task,
    ):
        # Submit a task
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-cancel: hello"},
            headers=admin_headers,
        )
        assert resp.status_code == 202
        task_id = resp.json().get("task_id") or resp.json().get("id")
        assert task_id is not None
        force_cleanup_task(task_id)

        # Cancel immediately — 200/204 means cancelled cleanly, 409 means the
        # worker already grabbed it (both are valid race outcomes)
        cancel_resp = await orchestrator.post(
            f"/api/v1/pipeline/tasks/{task_id}/cancel",
            headers=admin_headers,
        )
        assert cancel_resp.status_code in (200, 204, 409)

    async def test_queue_stats_endpoint(
        self,
        orchestrator: httpx.AsyncClient,
        admin_headers: dict,
    ):
        resp = await orchestrator.get("/api/v1/pipeline/queue-stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Response must contain at least one depth-related key
        assert any(k in data for k in ("queue_depth", "depth", "pending", "queued")), (
            f"queue-stats response missing depth info: {data}"
        )

    async def test_reap_now_endpoint(
        self,
        orchestrator: httpx.AsyncClient,
        admin_headers: dict,
    ):
        resp = await orchestrator.post("/api/v1/pipeline/reap-now", headers=admin_headers)
        if resp.status_code == 404:
            pytest.skip("reap-now endpoint not available in this build (needs container rebuild)")
        assert resp.status_code == 200
        assert resp.json() == {"status": "reaped"}


class TestQueueBehavior:
    """Queue submission and task retrieval."""

    async def test_submit_creates_task(
        self,
        orchestrator: httpx.AsyncClient,
        admin_headers: dict,
        force_cleanup_task,
    ):
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-queue: hello"},
            headers=admin_headers,
        )
        assert resp.status_code == 202
        submit_data = resp.json()
        task_id = submit_data.get("task_id") or submit_data.get("id")
        assert task_id is not None
        force_cleanup_task(task_id)

        # Fetch the task and verify expected fields are present
        get_resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}",
            headers=admin_headers,
        )
        assert get_resp.status_code == 200
        task = get_resp.json()
        assert task["id"] == task_id
        assert task["user_input"] == "nova-test-queue: hello"
        assert "status" in task
        assert task["status"] in (
            "queued", "context_running", "task_running",
            "critique_direction_running", "guardrail_running",
            "code_review_running", "critique_acceptance_running",
            "decision_running", "complete", "completed",
            "failed", "cancelled",
        )


class TestRunConditions:
    """Test should_agent_run() — pure function, no services needed."""

    def test_not_flag_returns_false_when_flag_set(self):
        from app.pipeline.agents.base import should_agent_run, PipelineState
        state = PipelineState(task_input="test", flags={"critique_approved"})
        condition = {"type": "not_flag", "flag": "critique_approved"}
        assert should_agent_run(condition, state) is False

    def test_not_flag_returns_true_when_flag_absent(self):
        from app.pipeline.agents.base import should_agent_run, PipelineState
        state = PipelineState(task_input="test", flags=set())
        condition = {"type": "not_flag", "flag": "critique_approved"}
        assert should_agent_run(condition, state) is True

    def test_on_flag_still_works(self):
        from app.pipeline.agents.base import should_agent_run, PipelineState
        state = PipelineState(task_input="test", flags={"guardrail_blocked"})
        assert should_agent_run({"type": "on_flag", "flag": "guardrail_blocked"}, state) is True
        assert should_agent_run({"type": "on_flag", "flag": "other"}, state) is False
