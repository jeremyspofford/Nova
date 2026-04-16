def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "db" in data


def test_health_includes_model_ready(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "model_ready" in data
    assert isinstance(data["model_ready"], bool)
