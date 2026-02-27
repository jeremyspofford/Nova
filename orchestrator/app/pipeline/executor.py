"""
Quartet pipeline executor.

Entry point: execute_pipeline(task_id)
Called by queue.py's queue_worker for every task dequeued from Redis.

Flow:
  1. Load task + pod config from DB
  2. Restore PipelineState from checkpoint (for retry resume)
  3. Execute agents in position order, evaluating run_conditions
  4. Handle the Code Review → Task refactor loop
  5. Persist every agent result as a checkpoint immediately after it completes
  6. Write heartbeats throughout (Reaper detects silence → retry)
  7. Mark task complete / failed / pending_human_review
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..config import settings
from ..db import get_pool
from ..queue import clear_heartbeat, write_heartbeat
from .agents.base import PipelineState, should_agent_run
from .checkpoint import (
    PIPELINE_STAGE_ORDER,
    first_incomplete_stage,
    load_checkpoint,
    save_checkpoint,
)

logger = logging.getLogger(__name__)

# ── Data classes for DB rows ───────────────────────────────────────────────────

@dataclass
class TaskRow:
    id: str
    pod_id: str | None
    user_input: str
    retry_count: int
    max_retries: int
    status: str
    checkpoint: dict
    metadata: dict

@dataclass
class PodRow:
    id: str
    name: str
    default_model: str | None
    max_cost_usd: float | None
    max_execution_seconds: int
    require_human_review: str
    escalation_threshold: str

@dataclass
class AgentRow:
    id: str
    name: str
    role: str
    enabled: bool
    position: int
    parallel_group: str | None
    model: str | None
    fallback_models: list[str]
    temperature: float
    max_tokens: int
    timeout_seconds: int
    max_retries: int
    system_prompt: str | None
    allowed_tools: list[str] | None
    on_failure: str
    run_condition: dict
    artifact_type: str | None


# ── Public API ─────────────────────────────────────────────────────────────────

async def execute_pipeline(task_id: str) -> None:
    """
    Main entry point. Called by queue_worker for every dequeued task.
    Runs the full quartet pipeline and writes final status to the tasks table.
    """
    logger.info(f"Pipeline starting for task {task_id}")
    start = time.monotonic()

    # Start heartbeat loop in background — keeps task alive in Reaper's eyes
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(task_id), name=f"heartbeat:{task_id}"
    )

    try:
        await _run_pipeline(task_id)
    except Exception as exc:
        logger.exception(f"Pipeline error for task {task_id}: {exc}")
        await mark_task_failed(task_id, error=str(exc))
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        await clear_heartbeat(task_id)
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info(f"Pipeline finished for task {task_id} in {elapsed}ms")


async def mark_task_failed(task_id: str, error: str) -> None:
    """Mark a task as failed. Called by queue._run_with_error_guard on crash."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'failed', error = $2, completed_at = now()
            WHERE id = $1 AND status NOT IN ('complete','failed','cancelled')
            """,
            task_id, error,
        )
    await _audit(task_id, "task_failed", "error", {"error": error})


# ── Core pipeline logic ────────────────────────────────────────────────────────

async def _run_pipeline(task_id: str) -> None:
    task = await _load_task(task_id)
    if not task:
        logger.error(f"Task {task_id} not found in DB — skipping")
        return

    # Select pod
    pod = await _load_pod(task.pod_id)
    if not pod:
        pod = await _load_default_pod()
    if not pod:
        await mark_task_failed(task_id, "No pod configured and no default pod found")
        return

    agents = await _load_pod_agents(pod.id)
    if not agents:
        await mark_task_failed(task_id, f"Pod '{pod.name}' has no agents configured")
        return

    # Per-task model override (set via metadata.model_override in the API request)
    model_override: str | None = task.metadata.get("model_override") or None

    # Mark task as started
    await _set_task_status(task_id, "queued")
    await _touch_task_started(task_id, pod.id)

    # Restore pipeline state from checkpoint (for retry resume)
    checkpoint = await load_checkpoint(task_id)
    state = PipelineState(task_input=task.user_input)

    # Reload completed stage outputs into state
    for role, output in checkpoint.items():
        state.completed[role] = output

    # Determine resume point
    stage_roles  = [a.role for a in agents if a.enabled]
    resume_stage = first_incomplete_stage(checkpoint, PIPELINE_STAGE_ORDER)
    logger.info(
        f"Task {task_id}: pod='{pod.name}' agents={len(agents)} "
        f"checkpoint={list(checkpoint.keys())} resume_from='{resume_stage}'"
    )

    # ── Execute pipeline ───────────────────────────────────────────────────
    code_review_iterations = 0
    task_agent_idx: int | None = None
    i = 0

    while i < len(agents):
        agent = agents[i]

        # Track task agent index for refactor looping
        if agent.role == "task":
            task_agent_idx = i

        # Skip disabled agents
        if not agent.enabled:
            i += 1
            continue

        # Skip if run_condition not satisfied
        if not should_agent_run(agent.run_condition, state):
            logger.debug(f"Skipping {agent.role} (run_condition not met)")
            i += 1
            continue

        # Skip checkpointed stages (already completed on a prior attempt)
        if agent.role in checkpoint and not _needs_rerun(agent.role, state):
            logger.debug(f"Skipping {agent.role} (already checkpointed)")
            i += 1
            continue

        # ── Run this agent ─────────────────────────────────────────────
        result = await _run_agent(agent, task_id, state, pod, code_review_iterations, model_override=model_override)

        if result is None:
            # Agent failed with on_failure=abort → task fails
            await mark_task_failed(task_id, f"Agent '{agent.role}' failed (on_failure=abort)")
            return

        # ── Post-run state updates ─────────────────────────────────────
        state.completed[agent.role] = result

        # Update pipeline flags
        if agent.role == "guardrail" and result.get("blocked"):
            state.flags.add("guardrail_blocked")
            logger.warning(f"Task {task_id}: Guardrail blocked output")

        if agent.role == "code_review":
            verdict = result.get("verdict", "pass")
            if verdict == "pass":
                state.flags.add("code_review_passed")
                state.flags.discard("code_review_rejected")
            elif verdict == "needs_refactor":
                code_review_iterations += 1
                if code_review_iterations < agent.max_retries and task_agent_idx is not None:
                    logger.info(
                        f"Task {task_id}: Code Review needs_refactor "
                        f"(iteration {code_review_iterations}/{agent.max_retries}) — looping to Task Agent"
                    )
                    # Build feedback string from issues
                    issues_text = "\n".join(
                        f"- [{iss['severity'].upper()}] {iss['description']}"
                        + (f" ({iss.get('file', '')}:{iss.get('line', '')})" if iss.get('file') else "")
                        for iss in result.get("issues", [])
                    )
                    state.completed["_refactor_feedback"] = issues_text
                    # Clear task checkpoint so Task Agent re-runs
                    if "task" in checkpoint:
                        del checkpoint["task"]
                        state.completed.pop("task", None)
                    i = task_agent_idx
                    continue
                else:
                    state.flags.add("code_review_rejected")
                    logger.warning(
                        f"Task {task_id}: Code Review rejected after {code_review_iterations} iterations"
                    )
            elif verdict == "reject":
                state.flags.add("code_review_rejected")

        # Save checkpoint after successful stage
        await save_checkpoint(task_id, agent.role, result)
        await _audit(task_id, f"stage_{agent.role}_complete", "info",
                     {"verdict": result.get("verdict"), "blocked": result.get("blocked")})

        # Check if human review needed after this stage
        if _should_pause_for_review(state, pod, result, agent.role):
            escalation_msg = result.get("escalation_message", "Task requires human review.")
            await _pause_for_human_review(task_id, escalation_msg)
            return

        i += 1

    # ── Pipeline complete ──────────────────────────────────────────────────
    final_output = state.completed.get("task", {}).get("output", "Task completed.")
    await _complete_task(task_id, final_output, state)


# ── Agent runner ───────────────────────────────────────────────────────────────

async def _run_agent(
    agent: AgentRow,
    task_id: str,
    state: PipelineState,
    pod: PodRow,
    code_review_iteration: int = 0,
    model_override: str | None = None,
) -> dict | None:
    """
    Instantiate and run a single agent. Returns output dict on success.
    Returns None if the agent failed and on_failure=abort.
    On on_failure=skip, returns an empty dict so the pipeline continues.
    """
    from .agents.context     import ContextAgent
    from .agents.task        import TaskAgent
    from .agents.guardrail   import GuardrailAgent
    from .agents.code_review import CodeReviewAgent
    from .agents.decision    import DecisionAgent

    # Resolve model: per-task override → agent → pod default → service default
    model = model_override or agent.model or pod.default_model or settings.default_model

    AGENT_CLASSES = {
        "context":     ContextAgent,
        "task":        TaskAgent,
        "guardrail":   GuardrailAgent,
        "code_review": CodeReviewAgent,
        "decision":    DecisionAgent,
    }

    agent_cls = AGENT_CLASSES.get(agent.role)
    if not agent_cls:
        logger.warning(f"Unknown agent role '{agent.role}' — skipping")
        return {}

    instance = agent_cls(
        model=model,
        system_prompt=agent.system_prompt,
        allowed_tools=agent.allowed_tools,
        temperature=agent.temperature,
        max_tokens=agent.max_tokens,
        fallback_models=agent.fallback_models,
    )

    # Create agent_session row
    session_id = await _create_session(task_id, agent)
    await _set_task_status(task_id, f"{agent.role}_running", current_stage=agent.role)

    start = time.monotonic()
    try:
        if agent.role == "task":
            refactor_feedback = state.completed.get("_refactor_feedback")
            result = await instance.run(state, refactor_feedback=refactor_feedback)
        elif agent.role == "code_review":
            result = await instance.run(state, iteration=code_review_iteration + 1)
        else:
            result = await instance.run(state)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        await _complete_session(session_id, result, elapsed_ms)
        return result

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.error(f"Agent '{agent.role}' error on task {task_id}: {exc}")
        await _fail_session(session_id, str(exc), elapsed_ms)

        if agent.on_failure == "skip":
            logger.info(f"Agent '{agent.role}' failed with on_failure=skip — continuing")
            return {}
        if agent.on_failure == "escalate":
            await _pause_for_human_review(task_id, f"Agent '{agent.role}' failed: {exc}")
            return None
        # on_failure == "abort" (default)
        return None


# ── Status / DB helpers ────────────────────────────────────────────────────────

async def _load_task(task_id: str) -> TaskRow | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, pod_id, user_input, retry_count, max_retries, status, checkpoint, metadata "
            "FROM tasks WHERE id = $1",
            task_id,
        )
    if not row:
        return None
    return TaskRow(
        id=str(row["id"]),
        pod_id=str(row["pod_id"]) if row["pod_id"] else None,
        user_input=row["user_input"],
        retry_count=row["retry_count"],
        max_retries=row["max_retries"],
        status=row["status"],
        checkpoint=dict(row["checkpoint"] or {}),
        metadata=dict(row["metadata"] or {}),
    )


async def _load_pod(pod_id: str | None) -> PodRow | None:
    if not pod_id:
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, default_model, max_cost_usd, max_execution_seconds, "
            "require_human_review, escalation_threshold FROM pods WHERE id = $1 AND enabled = true",
            pod_id,
        )
    if not row:
        return None
    return PodRow(**{k: (str(v) if k == "id" else v) for k, v in dict(row).items()})


async def _load_default_pod() -> PodRow | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, default_model, max_cost_usd, max_execution_seconds, "
            "require_human_review, escalation_threshold "
            "FROM pods WHERE name = $1 AND enabled = true",
            settings.default_pod_name,
        )
    if not row:
        return None
    return PodRow(**{k: (str(v) if k == "id" else v) for k, v in dict(row).items()})


async def _load_pod_agents(pod_id: str) -> list[AgentRow]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, role, enabled, position, parallel_group,
                   model, fallback_models, temperature, max_tokens, timeout_seconds,
                   max_retries, system_prompt, allowed_tools, on_failure,
                   run_condition, artifact_type
            FROM pod_agents
            WHERE pod_id = $1
            ORDER BY position ASC
            """,
            pod_id,
        )
    return [
        AgentRow(
            id=str(r["id"]),
            name=r["name"],
            role=r["role"],
            enabled=r["enabled"],
            position=r["position"],
            parallel_group=r["parallel_group"],
            model=r["model"],
            fallback_models=list(r["fallback_models"]) if r["fallback_models"] else [],
            temperature=float(r["temperature"]),
            max_tokens=r["max_tokens"],
            timeout_seconds=r["timeout_seconds"],
            max_retries=r["max_retries"],
            system_prompt=r["system_prompt"],
            allowed_tools=list(r["allowed_tools"]) if r["allowed_tools"] else None,
            on_failure=r["on_failure"],
            run_condition=dict(r["run_condition"] or {"type": "always"}),
            artifact_type=r["artifact_type"],
        )
        for r in rows
    ]


