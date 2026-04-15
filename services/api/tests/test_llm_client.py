import pytest
from app.llm_client import (
    route,
    route_internal,
    route_streaming,
    NoProvidersError,
    NoMatchingProvidersError,
    AllProvidersFailed,
    LLMResult,
)
from app.models.llm_provider import LLMProviderProfile


def make_provider(id="p1", provider_type="local", enabled=True):
    p = LLMProviderProfile()
    p.id = id
    p.name = id
    p.provider_type = provider_type
    p.endpoint_ref = "http://localhost:11434/v1"
    p.model_ref = "gemma3:4b"
    p.enabled = enabled
    return p


def test_raises_no_providers_when_db_empty(db_session):
    with pytest.raises(NoProvidersError):
        route(db_session, "triage", [{"role": "user", "content": "hi"}])


def test_raises_no_matching_providers_for_local_required_with_cloud_only(db_session):
    db_session.add(make_provider(provider_type="cloud"))
    db_session.commit()
    with pytest.raises(NoMatchingProvidersError):
        route(db_session, "triage", [{"role": "user", "content": "hi"}],
              privacy_preference="local_required")


def test_local_preferred_returns_local_first(db_session):
    local = make_provider(id="local", provider_type="local")
    cloud = make_provider(id="cloud", provider_type="cloud")
    db_session.add_all([local, cloud])
    db_session.commit()

    call_order = []

    def fake_caller(provider, messages):
        call_order.append(provider.id)
        return "ok"

    result = route(db_session, "triage", [{"role": "user", "content": "hi"}],
                   _caller=fake_caller)
    assert isinstance(result, LLMResult)
    assert call_order[0] == "local"


def test_falls_back_to_cloud_when_local_fails(db_session):
    local = make_provider(id="local", provider_type="local")
    cloud = make_provider(id="cloud", provider_type="cloud")
    db_session.add_all([local, cloud])
    db_session.commit()

    def fake_caller(provider, messages):
        if provider.id == "local":
            raise RuntimeError("Ollama down")
        return "cloud response"

    result = route(db_session, "triage", [{"role": "user", "content": "hi"}],
                   privacy_preference="local_preferred", _caller=fake_caller)
    assert result.output == "cloud response"
    assert result.provider_id == "cloud"


def test_raises_all_providers_failed_when_all_fail(db_session):
    db_session.add(make_provider())
    db_session.commit()

    def fake_caller(provider, messages):
        raise RuntimeError("dead")

    with pytest.raises(AllProvidersFailed):
        route(db_session, "triage", [{"role": "user", "content": "hi"}],
              _caller=fake_caller)


def test_route_internal_is_equivalent(db_session):
    db_session.add(make_provider())
    db_session.commit()

    def fake_caller(provider, messages):
        return "internal result"

    result = route_internal(db_session, "summarize",
                            [{"role": "user", "content": "hello"}],
                            _caller=fake_caller)
    assert result == "internal result"


def test_route_streaming_yields_chunks(db_session):
    db_session.add(make_provider())
    db_session.commit()

    def fake_streaming(provider, messages):
        yield "Hello"
        yield " World"

    chunks = list(
        route_streaming(
            db_session,
            "chat",
            [{"role": "user", "content": "hi"}],
            _caller=fake_streaming,
        )
    )
    assert chunks == ["Hello", " World"]


def test_route_streaming_raises_no_providers(db_session):
    with pytest.raises(NoProvidersError):
        list(route_streaming(db_session, "chat", [{"role": "user", "content": "hi"}]))


def test_route_streaming_raises_no_matching_providers(db_session):
    db_session.add(make_provider(provider_type="cloud"))
    db_session.commit()
    with pytest.raises(NoMatchingProvidersError):
        list(
            route_streaming(
                db_session,
                "chat",
                [{"role": "user", "content": "hi"}],
                privacy_preference="local_required",
            )
        )
