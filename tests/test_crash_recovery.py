"""Integration tests for crash recovery context endpoints."""
import pytest

pytestmark = pytest.mark.asyncio


class TestCheckpointExposure:
    async def test_task_detail_includes_checkpoint(self, orchestrator, test_api_key):
        headers = test_api_key["headers"]
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-checkpoint: say hello"},
            headers=headers,
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]
        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}", headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "checkpoint" in data, "Task detail must include checkpoint field"


class TestSessionsEndpoint:
    async def test_sessions_returns_list(self, orchestrator, test_api_key):
        headers = test_api_key["headers"]
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-sessions: say hello"},
            headers=headers,
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]
        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}/sessions", headers=headers
        )
        assert resp.status_code == 200
        sessions = resp.json()
        assert isinstance(sessions, list)

    async def test_sessions_have_expected_fields(self, orchestrator, test_api_key):
        headers = test_api_key["headers"]
        resp = await orchestrator.post(
            "/api/v1/pipeline/tasks",
            json={"user_input": "nova-test-session-fields: say hello"},
            headers=headers,
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]
        import asyncio
        await asyncio.sleep(3)
        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}/sessions", headers=headers
        )
        assert resp.status_code == 200
        sessions = resp.json()
        if sessions:
            s = sessions[0]
            for field in ("id", "role", "status", "error", "traceback", "duration_ms", "started_at"):
                assert field in s, f"Session missing field: {field}"
