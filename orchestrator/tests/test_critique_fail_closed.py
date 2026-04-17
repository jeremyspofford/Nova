"""AQ-001: critique agents must fail-closed on malformed LLM output.

Unit tests mock _call_llm to return non-JSON. The agents should then
route through think_json's retry-with-feedback, and on exhaustion default
to needs_revision (Direction) / fail (Acceptance) and log at ERROR level.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline.agents.base import PipelineState
from app.pipeline.agents.critique import (
    CritiqueAcceptanceAgent,
    CritiqueDirectionAgent,
)


def _make_state() -> PipelineState:
    return PipelineState(
        task_input="Write a function to sort a list",
        completed={"task": {"output": "def sort(x): return sorted(x)"}},
    )


async def test_critique_direction_fail_closed_on_malformed_json(caplog):
    """Direction returns needs_revision (not approved) when LLM can't produce JSON."""
    caplog.set_level(logging.DEBUG)

    agent = CritiqueDirectionAgent(model="mock-model")
    # Return non-JSON twice (think_json retries once with feedback, total=2)
    with patch.object(
        agent, "_call_llm",
        AsyncMock(side_effect=["not json at all", "still not {json"]),
    ):
        result = await agent.run(_make_state())

    assert result["verdict"] == "needs_revision", (
        f"Expected fail-closed needs_revision, got {result['verdict']}"
    )
    # Should NOT be the old fail-open default
    assert result["verdict"] != "approved"

    # ERROR-level log must fire — not WARNING — because this is a safety gate
    # firing in failure mode
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("critique" in r.getMessage().lower() for r in error_records), (
        f"Expected an ERROR-level critique log. Records: {[r.getMessage() for r in error_records]}"
    )


async def test_critique_acceptance_fail_closed_on_malformed_json(caplog):
    """Acceptance returns fail (not pass) when LLM can't produce JSON."""
    caplog.set_level(logging.DEBUG)

    agent = CritiqueAcceptanceAgent(model="mock-model")
    with patch.object(
        agent, "_call_llm",
        AsyncMock(side_effect=["gibberish", "also not json"]),
    ):
        result = await agent.run(_make_state())

    assert result["verdict"] == "fail", (
        f"Expected fail-closed fail, got {result['verdict']}"
    )
    assert result["verdict"] != "pass"

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("critique" in r.getMessage().lower() for r in error_records), (
        f"Expected an ERROR-level critique log. Records: {[r.getMessage() for r in error_records]}"
    )
