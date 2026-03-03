"""
Background cleanup job for expired working memories.

Same pattern as orchestrator's reaper: async sleep-loop, fault-tolerant.
Started as asyncio.create_task in main.py lifespan.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.config import settings
from app.db.database import AsyncSessionLocal

log = logging.getLogger(__name__)


async def cleanup_loop() -> None:
    """Periodically delete expired working memories."""
    log.info("Working memory cleanup job started (interval=%ds)", settings.working_memory_cleanup_interval_seconds)
    while True:
        try:
            await asyncio.sleep(settings.working_memory_cleanup_interval_seconds)
            deleted = await _delete_expired()
            if deleted:
                log.info("Cleanup: deleted %d expired working memories", deleted)
        except asyncio.CancelledError:
            log.info("Working memory cleanup job shutting down")
            break
        except Exception:
            log.exception("Cleanup cycle error — will retry next interval")


async def _delete_expired() -> int:
    """Delete working memories past their expires_at timestamp. Returns count deleted."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("DELETE FROM working_memories WHERE expires_at IS NOT NULL AND expires_at < now()")
        )
        await session.commit()
        return result.rowcount
