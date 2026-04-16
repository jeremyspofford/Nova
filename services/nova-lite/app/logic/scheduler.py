"""
Check which scheduled triggers are due and emit an event for each.

Each fired trigger:
  1. POSTs to /events with type "scheduled.{trigger_id}"
  2. PATCHes the trigger's last_fired_at so it won't re-fire this interval
"""
import logging
from datetime import datetime, timezone

from app.client import NovaClientError

log = logging.getLogger(__name__)


def _is_due(trigger: dict, now: datetime) -> bool:
    """Return True if the trigger should fire now."""
    if not trigger.get("enabled"):
        return False
    last_fired = trigger.get("last_fired_at")
    if last_fired is None:
        return True
    if isinstance(last_fired, str):
        last_fired_dt = datetime.fromisoformat(last_fired.replace("Z", "+00:00"))
    else:
        last_fired_dt = last_fired
    return (now - last_fired_dt).total_seconds() >= trigger["interval_seconds"]


def _in_active_hours(trigger: dict, now: datetime) -> bool:
    """Return True if current UTC time is within the trigger's active window."""
    start = trigger.get("active_hours_start")
    end = trigger.get("active_hours_end")
    if not start or not end:
        return True
    current = now.strftime("%H:%M")
    return start <= current <= end


def fire_due_triggers(client) -> int:
    """
    Fetch all triggers, fire those that are due, return the count fired.
    Errors from individual trigger firing are logged and skipped — never raised.
    """
    try:
        triggers = client.get_scheduled_triggers()
    except NovaClientError as exc:
        log.warning("Could not fetch scheduled triggers: %s", exc)
        return 0

    now = datetime.now(timezone.utc)
    fired = 0

    for trigger in triggers:
        if not _is_due(trigger, now) or not _in_active_hours(trigger, now):
            continue

        trigger_id = trigger["id"]
        try:
            client.post_event({
                "type": f"scheduled.{trigger_id}",
                "source": "scheduler",
                "subject": trigger["name"],
                "payload": {
                    **trigger.get("payload_template", {}),
                    "trigger_id": trigger_id,
                },
                "correlation_id": trigger_id,
            })
            client.patch_scheduled_trigger(trigger_id, {
                "last_fired_at": now.isoformat(),
            })
            log.info("Fired scheduled trigger: %s", trigger_id)
            fired += 1
        except NovaClientError as exc:
            log.warning("Failed to fire trigger %s: %s", trigger_id, exc)

    return fired
