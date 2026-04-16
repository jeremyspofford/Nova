import datetime as _dt
import json
import logging

from app.client import NovaClientError
from app.logic.utils import _extract_json

log = logging.getLogger(__name__)


def _build_triage_prompt(event: dict) -> str:
    return (
        "You are a task triage assistant. Given this event, create a task.\n\n"
        f"Event type: {event.get('type')}\n"
        f"Source: {event.get('source')}\n"
        f"Subject: {event.get('subject')}\n"
        f"Payload: {json.dumps(event.get('payload', {}))}\n\n"
        "Respond with JSON only (no markdown, no explanation):\n"
        '{"title": "...", "description": "...", "priority": "low|normal|high|urgent", '
        '"risk_class": "low|medium|high", "labels": ["..."]}'
    )


def _parse_triage_response(response: str) -> dict | None:
    """Parse LLM JSON response. Returns None if response is not valid JSON with a title."""
    try:
        data = json.loads(_extract_json(response))
        if "title" not in data or not data["title"]:
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None


def _handle_scheduler_tool_event(client, event: dict, payload: dict) -> dict | None:
    """Invoke the tool directly; return task-create dict if action_needed, else None.

    `client.invoke_tool` returns the /tools/{name}/invoke envelope:
        {"run_id", "status": "succeeded|failed", "output": {<handler output>}, "error"}
    The handler's escalation status lives in `output.status`.
    """
    tool_name = payload["tool"]
    tool_input = payload.get("input", {})
    envelope = client.invoke_tool(tool_name, tool_input)

    if envelope.get("status") == "failed":
        log.warning("scheduler tool %s failed: %s", tool_name, envelope.get("error"))
        return {
            "title": f"{tool_name} failed",
            "description": envelope.get("error") or "tool invocation failed",
            "priority": "normal",
            "risk_class": "low",
            "origin_event_id": event["id"],
            "labels": ["scheduler", tool_name, "tool-failure"],
        }

    output = envelope.get("output") or {}
    handler_status = output.get("status")
    if handler_status == "ok":
        return None
    if handler_status == "action_needed":
        return {
            "title": output.get("title") or event.get("subject") or tool_name,
            "description": output.get("description"),
            "priority": "normal",
            "risk_class": "low",
            "origin_event_id": event["id"],
            "labels": ["scheduler", tool_name],
        }
    log.warning(
        "scheduler tool %s returned unknown handler status %r; treating as action_needed",
        tool_name, handler_status,
    )
    return {
        "title": event.get("subject") or tool_name,
        "description": str(output),
        "priority": "normal",
        "risk_class": "low",
        "origin_event_id": event["id"],
        "labels": ["scheduler", tool_name, "unexpected-shape"],
    }


def _handle_scheduler_goal_event(event: dict, payload: dict) -> dict:
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    trigger_name = event.get("subject") or payload.get("trigger_id") or "scheduled goal"
    return {
        "title": f"{trigger_name} — {today}",
        "description": payload["goal"],
        "priority": "normal",
        "risk_class": "low",
        "origin_event_id": event["id"],
        "labels": ["scheduler", "goal"],
    }


def classify_and_create(client, event: dict) -> dict | None:
    """Given an event, classify it and create a Task. Deduplicates by origin_event_id."""
    existing = client.get_tasks(origin_event_id=event["id"], limit=1)
    if existing:
        log.debug("Task already exists for event %s, skipping", event["id"])
        return existing[0]

    # ── Scheduler-source fast path ──
    if event.get("source") == "scheduler":
        payload = event.get("payload") or {}
        if "tool" in payload:
            task_fields = _handle_scheduler_tool_event(client, event, payload)
            if task_fields is None:
                return None  # clean — no task, Run record is the activity
            return client.post_task(task_fields)
        if "goal" in payload:
            return client.post_task(_handle_scheduler_goal_event(event, payload))
        log.warning("scheduler event %s has neither tool nor goal in payload; falling through to LLM", event["id"])

    # ── LLM classify path (existing behavior) ──
    prompt = _build_triage_prompt(event)
    try:
        response = client.llm_route(
            purpose="triage",
            messages=[{"role": "user", "content": prompt}],
        )
        fields = _parse_triage_response(response)
    except NovaClientError as exc:
        log.warning("LLM unavailable during triage for event %s: %s", event["id"], exc)
        fields = None

    if fields is None:
        log.warning(
            "Triage LLM response unparseable for event %s, using subject as title",
            event["id"],
        )
        fields = {}

    return client.post_task({
        "title": fields.get("title") or event["subject"],
        "description": fields.get("description"),
        "priority": fields.get("priority", "normal"),
        "risk_class": fields.get("risk_class", "low"),
        "origin_event_id": event["id"],
        "labels": fields.get("labels", []),
    })
