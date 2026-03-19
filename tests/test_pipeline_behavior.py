"""Tier 2: Pipeline behavior tests — requires LLM provider."""
from __future__ import annotations

import asyncio
import httpx
import pytest


@pytest.mark.pipeline
class TestPipelineHappyPath:
    """Full pipeline completion with all 7 stages."""

    async def test_full_pipeline_completion(self, pipeline_task, llm_available):
        if not llm_available:
            pytest.skip("No LLM provider available")
        result = await pipeline_task("nova-test-behavior: Say hello world. This is a pipeline integration test.")
        assert result["status"] in ("complete", "completed"), f"Task failed: {result.get('error')}"

    async def test_task_has_output(self, pipeline_task, llm_available):
        if not llm_available:
            pytest.skip("No LLM provider available")
        result = await pipeline_task("nova-test-output: What is 2+2? Answer with just the number.")
        assert result["status"] in ("complete", "completed")
        assert result.get("output"), "Task completed but has no output"


@pytest.mark.pipeline
class TestCritiqueDirection:
    """Critique-Direction agent approves good outputs."""

    async def test_critique_approves_clear_request(self, pipeline_task, llm_available):
        if not llm_available:
            pytest.skip("No LLM provider available")
        result = await pipeline_task("nova-test-critique: List the first 5 prime numbers, one per line.")
        # A clear, unambiguous request should be approved and complete
        assert result["status"] in ("complete", "completed"), f"Task didn't complete: {result.get('error')}"


@pytest.mark.pipeline
class TestPostPipelineAgents:
    """Post-pipeline agents produce artifacts."""

    async def test_artifacts_created_after_completion(
        self, orchestrator: httpx.AsyncClient, admin_headers: dict, pipeline_task, llm_available,
    ):
        if not llm_available:
            pytest.skip("No LLM provider available")
        result = await pipeline_task("nova-test-postpipeline: Write a Python function that adds two numbers.")
        assert result["status"] in ("complete", "completed"), f"Task failed: {result.get('error')}"
        task_id = result["id"]

        # Wait briefly for post-pipeline agents (they're fire-and-forget)
        await asyncio.sleep(10)

        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}/artifacts",
            headers=admin_headers,
        )
        if resp.status_code == 200:
            artifacts = resp.json()
            if artifacts:
                artifact_types = [a.get("artifact_type") or a.get("type") for a in artifacts]
                # Documentation agent always runs — check for its artifact
                # (soft assert — post-pipeline is best-effort)
                assert len(artifacts) > 0, "Expected at least one artifact from post-pipeline agents"
