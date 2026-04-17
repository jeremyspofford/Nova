"""AQ-004: schema-validation exhaustion must raise, not return best-effort dict.

Covers both the inner contract (``BaseAgent._validate_schema`` raises ``ValueError``
after retry exhaustion) and the outer seam (``executor._run_agent``'s exception
handler routes the raised failure to the pod's ``on_failure`` policy).

All tests mock the LLM boundary and DB boundary — no live services, no I/O.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from app.pipeline.agents.base import BaseAgent, PipelineState


class _StrictOutput(BaseModel):
    """Pydantic schema used to force validation failure — required_field has no default."""
    required_field: str = Field(...)


# ─────────────────────────────────────────────────────────────────────────────
# _validate_schema — direct unit tests against BaseAgent
# ─────────────────────────────────────────────────────────────────────────────

async def test_validate_schema_raises_on_double_failure():
    """After retry-with-schema also fails validation, ``_validate_schema`` must raise.

    The old fail-open contract returned ``parsed`` (the raw pre-retry dict) with a
    ``logger.warning``. New contract: raise ``ValueError`` so the upstream
    ``_run_agent`` exception handler can route to the pod's ``on_failure`` policy.
    """
    agent = BaseAgent(model="mock-model")

    messages = [{"role": "user", "content": "hi"}]
    parsed = {"unrelated_field": "wrong"}  # missing required_field
    raw = '{"unrelated_field": "wrong"}'

    # Mock the retry LLM call to return something that still fails schema
    with patch.object(
        agent, "_call_llm", AsyncMock(return_value='{"still_wrong": true}'),
    ):
        with pytest.raises(ValueError, match=r"schema|valid"):
            await agent._validate_schema(
                parsed=parsed,
                raw_response=raw,
                messages=messages,
                output_schema=_StrictOutput,
                purpose="unit_test",
            )


async def test_validate_schema_error_carries_agent_role_and_purpose():
    """The raised ValueError must carry enough detail for the executor exception
    handler to build a useful error_context (stage, message, retryable=False)."""
    agent = BaseAgent(model="mock-model")
    agent.ROLE = "code_review"  # simulate a subclass

    with patch.object(
        agent, "_call_llm", AsyncMock(return_value='{"totally": "wrong"}'),
    ):
        with pytest.raises(ValueError) as excinfo:
            await agent._validate_schema(
                parsed={"bad": "dict"},
                raw_response='{"bad": "dict"}',
                messages=[{"role": "user", "content": "x"}],
                output_schema=_StrictOutput,
                purpose="code_review_verdict",
            )

    # Error message must include the agent role so the executor's logger.error
    # + error_context can attribute the failure.
    assert "code_review" in str(excinfo.value)

    # The exception must chain to the underlying validation error (via `raise ... from`)
    # so post-mortems can see the actual schema violation.
    assert excinfo.value.__cause__ is not None


async def test_validate_schema_stores_last_raw_output_on_exhaustion():
    """After exhaustion, ``self._last_raw_output`` must be set so the
    executor's post-mortem path can persist it to ``agent_sessions.output``."""
    agent = BaseAgent(model="mock-model")
    retry_raw = '{"still": "wrong"}'

    with patch.object(agent, "_call_llm", AsyncMock(return_value=retry_raw)):
        with pytest.raises(ValueError):
            await agent._validate_schema(
                parsed={"bad": "dict"},
                raw_response='{"bad": "dict"}',
                messages=[{"role": "user", "content": "x"}],
                output_schema=_StrictOutput,
                purpose="unit_test",
            )

    assert agent._last_raw_output is not None, (
        "Agent must stash the last raw LLM output for post-mortem debugging"
    )


