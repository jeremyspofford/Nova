"""QualityLoop primitive — dataclasses, Protocol, default decision rule.

Concrete loops live in orchestrator/app/quality_loop/loops/. They
implement the Protocol; the runner calls the lifecycle methods and
persists session rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class SenseReading:
    composite: float                    # 0-100
    dimensions: dict[str, float]        # 0-1 per dim
    sample_size: int                    # how many cases / messages
    snapshot_id: str                    # config snapshot at time of read


@dataclass
class Proposal:
    description: str                    # human-readable
    changes: dict[str, dict[str, Any]]  # {"retrieval.top_k": {"from": 5, "to": 7}}
    rationale: str                      # why this candidate, not another


@dataclass
class AppliedChange:
    proposal: Proposal
    applied_at: str                     # ISO timestamp
    revert_actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Verification:
    baseline: SenseReading
    after: SenseReading
    delta: dict[str, float]             # per-dim and "composite" key
    significant: bool                   # passed decision threshold


@dataclass
class Decision:
    outcome: Literal["improved", "no_change", "regressed", "aborted"]
    action: Literal["persist", "revert", "pending_approval"]
    confidence: float                   # 0-1


class QualityLoop(Protocol):
    name: str
    watches: list[str]
    agency: Literal["auto_apply", "propose_for_approval", "alert_only"]

    async def sense(self) -> SenseReading: ...
    async def snapshot(self) -> str: ...
    async def propose(self, reading: SenseReading) -> Proposal | None: ...
    async def apply(self, proposal: Proposal) -> AppliedChange: ...
    async def verify(self, baseline: SenseReading, applied: AppliedChange) -> Verification: ...
    async def decide(self, verification: Verification) -> Decision: ...
    async def revert(self, applied: AppliedChange) -> None: ...


def decide_default(
    verification: Verification,
    persist_threshold: float = 2.0,
    revert_threshold: float = 1.0,
) -> Decision:
    """Default decision rule: persist if composite delta >= persist_threshold,
    revert if delta <= -revert_threshold, otherwise no_change (revert)."""
    delta = verification.delta.get("composite", 0.0)
    if delta >= persist_threshold:
        return Decision(outcome="improved", action="persist", confidence=0.8)
    if delta <= -revert_threshold:
        return Decision(outcome="regressed", action="revert", confidence=0.85)
    return Decision(outcome="no_change", action="revert", confidence=0.6)
