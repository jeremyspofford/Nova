"""Quality loop runner — drives one iteration of a registered loop.

Lifecycle: snapshot -> sense -> propose -> (apply -> verify -> decide) -> persist.
Agency mode gates the apply step. One in-flight session per loop via Redis SETNX.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import get_pool
from app.quality_loop.base import QualityLoop
from app.store import get_redis

log = logging.getLogger(__name__)


async def iterate_loop(loop: QualityLoop) -> dict[str, Any]:
    """Run one iteration of the loop. Returns session summary dict."""
    redis = get_redis()
    lock_key = f"nova:quality:loop:{loop.name}:lock"
    lock_ttl = 1800  # 30 min — must exceed worst-case full lifecycle duration
    acquired = await redis.set(lock_key, "1", ex=lock_ttl, nx=True)
    if not acquired:
        log.info("Loop[%s]: skip - already in flight", loop.name)
        return {"skipped": True, "reason": "in_flight"}

    try:
        baseline_snapshot = await loop.snapshot()
        baseline = await loop.sense()
        proposal = await loop.propose(baseline)
        if proposal is None:
            log.info("Loop[%s]: no change proposed", loop.name)
            session_id = await _persist_session(
                loop_name=loop.name,
                baseline_snapshot_id=baseline_snapshot,
                proposed_changes=None,
                applied=False,
                outcome="no_change",
                decision="auto",
                decided_by="auto",
                notes={"reason": "scores at target"},
            )
            return {"session_id": session_id, "decision": "auto", "outcome": "no_change"}

        if loop.agency == "alert_only":
            session_id = await _persist_session(
                loop_name=loop.name,
                baseline_snapshot_id=baseline_snapshot,
                proposed_changes=proposal.changes,
                applied=False,
                outcome="aborted",
                decision="alert_only",
                decided_by="auto",
                notes={"description": proposal.description, "rationale": proposal.rationale},
            )
            log.warning("Loop[%s] ALERT: %s - agency=alert_only, no action taken",
                        loop.name, proposal.description)
            return {"session_id": session_id, "decision": "alert_only"}

        if loop.agency == "propose_for_approval":
            session_id = await _persist_session(
                loop_name=loop.name,
                baseline_snapshot_id=baseline_snapshot,
                proposed_changes=proposal.changes,
                applied=False,
                outcome=None,
                decision="pending_approval",
                decided_by=None,
                notes={"description": proposal.description, "rationale": proposal.rationale},
            )
            log.info("Loop[%s]: pending approval session=%s", loop.name, session_id)
            return {"session_id": session_id, "decision": "pending_approval"}

        # auto_apply path
        applied = await loop.apply(proposal)
        verification = await loop.verify(baseline, applied)
        decision = await loop.decide(verification)

        if decision.action == "revert":
            await loop.revert(applied)

        session_id = await _persist_session(
            loop_name=loop.name,
            baseline_snapshot_id=baseline_snapshot,
            proposed_changes=proposal.changes,
            applied=True,
            outcome=decision.outcome,
            decision=decision.action,
            decided_by="auto",
            notes={
                "description": proposal.description,
                "rationale": proposal.rationale,
                "delta": verification.delta,
                "confidence": decision.confidence,
            },
        )
        return {
            "session_id": session_id,
            "decision": decision.action,
            "outcome": decision.outcome,
        }
    finally:
        await redis.delete(lock_key)


async def _persist_session(
    *,
    loop_name: str,
    baseline_snapshot_id: str,
    proposed_changes: dict[str, Any] | None,
    applied: bool,
    outcome: str | None,
    decision: str,
    decided_by: str | None,
    notes: dict[str, Any],
) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO quality_loop_sessions
                (loop_name, baseline_snapshot_id, proposed_changes, applied,
                 outcome, decision, decided_by, decided_at, notes, completed_at)
            VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, NOW(), $8, NOW())
            RETURNING id::text
            """,
            loop_name,
            baseline_snapshot_id,
            proposed_changes if proposed_changes is not None else {},
            applied,
            outcome,
            decision,
            decided_by,
            notes,
        )
    return row["id"]
