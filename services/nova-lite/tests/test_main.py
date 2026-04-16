import pytest
import json
from app.logic.planner import Plan, Action
from app.main import process_task


def test_process_task_posts_approval_for_high_risk(fake_client):
    """High-risk tasks get posted to /approvals and processing stops there."""
    task = {
        "id": "task-1",
        "title": "Delete all files",
        "description": "risky op",
        "risk_class": "high",
        "approval_required": False,
        "status": "pending",
    }
    fake_client.tasks["task-1"] = task
    process_task(fake_client, task)
    assert "task-1" in fake_client.approvals


def test_process_task_posts_approval_when_approval_required(fake_client):
    """Tasks with approval_required=True also trigger approval."""
    task = {
        "id": "task-2",
        "title": "Send email",
        "risk_class": "low",
        "approval_required": True,
        "status": "pending",
    }
    fake_client.tasks["task-2"] = task
    process_task(fake_client, task)
    assert "task-2" in fake_client.approvals


def test_process_task_marks_done_when_no_actions(fake_client):
    """If planner returns empty actions, task is marked done with a summary."""
    task = {
        "id": "task-3",
        "title": "Check something",
        "risk_class": "low",
        "approval_required": False,
        "status": "pending",
    }
    fake_client.tasks["task-3"] = task
    fake_client._llm_response = json.dumps({"actions": [], "reasoning": "Nothing to do."})

    process_task(fake_client, task)
    assert fake_client.tasks["task-3"]["status"] == "done"
    assert "Nothing to do." in fake_client.tasks["task-3"]["result_summary"]


def test_process_task_runs_to_done_on_success(fake_client):
    """Happy path: plan → execute → summarize → done."""
    task = {
        "id": "task-4",
        "title": "Echo something",
        "risk_class": "low",
        "approval_required": False,
        "status": "pending",
    }
    fake_client.tasks["task-4"] = task
    fake_client.tools = [{"name": "debug.echo", "description": "echo", "input_schema": {}}]

    responses = iter([
        json.dumps({
            "actions": [{"tool_name": "debug.echo", "input": {"x": 1}, "reason": "test"}],
            "reasoning": "Echoing.",
        }),
        "Task completed: echoed successfully.",
    ])
    fake_client.llm_route = lambda purpose, messages, privacy_preference="local_preferred": next(responses)
    fake_client._invoke_result = {"run_id": "r1", "status": "succeeded"}

    process_task(fake_client, task)
    assert fake_client.tasks["task-4"]["status"] == "done"
    assert fake_client.tasks["task-4"]["result_summary"] == "Task completed: echoed successfully."


def test_process_task_marks_failed_when_tool_fails(fake_client):
    """If any run status is not 'succeeded', task ends as failed."""
    task = {
        "id": "task-5",
        "title": "Broken tool",
        "risk_class": "low",
        "approval_required": False,
        "status": "pending",
    }
    fake_client.tasks["task-5"] = task
    fake_client.tools = [{"name": "debug.echo", "description": "echo", "input_schema": {}}]

    responses = iter([
        json.dumps({
            "actions": [{"tool_name": "debug.echo", "input": {}, "reason": "test"}],
            "reasoning": "Trying.",
        }),
        "Tool failed.",
    ])
    fake_client.llm_route = lambda purpose, messages, privacy_preference="local_preferred": next(responses)
    fake_client._invoke_result = {"run_id": "r2", "status": "failed"}

    process_task(fake_client, task)
    assert fake_client.tasks["task-5"]["status"] == "failed"


def test_process_task_marks_failed_when_executor_raises(fake_client):
    """If executor returns empty results (tool error on first call), task should be failed."""
    from app.client import NovaClientError
    task = {
        "id": "task-6",
        "title": "Failing tool",
        "risk_class": "low",
        "approval_required": False,
        "status": "pending",
    }
    fake_client.tasks["task-6"] = task
    fake_client.tools = [{"name": "debug.echo", "description": "echo", "input_schema": {}}]

    responses = iter([
        json.dumps({
            "actions": [{"tool_name": "debug.echo", "input": {}, "reason": "test"}],
            "reasoning": "Trying.",
        }),
        "Tool crashed.",
    ])
    fake_client.llm_route = lambda purpose, messages, privacy_preference="local_preferred": next(responses)

    # First invoke_tool call raises NovaClientError → executor returns []
    def fail_invoke(tool_name, input, task_id=None):
        raise NovaClientError(500, "tool crashed")
    fake_client.invoke_tool = fail_invoke

    process_task(fake_client, task)
    assert fake_client.tasks["task-6"]["status"] == "failed"


def test_process_task_handles_ready_status(fake_client):
    """Tasks with status='ready' (post-approval) are processed the same as pending."""
    fake_client.tools = [{"name": "debug.echo", "description": "echo", "input_schema": {}}]
    fake_client._llm_response = '{"actions": [], "reasoning": "nothing to do"}'
    task = {
        "id": "task-ready-1",
        "title": "Approved task",
        "status": "ready",
        "risk_class": "low",
        "approval_required": False,
        "description": None,
        "goal": None,
    }
    fake_client.tasks["task-ready-1"] = task  # required: FakeClient.patch_task looks up by id
    process_task(fake_client, task)
    assert fake_client.tasks["task-ready-1"]["status"] == "done"
