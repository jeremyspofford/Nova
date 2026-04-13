from datetime import datetime, timezone, timedelta


def test_post_event_returns_id_and_timestamp(client):
    response = client.post("/events", json={
        "type": "test.event",
        "source": "test",
        "subject": "Test event",
    })
    assert response.status_code == 201
    data = response.json()
    assert set(data.keys()) == {"id", "timestamp"}
    assert data["id"]
    assert data["timestamp"]


def test_post_event_missing_required_fields(client):
    response = client.post("/events", json={"type": "test.event"})
    assert response.status_code == 422


def test_post_event_optional_fields(client):
    response = client.post("/events", json={
        "type": "ha.state_changed",
        "source": "home_assistant",
        "subject": "light.living_room",
        "payload": {"new_state": "on"},
        "priority": "high",
        "risk_class": "medium",
        "actor_type": "user",
    })
    assert response.status_code == 201


def test_get_events_empty(client):
    response = client.get("/events")
    assert response.status_code == 200
    assert response.json() == {"events": []}


def test_get_events_returns_posted(client):
    client.post("/events", json={"type": "t", "source": "s", "subject": "sub"})
    response = client.get("/events")
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "t"
    assert events[0]["source"] == "s"


def test_get_events_since_filter(client):
    # Post event A
    r_a = client.post("/events", json={"type": "t", "source": "s", "subject": "A"})
    ts_a = r_a.json()["timestamp"]

    # Post event B after A
    client.post("/events", json={"type": "t", "source": "s", "subject": "B"})

    # Query since ts_a — should return only B
    response = client.get(f"/events?since={ts_a}")
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    assert events[0]["subject"] == "B"


def test_get_events_type_filter(client):
    client.post("/events", json={"type": "type.a", "source": "s", "subject": "x"})
    client.post("/events", json={"type": "type.b", "source": "s", "subject": "y"})
    response = client.get("/events?type=type.a")
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "type.a"


def test_get_events_limit(client):
    for i in range(5):
        client.post("/events", json={"type": "t", "source": "s", "subject": str(i)})
    response = client.get("/events?limit=2")
    assert response.status_code == 200
    assert len(response.json()["events"]) == 2
