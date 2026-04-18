"""Tests for streaming token extraction from SSE chunks."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class MockAsyncLineIterator:
    """Mock httpx async line iterator for SSE streams."""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._index]
        self._index += 1
        return line


class MockStreamResponse:
    """Mock httpx streaming response context manager."""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def aiter_lines(self):
        return MockAsyncLineIterator(self._lines)


def _make_sse_lines(deltas: list[str], input_tokens: int = 0, output_tokens: int = 0) -> list[str]:
    """Build SSE lines simulating a streaming response with a final usage chunk."""
    lines = []
    for d in deltas:
        chunk = {"delta": d, "finish_reason": None}
        lines.append(f"data: {json.dumps(chunk)}")
    # Final chunk with usage info
    final = {
        "delta": "",
        "finish_reason": "stop",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": 0.0025,
    }
    lines.append(f"data: {json.dumps(final)}")
    lines.append("data: [DONE]")
    return lines


async def test_streaming_captures_token_counts():
    """Verify run_agent_turn_streaming extracts tokens from final SSE chunk."""
    sse_lines = _make_sse_lines(["Hello", " world"], input_tokens=50, output_tokens=10)
    mock_response = MockStreamResponse(sse_lines)

    mock_llm_client = MagicMock()
    mock_llm_client.stream = MagicMock(return_value=mock_response)

    usage_calls = []

    def capture_usage(**kwargs):
        usage_calls.append(kwargs)

    with (
        patch("app.agents.runner.get_llm_client", return_value=mock_llm_client),
        patch("app.agents.runner.get_memory_client", return_value=AsyncMock()),
        patch("app.agents.runner._get_memory_context", new_callable=AsyncMock, return_value=("", 0, [], [], None)),
        patch("app.agents.runner._build_nova_context", new_callable=AsyncMock, return_value=""),
        patch("app.agents.runner._store_exchange", new_callable=AsyncMock),
        patch("app.agents.runner._resolve_tool_rounds", new_callable=AsyncMock, return_value=(
            [{"role": "user", "content": "hi"}], False
        )),
        patch("app.agents.runner.resolve_effective_tools", new_callable=AsyncMock, return_value=([], [])),
        patch("app.usage.log_usage", side_effect=capture_usage),
    ):
        from uuid import UUID
        from app.agents.runner import run_agent_turn_streaming

        deltas = []
        async for d in run_agent_turn_streaming(
            agent_id="00000000-0000-0000-0000-000000000002",
            task_id=UUID("00000000-0000-0000-0000-000000000001"),
            session_id="test-session",
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            system_prompt="You are a test.",
        ):
            deltas.append(d)

    # Runner mixes status JSON events ({"status": ...}) with text deltas.
    # The test's assertion here is that text deltas flow through to the caller.
    text_deltas = [d for d in deltas if not (d.startswith("{") and '"status"' in d)]
    assert text_deltas == ["Hello", " world"]
    assert len(usage_calls) == 1
    assert usage_calls[0]["input_tokens"] == 50
    assert usage_calls[0]["output_tokens"] == 10
    assert usage_calls[0]["cost_usd"] == 0.0025


async def test_streaming_zero_tokens_when_no_usage():
    """When provider sends no usage data, tokens remain 0."""
    lines = [
        f'data: {json.dumps({"delta": "Hi", "finish_reason": None})}',
        f'data: {json.dumps({"delta": "", "finish_reason": "stop"})}',
        "data: [DONE]",
    ]
    mock_response = MockStreamResponse(lines)

    mock_llm_client = MagicMock()
    mock_llm_client.stream = MagicMock(return_value=mock_response)

    usage_calls = []

    def capture_usage(**kwargs):
        usage_calls.append(kwargs)

    with (
        patch("app.agents.runner.get_llm_client", return_value=mock_llm_client),
        patch("app.agents.runner.get_memory_client", return_value=AsyncMock()),
        patch("app.agents.runner._get_memory_context", new_callable=AsyncMock, return_value=("", 0, [], [], None)),
        patch("app.agents.runner._build_nova_context", new_callable=AsyncMock, return_value=""),
        patch("app.agents.runner._store_exchange", new_callable=AsyncMock),
        patch("app.agents.runner._resolve_tool_rounds", new_callable=AsyncMock, return_value=(
            [{"role": "user", "content": "hi"}], False
        )),
        patch("app.agents.runner.resolve_effective_tools", new_callable=AsyncMock, return_value=([], [])),
        patch("app.usage.log_usage", side_effect=capture_usage),
    ):
        from uuid import UUID
        from app.agents.runner import run_agent_turn_streaming

        async for _ in run_agent_turn_streaming(
            agent_id="00000000-0000-0000-0000-000000000002",
            task_id=UUID("00000000-0000-0000-0000-000000000001"),
            session_id="test-session",
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            system_prompt="You are a test.",
        ):
            pass

    assert usage_calls[0]["input_tokens"] == 0
    assert usage_calls[0]["output_tokens"] == 0
