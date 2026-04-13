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
