"""Tier 1: Pipeline mechanics tests — no LLM required."""
from __future__ import annotations

import asyncio
import httpx
import pytest


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
