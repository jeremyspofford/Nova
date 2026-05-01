"""Tier 4 — verifying phase routes goals through multi-signal verification.

The verifying executor (`cortex/app/maturation/verifying.py`) requires
multi-signal evidence to mark a goal `completed`:

  - cmd_results: all `verification_commands` exit 0
  - quartet_review: a Quartet-pipeline code-review verdict with confidence ≥ 0.7
  - criteria_eval: ≥75% of `success_criteria_structured` items pass

The aggregator (`cortex/app/maturation/aggregator.py`) refuses to auto-pass
on weak signals — by design. A goal with no spec produces quartet
confidence=0, which forces the outcome to "human-review" even when commands
and criteria are green.

That makes a fast integration test of "verifying → completed" structurally
hard: the only honest way to exercise the path is a real Quartet pipeline
run (1-3 minutes) against a real spec — which isn't a "fast pre-merge"
shape. The aggregator's rules are unit-tested in
`test_verification_aggregator.py`; this file's integration test was written
for the pre-decomposition simple-health-check executor and no longer
matches the architecture.
"""
import pytest


@pytest.mark.skip(
    reason=(
        "Test was written for the pre-decomposition verifying executor "
        "(simple health checks). After the multi-signal redesign, "
        "verifying → completed requires a real Quartet pipeline run "
        "(1-3 min). Integration coverage for that path belongs in a "
        "long-running real-LLM test, not the fast suite. Aggregator logic "
        "is covered by tests/test_verification_aggregator.py."
    ),
)
def test_verifying_completes_goal_when_services_healthy():
    """See module docstring — kept as a placeholder for the eventual real-LLM test."""
