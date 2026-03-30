"""Structured experience log for Cortex goal learning.

Records what was tried per goal, what happened, and lessons learned.
Used by the thinking cycle to avoid repeating failures and to detect stuck goals.
"""
from __future__ import annotations

import hashlib
import json
import logging

from .config import settings
from .db import get_pool

log = logging.getLogger(__name__)

# Budget tier ordering for condition comparison
TIER_ORDER = {"none": 0, "cheap": 1, "mid": 2, "best": 3}


def compute_approach_hash(text: str) -> str:
    """Normalize approach text and return a truncated SHA-256 hash.

    Normalization: lowercase, collapse whitespace. Preserves word order so
    this catches exact/near-exact duplicates but not semantic equivalents.
    """
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


async def record_reflection(
    goal_id: str,
    cycle_number: int,
    approach: str,
    outcome: str,
    outcome_score: float,
    task_id: str | None = None,
    drive: str = "serve",
    maturation_phase: str | None = None,
    lesson: str | None = None,
    failure_mode: str | None = None,
    context_snapshot: dict | None = None,
) -> str:
    """Insert a reflection and return its ID."""
    approach_hash = compute_approach_hash(approach)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO cortex_reflections
               (goal_id, cycle_number, drive, maturation_phase, task_id,
                approach, approach_hash, outcome, outcome_score,
                lesson, failure_mode, context_snapshot)
               VALUES ($1::uuid, $2, $3, $4, $5::uuid,
                       $6, $7, $8, $9,
                       $10, $11, $12::jsonb)
               RETURNING id""",
            goal_id, cycle_number, drive, maturation_phase,
            task_id,
            approach[:1000], approach_hash, outcome, outcome_score,
            lesson[:500] if lesson else None,
            failure_mode[:200] if failure_mode else None,
            json.dumps(context_snapshot or {}),
        )
    ref_id = str(row["id"])
    log.info(
        "Recorded reflection for goal %s: outcome=%s score=%.1f hash=%s",
        goal_id, outcome, outcome_score, approach_hash,
    )
    return ref_id


async def query_reflections(
    goal_id: str,
    phase: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Get recent reflections for a goal, optionally filtered by maturation phase."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if phase:
            rows = await conn.fetch(
                """SELECT id, cycle_number, approach, approach_hash, outcome,
                          outcome_score, lesson, failure_mode, maturation_phase,
                          context_snapshot, created_at
                   FROM cortex_reflections
                   WHERE goal_id = $1::uuid AND maturation_phase = $2
                   ORDER BY created_at DESC
                   LIMIT $3""",
                goal_id, phase, limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, cycle_number, approach, approach_hash, outcome,
                          outcome_score, lesson, failure_mode, maturation_phase,
                          context_snapshot, created_at
                   FROM cortex_reflections
                   WHERE goal_id = $1::uuid
                   ORDER BY created_at DESC
                   LIMIT $2""",
                goal_id, limit,
            )
    return [
        {
            "id": str(r["id"]),
            "cycle_number": r["cycle_number"],
            "approach": r["approach"],
            "approach_hash": r["approach_hash"],
            "outcome": r["outcome"],
            "outcome_score": r["outcome_score"],
            "lesson": r["lesson"],
            "failure_mode": r["failure_mode"],
            "maturation_phase": r["maturation_phase"],
            "context_snapshot": r["context_snapshot"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


def format_reflection_history(
    reflections: list[dict],
    current_goal_desc_hash: str | None = None,
) -> str:
    """Format reflections as a compact block for the planning prompt.

    Each entry is capped at ~40 tokens. Flags when the goal description has
    changed since older reflections (human intervention signal).
    Returns empty string if no reflections.
    """
    if not reflections:
        return ""

    lines = ["Prior experience with this goal:"]

    # Check if goal description changed since oldest reflection
    if current_goal_desc_hash and reflections:
        oldest = reflections[-1]  # list is newest-first
        old_hash = (oldest.get("context_snapshot") or {}).get("goal_description_hash")
        if old_hash and old_hash != current_goal_desc_hash:
            lines.append("(Note: goal description was modified since earlier attempts — prior failures may be less relevant)")

    for r in reversed(reflections):  # chronological order (oldest first)
        outcome = r["outcome"]
        score = r["outcome_score"]
        approach = r["approach"][:80]
        line = f"- [{outcome} ({score:.1f})] {approach}"
        if r.get("lesson"):
            line += f" → {r['lesson'][:60]}"
        lines.append(line)

    return "\n".join(lines)


async def check_approach_blocked(
    goal_id: str,
    approach_text: str,
    current_tier: str,
) -> tuple[bool, list[str]]:
    """Check if a proposed approach has already failed for this goal.

    Returns (is_blocked, list of failed approach descriptions).

    Dedup rules:
    - Same hash + prior score < 0.3 (true failure) + conditions NOT improved → block
    - Same hash + prior score >= 0.3 (partial success) → allow
    - Same hash + conditions improved since last attempt → allow
    """
    approach_hash = compute_approach_hash(approach_text)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT approach, outcome_score, context_snapshot
               FROM cortex_reflections
               WHERE goal_id = $1::uuid AND approach_hash = $2
               ORDER BY created_at DESC""",
            goal_id, approach_hash,
        )

    if not rows:
        return False, []

    failed_approaches = []
    for row in rows:
        prior_score = row["outcome_score"]
        if prior_score >= 0.3:
            # Partial success — allow retry
            continue

        # True failure — check if conditions improved
        prior_snapshot = row["context_snapshot"] or {}
        prior_tier = prior_snapshot.get("budget_tier", "none")
        if TIER_ORDER.get(current_tier, 0) > TIER_ORDER.get(prior_tier, 0):
            # Budget improved — allow retry
            continue

        failed_approaches.append(row["approach"][:100])

    is_blocked = len(failed_approaches) > 0
    return is_blocked, failed_approaches


async def count_consecutive_failures(goal_id: str) -> int:
    """Count consecutive failures/timeouts since the last success for a goal.

    'Consecutive' means for this specific goal, not consecutive Cortex cycles.
    Cancelled outcomes don't count (external, not the approach's fault).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Find the most recent success or partial success
        last_success = await conn.fetchrow(
            """SELECT created_at FROM cortex_reflections
               WHERE goal_id = $1::uuid AND outcome IN ('success', 'partial')
               ORDER BY created_at DESC LIMIT 1""",
            goal_id,
        )

        if last_success:
            # Count failures after the last success
            count = await conn.fetchval(
                """SELECT COUNT(*) FROM cortex_reflections
                   WHERE goal_id = $1::uuid
                     AND outcome IN ('failure', 'timeout')
                     AND created_at > $2""",
                goal_id, last_success["created_at"],
            )
        else:
            # No successes ever — count all failures
            count = await conn.fetchval(
                """SELECT COUNT(*) FROM cortex_reflections
                   WHERE goal_id = $1::uuid
                     AND outcome IN ('failure', 'timeout')""",
                goal_id,
            )

    return count


def compute_stuck_threshold(max_iterations: int) -> int:
    """Compute the stuck threshold for a goal.

    Scales with goal size: max(3, max_iterations // 10).
    """
    return max(settings.stuck_threshold_min, max_iterations // 10)
