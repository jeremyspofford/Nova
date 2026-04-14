import logging
from app.client import NovaClientError
from app.logic.planner import Plan

log = logging.getLogger(__name__)


def execute(client, task: dict, plan: Plan) -> list[dict]:
    """Invoke each planned action. Returns list of run result dicts."""
    results = []
    for action in plan.actions:
        try:
            run = client.invoke_tool(action.tool_name, action.input, task_id=task["id"])
        except NovaClientError as exc:
            log.warning(
                "Tool %s failed for task %s: %s", action.tool_name, task["id"], exc
            )
            return results  # return partial results; caller marks task as failed
        log.info(
            "Tool %s invoked for task %s: run %s status=%s",
            action.tool_name, task["id"], run.get("run_id"), run.get("status"),
        )
        results.append(run)
    return results