async def _set_task_status(
    task_id: str,
    status: str,
    current_stage: str | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = $2, current_stage = COALESCE($3, current_stage),
                last_heartbeat_at = now()
            WHERE id = $1
            """,
            task_id, status, current_stage,
        )


async def _touch_task_started(task_id: str, pod_id: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tasks SET started_at = now(), pod_id = $2 WHERE id = $1 AND started_at IS NULL",
            task_id, pod_id,
        )


async def _complete_task(task_id: str, output: str, state: PipelineState) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'complete', output = $2, completed_at = now(), current_stage = NULL
            WHERE id = $1
            """,
            task_id, output,
        )
    await _audit(task_id, "task_complete", "info", {"flags": list(state.flags)})
    logger.info(f"Task {task_id} complete")


async def _pause_for_human_review(task_id: str, escalation_message: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'pending_human_review',
                metadata = metadata || jsonb_build_object('escalation_message', $2::text),
                current_stage = NULL
            WHERE id = $1
            """,
            task_id, escalation_message,
        )
    await _audit(task_id, "task_escalated", "warning", {"message": escalation_message})
    logger.warning(f"Task {task_id} paused for human review: {escalation_message}")


async def _create_session(task_id: str, agent: AgentRow) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_sessions
                (task_id, pod_agent_id, role, position, status, model, started_at)
            VALUES ($1, $2::uuid, $3, $4, 'running', $5, now())
            RETURNING id
            """,
            task_id, agent.id, agent.role, agent.position, agent.model,
        )
    return str(row["id"])


