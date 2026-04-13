import json
import pytest
from app.logic.planner import plan, Action, Plan


SAMPLE_TASK = {
    "id": "task-1",
    "title": "Turn on living room light",
    "description": "User requested light on",
    "goal": None,
    "status": "inbox",
    "risk_class": "low",
}

SAMPLE_TOOLS = [
    {
        "name": "ha.light.turn_on",
        "display_name": "HA: Turn On Light",
        "description": "Turns on a Home Assistant light entity.",
        "input_schema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]},
    },
    {
        "name": "debug.echo",
        "display_name": "Debug Echo",
        "description": "Returns its input unchanged.",
        "input_schema": {"type": "object"},
    },
]


def test_plan_returns_actions_from_llm(fake_client):
    fake_client.tools = SAMPLE_TOOLS
    fake_client._llm_response = json.dumps({
        "actions": [
            {"tool_name": "ha.light.turn_on", "input": {"entity_id": "light.living_room"}, "reason": "User requested"},
        ],
        "reasoning": "Turning on the light as requested.",
    })
    result = plan(fake_client, SAMPLE_TASK)
    assert isinstance(result, Plan)
    assert len(result.actions) == 1
    assert result.actions[0].tool_name == "ha.light.turn_on"
    assert result.actions[0].input == {"entity_id": "light.living_room"}
    assert "turning on" in result.reasoning.lower()


def test_plan_returns_empty_actions_when_no_action_needed(fake_client):
    fake_client.tools = SAMPLE_TOOLS
    fake_client._llm_response = json.dumps({
        "actions": [],
        "reasoning": "Nothing to do.",
    })
    result = plan(fake_client, SAMPLE_TASK)
    assert result.actions == []
    assert result.reasoning == "Nothing to do."


def test_plan_falls_back_to_empty_on_parse_failure(fake_client):
    fake_client.tools = SAMPLE_TOOLS
    fake_client._llm_response = "I don't know what to do here."
    result = plan(fake_client, SAMPLE_TASK)
    assert isinstance(result, Plan)
    assert result.actions == []


def test_plan_caps_at_three_actions(fake_client):
    fake_client.tools = SAMPLE_TOOLS
    actions = [
        {"tool_name": "debug.echo", "input": {"n": i}, "reason": f"step {i}"}
        for i in range(5)
    ]
    fake_client._llm_response = json.dumps({"actions": actions, "reasoning": "many steps"})
    result = plan(fake_client, SAMPLE_TASK)
    assert len(result.actions) <= 3


def test_plan_falls_back_to_empty_on_nova_client_error(fake_client):
    from app.client import NovaClientError
    fake_client.tools = SAMPLE_TOOLS

    def raise_error(**kwargs):
        raise NovaClientError(503, "LLM unavailable")

    fake_client.llm_route = raise_error
    result = plan(fake_client, SAMPLE_TASK)
    assert isinstance(result, Plan)
    assert result.actions == []
