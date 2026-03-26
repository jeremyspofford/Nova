"""
Pipeline checkpoint system.

After each agent stage completes successfully, the executor calls save_checkpoint()
to persist the stage output to tasks.checkpoint (JSONB column).

On retry (triggered by the Reaper), load_checkpoint() lets the executor
skip already-completed stages and resume from the first incomplete one.

This means a task that crashes during Guardrail doesn't re-run Context + Task —
it resumes exactly where it left off.

Design note:
  Checkpoints are stored as a flat dict: {stage_role: stage_output_dict}
  e.g. {"context": {"curated_docs": "..."}, "task": {"code": "...", "explanation": "..."}}
  The executor checks this dict before running each stage.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Error classification ──────────────────────────────────────────────────────
#
# Structured error types from the error_context JSONB column (migration 044).
# Grouped by recovery behavior rather than matching on fragile substrings.

# Transient errors — worth retrying with standard backoff
_TRANSIENT_ERROR_TYPES = frozenset({
    "TimeoutError",
    "asyncio.TimeoutError",
    "ConnectionError",
    "ConnectionRefusedError",
    "ConnectionResetError",
    "OSError",
    "httpx.ConnectError",
    "httpx.ReadTimeout",
    "httpx.ConnectTimeout",
})

# Terminal errors — retrying won't fix the underlying cause
_TERMINAL_ERROR_TYPES = frozenset({
    "AuthenticationError",
    "PermissionError",
    "Forbidden",
    "Unauthorized",
    "ValidationError",
    "ValueError",
    "TypeError",
    "KeyError",
    "SchemaError",
    "pydantic.ValidationError",
    "InvalidAPIKeyError",
})

# Resource exhaustion — retry with longer backoff
_RESOURCE_ERROR_TYPES = frozenset({
    "MemoryError",
    "RateLimitError",
    "ResourceExhaustedError",
    "QuotaExceededError",
    "httpx.PoolTimeout",
})

# Maximum backoff cap in seconds
_MAX_BACKOFF_SECONDS = 120

# Stage roles in execution order — used to determine resume point
PIPELINE_STAGE_ORDER = [
    "context",
    "task",
    "critique_direction",
    "guardrail",
    "code_review",
    "critique_acceptance",
    "decision",
]


# ── Save / Load ────────────────────────────────────────────────────────────────

async def save_checkpoint(task_id: str, stage: str, output: dict[str, Any]) -> None:
    """
    Persist a completed stage's output to the tasks.checkpoint column.
    Called immediately after a stage agent returns successfully.
    Safe to call concurrently — uses a JSON merge update.
    """
    from ..db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET checkpoint = checkpoint || jsonb_build_object($2::text, $3::jsonb)
            WHERE id = $1
            """,
            task_id,
            stage,
            output,  # dict → codec handles JSONB serialisation
        )
    logger.debug(f"Checkpoint saved: task={task_id} stage={stage}")


async def load_checkpoint(task_id: str) -> dict[str, Any]:
    """
    Load all saved checkpoints for a task.
    Returns a dict of {stage: output} for stages that already completed.
    Empty dict if the task has never been checkpointed (fresh start).
    """
    from ..db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT checkpoint FROM tasks WHERE id = $1", task_id
        )
        if row is None:
            return {}
        return row["checkpoint"] if isinstance(row["checkpoint"], dict) else {}


async def clear_checkpoint(task_id: str) -> None:
    """
    Wipe all checkpoints for a task.
    Called when a task is forcefully restarted from scratch (not a resume retry).
    """
    from ..db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tasks SET checkpoint = '{}' WHERE id = $1", task_id
        )


def first_incomplete_stage(
    checkpoint: dict[str, Any],
    stage_order: list[str],
) -> str:
    """
    Return the first stage in stage_order that is NOT in the checkpoint.
    If all stages are checkpointed, returns the last stage name (pipeline is done).
    The executor uses this to know where to resume after a retry.

    Example:
      checkpoint = {"context": {...}, "task": {...}}
      stage_order = ["context", "task", "guardrail", "code_review"]
      → returns "guardrail"
    """
    for stage in stage_order:
        if stage not in checkpoint:
            return stage
    return stage_order[-1]


# ── Recovery strategy ──────────────────────────────────────────────────────────
#
# This function is called by the Reaper (and the executor on retry) to decide
# WHAT to do with a failed task given its current checkpoint state.
#
# The decision shapes the entire recovery behavior:
#   - "resume"  → pick up from the first un-checkpointed stage
#   - "restart" → wipe the checkpoint and start from the beginning
#   - "escalate"→ move to pending_human_review, do not retry automatically
#   - "abandon" → mark as failed, move to dead letter
#
# Design considerations:
#   1. A task that checkpointed context+task but crashed in guardrail should almost
#      always RESUME — re-running two expensive LLM calls for no reason wastes money.
#   2. A task that crashed with zero checkpoints (nothing completed) has nothing to
#      resume from — RESTART is appropriate.
#   3. A task that has been retried many times suggests something is systematically
#      wrong — ESCALATE to human review rather than looping forever.
#   4. A task in pending_human_review should never be auto-recovered.
#
# Parameters:
#   checkpoint     — output of load_checkpoint() — {stage: data} for completed stages
#   retry_count    — how many times this task has already been retried
#   max_retries    — configured limit
#   current_status — the task's status at time of failure
#   error          — the error message from the failed run (if any)
#   error_context  — structured JSONB from migration 044 (optional, for backward compat)
#
# Returns a dict: {"action": "resume"|"restart"|"escalate"|"abandon",
#                   "delay_s": float, "reason": str}

