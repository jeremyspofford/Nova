"""Tests for the two-phase tool-calling loop in conversations."""
from datetime import datetime, timezone
from unittest.mock import patch


def make_provider_in_db(db_session):
    """Seed a local provider so route_streaming / route_with_tools have a target."""
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
    """Shaped like _call_provider_streaming_real — yields chunks."""
    yield "You have 2 triggers: system-heartbeat and daily-summary."


def test_non_sensitive_tool_call_auto_executes(client, db_session):
    """A non-sensitive tool call executes immediately, no confirmation gate."""
    make_provider_in_db(db_session)
    from app.tools.seed import seed_tools
    seed_tools(db_session)

    # First call returns a tool_call for nova.query_activity (non-sensitive); second returns text.
    with patch("app.llm_client.route_with_tools") as mock_llm, \
         patch("app.llm_client._call_provider_streaming_real", fake_streaming_caller):
        mock_llm.side_effect = [
            {"tool_calls": [{"name": "nova.query_activity", "arguments": {"limit": 5}}]},
            {"content": "You have 2 triggers: system-heartbeat and daily-summary."},
        ]

        conv = client.post("/conversations").json()
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "list my recent runs"},
        )

        text = resp.text
        assert "2 triggers" in text or "system-heartbeat" in text

    # Run row should have been recorded for the auto-executed tool call.
    from app.models.run import Run
    runs = db_session.query(Run).all()
    assert len(runs) == 1
    assert runs[0].tool_name == "nova.query_activity"
    assert runs[0].trigger_type == "chat"


def test_sensitive_tool_call_stores_pending(client, db_session):
    """scheduler.create_trigger is intercepted and prompts for confirmation."""
    make_provider_in_db(db_session)
    from app.tools.seed import seed_tools
    seed_tools(db_session)

    with patch("app.llm_client.route_with_tools") as mock_llm:
        mock_llm.return_value = {"tool_calls": [{
            "name": "scheduler.create_trigger",
            "arguments": {
                "id": "sideproject-daily",
                "name": "SideProject daily",
                "cron_expression": "0 9 * * *",
                "payload_template": {"goal": "Check r/SideProject"},
            },
        }]}

        conv = client.post("/conversations").json()
        resp = client.post(
            f"/conversations/{conv['id']}/messages",
            json={"content": "create a trigger: every day 9am check reddit"},
        )
        assert "Confirm" in resp.text

    from app.models.conversation import Conversation
    db_session.expire_all()
    conv_row = db_session.query(Conversation).filter_by(id=conv["id"]).first()
    assert conv_row.pending_tool_call is not None
    assert conv_row.pending_tool_call["name"] == "scheduler.create_trigger"


def test_confirmation_yes_commits_pending(client, db_session):
    """User says 'yes' → pending dispatched, cleared."""
    make_provider_in_db(db_session)
    from app.models.conversation import Conversation

    conv = Conversation(
        id="c-1",
        title="test",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        pending_tool_call={
            "name": "scheduler.create_trigger",
            "arguments": {
                "id": "test-t",
                "name": "Test",
                "cron_expression": "0 9 * * *",
                "payload_template": {"goal": "test"},
            },
        },
        pending_tool_call_at=datetime.now(timezone.utc),
    )
    db_session.add(conv)
    db_session.commit()

    # Mock the dispatch so it doesn't actually execute scheduler.create_trigger
    # (that tool doesn't exist yet — Task 9 adds it). Patch tool_handlers.dispatch.
    with patch("app.tools.handlers.dispatch", return_value={"summary": "Created trigger"}):
        resp = client.post("/conversations/c-1/messages", json={"content": "yes"})

    assert resp.status_code == 200 or resp.status_code == 201
    db_session.expire_all()
    conv = db_session.query(Conversation).filter_by(id="c-1").first()
    assert conv.pending_tool_call is None


def test_confirmation_no_clears_pending(client, db_session):
    """User says 'no' → pending cleared, 'Cancelled.' streamed."""
    make_provider_in_db(db_session)
    from app.models.conversation import Conversation

    conv = Conversation(
        id="c-2",
        title="test",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        pending_tool_call={"name": "scheduler.create_trigger", "arguments": {}},
        pending_tool_call_at=datetime.now(timezone.utc),
    )
    db_session.add(conv)
    db_session.commit()

    resp = client.post("/conversations/c-2/messages", json={"content": "no"})

    db_session.expire_all()
    conv = db_session.query(Conversation).filter_by(id="c-2").first()
    assert conv.pending_tool_call is None
    assert "Cancelled" in resp.text or "cancelled" in resp.text.lower()


def test_whole_word_confirm_yesterday_does_not_match():
    """'yesterday' must NOT match the 'yes' confirmation pattern."""
    from app.routers.conversations import CONFIRM_RE
    assert CONFIRM_RE.search("yesterday") is None
    assert CONFIRM_RE.search("yes") is not None
    assert CONFIRM_RE.search("yes please") is not None
