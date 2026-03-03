"""
Reaper: periodic background task that detects and recovers from failures.

Runs every REAPER_INTERVAL_SECONDS as asyncio.create_task in main.py lifespan.
Replaces the startup-only recover_stale_agents() with continuous monitoring.

What it catches:
  1. Tasks stuck in running states with no heartbeat → retry or fail + dead letter
  2. Agent sessions running past their timeout → mark failed, propagate to task
  3. Tasks queued but never started (queue worker died) → re-enqueue

The Reaper does NOT cancel actively-running tasks — it only acts on tasks
that have gone silent (heartbeat expired or no started_at after grace period).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REAPER_INTERVAL_SECONDS = 60       # how often the reaper wakes up
STALE_HEARTBEAT_SECONDS = 150      # task is stale if heartbeat silent for this long
STALE_QUEUED_SECONDS    = 120      # task is stuck if queued but not started within this
SESSION_TIMEOUT_BUFFER  = 30       # extra seconds before declaring a session timed out


# ── Main loop ──────────────────────────────────────────────────────────────────

async def reaper_loop() -> None:
    """
    Entry point. Started as asyncio.create_task in main.py lifespan.
    Wakes every REAPER_INTERVAL_SECONDS, runs all reap checks, sleeps again.
    """
    logger.info("Reaper started")
    while True:
        try:
            await asyncio.sleep(REAPER_INTERVAL_SECONDS)
            await _reap_stale_running_tasks()
            await _reap_stuck_queued_tasks()
            await _reap_timed_out_sessions()
        except asyncio.CancelledError:
            logger.info("Reaper shutting down")
            break
        except Exception:
            logger.exception("Reaper cycle error — will retry next interval")


# ── Reap stale running tasks ───────────────────────────────────────────────────

async def _reap_stale_running_tasks() -> None:
    """
    Find tasks in active states whose heartbeat has expired.
    These are tasks that started execution but the pipeline process died.

    Recovery decision:
      - retry_count < max_retries → re-queue (checkpoint allows resuming from
        last completed stage rather than starting over)
      - retry_count >= max_retries → mark failed + dead letter
    """
    from .pipeline.checkpoint import load_checkpoint
    from .queue import enqueue_task, move_to_dead_letter
    from .db import get_pool

    ACTIVE_STATES = (
        "context_running", "task_running", "guardrail_running",
        "review_running", "completing",
    )

    pool = get_pool()
    async with pool.acquire() as conn:
        stale_tasks = await conn.fetch(
            """
            SELECT id, status, retry_count, max_retries, checkpoint
            FROM tasks
            WHERE status = ANY($1::text[])
              AND (
                last_heartbeat_at IS NULL
                OR last_heartbeat_at < now() - ($2 || ' seconds')::interval
              )
            """,
            list(ACTIVE_STATES),
            str(STALE_HEARTBEAT_SECONDS),
        )

        for task in stale_tasks:
            task_id     = str(task["id"])
            retry_count = task["retry_count"]
            max_retries = task["max_retries"]

            if retry_count < max_retries:
                logger.warning(
                    f"Reaper: task {task_id} stale in state '{task['status']}' "
                    f"(attempt {retry_count + 1}/{max_retries}) — re-queuing"
                )
                updated = await conn.fetchval(
                    """
                    UPDATE tasks
                    SET status = 'queued',
                        retry_count = retry_count + 1,
                        queued_at = now(),
                        current_stage = NULL,
                        error = NULL
                    WHERE id = $1 AND status = ANY($2::text[])
                    RETURNING id
                    """,
                    task["id"],
                    list(ACTIVE_STATES),
                )
                if not updated:
                    logger.info(f"Reaper: task {task_id} already handled by another process — skipping")
                    continue
                await enqueue_task(task_id)
                await _audit(conn, "task_requeued", "warning", task_id=task_id,
                             data={"retry_count": retry_count + 1, "reason": "heartbeat_timeout"})
            else:
                logger.error(
                    f"Reaper: task {task_id} exhausted {max_retries} retries — failing"
                )
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        error = 'Exhausted retries after heartbeat timeouts',
                        completed_at = now()
                    WHERE id = $1
                    """,
                    task["id"],
                )
                await move_to_dead_letter(task_id, reason="heartbeat_timeout_max_retries")
                await _audit(conn, "task_failed", "error", task_id=task_id,
                             data={"reason": "heartbeat_timeout_max_retries"})


