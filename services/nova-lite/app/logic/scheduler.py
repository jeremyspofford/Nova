"""
Check which scheduled triggers are due (cron-based) and emit an event for each.

Each fired trigger claims its interval first (PATCH last_fired_at), then emits
the event. Patch-first ordering means a transient API failure during firing
will cost at most one missed event rather than spam the event stream on every
subsequent tick until the patch eventually lands.
"""
import logging
from datetime import datetime, timezone

from croniter import croniter

from app.client import NovaClientError

log = logging.getLogger(__name__)

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_last_fired(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_due(trigger: dict, now: datetime) -> bool:
    """Return True if the trigger's next cron occurrence has passed since last_fired."""
    if not trigger.get("enabled"):
        return False
    last_fired = _parse_last_fired(trigger.get("last_fired_at"))
    base = last_fired or _EPOCH
    next_fire = croniter(trigger["cron_expression"], base).get_next(datetime)
    return now >= next_fire


def _in_active_hours(trigger: dict, now: datetime) -> bool:
    """Return True if current UTC time is within the trigger's active window.

    If either bound is missing, the trigger is considered always active.
    Midnight-wrapping windows (start > end, e.g. "22:00"–"06:00") are not
    supported: that configuration makes the comparison impossible and the
    trigger will never fire.
    """
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
            client.patch_scheduled_trigger(trigger_id, {"last_fired_at": now.isoformat()})
            client.post_event({
                "type": f"scheduled.{trigger_id}",
                "source": "scheduler",
                "subject": trigger["name"],
                "payload": {**trigger.get("payload_template", {}), "trigger_id": trigger_id},
                "correlation_id": trigger_id,
            })
            log.info("Fired scheduled trigger: %s", trigger_id)
            fired += 1
        except NovaClientError as exc:
            log.warning("Failed to fire trigger %s: %s", trigger_id, exc)

    return fired
