def test_list_triggers_after_seed(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    resp = client.get("/system/triggers")
    assert resp.status_code == 200
    triggers = resp.json()["triggers"]
    assert len(triggers) == 2
    ids = {t["id"] for t in triggers}
    assert "system-heartbeat" in ids
    assert "daily-summary" in ids


def test_patch_trigger_enabled(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    resp = client.patch("/system/triggers/system-heartbeat", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_patch_trigger_last_fired_at(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    ts = "2026-04-16T12:00:00+00:00"
    resp = client.patch("/system/triggers/system-heartbeat", json={"last_fired_at": ts})
    assert resp.status_code == 200
    assert resp.json()["last_fired_at"] is not None


def test_patch_trigger_not_found(client):
    resp = client.patch("/system/triggers/nonexistent", json={"enabled": False})
    assert resp.status_code == 404


def test_patch_trigger_rejects_invalid_cron(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    resp = client.patch("/system/triggers/system-heartbeat", json={"cron_expression": "not a cron"})
    assert resp.status_code == 422


def test_patch_trigger_rejects_malformed_active_hours(client, db_session):
    from app.tools.seed import seed_scheduled_triggers
    seed_scheduled_triggers(db_session)
    resp = client.patch("/system/triggers/system-heartbeat", json={"active_hours_start": "9am"})
    assert resp.status_code == 422


def test_seed_preserves_user_modifications(db_session):
    from app.tools.seed import seed_scheduled_triggers
    from app.models.scheduled_trigger import ScheduledTrigger

    seed_scheduled_triggers(db_session)
    row = db_session.query(ScheduledTrigger).filter_by(id="system-heartbeat").first()
    row.enabled = False
    row.cron_expression = "0 12 * * *"
    db_session.commit()

    seed_scheduled_triggers(db_session)  # re-seed
    db_session.refresh(row)
    assert row.enabled is False
    assert row.cron_expression == "0 12 * * *"
    assert row.name == "System Heartbeat"


def test_system_info(client):
    resp = client.get("/system/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "nova-api"
    assert "version" in data
    assert "deployment_mode" in data