async def test_validate_schema_returns_on_retry_success():
    """Sanity: if the retry produces valid output, return the validated dict
    (Pydantic-dumped) — the fail-open change must not regress the happy path."""
    agent = BaseAgent(model="mock-model")

    with patch.object(
        agent, "_call_llm",
        AsyncMock(return_value='{"required_field": "now-correct"}'),
    ):
        result = await agent._validate_schema(
            parsed={"unrelated": "wrong"},
            raw_response='{"unrelated": "wrong"}',
            messages=[{"role": "user", "content": "hi"}],
            output_schema=_StrictOutput,
            purpose="unit_test",
        )

    assert result == {"required_field": "now-correct"}


async def test_validate_schema_returns_on_first_attempt_success():
    """Sanity: if ``parsed`` already satisfies the schema, no retry LLM call is made."""
    agent = BaseAgent(model="mock-model")

    # If _call_llm fires, it would blow up (this is the assertion) — the test
    # proves the happy path short-circuits before the retry.
    call_llm = AsyncMock(side_effect=AssertionError("retry should not happen"))
    with patch.object(agent, "_call_llm", call_llm):
        result = await agent._validate_schema(
            parsed={"required_field": "already-correct"},
            raw_response='{"required_field": "already-correct"}',
            messages=[{"role": "user", "content": "hi"}],
            output_schema=_StrictOutput,
            purpose="unit_test",
        )

    assert result == {"required_field": "already-correct"}
    call_llm.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# executor._run_agent — exception path routes to on_failure policy
# ─────────────────────────────────────────────────────────────────────────────

def _make_agent_row(role: str = "code_review", on_failure: str = "abort") -> MagicMock:
    """Build a minimal AgentRow-shaped mock matching the dataclass at executor.py:129."""
    agent_row = MagicMock()
    agent_row.id = "00000000-0000-0000-0000-000000000001"
    agent_row.name = f"test-{role}"
    agent_row.role = role
    agent_row.enabled = True
    agent_row.position = 0
    agent_row.parallel_group = None
    agent_row.model = "mock-model"
    agent_row.fallback_models = []
    agent_row.temperature = 0.3
    agent_row.max_tokens = 4096
    agent_row.timeout_seconds = 60
    agent_row.max_retries = 1
    agent_row.system_prompt = None
    agent_row.allowed_tools = []
    agent_row.on_failure = on_failure
    agent_row.run_condition = {}
    agent_row.artifact_type = None
    return agent_row


def _make_pod_row() -> MagicMock:
    pod = MagicMock()
    pod.id = "00000000-0000-0000-0000-000000000002"
    pod.name = "test-pod"
    pod.default_model = "mock-model"
    pod.max_cost_usd = None
    pod.max_execution_seconds = 600
    pod.require_human_review = "never"
    pod.escalation_threshold = "high"
    pod.sandbox = "workspace"
    return pod


