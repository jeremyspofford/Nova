"""
Reaper: periodic background task that detects and recovers from failures.

Runs every settings.reaper_interval_seconds as asyncio.create_task in main.py lifespan.
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

from .config import settings

logger = logging.getLogger(__name__)


# ── Main loop ──────────────────────────────────────────────────────────────────

async def reaper_loop() -> None:
    """
    Entry point. Started as asyncio.create_task in main.py lifespan.
    Wakes every settings.reaper_interval_seconds, runs all reap checks, sleeps again.
    """
    logger.info("Reaper started")
    _cycle = 0
    while True:
        try:
            await asyncio.sleep(settings.reaper_interval_seconds)
            await _reap_stale_running_tasks()
            await _reap_stuck_queued_tasks()
            await _reap_timed_out_sessions()
            # Run task history cleanup once per ~60 cycles (~hourly at 60s interval)
            _cycle += 1
            if _cycle % 60 == 0:
                await _cleanup_expired_tasks()
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
        "context_running", "task_running",
        "critique_direction_running", "guardrail_running",
        "code_review_running", "critique_acceptance_running",
        "decision_running", "completing",
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
            str(settings.task_stale_seconds),
        )

        for task in stale_tasks:
            task_id     = str(task["id"])
            retry_count = task["retry_count"]
            max_retries = task["max_retries"]

            if retry_count < max_retries:
                logger.warning(
                    "Reaper: task %s stale in state '%s' (attempt %d/%d) — re-queuing",
                    task_id, task["status"], retry_count + 1, max_retries,
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
                    logger.info("Reaper: task %s already handled by another process — skipping", task_id)
                    continue
                await enqueue_task(task_id)
                await _audit(conn, "task_requeued", "warning", task_id=task_id,
                             data={"retry_count": retry_count + 1, "reason": "heartbeat_timeout"})
            else:
                logger.error(
                    "Reaper: task %s exhausted %d retries — failing", task_id, max_retries,
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
        # CAS UPDATE: atomically claim stuck tasks by bumping queued_at.
        # Only one reaper wins the row — prevents double-enqueue races.
        stuck = await conn.fetch(
            """
            UPDATE tasks
            SET queued_at = now()
            WHERE status = 'queued'
              AND queued_at < now() - ($1 || ' seconds')::interval
            RETURNING id
            """,
            str(settings.stale_queued_seconds),
        )

        for task in stuck:
            task_id = str(task["id"])
            logger.warning("Reaper: task %s stuck in queued state — re-pushing to queue", task_id)
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
            settings.session_timeout_buffer_seconds,
        )

        for session in timed_out:
            session_id = str(session["id"])
            task_id    = str(session["task_id"])
            logger.warning(
                "Reaper: agent session %s (role=%s) timed out on task %s",
                session_id, session["role"], task_id,
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


# ── Auto-cleanup expired task history ─────────────────────────────────────────

async def _cleanup_expired_tasks() -> None:
    """
    Delete terminal tasks older than the configured retention period.
    Reads `task_history_retention_days` from platform config.
    0 or missing = disabled (keep forever).
    """
    from .db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM platform_config WHERE key = 'task_history_retention_days'"
        )
        if not row:
            return
        try:
            days = int(row["value"].strip('"'))
        except (ValueError, TypeError, AttributeError):
            return
        if days <= 0:
            return

        result = await conn.execute(
            """
            DELETE FROM tasks
            WHERE status IN ('complete', 'failed', 'cancelled')
              AND completed_at < now() - ($1 || ' days')::interval
            """,
            str(days),
        )
        deleted = int(result.split()[-1])
        if deleted > 0:
            logger.info("Auto-cleanup: deleted %d tasks older than %d days", deleted, days)
            await _audit(conn, "task_history_cleanup", "info",
                         data={"deleted": deleted, "retention_days": days})


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
    from .audit import write_audit_log
    await write_audit_log(
        conn,
        event_type=event_type,
        severity=severity,
        task_id=task_id,
        message=f"Reaper: {event_type}",
        data=data,
    )