async def _complete_session(session_id: str, output: dict, elapsed_ms: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE agent_sessions
            SET status = 'complete', output = $2::jsonb,
                completed_at = now(), duration_ms = $3
            WHERE id = $1
            """,
            session_id, output, elapsed_ms,
        )


async def _fail_session(session_id: str, error: str, elapsed_ms: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE agent_sessions
            SET status = 'failed', error = $2,
                completed_at = now(), duration_ms = $3
            WHERE id = $1
            """,
            session_id, error, elapsed_ms,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _needs_rerun(role: str, state: PipelineState) -> bool:
    """Return True if a checkpointed stage needs to run again (e.g. task after refactor)."""
    if role == "task" and "_refactor_feedback" in state.completed:
        return True
    return False


def _should_pause_for_review(
    state: PipelineState,
    pod: PodRow,
    result: dict,
    agent_role: str,
) -> bool:
    """Determine if the pipeline should pause for human review after this stage."""
    if pod.require_human_review == "always":
        return agent_role == "decision"  # pause after decision agent on always mode

    if pod.require_human_review == "never":
        return False

    # on_escalation (default): pause if decision agent chose escalate
    if agent_role == "decision" and result.get("action") == "escalate":
        return True

    # Also pause if guardrail found critical findings and threshold is low
    if agent_role == "guardrail" and result.get("blocked"):
        finding_severities = {f.get("severity") for f in result.get("findings", [])}
        threshold_map = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        threshold_val = threshold_map.get(pod.escalation_threshold, 2)
        severity_vals = {threshold_map.get(s, 0) for s in finding_severities}
        if any(v >= threshold_val for v in severity_vals):
            return True

    return False


async def _heartbeat_loop(task_id: str) -> None:
    """Write a heartbeat every task_heartbeat_interval_seconds while the pipeline runs."""
    interval = settings.task_heartbeat_interval_seconds
    while True:
        try:
            await write_heartbeat(task_id)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception(f"Heartbeat error for task {task_id}")
            await asyncio.sleep(interval)


async def _audit(
    task_id: str,
    event_type: str,
    severity: str,
    data: dict | None = None,
) -> None:
    """Best-effort write to the immutable audit log."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (event_type, severity, task_id, message, data)
                VALUES ($1, $2, $3::uuid, $4, $5::jsonb)
                """,
                event_type, severity, task_id,
                f"Pipeline: {event_type}",
                data or {},
            )
    except Exception:
        logger.exception("Failed to write pipeline audit log entry")
