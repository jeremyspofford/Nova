"""Task feedback loop — poll dispatched tasks and score outcomes.

After cortex dispatches a pipeline task, this module polls the orchestrator
until the task reaches a terminal state (or times out), then returns a
structured result with an accurate outcome score.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .clients import get_task_status
from .config import settings

log = logging.getLogger(__name__)

# Terminal task statuses — the task won't change after reaching one of these
_TERMINAL = frozenset({"complete", "failed", "cancelled"})


@dataclass
class TaskOutcome:
    """Result of waiting for a dispatched task."""
    task_id: str
    status: str  # complete | failed | cancelled | running | unknown
    score: float  # 0.0–1.0 outcome score
    confidence: float  # how confident we are in the score
    output: str | None = None
    error: str | None = None
    findings_count: int = 0
    timed_out: bool = False
    total_cost_usd: float = 0.0


def _score_task(task: dict, timed_out: bool) -> TaskOutcome:
    """Derive an outcome score from a task's terminal state."""
    task_id = task.get("id", "unknown")
    status = task.get("status", "unknown")
    output = task.get("output")
    error = task.get("error")
    findings_count = task.get("findings_count", 0)
    total_cost_usd = float(task.get("total_cost_usd") or 0)

    if timed_out:
        return TaskOutcome(
            task_id=task_id, status="running", score=0.5, confidence=0.3,
            output=output, error=error, findings_count=findings_count,
            timed_out=True, total_cost_usd=total_cost_usd,
        )

    if status == "complete":
        # Guardrail findings indicate the task completed but with issues
        if findings_count > 0:
            return TaskOutcome(
                task_id=task_id, status=status, score=0.6, confidence=0.8,
                output=output, error=error, findings_count=findings_count,
                total_cost_usd=total_cost_usd,
            )
        return TaskOutcome(
            task_id=task_id, status=status, score=0.8, confidence=0.9,
            output=output, error=error, findings_count=findings_count,
            total_cost_usd=total_cost_usd,
        )

    if status == "failed":
        return TaskOutcome(
            task_id=task_id, status=status, score=0.2, confidence=0.9,
            output=output, error=error, findings_count=findings_count,
            total_cost_usd=total_cost_usd,
        )

    if status == "cancelled":
        return TaskOutcome(
            task_id=task_id, status=status, score=0.1, confidence=0.9,
            output=output, error=error, findings_count=findings_count,
            total_cost_usd=total_cost_usd,
        )

    # Unexpected status — treat as unknown
    return TaskOutcome(
        task_id=task_id, status=status, score=0.5, confidence=0.3,
        output=output, error=error, findings_count=findings_count,
        total_cost_usd=total_cost_usd,
    )


async def await_task(task_id: str) -> TaskOutcome:
    """Poll a dispatched task until it completes or times out.

    Polls every `task_poll_interval` seconds, up to `task_poll_max_wait` total.
    Returns a TaskOutcome with the actual score based on the task result.
    """
    poll_interval = settings.task_poll_interval
    max_wait = settings.task_poll_max_wait
    elapsed = 0

    log.info("Tracking task %s (poll=%ds, max_wait=%ds)", task_id, poll_interval, max_wait)

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        task = await get_task_status(task_id)
        if task is None:
            # Task not found or service unreachable — keep trying until timeout
            log.debug("Task %s: poll returned None (elapsed=%ds)", task_id, elapsed)
            continue

        status = task.get("status", "unknown")
        log.debug("Task %s: status=%s (elapsed=%ds)", task_id, status, elapsed)

        if status in _TERMINAL:
            outcome = _score_task(task, timed_out=False)
            log.info(
                "Task %s finished: status=%s score=%.1f findings=%d (waited %ds)",
                task_id, outcome.status, outcome.score, outcome.findings_count, elapsed,
            )
            return outcome

    # Timed out — get the latest state for the score
    log.warning("Task %s still running after %ds — continuing cycle", task_id, max_wait)
    task = await get_task_status(task_id)
    if task is None:
        return TaskOutcome(
            task_id=task_id, status="unknown", score=0.5, confidence=0.2,
            timed_out=True,
        )
    return _score_task(task, timed_out=True)
