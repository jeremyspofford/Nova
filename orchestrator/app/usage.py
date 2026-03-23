"""
Fire-and-forget usage event logger.

Callers write log_usage(...) synchronously — no await, no latency impact
on the response path. The actual DB insert is scheduled as a background
asyncio task that runs after the response is returned.

Errors inside the background task are caught and logged as warnings so
they never propagate to the caller or affect response behavior.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.db import insert_usage_event

log = logging.getLogger(__name__)


def log_usage(
    api_key_id: UUID | None,
    agent_id: UUID | None,
    session_id: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    duration_ms: int | None,
    metadata: dict | None = None,
    outcome_score: float | None = None,
    outcome_confidence: float | None = None,
    agent_name: str | None = None,
    pod_name: str | None = None,
) -> None:
    """Schedule a usage event insert as a background task.

    Safe to call from both sync and async contexts — asyncio.create_task
    requires an active event loop, which FastAPI/uvicorn always provides.
    Tasks complete before uvicorn's graceful shutdown drains the loop.
    """
    asyncio.create_task(
        _safe_insert(
            api_key_id=api_key_id,
            agent_id=agent_id,
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            metadata=metadata,
            outcome_score=outcome_score,
            outcome_confidence=outcome_confidence,
            agent_name=agent_name,
            pod_name=pod_name,
        )
    )


async def _safe_insert(**kwargs) -> None:
    try:
        await insert_usage_event(**kwargs)
    except Exception as e:
        log.warning("Failed to log usage event: %s", e)
