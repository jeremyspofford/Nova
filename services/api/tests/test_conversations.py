import json
from unittest.mock import patch

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


def make_provider_in_db(db_session):
    from app.models.llm_provider import LLMProviderProfile
    p = LLMProviderProfile()
    p.id = "test-provider"
    p.name = "test"
    p.provider_type = "local"
    p.endpoint_ref = "http://localhost:11434/v1"
    p.model_ref = "qwen2.5-coder:7b"
    p.enabled = True
    p.supports_tools = True
    p.supports_streaming = True
    p.privacy_class = "local_only"
    p.cost_class = "low"
    p.latency_class = "medium"
    db_session.add(p)
    db_session.commit()


def fake_streaming_caller(provider, messages):
    yield "Hello"
    yield " Nova"


def text_only_route_with_tools(content: str):
    """Helper: mock route_with_tools to return plain text (no tool_calls)."""
    return {"content": content}


def test_send_message_non_streaming(client, db_session):
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()

    # Phase 1 returns no tool_calls so Phase 2 runs via route() → _call_provider_real.
    with patch("app.llm_client.route_with_tools", return_value={"content": ""}), \
         patch("app.llm_client._call_provider_real", lambda p, m: "Non-streaming reply"):
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "hello", "stream": False},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["role"] == "assistant"
    assert data["content"] == "Non-streaming reply"
    assert data["conversation_id"] == conv["id"]


def test_send_message_persists_user_message(client, db_session):
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()

    with patch("app.llm_client.route_with_tools", return_value={"content": ""}), \
         patch("app.llm_client._call_provider_real", lambda p, m: "ok"):
        client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "my question", "stream": False},
        )

    msgs = client.get(f"/conversations/{conv['id']}/messages").json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "my question"
    assert msgs[1]["role"] == "assistant"


def test_send_message_sse_streams_chunks(client, db_session):
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()

    with patch("app.llm_client.route_with_tools", return_value={"content": ""}), \
         patch("app.llm_client._call_provider_streaming_real", fake_streaming_caller):
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "hi", "stream": True},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    lines = [l for l in resp.text.split("\n") if l.startswith("data: ")]
    events = [json.loads(l[6:]) for l in lines]
    deltas = [e["delta"] for e in events if "delta" in e]
    assert deltas == ["Hello", " Nova"]
    assert events[-1].get("complete") is True


def test_send_message_sse_persists_assistant_message(client, db_session):
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()

    with patch("app.llm_client.route_with_tools", return_value={"content": ""}), \
         patch("app.llm_client._call_provider_streaming_real", fake_streaming_caller):
        client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "hi", "stream": True},
        )

    msgs = client.get(f"/conversations/{conv['id']}/messages").json()["messages"]
    assert any(m["role"] == "assistant" and m["content"] == "Hello Nova" for m in msgs)


def test_send_message_sets_title_from_first_message(client, db_session):
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()
    assert conv["title"] == "New Chat"

    with patch("app.llm_client.route_with_tools", return_value={"content": ""}), \
         patch("app.llm_client._call_provider_real", lambda p, m: "reply"):
        client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "Turn on the living room lights please", "stream": False},
        )

    convs = client.get("/conversations").json()["conversations"]
    assert convs[0]["title"] == "Turn on the living room lights please"


def test_send_message_title_truncates_at_word_boundary(client, db_session):
    make_provider_in_db(db_session)
    conv = client.post("/conversations").json()
    long_msg = "This is a very long message that definitely exceeds fifty characters total here"

    with patch("app.llm_client.route_with_tools", return_value={"content": ""}), \
         patch("app.llm_client._call_provider_real", lambda p, m: "ok"):
        client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": long_msg, "stream": False},
        )

    convs = client.get("/conversations").json()["conversations"]
    title = convs[0]["title"]
    assert len(title) <= 50
    assert not title.endswith(" ")  # no trailing space
    assert title == "This is a very long message that definitely"


def test_send_message_conversation_not_found(client):
    resp = client.post(
        "/conversations/nonexistent/messages",
        json={"content": "hi"},
    )
    assert resp.status_code == 404


def test_tool_call_executes_and_creates_run(client, db_session):
    """When route_with_tools emits a tool_call, the tool runs and a Run row is created."""
    make_provider_in_db(db_session)
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    conv = client.post("/conversations").json()

    # First turn returns a tool_call; second turn returns content (Phase 1 exits loop);
    # Phase 2 then streams the final reply via _call_provider_real.
    with patch(
        "app.llm_client.route_with_tools",
        side_effect=[
            {"tool_calls": [{"name": "debug.echo", "arguments": {"message": "hi"}}]},
            {"content": ""},  # unused; Phase 2 uses route()
        ],
    ), patch("app.llm_client._call_provider_real", lambda p, m: "Done!"):
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "echo hi", "stream": False},
        )

    assert resp.status_code == 201
    from app.models.run import Run
    runs = db_session.query(Run).all()
    assert len(runs) == 1
    assert runs[0].tool_name == "debug.echo"
    assert runs[0].trigger_type == "chat"
    assert runs[0].status == "succeeded"
    assert runs[0].summary == "debug.echo \u2192 succeeded"


def test_unknown_tool_call_records_failed_run(client, db_session):
    """When route_with_tools emits a bogus tool name, Run is recorded as failed."""
    make_provider_in_db(db_session)
    from app.tools.seed import seed_tools
    seed_tools(db_session)
    conv = client.post("/conversations").json()

    with patch(
        "app.llm_client.route_with_tools",
        side_effect=[
            {"tool_calls": [{"name": "nonexistent.tool", "arguments": {}}]},
            {"content": ""},
        ],
    ), patch("app.llm_client._call_provider_real", lambda p, m: "I couldn't find that tool."):
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "do the thing", "stream": False},
        )

    assert resp.status_code == 201
    from app.models.run import Run
    runs = db_session.query(Run).all()
    assert len(runs) == 1
    assert runs[0].tool_name == "nonexistent.tool"
    assert runs[0].status == "failed"
    assert runs[0].error is not None
