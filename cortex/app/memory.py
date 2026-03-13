"""Engram memory integration for Cortex.

Three integration points:
1. PERCEIVE — query engram context for drive-informed decisions
2. REFLECT — write cycle outcomes as engrams for long-term learning
3. IDLE — trigger consolidation when nothing else to do
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .clients import get_memory
from .config import settings

log = logging.getLogger(__name__)


async def perceive_with_memory(stimuli: list[dict], goal_context: str = "") -> dict:
    """Query engram network for context relevant to current cycle.

    Returns dict with memory_context (str), engram_ids (list), retrieval_log_id (str|None).
    """
    if not settings.memory_enabled:
        return {"memory_context": "", "engram_ids": [], "retrieval_log_id": None}

    # Build a query from stimuli + goal context
    query_parts = []
    if goal_context:
        query_parts.append(f"Current goal: {goal_context}")
    for s in stimuli[:5]:
        query_parts.append(f"{s.get('type', 'unknown')}: {json.dumps(s.get('payload', {}))}")

    query = " | ".join(query_parts) or "general system status and pending work"

    try:
        mem = get_memory()
        resp = await mem.post(
            "/api/v1/engrams/context",
            json={"query": query, "session_id": "cortex-perceive", "current_turn": 0},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "memory_context": data.get("context", ""),
                "engram_ids": data.get("engram_ids", []),
                "retrieval_log_id": data.get("retrieval_log_id"),
            }
        log.debug("Memory context request returned %d", resp.status_code)
    except Exception as e:
        log.debug("Failed to get memory context: %s", e)

    return {"memory_context": "", "engram_ids": [], "retrieval_log_id": None}


async def reflect_to_engrams(
    cycle_number: int,
    drive: str,
    urgency: float,
    action_summary: str,
    outcome: str,
    goal_id: str | None = None,
    budget_tier: str = "best",
) -> None:
    """Ingest cycle outcome into engram network for long-term learning.

    Only ingests when an action was actually taken (not idle cycles).
    """
    if not settings.reflect_to_engrams:
        return

    raw_text = (
        f"Cortex cycle #{cycle_number}: "
        f"Drive '{drive}' won (urgency {urgency:.2f}). "
        f"Action: {action_summary}. "
        f"Outcome: {outcome}."
    )

    try:
        mem = get_memory()
        await mem.post(
            "/api/v1/engrams/ingest",
            json={
                "raw_text": raw_text,
                "source_type": "cortex",
                "source_id": "cortex-reflect",
                "metadata": {
                    "drive": drive,
                    "goal_id": goal_id,
                    "budget_tier": budget_tier,
                    "cycle": cycle_number,
                },
            },
            timeout=10.0,
        )
        log.debug("Reflected cycle %d to engrams", cycle_number)
    except Exception as e:
        log.debug("Failed to reflect to engrams: %s", e)


async def maybe_consolidate() -> bool:
    """Trigger consolidation if enough time has passed since last run.

    Returns True if consolidation was triggered.
    """
    if not settings.idle_consolidation:
        return False

    try:
        mem = get_memory()

        # Check last consolidation time
        resp = await mem.get("/api/v1/engrams/consolidation-log?limit=1", timeout=5.0)
        if resp.status_code == 200:
            entries = resp.json().get("entries", [])
            if entries:
                last_at = datetime.fromisoformat(entries[0]["created_at"])
                elapsed = (datetime.now(timezone.utc) - last_at).total_seconds()
                if elapsed < settings.consolidation_cooldown:
                    return False

        # Trigger consolidation (fire and forget with timeout)
        await mem.post("/api/v1/engrams/consolidate", timeout=30.0)
        log.info("Triggered idle consolidation")
        return True
    except Exception as e:
        log.debug("Consolidation trigger failed: %s", e)
        return False


async def mark_engrams_used(retrieval_log_id: str, engram_ids: list[str]) -> None:
    """Report which engrams were used during planning."""
    if not retrieval_log_id or not engram_ids:
        return
    try:
        mem = get_memory()
        await mem.post(
            "/api/v1/engrams/mark-used",
            json={"retrieval_log_id": retrieval_log_id, "engram_ids_used": engram_ids},
            timeout=5.0,
        )
    except Exception as e:
        log.debug("Failed to mark engrams used: %s", e)
