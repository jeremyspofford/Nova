import pytest


def test_create_conversation_returns_id_and_title(client):
    resp = client.post("/conversations")
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["title"] == "New Chat"
    assert "created_at" in data
    assert "updated_at" in data


def test_list_conversations_empty(client):
    resp = client.get("/conversations")
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_list_conversations_returns_created(client):
    client.post("/conversations")
    client.post("/conversations")
    resp = client.get("/conversations")
    convs = resp.json()["conversations"]
    assert len(convs) == 2
    assert "message_count" in convs[0]
    assert convs[0]["message_count"] == 0


def test_list_conversations_limit(client):
    for _ in range(12):
        client.post("/conversations")
    resp = client.get("/conversations?limit=5")
    assert len(resp.json()["conversations"]) == 5


def test_get_messages_empty(client):
    conv = client.post("/conversations").json()
    resp = client.get(f"/conversations/{conv['id']}/messages")
    assert resp.status_code == 200
    assert resp.json() == {"messages": []}


def test_get_messages_not_found(client):
    resp = client.get("/conversations/nonexistent/messages")
    assert resp.status_code == 404
