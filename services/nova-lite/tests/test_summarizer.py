from app.logic.summarizer import summarize
from app.logic.planner import Action, Plan


def test_summarize_calls_llm_and_returns_string(fake_client):
    """summarize() calls llm_route and returns its output string."""
    fake_client._llm_response = "Task completed successfully."
    plan = Plan(
        actions=[Action(tool_name="debug.echo", input={}, reason="test")],
        reasoning="just echoing",
    )
    results = [{"run_id": "r1", "status": "succeeded"}]
    result = summarize(fake_client, {"id": "t1", "title": "Test"}, plan, results)
    assert result == "Task completed successfully."


def test_summarize_with_no_actions(fake_client):
    fake_client._llm_response = "Nothing needed."
    result = summarize(fake_client, {"id": "t1", "title": "Test"}, Plan(), [])
    assert result == "Nothing needed."


def test_summarize_returns_empty_string_on_llm_error(fake_client):
    from app.client import NovaClientError
    def raise_error(**kwargs):
        raise NovaClientError(503, "unavailable")
    fake_client.llm_route = raise_error
    result = summarize(fake_client, {"id": "t1", "title": "Test"}, Plan(), [])
    assert result == ""
