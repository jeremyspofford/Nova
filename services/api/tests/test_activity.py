from datetime import datetime, timezone, timedelta
from app.models.run import Run


def _make_run(db, id="run-1", tool_name="ha.light.turn_on", status="succeeded",
              trigger_type="chat", summary=None, started_at=None, output=None):
    run = Run(
        id=id,
        tool_name=tool_name,
        task_id=None,
        executor_type="chat",
        trigger_type=trigger_type,
        status=status,
        started_at=started_at or datetime.now(timezone.utc),
        output=output or ({"status": "ok"} if status == "succeeded" else None),
        error="timeout" if status == "failed" else None,
        summary=summary or f"{tool_name} → {status}",
    )
    db.add(run)
    db.commit()
    return run


def test_get_activity_empty(client):
    resp = client.get("/activity")
    assert resp.status_code == 200
    assert resp.json() == {"entries": [], "total": 0}


def test_get_activity_returns_succeeded_run(client, db_session):
    _make_run(db_session)
    resp = client.get("/activity")
    data = resp.json()
    assert data["total"] == 1
    entry = data["entries"][0]
    assert entry["tool_name"] == "ha.light.turn_on"
    assert entry["status"] == "succeeded"
    assert entry["trigger_type"] == "chat"
    assert entry["summary"] == "ha.light.turn_on → succeeded"


def test_get_activity_excludes_queued_and_cancelled(client, db_session):
    _make_run(db_session, id="r1", status="succeeded")
    _make_run(db_session, id="r2", tool_name="http.request", status="queued")
    _make_run(db_session, id="r3", tool_name="debug.echo", status="cancelled")
    assert client.get("/activity").json()["total"] == 1


def test_get_activity_excludes_null_tool_name(client, db_session):
    run = Run(id="r-notool", tool_name=None, task_id=None, executor_type="system",
              trigger_type="agent_loop", status="succeeded",
              started_at=datetime.now(timezone.utc))
    db_session.add(run)
    db_session.commit()
    assert client.get("/activity").json()["total"] == 0


def test_get_activity_output_truncated(client, db_session):
    _make_run(db_session, id="r-big", tool_name="http.request",
              output={"body": "x" * 3000})
    entry = client.get("/activity").json()["entries"][0]
    assert entry["output"].endswith("... [truncated]")
    assert len(entry["output"]) == 2000 + len(" ... [truncated]")


def test_get_activity_pagination(client, db_session):
    now = datetime.now(timezone.utc)
    for i in range(5):
        run = Run(id=f"r-{i}", tool_name="debug.echo", status="succeeded",
                  trigger_type="chat", executor_type="chat",
                  started_at=now + timedelta(seconds=i))
        db_session.add(run)
    db_session.commit()
    d1 = client.get("/activity?limit=3&offset=0").json()
    assert d1["total"] == 5
    assert len(d1["entries"]) == 3
    d2 = client.get("/activity?limit=3&offset=3").json()
    assert d2["total"] == 5
    assert len(d2["entries"]) == 2


def test_get_activity_ordered_newest_first(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(Run(id="old", tool_name="debug.echo", status="succeeded",
                       trigger_type="chat", executor_type="chat",
                       started_at=now - timedelta(hours=1)))
    db_session.add(Run(id="new", tool_name="ha.light.turn_on", status="succeeded",
                       trigger_type="chat", executor_type="chat",
                       started_at=now))
    db_session.commit()
    entries = client.get("/activity").json()["entries"]
    assert entries[0]["id"] == "new"
    assert entries[1]["id"] == "old"
