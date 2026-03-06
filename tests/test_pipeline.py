"""Pipeline integration tests — full end-to-end (requires LLM provider)."""
from __future__ import annotations

import asyncio

import httpx
import pytest


@pytest.mark.requires_llm
class TestPipelineExecution:
    """These tests submit real tasks through the pipeline.

    Skipped unless an LLM provider is available (checked via llm_available fixture).
    """

    async def test_submit_and_complete(
        self,
        orchestrator: httpx.AsyncClient,
        test_api_key: dict,
        llm_available: bool,
    ):
        if not llm_available:
            pytest.skip("No LLM provider available")

        headers = test_api_key["headers"]

        # Submit a simple task to the pipeline
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "Say hello world. This is an integration test."},
            headers=headers,
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        task_id = data.get("task_id") or data.get("id")
        assert task_id is not None

        # Poll until complete or timeout (120s)
        status = None
        for _ in range(24):
            await asyncio.sleep(5)
            resp = await orchestrator.get(
                f"/api/v1/pipeline/tasks/{task_id}",
                headers=headers,
            )
            assert resp.status_code == 200
            status = resp.json().get("status")
            if status in ("complete", "completed", "failed", "error"):
                break
        else:
            pytest.fail(f"Pipeline task {task_id} did not complete within 120s (last status: {status})")

        task_data = resp.json()
        assert task_data["status"] in ("complete", "completed"), (
            f"Task failed: {task_data.get('error') or task_data.get('output')}"
        )

    async def test_queue_stats(self, orchestrator: httpx.AsyncClient, admin_headers: dict, llm_available: bool):
        if not llm_available:
            pytest.skip("No LLM provider available")

        resp = await orchestrator.get("/api/v1/pipeline/queue-stats", headers=admin_headers)
        assert resp.status_code == 200
