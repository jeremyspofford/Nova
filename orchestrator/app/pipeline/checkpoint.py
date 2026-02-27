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

# Stage roles in execution order — used to determine resume point
PIPELINE_STAGE_ORDER = [
    "context",
    "task",
    "guardrail",
    "code_review",
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
        return dict(row["checkpoint"] or {})


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
#   checkpoint    — output of load_checkpoint() — {stage: data} for completed stages
#   retry_count   — how many times this task has already been retried
#   max_retries   — configured limit
#   current_status — the task's status at time of failure
#   error         — the error message from the failed run (if any)
#
# Return one of: "resume" | "restart" | "escalate" | "abandon"

def recovery_strategy(
    checkpoint: dict[str, Any],
    retry_count: int,
    max_retries: int,
    current_status: str,
    error: str | None,
) -> str:
    """
    Decide how to recover a failed or stale task.

    Decision ladder (evaluated top-to-bottom, first match wins):
      1. Human review state       → escalate  (never auto-recover)
      2. Retries exhausted        → abandon   (dead-letter for inspection)
      3. Terminal error pattern   → escalate  (retrying won't help; surface to human)
      4. First retry, checkpoint  → resume    (optimistic: skip completed stages)
      5. First retry, no ckpt     → restart   (nothing to resume from)
      6. Subsequent retry, 2+ckpts→ resume    (expensive work worth preserving)
      7. Subsequent retry, <2ckpts→ restart   (not much done; start clean)
    """
    # Errors that indicate a permanent condition — retrying is pointless
    TERMINAL_PATTERNS = (
        "permission denied",
        "forbidden",
        "unauthorized",
        "not found",
        "does not exist",
        "no such file",
        "invalid api key",
        "quota exceeded",
    )

    # 1. Never auto-recover tasks waiting on a human decision
    if current_status == "pending_human_review":
        return "escalate"

    # 2. Exhausted all configured retries — give up cleanly
    if retry_count >= max_retries:
        return "abandon"

    # 3. Terminal errors won't be fixed by retrying — escalate immediately
    if error and any(p in error.lower() for p in TERMINAL_PATTERNS):
        logger.warning("Terminal error detected, escalating task: %s", error)
        return "escalate"

    # 4 & 5. First retry: be optimistic
    if retry_count == 0:
        return "resume" if checkpoint else "restart"

    # 6 & 7. Subsequent retries: preserve expensive checkpoint work (context + task
    # together represent the majority of LLM cost); restart if little was saved
    return "resume" if len(checkpoint) >= 2 else "restart"
