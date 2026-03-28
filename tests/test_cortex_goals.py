"""Integration tests for cortex goal execution and cost tracking pipeline.

These tests verify:
- Goal cost tracking fields exist and are returned by the API
- Task detail includes total_cost_usd (needed for cortex cost rollup)
- Goals carry descriptions for LLM planning context
- Goal budget fields (max_cost_usd, max_iterations) are honored
- System goals have the expected schema
"""
import pytest


class TestGoalCostTracking:
    """Verify the cost tracking pipeline from tasks to goals."""

    async def test_goal_response_includes_cost_fields(self, orchestrator, admin_headers):
        """Goals must return cost_so_far_usd and max_cost_usd for budget tracking."""
        resp = await orchestrator.post("/api/v1/goals", headers=admin_headers, json={
            "title": "nova-test-cost-tracking",
            "description": "Test goal for cost field verification",
            "max_cost_usd": 5.0,
        })
        assert resp.status_code == 201
        goal = resp.json()
        goal_id = goal["id"]

        assert "cost_so_far_usd" in goal, "Goal response must include cost_so_far_usd"
        assert "max_cost_usd" in goal, "Goal response must include max_cost_usd"
        assert float(goal["cost_so_far_usd"]) == 0.0, "New goal cost should start at 0"
        assert float(goal["max_cost_usd"]) == 5.0

        await orchestrator.delete(f"/api/v1/goals/{goal_id}", headers=admin_headers)

    async def test_task_detail_includes_cost(self, orchestrator, admin_headers):
        """Task detail endpoint must return total_cost_usd for cortex to read.
        Requires service rebuild after the pipeline_router.py SELECT fix."""
        # Find any existing task to check response schema
        resp = await orchestrator.get(
            "/api/v1/pipeline/tasks",
            headers=admin_headers,
            params={"limit": 1},
        )
        if resp.status_code != 200:
            pytest.skip("Tasks list endpoint not available")

        tasks = resp.json()
        tasks = tasks.get("tasks", tasks) if isinstance(tasks, dict) else tasks
        if not tasks:
            pytest.skip("No tasks exist to verify schema")

        task_id = tasks[0]["id"] if isinstance(tasks[0], dict) else tasks[0]
        resp = await orchestrator.get(
            f"/api/v1/pipeline/tasks/{task_id}", headers=admin_headers,
        )
        assert resp.status_code == 200
        task = resp.json()
        if "total_cost_usd" not in task:
            pytest.fail(
                "Task detail must include total_cost_usd for cortex cost rollup. "
                "Rebuild services to pick up the pipeline_router.py SELECT fix."
            )

    async def test_goal_stats_includes_cost(self, orchestrator, admin_headers):
        """Goal stats endpoint must aggregate cost data."""
        resp = await orchestrator.get("/api/v1/goals/stats", headers=admin_headers)
        assert resp.status_code == 200
        stats = resp.json()
        assert "total_cost_usd" in stats, "Goal stats must include total_cost_usd"


class TestGoalContext:
    """Verify goals carry enough context for LLM planning."""

    async def test_goal_with_description(self, orchestrator, admin_headers):
        """Goals should accept and return descriptions for planning context."""
        resp = await orchestrator.post("/api/v1/goals", headers=admin_headers, json={
            "title": "nova-test-described-goal",
            "description": "Scan configured feeds for AI research papers and summarize findings.",
            "success_criteria": "At least 3 summaries produced.",
        })
        assert resp.status_code == 201
        goal = resp.json()
        goal_id = goal["id"]

        assert goal["description"] == "Scan configured feeds for AI research papers and summarize findings."
        # success_criteria should persist if the schema supports it
        if "success_criteria" in goal:
            assert goal["success_criteria"] == "At least 3 summaries produced."

        await orchestrator.delete(f"/api/v1/goals/{goal_id}", headers=admin_headers)

    async def test_goal_iteration_fields(self, orchestrator, admin_headers):
        """Goals must track iteration/max_iterations for progress calculation."""
        resp = await orchestrator.post("/api/v1/goals", headers=admin_headers, json={
            "title": "nova-test-iteration-tracking",
            "max_iterations": 25,
        })
        assert resp.status_code == 201
        goal = resp.json()
        goal_id = goal["id"]

        assert goal["iteration"] == 0
        assert goal["max_iterations"] == 25
        assert "progress" in goal

        await orchestrator.delete(f"/api/v1/goals/{goal_id}", headers=admin_headers)

    async def test_system_goals_have_descriptions(self, orchestrator, admin_headers):
        """System goals must have descriptions — bare titles cause the LLM to skip."""
        system_goal_ids = [
            "d0000000-0000-0000-0000-000000000001",
            "d0000000-0000-0000-0000-000000000002",
            "d0000000-0000-0000-0000-000000000003",
        ]
        for goal_id in system_goal_ids:
            resp = await orchestrator.get(f"/api/v1/goals/{goal_id}", headers=admin_headers)
            if resp.status_code != 200:
                continue
            goal = resp.json()
            assert goal.get("description"), (
                f"System goal '{goal['title']}' must have a description "
                "for the cortex planner to generate actionable plans"
            )

    async def test_goal_current_plan_field(self, orchestrator, admin_headers):
        """Goals should expose current_plan for tracking last task status."""
        resp = await orchestrator.post("/api/v1/goals", headers=admin_headers, json={
            "title": "nova-test-plan-field",
        })
        assert resp.status_code == 201
        goal = resp.json()
        goal_id = goal["id"]

        assert "current_plan" in goal, "Goal must expose current_plan for cortex tracking"

        await orchestrator.delete(f"/api/v1/goals/{goal_id}", headers=admin_headers)
