def test_get_run_by_id(client, db_session):
    from app.models.run import Run
    from datetime import datetime, timezone
    import uuid
    run = Run(
        id=str(uuid.uuid4()),
        tool_name="debug.echo",
        status="succeeded",
        executor_type="internal",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.commit()
    response = client.get(f"/runs/{run.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == run.id
    assert data["status"] == "succeeded"
    assert data["tool_name"] == "debug.echo"


def test_get_run_not_found(client):
    response = client.get("/runs/nonexistent-id")
    assert response.status_code == 404


def test_get_task_runs_not_found(client):
    response = client.get("/tasks/nonexistent-id/runs")
    assert response.status_code == 404


def test_get_task_runs_empty(client):
    # Create a task first
    r = client.post("/tasks", json={"title": "test task"})
    task_id = r.json()["id"]
    response = client.get(f"/tasks/{task_id}/runs")
    assert response.status_code == 200
    assert response.json() == {"runs": []}
