import pytest
from unittest.mock import patch
from app.models.llm_provider import LLMProviderProfile


def make_provider(db, id="p1", provider_type="local"):
    p = LLMProviderProfile(
        id=id,
        name="Test Provider",
        provider_type=provider_type,
        endpoint_ref="http://localhost:11434/v1",
        model_ref="gemma3:4b",
        enabled=True,
        supports_tools=False,
        supports_streaming=False,
        privacy_class="local_only",
        cost_class="low",
        latency_class="medium",
    )
    db.add(p)
    db.commit()
    return p


def test_llm_route_503_when_no_providers(client):
    response = client.post("/llm/route", json={
        "purpose": "triage",
        "input": {"messages": [{"role": "user", "content": "hi"}]},
    })
    assert response.status_code == 503
    assert "No LLM providers" in response.json()["detail"]


def test_llm_route_503_local_required_with_cloud_only(client, db_session):
    make_provider(db_session, provider_type="cloud")
    response = client.post("/llm/route", json={
        "purpose": "triage",
        "input": {"messages": [{"role": "user", "content": "hi"}]},
        "privacy_preference": "local_required",
    })
    assert response.status_code == 503


def test_llm_route_success(client, db_session):
    make_provider(db_session)
    with patch("app.llm_client._call_provider_real", return_value="mocked response"):
        response = client.post("/llm/route", json={
            "purpose": "triage",
            "input": {"messages": [{"role": "user", "content": "hello"}]},
        })
    assert response.status_code == 200
    data = response.json()
    assert data["output"] == "mocked response"
    assert data["provider_id"] == "p1"
    assert data["model_ref"] == "gemma3:4b"


def test_llm_route_502_when_provider_fails(client, db_session):
    make_provider(db_session)
    with patch("app.llm_client._call_provider_real", side_effect=RuntimeError("connection refused")):
        response = client.post("/llm/route", json={
            "purpose": "triage",
            "input": {"messages": [{"role": "user", "content": "hi"}]},
        })
    assert response.status_code == 502
