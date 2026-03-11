"""Drive system — each drive computes urgency and proposes actions.

Priority × urgency determines which drive wins each cycle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class DriveResult:
    """Output from a drive's assess() method."""
    name: str
    priority: int
    urgency: float  # 0.0–1.0
    description: str
    proposed_action: str | None = None  # Human-readable action description
    context: dict = field(default_factory=dict)  # Data for the PLAN phase


@dataclass
class DriveWinner:
    """The winning drive after evaluation."""
    result: DriveResult
    score: float  # priority_weight * urgency


# Priority weights — lower priority number = higher weight
PRIORITY_WEIGHTS = {1: 5.0, 2: 4.0, 3: 3.0, 4: 2.0, 5: 1.0}


def evaluate(results: list[DriveResult], budget_tier: str) -> DriveWinner | None:
    """Score all drives, apply budget penalty, return the winner.

    Returns None if no drive has urgency > 0 or budget is exhausted.
    """
    if budget_tier == "none":
        # Budget exhausted — only maintain can run (health checks are free)
        results = [r for r in results if r.name == "maintain"]

    scored = []
    for r in results:
        if r.urgency <= 0:
            continue
        weight = PRIORITY_WEIGHTS.get(r.priority, 1.0)
        score = weight * r.urgency

        # Budget penalty: reduce score for expensive drives when budget is tight
        if budget_tier == "cheap" and r.name not in ("maintain", "reflect"):
            score *= 0.3
        elif budget_tier == "mid" and r.name in ("improve", "learn"):
            score *= 0.5

        scored.append(DriveWinner(result=r, score=score))

    if not scored:
        return None

    scored.sort(key=lambda w: w.score, reverse=True)
    winner = scored[0]
    log.info(
        "Drive evaluation: winner=%s score=%.2f (urgency=%.2f, tier=%s) | %s",
        winner.result.name, winner.score, winner.result.urgency,
        budget_tier,
        ", ".join(f"{s.result.name}={s.score:.2f}" for s in scored),
    )
    return winner