async def _run_executor_with_raising_agent(
    on_failure: str,
    raising_exc: Exception,
) -> tuple[object, object, AsyncMock, AsyncMock]:
    """Helper: execute ``_run_agent`` with an agent class whose ``.run()`` raises,
    mocking out every DB/IO call. Returns ``(result_dict, session_id, mark_task_failed_mock,
    pause_for_review_mock)``."""
    from app.pipeline import executor

    agent_row = _make_agent_row(role="code_review", on_failure=on_failure)
    pod = _make_pod_row()
    state = PipelineState(task_input="hi")

    # A fake agent class whose constructor accepts the kwargs BaseAgent takes,
    # and whose run() raises the given exception — simulates _validate_schema
    # failing deep inside the agent's run path.
    raised = raising_exc

    class _RaisingAgent:
        DEFAULT_SYSTEM = "test"

        def __init__(self, **kwargs):
            self._usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "llm_calls": 0}
            self._training_log = []
            self._last_raw_output = "<<raw output stashed by _validate_schema>>"

        async def run(self, state, **kwargs):
            raise raised

    fake_agent_classes = {"code_review": _RaisingAgent}

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        # Swap the agent class registry so our raising agent is used
        patch.dict(
            "app.pipeline.executor.__dict__",
            {"AGENT_CLASSES_TEST_OVERRIDE": fake_agent_classes},
        ),
        # Patch the lazy model resolvers — they'd otherwise try DB/config lookups
        patch("app.pipeline.executor.get_pool", return_value=mock_pool),
        patch("app.model_resolver.resolve_default_model", AsyncMock(return_value="mock-model")),
        patch("app.pipeline.stage_model_resolver.resolve_stage_model", AsyncMock(return_value=None)),
        patch("app.pipeline.complexity_model_map.resolve_complexity_model", AsyncMock(return_value=None)),
        patch("app.pipeline.executor._create_session", AsyncMock(return_value="session-123")),
        patch("app.pipeline.executor._set_task_status", AsyncMock()),
        patch("app.pipeline.executor._complete_session", AsyncMock()),
        patch("app.pipeline.executor._fail_session", AsyncMock()),
        patch("app.pipeline.executor._write_training_logs", AsyncMock()),
        patch("app.pipeline.executor._pause_for_human_review", AsyncMock()) as pause_mock,
        patch("app.pipeline.executor.mark_task_failed", AsyncMock()) as fail_mock,
        # Patch the agent-class lookup by monkeypatching the import targets
        patch("app.pipeline.agents.code_review.CodeReviewAgent", _RaisingAgent),
        # log_usage is called for adaptive-routing scoring — best-effort, mock it
        patch("app.usage.log_usage", MagicMock()),
    ):
        result = await executor._run_agent(
            agent_row,
            task_id="task-123",
            state=state,
            pod=pod,
        )

    return result, raised, fail_mock, pause_mock


async def test_executor_on_failure_abort_marks_task_failed_when_agent_raises():
    """``on_failure=abort``: a raising agent triggers ``mark_task_failed`` and
    returns ``(None, session_id)``. Locks the contract that ``_validate_schema``'s
    new ``raise ValueError`` behavior flows through to a clean task failure."""
    raised = ValueError(
        "Agent code_review could not produce schema-valid output after retry"
    )
    result, _raised, fail_mock, pause_mock = await _run_executor_with_raising_agent(
        on_failure="abort",
        raising_exc=raised,
    )

    output, session_id = result
    assert output is None, "abort path must return None so the pipeline halts"
    assert session_id == "session-123"
    fail_mock.assert_awaited_once()
    # error_context must carry the stage and a retryable=False hint (ValueError is non-retryable)
    call_kwargs = fail_mock.await_args.kwargs
    assert "code_review" in call_kwargs["error"]
    assert call_kwargs["error_context"]["stage"] == "code_review"
    assert call_kwargs["error_context"]["retryable"] is False
    pause_mock.assert_not_awaited()


async def test_executor_on_failure_skip_returns_empty_dict_when_agent_raises():
    """``on_failure=skip``: the pipeline continues with an empty result for this agent."""
    raised = ValueError(
        "Agent code_review could not produce schema-valid output after retry"
    )
    result, _raised, fail_mock, pause_mock = await _run_executor_with_raising_agent(
        on_failure="skip",
        raising_exc=raised,
    )

    output, session_id = result
    assert output == {}, "skip path must return empty dict so the pipeline continues"
    assert session_id == "session-123"
    fail_mock.assert_not_awaited()
    pause_mock.assert_not_awaited()


async def test_executor_on_failure_escalate_pauses_for_human_review():
    """``on_failure=escalate``: the pipeline pauses for human review."""
    raised = ValueError(
        "Agent code_review could not produce schema-valid output after retry"
    )
    result, _raised, fail_mock, pause_mock = await _run_executor_with_raising_agent(
        on_failure="escalate",
        raising_exc=raised,
    )

    output, session_id = result
    assert output is None, "escalate path must halt the pipeline (None result)"
    assert session_id == "session-123"
    pause_mock.assert_awaited_once()
    fail_mock.assert_not_awaited()
