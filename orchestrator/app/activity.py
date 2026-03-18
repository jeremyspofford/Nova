"""Activity event emission — lightweight helper for the activity_events table."""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


async def emit_activity(
    pool,
    event_type: str,
    service: str,
    summary: str,
    severity: str = "info",
    metadata: dict | None = None,
) -> None:
    """Insert an activity event row. Never raises — activity logging must not crash the caller."""
    try:
        await pool.execute(
            """INSERT INTO activity_events (event_type, service, severity, summary, metadata)
               VALUES ($1, $2, $3, $4, $5)""",
            event_type, service, severity, summary, json.dumps(metadata or {}),
        )
    except Exception:
        log.debug("Failed to emit activity event %s", event_type, exc_info=True)
