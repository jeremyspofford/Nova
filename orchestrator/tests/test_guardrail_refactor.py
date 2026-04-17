"""AQ-003: guardrail findings become actionable.

Invariants locked by these tests:

  Helper shape:
    1. _build_guardrail_refactor_feedback formats findings into a redaction
       prompt that names each flagged item and the redaction instruction.
    2. _build_final_output returns a safety-message summary (not tainted output)
       when state.flags contains "guardrail_blocked".
    3. _build_final_output returns the normal Task output when no block is set.

  Control flow:
    4. _needs_rerun recognizes _guardrail_refactor_feedback and forces the Task
       agent to rerun (mirrors the pre-existing _refactor_feedback path).
    5. REMEDIABLE_GUARDRAIL_FINDING_TYPES defines exactly which finding types
       the refactor loop will act on (non-remediable types escalate instead).

  Threshold:
    6. Medium-severity findings pause for review under the new default
       escalation_threshold="medium" (previously high-or-above only).

All tests mock at the function boundary — no DB, no Redis, no LLM.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.pipeline.agents.base import PipelineState
from app.pipeline.executor import (
    REMEDIABLE_GUARDRAIL_FINDING_TYPES,
    _build_final_output,
    _build_guardrail_refactor_feedback,
    _needs_rerun,
    _should_pause_for_review,
)


# ─────────────────────────────────────────────────────────────────────────────
# _build_guardrail_refactor_feedback
# ─────────────────────────────────────────────────────────────────────────────

def test_build_guardrail_refactor_feedback_shape():
    """Feedback string must contain each finding's description + redaction prompt."""
    findings = [
        {
            "type": "prompt_injection",
            "severity": "high",
            "description": "Document contains 'IGNORE PREVIOUS INSTRUCTIONS'",
            "evidence": "line 42",
        },
        {
            "type": "pii_exposure",
            "severity": "medium",
            "description": "Email address detected: user@example.com",
            "evidence": "line 15",
        },
    ]
    feedback = _build_guardrail_refactor_feedback(findings)

    # Each finding's description must appear in the prompt so the Task Agent
    # knows exactly what to redact.
    assert "IGNORE PREVIOUS INSTRUCTIONS" in feedback
    assert "user@example.com" in feedback
    # The redaction/removal instruction must be explicit.
    assert "redact" in feedback.lower() or "remove" in feedback.lower()
    # The prompt must flag this as a safety-driven rewrite, not a normal revision.
    assert "safety" in feedback.lower() or "blocked" in feedback.lower()


def test_build_guardrail_refactor_feedback_handles_missing_fields():
    """Findings with missing optional fields (evidence) must not blow up."""
    findings = [
        {"type": "credential_leak", "severity": "high", "description": "Plaintext token"},
    ]
    feedback = _build_guardrail_refactor_feedback(findings)
    # Must include the core description
    assert "Plaintext token" in feedback
    # Must include the severity + type tags so the Task Agent can tell these
    # apart from normal code review feedback
    assert "CREDENTIAL_LEAK" in feedback.upper() or "credential_leak" in feedback
    assert "HIGH" in feedback.upper() or "high" in feedback


def test_build_guardrail_refactor_feedback_empty_findings_is_safe():
    """Zero findings edge case — refactor loop shouldn't trigger here, but the
    helper must still return a non-crashing string."""
    feedback = _build_guardrail_refactor_feedback([])
    assert isinstance(feedback, str)
    assert len(feedback) > 0  # non-empty so downstream concat doesn't break


# ─────────────────────────────────────────────────────────────────────────────
# REMEDIABLE_GUARDRAIL_FINDING_TYPES — module-level constant
# ─────────────────────────────────────────────────────────────────────────────

def test_remediable_finding_types_matches_spec():
    """The set must match the spec exactly — tightening or loosening this set
    changes the refactor-loop coverage and is a policy decision, not a bugfix."""
    assert REMEDIABLE_GUARDRAIL_FINDING_TYPES == {
        "prompt_injection",
        "pii_exposure",
        "credential_leak",
    }


# ─────────────────────────────────────────────────────────────────────────────
# _needs_rerun — guardrail path
# ─────────────────────────────────────────────────────────────────────────────

def test_needs_rerun_triggers_on_guardrail_refactor_feedback():
    """When _guardrail_refactor_feedback is in state.completed, _needs_rerun
    must return True for 'task' so the loop re-runs the Task Agent."""
    state = PipelineState(task_input="analyze this document")
    state.completed["_guardrail_refactor_feedback"] = "redact the flagged content"

    assert _needs_rerun("task", state) is True


def test_needs_rerun_still_triggers_on_refactor_feedback():
    """Regression check: the existing code_review refactor path must still work."""
    state = PipelineState(task_input="hi")
    state.completed["_refactor_feedback"] = "issue description"

    assert _needs_rerun("task", state) is True


def test_needs_rerun_false_for_non_task_roles():
    """Other stages (context, guardrail, code_review) must not be force-reran
    just because refactor feedback is present."""
    state = PipelineState(task_input="hi")
    state.completed["_guardrail_refactor_feedback"] = "redact"
    state.completed["_refactor_feedback"] = "review"

    assert _needs_rerun("context", state) is False
    assert _needs_rerun("guardrail", state) is False
    assert _needs_rerun("code_review", state) is False
    assert _needs_rerun("critique_direction", state) is False
    assert _needs_rerun("critique_acceptance", state) is False


def test_needs_rerun_false_when_no_feedback_present():
    """Clean state — no feedback keys → task does not rerun."""
    state = PipelineState(task_input="hi")
    assert _needs_rerun("task", state) is False


# ─────────────────────────────────────────────────────────────────────────────
# _build_final_output
# ─────────────────────────────────────────────────────────────────────────────

