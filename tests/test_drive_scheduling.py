"""Regression tests for cortex drive scheduling.

The bug this guards against: when no quality measurements have been
collected yet, `/api/v1/quality/summary` returns
``{"composite": 0.0, "dimensions": {}}``. The quality drive treated
``composite < 75`` as evidence of regression and pumped urgency to
its 0.8 cap, beating the `serve` drive every cycle. Result: maturation
goals never got processed even when stale work existed.

Two fixes locked in here:
1. Empty quality data → urgency 0.0 (no signal, not "max regression").
2. Quality drive routes to its `react()` executor in cycle.py instead of
   falling through to the "no executor" branch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow importing cortex.app.* without installing the package
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cortex"))


# ───────────────────────────────────────────────────────────────────────────
# Quality drive: empty data should NOT register as regression
# ───────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quality_drive_returns_zero_urgency_on_empty_data(monkeypatch):
    """When the orchestrator has no quality measurements yet, urgency=0."""
    from app.drives import quality

    class FakeResp:
        status_code = 200
        def json(self):
            return {"composite": 0.0, "dimensions": {}, "period_days": 7}

    class FakeClient:
        async def get(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr(quality, "get_orchestrator", lambda: FakeClient())
    result = await quality.assess()

    assert result.urgency == 0.0, (
        f"Empty data should yield urgency=0, got {result.urgency} "
        f"(description={result.description!r}). Without this guard, the quality "
        "drive dominates every cycle on a fresh install."
    )
    assert result.name == "quality"


@pytest.mark.asyncio
async def test_quality_drive_still_fires_on_real_regression(monkeypatch):
    """Confirm the empty-data fix didn't accidentally disable the drive entirely."""
    from app.drives import quality

    class FakeResp:
        status_code = 200
        def json(self):
            return {
                "composite": 30.0,
                "dimensions": {
                    "memory_relevance": {"avg": 0.4, "count": 10},
                    "memory_usage": {"avg": 0.5, "count": 10},
                },
                "period_days": 7,
            }

    class FakeClient:
        async def get(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr(quality, "get_orchestrator", lambda: FakeClient())
    result = await quality.assess()

    # Real low composite + weak dims → real urgency
    assert result.urgency > 0.0
    assert "memory_relevance" in (result.context.get("weak_dimensions") or [])


# ───────────────────────────────────────────────────────────────────────────
# Cycle routing: quality drive has an executor branch
# ───────────────────────────────────────────────────────────────────────────

def test_cycle_routes_quality_drive_to_executor():
    """cycle.py must have a 'quality' branch in the executor router.

    Source-text lock-in: if the quality executor is removed, this fails.
    """
    cycle_src = (ROOT / "cortex" / "app" / "cycle.py").read_text()
    assert "drive.name == \"quality\"" in cycle_src, (
        "cycle.py is missing the quality drive executor branch. The drive "
        "would fall through to 'no executor' and burn cycles doing nothing."
    )
    assert "_execute_quality" in cycle_src, (
        "cycle.py is missing _execute_quality function definition"
    )


def test_quality_drive_imported_in_cycle():
    """cycle.py must import the quality drive module."""
    cycle_src = (ROOT / "cortex" / "app" / "cycle.py").read_text()
    # Imported via `from .drives import (..., quality, ...)`
    assert "quality," in cycle_src or "quality\n" in cycle_src, (
        "quality drive not imported in cycle.py"
    )
