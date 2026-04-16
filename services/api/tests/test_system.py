import pytest


def test_list_triggers_empty(client):
    resp = client.get("/system/triggers")
    assert resp.status_code == 200
    assert resp.json()["triggers"] == []


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
