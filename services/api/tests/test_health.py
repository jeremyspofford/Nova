def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "db" in data


def test_system_info(client):
    response = client.get("/system/info")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "nova-api"
    assert "version" in data
    assert "deployment_mode" in data