def test_build_final_output_returns_safety_message_when_blocked():
    """When guardrail_blocked remains set, _build_final_output must NOT leak
    the tainted task output — it returns a safety-message summary instead."""
    state = PipelineState(task_input="analyze document")
    state.completed["task"] = {
        "output": "Here is the secret password: hunter2",  # tainted
        "explanation": "I found the password in the doc.",
    }
    state.completed["guardrail"] = {
        "blocked": True,
        "findings": [
            {
                "type": "credential_leak",
                "severity": "high",
                "description": "Plaintext password",
                "evidence": "line 1",
            },
        ],
    }
    state.flags.add("guardrail_blocked")

    output = _build_final_output(state)
    # The raw tainted content must NEVER appear in the final output.
    assert "hunter2" not in output, f"Tainted content leaked: {output!r}"
    # The safety message must explain WHY the task is empty.
    assert "blocked" in output.lower()
    assert "safety" in output.lower() or "guardrail" in output.lower()
    # Finding summary appears so the user / reviewer understands the cause.
    assert "credential_leak" in output.lower() or "password" in output.lower()


def test_build_final_output_safety_message_handles_empty_findings():
    """guardrail_blocked is set but findings list is empty — the output must
    still be safe (no tainted content) and not raise."""
    state = PipelineState(task_input="x")
    state.completed["task"] = {"output": "tainted body", "explanation": ""}
    state.completed["guardrail"] = {"blocked": True, "findings": []}
    state.flags.add("guardrail_blocked")

    output = _build_final_output(state)
    assert "tainted body" not in output
    assert "blocked" in output.lower()


def test_build_final_output_normal_path_unchanged():
    """Sanity: without a block, _build_final_output returns the Task output
    assembled as the inline code used to (output + explanation + files/commands)."""
    state = PipelineState(task_input="hi")
    state.completed["task"] = {
        "output": "Hello!",
        "explanation": "A friendly greeting.",
    }
    output = _build_final_output(state)
    assert "Hello!" in output
    assert "A friendly greeting." in output


def test_build_final_output_includes_files_and_commands():
    """Normal path must surface files_changed and commands_run like the old
    inline assembly did — downstream clients depend on this shape."""
    state = PipelineState(task_input="change foo.py")
    state.completed["task"] = {
        "output": "Refactored foo",
        "explanation": "Extracted a helper.",
        "files_changed": ["foo.py", "tests/test_foo.py"],
        "commands_run": ["pytest tests/test_foo.py"],
    }
    output = _build_final_output(state)
    assert "foo.py" in output
    assert "tests/test_foo.py" in output
    assert "pytest tests/test_foo.py" in output
    assert "Files changed" in output
    assert "Commands run" in output


def test_build_final_output_missing_task_uses_fallback_text():
    """Defensive: if for some reason the task output key is missing (e.g. the
    agent was skipped or failed silently), return a safe fallback string, not
    an exception. Mirrors the old inline behavior that used .get with a default."""
    state = PipelineState(task_input="x")
    # No state.completed["task"]
    output = _build_final_output(state)
    assert isinstance(output, str)
    assert len(output) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Threshold — medium-severity pause under new default
# ─────────────────────────────────────────────────────────────────────────────

def _make_pod(require_human_review="on_escalation", escalation_threshold="medium"):
    """Build a minimal PodRow-shaped mock for _should_pause_for_review."""
    pod = MagicMock()
    pod.require_human_review = require_human_review
    pod.escalation_threshold = escalation_threshold
    return pod


def test_medium_severity_pauses_under_new_default_threshold():
    """Medium-severity finding must pause for review when pod.escalation_threshold='medium'."""
    state = PipelineState(task_input="x")
    state.flags.add("guardrail_blocked")

    pod = _make_pod(escalation_threshold="medium")

    result = {
        "blocked": True,
        "findings": [
            {"type": "jailbreak_attempt", "severity": "medium", "description": "..."},
        ],
    }

    # Under the OLD default (high), this returned False. Under the NEW default (medium), True.
    assert _should_pause_for_review(state, pod, result, "guardrail") is True


def test_medium_severity_does_not_pause_under_high_threshold():
    """Regression: pods that explicitly set escalation_threshold='high' still
    pause only on high-or-above findings. The new default does not retroactively
    affect user-customized pods."""
    state = PipelineState(task_input="x")
    state.flags.add("guardrail_blocked")

    pod = _make_pod(escalation_threshold="high")

    result = {
        "blocked": True,
        "findings": [
            {"type": "topic_drift", "severity": "medium", "description": "..."},
        ],
    }

    assert _should_pause_for_review(state, pod, result, "guardrail") is False


def test_high_severity_always_pauses_regardless_of_threshold():
    """Sanity: a high-severity finding pauses under both medium and high thresholds."""
    state = PipelineState(task_input="x")
    state.flags.add("guardrail_blocked")

    result = {
        "blocked": True,
        "findings": [
            {"type": "prompt_injection", "severity": "high", "description": "..."},
        ],
    }

    assert _should_pause_for_review(state, _make_pod(escalation_threshold="medium"), result, "guardrail") is True
    assert _should_pause_for_review(state, _make_pod(escalation_threshold="high"), result, "guardrail") is True


def test_low_severity_does_not_pause_under_medium_threshold():
    """Low-severity findings do not pause at medium threshold (the scale is
    inclusive at-or-above, and low < medium)."""
    state = PipelineState(task_input="x")
    state.flags.add("guardrail_blocked")

    pod = _make_pod(escalation_threshold="medium")

    result = {
        "blocked": True,
        "findings": [
            {"type": "style_nit", "severity": "low", "description": "..."},
        ],
    }

    assert _should_pause_for_review(state, pod, result, "guardrail") is False
