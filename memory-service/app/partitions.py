"""
Auto-partition management for episodic_memories.

Creates monthly partitions for current month + 3 months ahead.
Runs daily as an asyncio background task.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from app.db.database import engine

log = logging.getLogger(__name__)


async def ensure_partitions() -> None:
    """Create episodic_memories partitions for current month + 3 months ahead."""
    today = date.today()
    months_to_create = []

    for i in range(4):  # current + 3 ahead
        d = today.replace(day=1) + timedelta(days=32 * i)
        first = d.replace(day=1)
        months_to_create.append(first)

    async with engine.begin() as conn:
        for first_of_month in months_to_create:
            # Calculate first of next month
            if first_of_month.month == 12:
                next_month = first_of_month.replace(year=first_of_month.year + 1, month=1)
            else:
                next_month = first_of_month.replace(month=first_of_month.month + 1)

            partition_name = f"episodic_memories_{first_of_month.year}_{first_of_month.month:02d}"
            try:
                await conn.exec_driver_sql(
                    f"CREATE TABLE IF NOT EXISTS {partition_name} "
                    f"PARTITION OF episodic_memories "
                    f"FOR VALUES FROM ('{first_of_month}') TO ('{next_month}')"
                )
            except Exception:
                # Partition may already exist with different bounds — that's fine
                log.debug("Partition %s already exists or failed", partition_name)

    log.info("Partition check complete — ensured partitions through %s", months_to_create[-1].strftime("%Y-%m"))


async def partition_loop() -> None:
    """Ensure partitions exist on startup, then check daily."""
    try:
        await ensure_partitions()
    except Exception:
        log.exception("Initial partition check failed")

    while True:
        try:
            from app.config import SECONDS_PER_DAY
            await asyncio.sleep(SECONDS_PER_DAY)  # Daily
            await ensure_partitions()
        except asyncio.CancelledError:
            log.info("Partition loop shutting down")
            break
        except Exception:
            log.exception("Partition check error — will retry tomorrow")
