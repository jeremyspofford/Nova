"""
Retrieval logger — Phase 5 of the Engram Network (Neural Router foundation).

Logs every retrieval event to the retrieval_log table:
  - What was queried (embedding + text)
  - What was surfaced (engram IDs from activation)
  - What was actually used (filled later by the orchestrator)
  - Temporal context (time, day, active goal)

This data is the training set for the Neural Router. Per the spec's rollout
strategy, Phase 5 starts by just logging observations silently. The actual
NN training happens after 200+ observations have been collected.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding import to_pg_vector

log = logging.getLogger(__name__)


async def log_retrieval(
    session: AsyncSession,
    query_embedding: list[float],
    query_text: str,
    engram_ids_surfaced: list[str],
    session_id: str = "",
    active_goal: str = "",
) -> str | None:
    """Log a retrieval event for future Neural Router training.

    Returns the log entry ID (for later marking which engrams were used).
    """
    try:
        now = datetime.now(timezone.utc)
        temporal_context = {
            "time_of_day": now.strftime("%H:%M"),
            "day_of_week": now.strftime("%A"),
            "active_goal": active_goal,
        }

        result = await session.execute(
            text("""
                INSERT INTO retrieval_log
                    (query_embedding, query_text, temporal_context,
                     engrams_surfaced, session_id)
                VALUES
                    (CAST(:embedding AS halfvec), :query_text,
                     CAST(:temporal AS jsonb),
                     CAST(:surfaced AS uuid[]), :session_id)
                RETURNING id
            """),
            {
                "embedding": to_pg_vector(query_embedding),
                "query_text": query_text,
                "temporal": json.dumps(temporal_context),
                "surfaced": engram_ids_surfaced,
                "session_id": session_id,
            },
        )
        row = result.fetchone()
        return str(row.id) if row else None
    except Exception:
        log.debug("Failed to log retrieval", exc_info=True)
        return None


async def mark_engrams_used(
    session: AsyncSession,
    retrieval_log_id: str,
    engram_ids_used: list[str],
) -> None:
    """Mark which surfaced engrams were actually referenced by the LLM.

    Called after the LLM response is generated, when we can determine
    which memories were actually used.
    """
    try:
        await session.execute(
            text("""
                UPDATE retrieval_log
                SET engrams_used = CAST(:used AS uuid[])
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": retrieval_log_id, "used": engram_ids_used},
        )
    except Exception:
        log.debug("Failed to mark engrams used", exc_info=True)


async def get_observation_count(session: AsyncSession) -> int:
    """Count total retrieval observations (for router readiness check)."""
    try:
        result = await session.execute(
            text("SELECT count(*) FROM retrieval_log")
        )
        return result.scalar() or 0
    except Exception:
        return 0
