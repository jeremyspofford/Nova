from app.logic import triage


def test_scheduler_tool_event_bypasses_llm(fake_client):
    event = {
        "id": "evt-1",
        "type": "scheduled.system-heartbeat",
        "source": "scheduler",
        "subject": "System Heartbeat",
        "payload": {"tool": "nova.system_health", "input": {}, "trigger_id": "system-heartbeat"},
    }
    fake_client._invoke_result_by_tool = {
        "nova.system_health": {"status": "ok", "message": "all clear"},
    }

    triage.classify_and_create(fake_client, event)

    # No LLM call should have happened (fake_client._llm_response was never consumed)
    # No task should have been created for ok status
    assert len(fake_client.tasks) == 0


def test_scheduler_tool_event_ok_creates_no_task(fake_client):
    event = {
        "id": "evt-1", "type": "scheduled.x", "source": "scheduler",
        "subject": "X", "payload": {"tool": "nova.system_health", "input": {}, "trigger_id": "x"},
    }
    fake_client._invoke_result_by_tool = {
        "nova.system_health": {"status": "ok", "message": "all clear"},
    }
    triage.classify_and_create(fake_client, event)
    assert len(fake_client.tasks) == 0


def test_scheduler_tool_event_action_needed_creates_task(fake_client):
    event = {
        "id": "evt-1", "type": "scheduled.x", "source": "scheduler",
        "subject": "Heartbeat", "payload": {"tool": "nova.system_health", "input": {}, "trigger_id": "x"},
    }
    fake_client._invoke_result_by_tool = {
        "nova.system_health": {
            "status": "action_needed",
            "title": "Disk at 95%",
            "description": "Free space or investigate.",
            "details": {"disk_pct": 95},
        },
    }
    triage.classify_and_create(fake_client, event)
    assert len(fake_client.tasks) == 1
    task = list(fake_client.tasks.values())[0]
    assert task["title"] == "Disk at 95%"
    assert "Free space" in task["description"]
    assert task["origin_event_id"] == "evt-1"


def test_scheduler_goal_event_creates_task_with_goal_description(fake_client):
    event = {
        "id": "evt-2", "type": "scheduled.x", "source": "scheduler",
        "subject": "SideProject daily digest",
        "payload": {"goal": "Check r/SideProject and summarize top 5 posts", "trigger_id": "x"},
    }
    triage.classify_and_create(fake_client, event)
    assert len(fake_client.tasks) == 1
    task = list(fake_client.tasks.values())[0]
    assert "SideProject daily digest" in task["title"]
    assert task["description"] == "Check r/SideProject and summarize top 5 posts"


def test_non_scheduler_event_still_uses_llm(fake_client):
    """Regression: non-scheduler events still go through the LLM classify path."""
    fake_client._llm_response = '{"title": "Classified Title", "description": "d", "priority": "normal", "risk_class": "low", "labels": []}'
    event = {
        "id": "evt-3", "type": "user.request", "source": "human",
        "subject": "x", "payload": {"message": "do the thing"},
    }
    triage.classify_and_create(fake_client, event)
    assert len(fake_client.tasks) == 1
    task = list(fake_client.tasks.values())[0]
    assert task["title"] == "Classified Title"
