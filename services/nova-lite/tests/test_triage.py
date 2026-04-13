import json
import pytest
from app.logic.triage import classify_and_create


SAMPLE_EVENT = {
    "id": "event-1",
    "type": "ha.state_changed",
    "source": "home_assistant",
    "subject": "light.living_room turned on",
    "payload": {"entity_id": "light.living_room", "new_state": "on"},
    "timestamp": "2026-04-13T10:00:00Z",
}


def test_creates_task_with_llm_fields(fake_client):
    fake_client._llm_response = json.dumps({
        "title": "Living room light turned on",
        "description": "HA state change detected",
        "priority": "low",
        "risk_class": "low",
        "labels": ["home_assistant"],
    })
    task = classify_and_create(fake_client, SAMPLE_EVENT)
    assert task["title"] == "Living room light turned on"
    assert task["priority"] == "low"
    assert task["origin_event_id"] == "event-1"
    assert "home_assistant" in task["labels"]


def test_falls_back_to_event_subject_on_parse_failure(fake_client):
    fake_client._llm_response = "I cannot parse this as JSON, sorry."
    task = classify_and_create(fake_client, SAMPLE_EVENT)
    assert task["title"] == SAMPLE_EVENT["subject"]
    assert task["origin_event_id"] == "event-1"


def test_falls_back_on_missing_title_key(fake_client):
    fake_client._llm_response = json.dumps({"priority": "high"})
    task = classify_and_create(fake_client, SAMPLE_EVENT)
    assert task["title"] == SAMPLE_EVENT["subject"]


def test_falls_back_on_llm_error(fake_client):
    from app.client import NovaClientError
    def fail_llm_route(*args, **kwargs):
        raise NovaClientError(503, "LLM unavailable")
    fake_client.llm_route = fail_llm_route
    task = classify_and_create(fake_client, SAMPLE_EVENT)
    assert task["title"] == SAMPLE_EVENT["subject"]
    assert task["origin_event_id"] == "event-1"


def test_dedup_skips_creation_if_task_exists(fake_client):
    existing = fake_client.post_task({
        "title": "existing", "origin_event_id": "event-1"
    })
    fake_client._llm_response = json.dumps({"title": "new task"})
    result = classify_and_create(fake_client, SAMPLE_EVENT)
    assert result["id"] == existing["id"]
    assert len(fake_client.tasks) == 1
