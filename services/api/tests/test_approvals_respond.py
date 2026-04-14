def _create_task_with_approval(client):
    """Helper: create a task, request approval, return (task, approval)."""
    task = client.post("/tasks", json={"title": "risky"}).json()
    approval = client.post(f"/tasks/{task['id']}/approvals", json={
        "summary": "confirm action",
        "consequence": "something will happen",
    }).json()
    return task, approval


def test_get_approval_returns_record(client):
    _, approval = _create_task_with_approval(client)
    response = client.get(f"/approvals/{approval['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == approval["id"]
    assert data["status"] == "pending"
    assert data["summary"] == "confirm action"


def test_get_approval_404(client):
    response = client.get("/approvals/nonexistent")
    assert response.status_code == 404


def test_respond_approve_sets_status_and_updates_task(client):
    task, approval = _create_task_with_approval(client)
    response = client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "approve",
        "decided_by": "user",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["decision"] == "approve"
    assert data["decided_by"] == "user"
    assert data["decided_at"] is not None

    updated_task = client.get(f"/tasks/{task['id']}").json()
    assert updated_task["status"] == "ready"


def test_respond_deny_sets_status_and_updates_task(client):
    task, approval = _create_task_with_approval(client)
    response = client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "deny",
        "decided_by": "user",
        "reason": "too risky",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "denied"
    assert data["reason"] == "too risky"

    updated_task = client.get(f"/tasks/{task['id']}").json()
    assert updated_task["status"] == "cancelled"


def test_respond_409_on_non_pending_approval(client):
    _, approval = _create_task_with_approval(client)
    # First response succeeds
    client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "approve", "decided_by": "user"
    })
    # Second response must 409
    response = client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "deny", "decided_by": "user"
    })
    assert response.status_code == 409


def test_respond_404_on_unknown_approval(client):
    response = client.post("/approvals/nonexistent/respond", json={
        "decision": "approve", "decided_by": "user"
    })
    assert response.status_code == 404


def test_respond_with_reason(client):
    _, approval = _create_task_with_approval(client)
    response = client.post(f"/approvals/{approval['id']}/respond", json={
        "decision": "approve",
        "decided_by": "user",
        "reason": "looks safe",
    })
    assert response.status_code == 200
    assert response.json()["reason"] == "looks safe"


def test_get_task_approvals_returns_list(client):
    task, approval = _create_task_with_approval(client)
    response = client.get(f"/tasks/{task['id']}/approvals")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == approval["id"]
    assert data[0]["status"] == "pending"


def test_get_task_approvals_empty_for_unknown_task(client):
    response = client.get("/tasks/nonexistent/approvals")
    assert response.status_code == 200
    assert response.json() == []
