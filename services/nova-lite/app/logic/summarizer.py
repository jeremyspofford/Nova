import json
import logging
from app.logic.planner import Plan

log = logging.getLogger(__name__)


def _build_summary_prompt(task: dict, plan: Plan, results: list[dict]) -> str:
    actions_text = "\n".join(
        f"- {a.tool_name}: {json.dumps(a.input)} → {r.get('status', 'unknown')}"
        for a, r in zip(plan.actions, results)
    ) or "No actions were taken."
    return (
        "Write a one-sentence result summary for this completed task.\n\n"
        f"Task: {task.get('title')}\n"
        f"Actions taken:\n{actions_text}\n"
        f"Planner reasoning: {plan.reasoning}\n\n"
        "Respond with a single sentence only."
    )


def summarize(client, task: dict, plan: Plan, results: list[dict]) -> str:
    """Use LLM to produce a result_summary string for the task."""
    prompt = _build_summary_prompt(task, plan, results)
    return client.llm_route(
        purpose="summarize",
        messages=[{"role": "user", "content": prompt}],
    )
