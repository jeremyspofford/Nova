"""Background thinking loop — runs cycles on a timer, respects pause and budget."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .config import settings
from .cycle import run_cycle
from .db import get_pool

log = logging.getLogger(__name__)

_task: asyncio.Task | None = None


async def start() -> None:
    """Start the thinking loop as a background task."""
    global _task
    if _task is not None:
        log.warning("Thinking loop already running")
        return
    _task = asyncio.create_task(_loop(), name="cortex-thinking-loop")
    log.info("Thinking loop started (interval=%ds, enabled=%s)",
             settings.cycle_interval_seconds, settings.enabled)


async def stop() -> None:
    """Stop the thinking loop gracefully."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    log.info("Thinking loop stopped")


async def _loop() -> None:
    """Main loop — check state, run cycle, sleep, repeat."""
    # Initial delay: let other services finish starting
    await asyncio.sleep(15)

    while True:
        try:
            interval = settings.cycle_interval_seconds

            # Check if enabled
            if not settings.enabled:
                log.debug("Cortex disabled — sleeping %ds", interval)
                await asyncio.sleep(interval)
                continue

            # Check if paused
            pool = get_pool()
            async with pool.acquire() as conn:
                status = await conn.fetchval(
                    "SELECT status FROM cortex_state WHERE id = true"
                )

            if status == "paused":
                log.debug("Cortex paused — sleeping %ds", interval)
                await asyncio.sleep(interval)
                continue

            # Run one cycle
            log.info("Starting thinking cycle")
            state = await run_cycle()
            log.info(
                "Cycle %d complete: drive=%s, outcome=%s",
                state.cycle_number,
                state.action_taken,
                (state.outcome[:80] if state.outcome else "none"),
            )

            # Adaptive interval: shorter when busy, longer when idle
            if state.action_taken == "idle":
                interval = min(interval * 2, 1800)  # Max 30 min when idle
            elif state.error:
                interval = min(interval * 3, 3600)  # Back off on errors

            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Thinking loop error: %s", e, exc_info=True)
            await asyncio.sleep(60)  # Brief pause on unexpected errors
