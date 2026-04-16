from datetime import datetime, timedelta, timezone

import pytest

from app.logic.scheduler import _in_active_hours, _is_due, fire_due_triggers


# ── _is_due ────────────────────────────────────────────────────────────────

def test_is_due_never_fired():
    trigger = {"enabled": True, "interval_seconds": 1800, "last_fired_at": None}
    assert _is_due(trigger, datetime.now(timezone.utc)) is True


def test_is_due_recently_fired():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=60)).isoformat()
    trigger = {"enabled": True, "interval_seconds": 1800, "last_fired_at": recent}
    assert _is_due(trigger, now) is False


def test_is_due_interval_exactly_elapsed():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=1800)).isoformat()
    trigger = {"enabled": True, "interval_seconds": 1800, "last_fired_at": old}
    assert _is_due(trigger, now) is True


def test_is_due_interval_overdue():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=3600)).isoformat()
    trigger = {"enabled": True, "interval_seconds": 1800, "last_fired_at": old}
    assert _is_due(trigger, now) is True


def test_is_due_disabled_trigger():
    trigger = {"enabled": False, "interval_seconds": 1800, "last_fired_at": None}
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
        "interval_seconds": 1800,
        "last_fired_at": last_fired,
        "active_hours_start": None,
        "active_hours_end": None,
        "payload_template": {"check": "system_health"},
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
