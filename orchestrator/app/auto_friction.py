"""Auto-friction subscriber — creates friction log entries from pipeline failures.

Subscribes to the existing nova:notifications Redis pub/sub channel and creates
friction_log entries when task_failed events arrive. Fully decoupled from the
executor — no import dependency on friction_router or friction_log schema from
the pipeline code.

Loop guard: tasks with metadata.source == "friction_log" (from "Fix This") are
skipped to prevent friction→task→friction chains.
"""
from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger(__name__)

_healthy = False


def is_healthy() -> bool:
    """Health check for /health/ready — True if subscriber is running."""
    return _healthy


async def auto_friction_subscriber() -> None:
    """Background task: subscribe to nova:notifications, create friction on task_failed."""
    global _healthy
    from app.store import get_redis
    from app.db import get_pool

    log.info("Auto-friction subscriber starting")

    while True:
        try:
            redis = get_redis()
            pubsub = redis.pubsub()
            await pubsub.subscribe("nova:notifications")
            _healthy = True
            log.info("Auto-friction subscriber connected to nova:notifications")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    if data.get("type") != "task_failed":
                        continue
                    await _handle_task_failed(data, get_pool())
                except Exception as e:
                    log.warning(f"Auto-friction event handling failed: {e}")

        except asyncio.CancelledError:
            _healthy = False
            log.info("Auto-friction subscriber shutting down")
            return
        except Exception as e:
            _healthy = False
            log.warning(f"Auto-friction subscriber error, reconnecting in 5s: {e}")
            await asyncio.sleep(5)


async def _handle_task_failed(data: dict, pool) -> None:
    """Create a friction entry from a task_failed notification."""
    task_id = data.get("task_id", "")
    error = data.get("body", "Unknown error")

    # Loop guard: check if this task was created from "Fix This"
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT metadata FROM tasks WHERE id = $1", task_id)
        if not row:
            return
        metadata = row["metadata"] or {}
        if metadata.get("source") == "friction_log":
            log.debug(f"Skipping auto-friction for Fix-This task {task_id[:8]}")
            return

        # Create friction entry
        await conn.execute(
            """
            INSERT INTO friction_log (description, severity, source, metadata)
            VALUES ($1, 'blocker', 'auto', $2::jsonb)
            """,
            f"Pipeline task failed: {error[:200]}",
            json.dumps({"failed_task_id": task_id, "error": error[:500]}),
        )
    log.info(f"Auto-friction entry created for task {task_id[:8]}")