# ── Reap stuck queued tasks ────────────────────────────────────────────────────

async def _reap_stuck_queued_tasks() -> None:
    """
    Find tasks that have been in 'queued' state too long without being picked up.
    This catches the case where the queue worker died after the task was dequeued
    from Redis but before it updated the DB status to a running state.

    Fix: re-push the task_id back onto the Redis queue. The DB status stays
    'queued' — the worker will pick it up and transition to a running state.
    """
    from .queue import enqueue_task
    from .db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        stuck = await conn.fetch(
            """
            SELECT id FROM tasks
            WHERE status = 'queued'
              AND queued_at < now() - ($1 || ' seconds')::interval
            """,
            str(STALE_QUEUED_SECONDS),
        )

        for task in stuck:
            task_id = str(task["id"])
            # Guard: confirm task is still queued before re-pushing
            still_queued = await conn.fetchval(
                """
                SELECT id FROM tasks
                WHERE id = $1 AND status = 'queued'
                """,
                task["id"],
            )
            if not still_queued:
                logger.info(f"Reaper: task {task_id} no longer queued — skipping")
                continue
            logger.warning(f"Reaper: task {task_id} stuck in queued state — re-pushing to queue")
            await enqueue_task(task_id)
            await _audit(conn, "task_requeued", "warning", task_id=task_id,
                         data={"reason": "stuck_in_queued"})


# ── Reap timed-out agent sessions ─────────────────────────────────────────────

async def _reap_timed_out_sessions() -> None:
    """
    Find agent sessions running past their timeout_seconds (from pod_agents config).
    Mark them failed. The pipeline executor's heartbeat loop will detect the failed
    session and handle it per the agent's on_failure config (abort/skip/escalate).
    """
    from .db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        timed_out = await conn.fetch(
            """
            SELECT s.id, s.task_id, s.role, pa.timeout_seconds
            FROM agent_sessions s
            LEFT JOIN pod_agents pa ON pa.id = s.pod_agent_id
            WHERE s.status = 'running'
              AND s.started_at IS NOT NULL
              AND s.started_at < now() - (
                  COALESCE(pa.timeout_seconds, 60) + $1
              ) * interval '1 second'
            """,
            SESSION_TIMEOUT_BUFFER,
        )

        for session in timed_out:
            session_id = str(session["id"])
            task_id    = str(session["task_id"])
            logger.warning(
                f"Reaper: agent session {session_id} (role={session['role']}) "
                f"timed out on task {task_id}"
            )
            await conn.execute(
                """
                UPDATE agent_sessions
                SET status = 'failed',
                    error = 'Agent session exceeded timeout',
                    completed_at = now()
                WHERE id = $1
                """,
                session["id"],
            )
            await _audit(conn, "session_timeout", "warning",
                         task_id=task_id,
                         data={"session_id": session_id, "role": session["role"]})


# ── Audit helper ──────────────────────────────────────────────────────────────

async def _audit(
    conn,
    event_type: str,
    severity: str,
    *,
    task_id: str | None = None,
    data: dict | None = None,
) -> None:
    """Write a reaper event to the immutable audit log."""
    import json
    try:
        await conn.execute(
            """
            INSERT INTO audit_log (event_type, severity, task_id, message, data)
            VALUES ($1, $2, $3::uuid, $4, $5::jsonb)
            """,
            event_type,
            severity,
            task_id,
            f"Reaper: {event_type}",
            json.dumps(data or {}),
        )
    except Exception:
        logger.exception("Failed to write reaper audit log entry")
