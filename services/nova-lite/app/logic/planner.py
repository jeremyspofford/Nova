import json
import logging
from dataclasses import dataclass, field

from app.client import NovaClientError

log = logging.getLogger(__name__)

MAX_ACTIONS = 3


@dataclass
class Action:
    tool_name: str
    input: dict
    reason: str


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    reasoning: str = ""


def _build_plan_prompt(task: dict, tools: list[dict]) -> str:
    tool_descriptions = "\n".join(
        f"- {t['name']}: {t['description']} | input_schema: {json.dumps(t.get('input_schema', {}))}"
        for t in tools
    )
    return (
        "You are a task planner. Given this task and available tools, decide what actions to take.\n\n"
        f"Task: {task['title']}\n"
        f"Description: {task.get('description') or 'none'}\n"
        f"Goal: {task.get('goal') or 'none'}\n\n"
        f"Available tools:\n{tool_descriptions}\n\n"
        f"Respond with JSON only (no markdown). Use 0–{MAX_ACTIONS} actions:\n"
        '{"actions": [{"tool_name": "...", "input": {...}, "reason": "..."}], "reasoning": "..."}'
    )


def _parse_plan_response(response: str) -> Plan:
    try:
        data = json.loads(response)
        raw_actions = data.get("actions", [])[:MAX_ACTIONS]
        actions = [
            Action(
                tool_name=a["tool_name"],
                input=a.get("input", {}),
                reason=a.get("reason", ""),
            )
            for a in raw_actions
            if isinstance(a, dict) and "tool_name" in a
        ]
        return Plan(actions=actions, reasoning=data.get("reasoning", ""))
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        log.warning("Failed to parse plan response: %s", e)
        return Plan()


def plan(client, task: dict) -> Plan:
    """Given a task in inbox/ready, ask LLM for 0-3 tool actions."""
    try:
        tools = client.get_tools()
    except NovaClientError as exc:
        log.warning("Could not fetch tools for task %s: %s", task.get("id"), exc)
        return Plan()
    prompt = _build_plan_prompt(task, tools)
    try:
        response = client.llm_route(
            purpose="plan",
            messages=[{"role": "user", "content": prompt}],
        )
    except NovaClientError as exc:
        log.warning("LLM unavailable during planning for task %s: %s", task.get("id"), exc)
        return Plan()
    return _parse_plan_response(response)
