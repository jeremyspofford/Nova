def test_create_task_minimal(client):
    response = client.post("/tasks", json={"title": "test task"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "test task"
    assert "id" in data
    assert data["status"] == "inbox"
    assert data["priority"] == "normal"
    assert data["risk_class"] == "low"
    assert data["approval_required"] is False
    assert data["last_decision"] == "none"
    assert data["labels"] == []
    assert data["metadata"] == {}


def test_create_task_missing_title(client):
    response = client.post("/tasks", json={})
    assert response.status_code == 422


def test_list_tasks_empty(client):
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == {"tasks": []}


def test_list_tasks_returns_created(client):
    client.post("/tasks", json={"title": "task one"})
    client.post("/tasks", json={"title": "task two"})
    response = client.get("/tasks")
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert len(tasks) == 2


def test_list_tasks_filter_by_status(client):
    client.post("/tasks", json={"title": "inbox task"})
    response = client.get("/tasks?status=inbox")
    assert response.status_code == 200
    assert len(response.json()["tasks"]) == 1

    response = client.get("/tasks?status=done")
    assert response.status_code == 200
    assert len(response.json()["tasks"]) == 0


def test_get_task_by_id(client):
    created = client.post("/tasks", json={"title": "find me"}).json()
    response = client.get(f"/tasks/{created['id']}")
    assert response.status_code == 200
    assert response.json()["title"] == "find me"


def test_get_task_not_found(client):
    response = client.get("/tasks/nonexistent-id")
    assert response.status_code == 404


def test_patch_task(client):
    created = client.post("/tasks", json={"title": "old title"}).json()
    response = client.patch(
        f"/tasks/{created['id']}",
        json={"title": "new title", "status": "ready"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "new title"
    assert data["status"] == "ready"


def test_patch_task_not_found(client):
    response = client.patch("/tasks/nonexistent-id", json={"title": "x"})
    assert response.status_code == 404
