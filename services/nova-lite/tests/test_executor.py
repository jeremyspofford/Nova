from app.logic.executor import execute
from app.logic.planner import Action, Plan


def test_execute_invokes_each_action(fake_client):
    """execute() calls invoke_tool for each action in the plan."""
    plan = Plan(
        actions=[
            Action(tool_name="debug.echo", input={"x": 1}, reason="test"),
            Action(tool_name="debug.echo", input={"x": 2}, reason="test"),
        ]
    )
    task = {"id": "task-1"}
    fake_client._invoke_result = {"run_id": "r1", "status": "succeeded"}

    results = execute(fake_client, task, plan)
    assert len(results) == 2
    assert all(r["status"] == "succeeded" for r in results)


def test_execute_empty_plan_returns_empty_list(fake_client):
    plan = Plan(actions=[])
    results = execute(fake_client, {"id": "task-1"}, plan)
    assert results == []
