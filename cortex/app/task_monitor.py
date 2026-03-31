"""Background task monitor — polls dispatched tasks without blocking the cycle.

Replaces the synchronous await_task() pattern. Tasks are tracked in a dict
and results are collected into a queue for the next cycle's PERCEIVE phase.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass

from .clients import get_task_status
from .config import settings
from .task_tracker import _score_task, TaskOutcome, _TERMINAL

log = logging.getLogger(__name__)


@dataclass
class PendingTask:
    """A dispatched task being monitored in the background."""
    task_id: str
    goal_id: str
    cycle_dispatched: int
    plan_text: str
    dispatched_at: float  # time.monotonic()


# Module-level state
_pending: dict[str, PendingTask] = {}  # task_id -> PendingTask
_completed: deque[tuple[PendingTask, TaskOutcome]] = deque()
_monitor_task: asyncio.Task | None = None


def dispatch(task_id: str, goal_id: str, cycle: int, plan_text: str) -> None:
    """Register a newly dispatched task for background monitoring."""
    _pending[task_id] = PendingTask(
        task_id=task_id, goal_id=goal_id,
        cycle_dispatched=cycle, plan_text=plan_text,
        dispatched_at=time.monotonic(),
    )
    _ensure_monitor_running()
    log.info("Monitoring task %s for goal %s (pending=%d)", task_id, goal_id, len(_pending))


def collect_completed() -> list[tuple[PendingTask, TaskOutcome]]:
    """Drain completed tasks. Called during PERCEIVE phase."""
    results = list(_completed)
    _completed.clear()
    return results


def pending_count() -> int:
    """Number of tasks being monitored."""
    return len(_pending)


def pending_goal_ids() -> set[str]:
    """Goal IDs with tasks currently in-flight."""
    return {pt.goal_id for pt in _pending.values()}


def _ensure_monitor_running() -> None:
    """Start the background monitor loop if not already running."""
    global _monitor_task
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(_monitor_loop(), name="task-monitor")


async def _monitor_loop() -> None:
    """Poll all pending tasks at intervals. Moves completed tasks to results queue."""
    poll_interval = settings.task_poll_interval  # 10s
    max_age = settings.task_poll_max_wait  # 300s

    try:
        while _pending:
            await asyncio.sleep(poll_interval)
            done_ids = []

            for task_id, pt in list(_pending.items()):
                try:
                    task = await get_task_status(task_id)
                except Exception as e:
                    log.warning("Error polling task %s: %s", task_id, e)
                    task = None

                if task is None:
                    # Service unreachable — check age-based timeout
                    age = time.monotonic() - pt.dispatched_at
                    if age > max_age:
                        log.warning("Task %s timed out after %.0fs (no response)", task_id, age)
                        _completed.append((pt, TaskOutcome(
                            task_id=task_id, status="unknown", score=0.5, confidence=0.2,
                            timed_out=True,
                        )))
                        done_ids.append(task_id)
                    continue

                status = task.get("status", "unknown")
                if status in _TERMINAL:
                    outcome = _score_task(task, timed_out=False)
                    log.info(
                        "Task %s finished: status=%s score=%.1f (monitored %.0fs)",
                        task_id, outcome.status, outcome.score,
                        time.monotonic() - pt.dispatched_at,
                    )
                    _completed.append((pt, outcome))
                    done_ids.append(task_id)
                else:
                    # Check age-based timeout
                    age = time.monotonic() - pt.dispatched_at
                    if age > max_age:
                        outcome = _score_task(task, timed_out=True)
                        log.warning(
                            "Task %s timed out after %.0fs (status=%s)",
                            task_id, age, status,
                        )
                        _completed.append((pt, outcome))
                        done_ids.append(task_id)

            for tid in done_ids:
                del _pending[tid]

    except Exception as e:
        log.error("Monitor loop crashed: %s — failing all pending tasks", e, exc_info=True)
        for task_id, pt in list(_pending.items()):
            _completed.append((pt, TaskOutcome(
                task_id=task_id, status="failed", score=0.2, confidence=0.5,
                error=f"Monitor crashed: {e}", timed_out=False,
            )))
        _pending.clear()

    log.debug("Monitor loop exiting — no pending tasks")
