from datetime import datetime, timedelta, timezone

import pytest

from app.logic.scheduler import _in_active_hours, _is_due, fire_due_triggers


# ── _is_due ────────────────────────────────────────────────────────────────

def test_is_due_never_fired():
    trigger = {"enabled": True, "cron_expression": "*/30 * * * *", "last_fired_at": None}
    assert _is_due(trigger, datetime.now(timezone.utc)) is True


def test_is_due_recently_fired():
    now = datetime(2026, 4, 16, 10, 5, tzinfo=timezone.utc)
    recent = datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc).isoformat()
    trigger = {"enabled": True, "cron_expression": "*/30 * * * *", "last_fired_at": recent}
    assert _is_due(trigger, now) is False


def test_is_due_cron_occurrence_reached():
    now = datetime(2026, 4, 16, 10, 30, tzinfo=timezone.utc)
    last = datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc).isoformat()
    trigger = {"enabled": True, "cron_expression": "*/30 * * * *", "last_fired_at": last}
    assert _is_due(trigger, now) is True


def test_is_due_catchup_once():
    """If Nova was offline for multiple cron occurrences, fire exactly once on catch-up."""
    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    last = datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc).isoformat()
    trigger = {"enabled": True, "cron_expression": "*/30 * * * *", "last_fired_at": last}
    assert _is_due(trigger, now) is True


def test_is_due_disabled_trigger():
    trigger = {"enabled": False, "cron_expression": "* * * * *", "last_fired_at": None}
    assert _is_due(trigger, datetime.now(timezone.utc)) is False


# ── _in_active_hours ────────────────────────────────────────────────────────

def test_in_active_hours_no_restriction():
    trigger = {"active_hours_start": None, "active_hours_end": None}
    assert _in_active_hours(trigger, datetime.now(timezone.utc)) is True


def test_in_active_hours_within_window():
    now = datetime(2026, 4, 16, 14, 30, tzinfo=timezone.utc)
    trigger = {"active_hours_start": "09:00", "active_hours_end": "22:00"}
    assert _in_active_hours(trigger, now) is True


def test_in_active_hours_outside_window():
    now = datetime(2026, 4, 16, 3, 0, tzinfo=timezone.utc)
    trigger = {"active_hours_start": "09:00", "active_hours_end": "22:00"}
    assert _in_active_hours(trigger, now) is False


def test_in_active_hours_boundary_start():
    now = datetime(2026, 4, 16, 9, 0, tzinfo=timezone.utc)
    trigger = {"active_hours_start": "09:00", "active_hours_end": "22:00"}
    assert _in_active_hours(trigger, now) is True


def test_in_active_hours_start_only_is_always_active():
    trigger = {"active_hours_start": "09:00", "active_hours_end": None}
    assert _in_active_hours(trigger, datetime.now(timezone.utc)) is True


def test_in_active_hours_end_only_is_always_active():
    trigger = {"active_hours_start": None, "active_hours_end": "22:00"}
    assert _in_active_hours(trigger, datetime.now(timezone.utc)) is True


# ── fire_due_triggers ────────────────────────────────────────────────────────

def _make_trigger(trigger_id="system-heartbeat", last_fired_offset_seconds=None):
    now = datetime.now(timezone.utc)
    last_fired = None
    if last_fired_offset_seconds is not None:
        last_fired = (now - timedelta(seconds=last_fired_offset_seconds)).isoformat()
    return {
        "id": trigger_id,
        "name": "System Heartbeat",
        "enabled": True,
        # Every 30 minutes — mirrors the original `interval_seconds=1800` semantics
        # used by existing `fire_due_triggers` tests. A 60s offset sits inside the
        # 30-minute window so `test_fire_due_skips_recent_trigger` correctly returns 0.
        "cron_expression": "*/30 * * * *",
        "last_fired_at": last_fired,
        "active_hours_start": None,
        "active_hours_end": None,
        "payload_template": {"tool": "nova.system_health", "input": {}},
    }


def test_fire_due_fires_overdue_trigger(fake_client):
    fake_client.scheduled_triggers = [_make_trigger(last_fired_offset_seconds=2000)]
    count = fire_due_triggers(fake_client)
    assert count == 1
    assert len(fake_client.posted_events) == 1
    event = fake_client.posted_events[0]
    assert event["type"] == "scheduled.system-heartbeat"
    assert event["source"] == "scheduler"
    assert "system-heartbeat" in fake_client.patched_triggers
    assert fake_client.patched_triggers["system-heartbeat"]["last_fired_at"] is not None


def test_fire_due_fires_never_fired_trigger(fake_client):
    fake_client.scheduled_triggers = [_make_trigger(last_fired_offset_seconds=None)]
    count = fire_due_triggers(fake_client)
    assert count == 1


def test_fire_due_skips_recent_trigger(fake_client):
    fake_client.scheduled_triggers = [_make_trigger(last_fired_offset_seconds=60)]
    count = fire_due_triggers(fake_client)
    assert count == 0
    assert len(fake_client.posted_events) == 0


def test_fire_due_skips_disabled_trigger(fake_client):
    trigger = _make_trigger()
    trigger["enabled"] = False
    fake_client.scheduled_triggers = [trigger]
    count = fire_due_triggers(fake_client)
    assert count == 0


def test_fire_due_multiple_triggers_mixed(fake_client):
    fake_client.scheduled_triggers = [
        _make_trigger("heartbeat", last_fired_offset_seconds=2000),
        _make_trigger("summary", last_fired_offset_seconds=60),
    ]
    count = fire_due_triggers(fake_client)
    assert count == 1
    assert fake_client.posted_events[0]["type"] == "scheduled.heartbeat"


def test_fire_due_handles_client_error_gracefully(fake_client):
    from app.client import NovaClientError

    def raise_error():
        raise NovaClientError(503, "unavailable")

    fake_client.get_scheduled_triggers = raise_error
    count = fire_due_triggers(fake_client)
    assert count == 0


def test_fire_due_event_contains_trigger_id_in_payload(fake_client):
    fake_client.scheduled_triggers = [_make_trigger(last_fired_offset_seconds=2000)]
    fire_due_triggers(fake_client)
    assert fake_client.posted_events[0]["payload"]["trigger_id"] == "system-heartbeat"
