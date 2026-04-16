import pytest


def test_scheduler_create_trigger_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_create_trigger
    result = handle_scheduler_create_trigger({
        "id": "my-trigger",
        "name": "My Trigger",
        "cron_expression": "0 9 * * *",
        "payload_template": {"goal": "Check something"},
    }, db_session)
    assert "my-trigger" in result["summary"]

    from app.models.scheduled_trigger import ScheduledTrigger
    assert db_session.query(ScheduledTrigger).filter_by(id="my-trigger").first() is not None


def test_scheduler_list_triggers_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_list_triggers
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    result = handle_scheduler_list_triggers({}, db_session)
    ids = {t["id"] for t in result["triggers"]}
    assert "system-heartbeat" in ids
    assert "daily-summary" in ids


def test_scheduler_update_trigger_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_update_trigger
    from app.tools.seed import seed_scheduled_triggers
    from app.models.scheduled_trigger import ScheduledTrigger
    seed_scheduled_triggers(db_session)
    result = handle_scheduler_update_trigger({
        "id": "system-heartbeat",
        "updates": {"enabled": False},
    }, db_session)
    db_session.expire_all()
    trigger = db_session.query(ScheduledTrigger).filter_by(id="system-heartbeat").first()
    assert trigger.enabled is False


def test_scheduler_delete_trigger_handler(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_delete_trigger
    from app.tools.seed import seed_scheduled_triggers
    from app.models.scheduled_trigger import ScheduledTrigger
    seed_scheduled_triggers(db_session)
    result = handle_scheduler_delete_trigger({"id": "daily-summary"}, db_session)
    assert "daily-summary" in result["summary"]
    assert db_session.query(ScheduledTrigger).filter_by(id="daily-summary").first() is None


def test_scheduler_create_invalid_cron_raises(db_session):
    from app.tools.scheduler_handlers import handle_scheduler_create_trigger
    with pytest.raises(Exception):  # Pydantic ValidationError wrapped
        handle_scheduler_create_trigger({
            "id": "bad",
            "name": "Bad",
            "cron_expression": "not a cron",
            "payload_template": {"goal": "x"},
        }, db_session)
