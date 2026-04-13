import json
import logging

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
        data = json.loads(response)
        if "title" not in data or not data["title"]:
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None


def classify_and_create(client, event: dict) -> dict:
    """Given an event, use LLM to classify it and create a Task. Deduplicates by origin_event_id."""
    existing = client.get_tasks(origin_event_id=event["id"], limit=1)
    if existing:
        log.debug("Task already exists for event %s, skipping", event["id"])
        return existing[0]

    prompt = _build_triage_prompt(event)
    response = client.llm_route(
        purpose="triage",
        messages=[{"role": "user", "content": prompt}],
    )

    fields = _parse_triage_response(response)
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
