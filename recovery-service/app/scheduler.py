"""Background checkpoint scheduler — creates automatic database backups on an interval."""

import asyncio
import logging

from .backup import create_checkpoint, prune_checkpoints
from .config import settings

logger = logging.getLogger("nova.recovery.scheduler")


async def checkpoint_loop() -> None:
    """Run checkpoint backups every CHECKPOINT_INTERVAL_HOURS. Prunes old checkpoints."""
    interval_seconds = settings.checkpoint_interval_hours * 3600
    if interval_seconds <= 0:
        logger.info("Checkpoint scheduler disabled (interval=0)")
        return

    logger.info(
        "Checkpoint scheduler started: every %dh, keep %d",
        settings.checkpoint_interval_hours,
        settings.checkpoint_max_keep,
    )

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            result = await create_checkpoint()
            logger.info("Checkpoint complete: %s", result["filename"])
            pruned = prune_checkpoints(settings.checkpoint_max_keep)
            if pruned:
                logger.info("Pruned %d old checkpoint(s)", pruned)
        except Exception:
            logger.exception("Checkpoint failed")
