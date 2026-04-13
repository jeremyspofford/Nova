def test_post_approval_creates_record(client):
    task = client.post("/tasks", json={"title": "risky task"}).json()
    response = client.post(f"/tasks/{task['id']}/approvals", json={
        "summary": "Nova-lite wants to turn on all the lights",
        "consequence": "All lights in the house will turn on",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["task_id"] == task["id"]
    assert data["status"] == "pending"
    assert data["summary"] == "Nova-lite wants to turn on all the lights"
    assert data["consequence"] == "All lights in the house will turn on"
    assert data["options"] == ["approve", "deny"]  # default
    assert data["requested_by"] == "nova-lite"
    assert "id" in data
    assert data["requested_at"] is not None


def test_post_approval_moves_task_to_needs_approval(client):
    task = client.post("/tasks", json={"title": "risky task"}).json()
    client.post(f"/tasks/{task['id']}/approvals", json={"summary": "please approve"})
    updated = client.get(f"/tasks/{task['id']}").json()
    assert updated["status"] == "needs_approval"


def test_post_approval_custom_options(client):
    task = client.post("/tasks", json={"title": "task"}).json()
    response = client.post(f"/tasks/{task['id']}/approvals", json={
        "summary": "choose",
        "options": ["yes", "no", "later"],
    })
    assert response.status_code == 201
    assert response.json()["options"] == ["yes", "no", "later"]


def test_post_approval_task_not_found(client):
    response = client.post("/tasks/nonexistent/approvals", json={"summary": "test"})
    assert response.status_code == 404


def test_post_approval_conflict_on_duplicate_pending(client):
    task = client.post("/tasks", json={"title": "task"}).json()
    client.post(f"/tasks/{task['id']}/approvals", json={"summary": "first request"})
    response = client.post(f"/tasks/{task['id']}/approvals", json={"summary": "duplicate"})
    assert response.status_code == 409