def _classify_error_context(error_context: dict[str, Any]) -> str:
    """
    Classify an error by its structured error_context JSONB.

    Returns one of: "transient", "terminal", "resource", "unknown"
    """
    error_type = error_context.get("type", "")

    # Explicit retryable flag from the executor takes priority
    retryable = error_context.get("retryable")
    if retryable is False:
        return "terminal"

    if error_type in _TERMINAL_ERROR_TYPES:
        return "terminal"
    if error_type in _RESOURCE_ERROR_TYPES:
        return "resource"
    if error_type in _TRANSIENT_ERROR_TYPES:
        return "transient"

    return "unknown"


def backoff_delay(retry_count: int, base_delay: float = 5.0) -> float:
    """
    Exponential backoff: base_delay * 2^retry_count, capped at _MAX_BACKOFF_SECONDS.

    This does NOT block — it returns metadata for the reaper to use when
    scheduling the next retry.
    """
    return min(base_delay * (2 ** retry_count), _MAX_BACKOFF_SECONDS)


def recovery_strategy(
    checkpoint: dict[str, Any],
    retry_count: int,
    max_retries: int,
    current_status: str,
    error: str | None,
    error_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Decide how to recover a failed or stale task.

    Returns a dict with:
      action   — "resume" | "restart" | "escalate" | "abandon"
      delay_s  — suggested delay before retry (0 for non-retry actions)
      reason   — human-readable explanation for logging/audit

    Decision ladder (evaluated top-to-bottom, first match wins):
      1. Human review state           → escalate  (never auto-recover)
      2. Retries exhausted            → abandon   (dead-letter for inspection)
      3. Structured error_context     → classify by error type (new path)
      4. Substring fallback           → legacy pattern matching (backward compat)
      5. First retry, checkpoint      → resume    (optimistic)
      6. First retry, no ckpt         → restart   (nothing to resume from)
      7. Subsequent retry, 2+ ckpts   → resume    (expensive work worth preserving)
      8. Subsequent retry, <2 ckpts   → restart   (not much done; start clean)
    """

    def _result(action: str, reason: str, delay_s: float = 0.0) -> dict[str, Any]:
        return {"action": action, "delay_s": delay_s, "reason": reason}

    # 1. Never auto-recover tasks waiting on a human decision
    if current_status == "pending_human_review":
        return _result("escalate", "task is in pending_human_review")

    # 2. Exhausted all configured retries — give up cleanly
    if retry_count >= max_retries:
        return _result("abandon", f"retry limit reached ({retry_count}/{max_retries})")

    # 3. Structured error classification (new path — requires error_context JSONB)
    if error_context and isinstance(error_context, dict) and error_context.get("type"):
        classification = _classify_error_context(error_context)

        if classification == "terminal":
            logger.warning(
                "Terminal error type '%s', escalating task: %s",
                error_context.get("type"),
                error_context.get("message", "")[:200],
            )
            return _result(
                "escalate",
                f"terminal error type: {error_context.get('type')}",
            )

        if classification == "resource":
            delay = backoff_delay(retry_count, base_delay=15.0)
            logger.info(
                "Resource error '%s', retrying with extended backoff (%.1fs)",
                error_context.get("type"),
                delay,
            )
            action = "resume" if checkpoint else "restart"
            return _result(action, f"resource error: {error_context.get('type')}", delay)

        if classification == "transient":
            delay = backoff_delay(retry_count, base_delay=5.0)
            action = "resume" if checkpoint else "restart"
            return _result(action, f"transient error: {error_context.get('type')}", delay)

        # Unknown error type — retry for first 2 attempts, then escalate
        if retry_count >= 2:
            logger.warning(
                "Unknown error type '%s' after %d retries, escalating",
                error_context.get("type"),
                retry_count,
            )
            return _result(
                "escalate",
                f"unknown error type '{error_context.get('type')}' after {retry_count} retries",
            )
        delay = backoff_delay(retry_count)
        action = "resume" if checkpoint else "restart"
        return _result(action, f"unknown error type: {error_context.get('type')}", delay)

    # 4. Fallback: substring matching for tasks without error_context (backward compat)
    _TERMINAL_PATTERNS = (
        "permission denied",
        "forbidden",
        "unauthorized",
        "not found",
        "does not exist",
        "no such file",
        "invalid api key",
        "quota exceeded",
    )
    if error and any(p in error.lower() for p in _TERMINAL_PATTERNS):
        logger.warning("Terminal error detected (substring fallback), escalating: %s", error[:200])
        return _result("escalate", f"terminal error pattern in message: {error[:100]}")

    # 5 & 6. First retry: be optimistic
    if retry_count == 0:
        action = "resume" if checkpoint else "restart"
        return _result(action, "first retry attempt")

    # 7 & 8. Subsequent retries: preserve expensive checkpoint work
    action = "resume" if len(checkpoint) >= 2 else "restart"
    delay = backoff_delay(retry_count)
    return _result(action, f"retry {retry_count}, checkpoints={len(checkpoint)}", delay)
