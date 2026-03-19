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
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..audit import write_audit_log
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
    sandbox: str = "workspace"

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
    from nova_contracts.logging import set_context, clear_context
    set_context(task_id=task_id)

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
        clear_context()


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
    await _backfill_training_success(task_id, success=False)
    await _audit(task_id, "task_failed", "error", {"error": error})
    # Emit activity event for dashboard feed
    try:
        from ..activity import emit_activity
        await emit_activity(pool, "task_failed", "pipeline", f"Task {task_id[:8]}... failed: {error[:120]}", severity="error", metadata={"task_id": task_id, "error": error[:500]})
    except Exception:
        pass


# ── Core pipeline logic ────────────────────────────────────────────────────────

async def _run_pipeline(task_id: str) -> None:
    task = await _load_task(task_id)
    if not task:
        logger.error(f"Task {task_id} not found in DB — skipping")
        return

    # Select pod — falls back to default pod if task.pod_id is None or not found
    pod = await _load_pod(task.pod_id) or await _load_pod(None)
    if not pod:
        await mark_task_failed(task_id, "No pod configured and no default pod found")
        return

    agents = await _load_pod_agents(pod.id)
    if not agents:
        await mark_task_failed(task_id, f"Pod '{pod.name}' has no agents configured")
        return

    # Per-task model override (set via metadata.model_override in the API request)
    model_override: str | None = task.metadata.get("model_override") or None

    # Classify task complexity for model routing (Phase 3)
    from .complexity_classifier import classify_complexity
    complexity = await classify_complexity(task.user_input)
    if complexity:
        logger.info(f"Task {task_id}: complexity classified as '{complexity}'")

    # Mark task as started
    await _set_task_status(task_id, "queued")
    await _touch_task_started(task_id, pod.id)

    # Restore pipeline state from checkpoint (for retry resume)
    checkpoint = await load_checkpoint(task_id)
    state = PipelineState(task_input=task.user_input, complexity=complexity)

    # Reload completed stage outputs into state
    for role, output in checkpoint.items():
        state.completed[role] = output

    # ── Adaptive stage skipping (Phase 4b) ────────────────────────────────
    # Use complexity classification to skip stages that add no value for
    # simple tasks.  We inject synthetic checkpoint entries so the existing
    # skip-if-checkpointed logic handles them transparently.
    if complexity:
        skipped = _apply_adaptive_skips(complexity, task.user_input, state, checkpoint, task_id)
        if skipped:
            # Persist the synthetic checkpoints to the DB so retries also skip
            for role in skipped:
                await save_checkpoint(task_id, role, state.completed[role])

    # Determine resume point
    stage_roles  = [a.role for a in agents if a.enabled]
    resume_stage = first_incomplete_stage(checkpoint, PIPELINE_STAGE_ORDER)
    logger.info(
        f"Task {task_id}: pod='{pod.name}' agents={len(agents)} "
        f"checkpoint={list(checkpoint.keys())} resume_from='{resume_stage}'"
    )

    # ── Execute pipeline ───────────────────────────────────────────────────
    code_review_iterations = 0
    direction_iterations = 0
    acceptance_iterations = 0
    task_agent_idx: int | None = None
    i = 0

    while i < len(agents):
        agent = agents[i]

        # ── Parallel group detection ──────────────────────────────────
        # If this agent has a parallel_group, collect all consecutive agents
        # sharing the same group and run them concurrently.
        if agent.parallel_group and agent.enabled:
            group_name = agent.parallel_group
            group_agents = []
            j = i
            while j < len(agents) and agents[j].parallel_group == group_name:
                group_agents.append(agents[j])
                j += 1

            if len(group_agents) > 1:
                logger.info(
                    f"Task {task_id}: Running parallel group '{group_name}' "
                    f"({len(group_agents)} agents: {[a.role for a in group_agents]})"
                )
                abort = await _run_parallel_group(
                    group_agents, task_id, state, pod, checkpoint,
                    code_review_iterations, model_override, complexity=complexity,
                )
                if abort:
                    await mark_task_failed(task_id, f"Parallel group '{group_name}' had a fatal agent failure")
                    return

                # ── Post-group flag processing ──────────────────────────
                # _run_parallel_group merges results into state.completed and
                # saves checkpoints, but flag-setting, refactor loops, and
                # human-review pauses must be handled here.

                # Guardrail flags
                guardrail_result = state.completed.get("guardrail")
                if guardrail_result and guardrail_result.get("blocked"):
                    state.flags.add("guardrail_blocked")
                    logger.warning(f"Task {task_id}: Guardrail blocked output")
                    if _should_pause_for_review(state, pod, guardrail_result, "guardrail"):
                        escalation_msg = guardrail_result.get(
                            "escalation_message", "Task requires human review."
                        )
                        await _pause_for_human_review(task_id, escalation_msg, state)
                        return

                # Code Review flags + refactor loop
                code_review_result = state.completed.get("code_review")
                if code_review_result:
                    cr_agent = next(
                        (a for a in group_agents if a.role == "code_review"), None
                    )
                    verdict = code_review_result.get("verdict", "pass")
                    if verdict == "pass":
                        state.flags.add("code_review_passed")
                        state.flags.discard("code_review_rejected")
                    elif verdict == "needs_refactor":
                        code_review_iterations += 1
                        max_refactor = cr_agent.max_retries if cr_agent else 1
                        if code_review_iterations < max_refactor and task_agent_idx is not None:
                            logger.info(
                                f"Task {task_id}: Code Review needs_refactor "
                                f"(iteration {code_review_iterations}/{max_refactor}) "
                                f"— looping to Task Agent"
                            )
                            issues_text = "\n".join(
                                f"- [{iss['severity'].upper()}] {iss['description']}"
                                + (f" ({iss.get('file', '')}:{iss.get('line', '')})"
                                   if iss.get("file") else "")
                                for iss in code_review_result.get("issues", [])
                            )
                            state.completed["_refactor_feedback"] = issues_text
                            # Clear checkpoints so Task, critique, Guardrail, and Code Review re-run
                            for clear_role in ("task", "critique_direction", "guardrail", "code_review", "critique_acceptance"):
                                checkpoint.pop(clear_role, None)
                                state.completed.pop(clear_role, None)
                            i = task_agent_idx
                            continue
                        else:
                            state.flags.add("code_review_rejected")
                            logger.warning(
                                f"Task {task_id}: Code Review rejected after "
                                f"{code_review_iterations} iterations"
                            )
                    elif verdict == "reject":
                        state.flags.add("code_review_rejected")

                # Post-group compaction
                await _maybe_compact_state(state, task_id)
                i = j
                continue

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
        result, session_id = await _run_agent(agent, task_id, state, pod, code_review_iterations, model_override=model_override, complexity=complexity)

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
                    # Clear checkpoints so Task, critique, guardrail, and Code Review re-run
                    for clear_role in ("task", "critique_direction", "guardrail", "code_review", "critique_acceptance"):
                        checkpoint.pop(clear_role, None)
                        state.completed.pop(clear_role, None)
                    i = task_agent_idx
                    continue
                else:
                    state.flags.add("code_review_rejected")
                    logger.warning(
                        f"Task {task_id}: Code Review rejected after {code_review_iterations} iterations"
                    )
            elif verdict == "reject":
                state.flags.add("code_review_rejected")

        # Set has_code_artifacts flag after Task Agent produces code
        if agent.role == "task":
            if result.get("artifact_type") in ("code", "config") or result.get("files_changed"):
                state.flags.add("has_code_artifacts")

        # ── Critique-Direction handling ──────────────────────────────
        if agent.role == "critique_direction":
            verdict = result.get("verdict", "approved")
            if verdict == "approved":
                state.flags.add("critique_approved")
                logger.info(f"Task {task_id}: Critique-Direction approved")
            elif verdict == "needs_revision":
                direction_iterations += 1
                if direction_iterations < settings.clarification_max_rounds and task_agent_idx is not None:
                    state.completed["_critique_feedback"] = result.get("feedback", "")
                    for clear_role in ("task", "critique_direction"):
                        checkpoint.pop(clear_role, None)
                        state.completed.pop(clear_role, None)
                    i = task_agent_idx
                    continue
                else:
                    await _pause_for_human_review(task_id, "Critique-Direction exhausted revision rounds", state)
                    return
            elif verdict == "needs_clarification":
                questions = result.get("questions", ["Could you clarify your request?"])
                await _pause_for_clarification(task_id, questions)
                return

        # ── Critique-Acceptance handling ─────────────────────────────
        if agent.role == "critique_acceptance":
            verdict = result.get("verdict", "pass")
            if verdict == "fail":
                acceptance_iterations += 1
                if acceptance_iterations <= 1 and task_agent_idx is not None:
                    state.completed["_acceptance_feedback"] = result.get("feedback", "")
                    for clear_role in ("task", "guardrail", "code_review", "critique_acceptance"):
                        checkpoint.pop(clear_role, None)
                        state.completed.pop(clear_role, None)
                    i = task_agent_idx
                    continue
                else:
                    await _pause_for_human_review(task_id, "Critique-Acceptance exhausted revision rounds", state)
                    return

        # Save checkpoint after successful stage
        await save_checkpoint(task_id, agent.role, result)
        await _audit(task_id, f"stage_{agent.role}_complete", "info",
                     {"verdict": result.get("verdict"), "blocked": result.get("blocked")})

        # ── Context compaction check ──────────────────────────────────
        # If pipeline state is growing large, compact prior stage outputs
        # to a summary so downstream agents don't exceed context windows.
        await _maybe_compact_state(state, task_id)

        # Persist structured records (guardrail findings, code reviews, artifacts)
        await _persist_stage_records(task_id, agent, session_id, result, code_review_iterations)

        # Check if human review needed after this stage
        if _should_pause_for_review(state, pod, result, agent.role):
            escalation_msg = result.get("escalation_message", "Task requires human review.")
            await _pause_for_human_review(task_id, escalation_msg, state)
            return

        i += 1

    # ── Backfill training log success status ──────────────────────────────
    await _backfill_training_success(task_id, success=True)
    await _backfill_outcome_scores(task_id)

    # ── Pipeline complete ──────────────────────────────────────────────────
    task_result = state.completed.get("task", {})
    final_output = task_result.get("output", "Task completed.")

    # Append the detailed explanation so users see what was actually done
    explanation = task_result.get("explanation", "")
    if explanation:
        final_output = f"{final_output}\n\n---\n\n{explanation}"

    # Include files changed and commands run if present
    files_changed = task_result.get("files_changed", [])
    commands_run = task_result.get("commands_run", [])
    if files_changed:
        final_output += f"\n\n**Files changed:** {', '.join(files_changed)}"
    if commands_run:
        final_output += f"\n\n**Commands run:**\n" + "\n".join(f"- {c}" for c in commands_run)

    # Best-effort memory extraction — fire-and-forget, never blocks completion
    asyncio.create_task(
        _extract_task_memory(task_id, task.user_input, final_output, state),
        name=f"memory:{task_id}",
    )

    await _complete_task(task_id, final_output, state)


# ── Parallel group runner ──────────────────────────────────────────────────────

async def _run_parallel_group(
    group_agents: list[AgentRow],
    task_id: str,
    state: PipelineState,
    pod: PodRow,
    checkpoint: dict,
    code_review_iterations: int,
    model_override: str | None,
    complexity: str | None = None,
) -> bool:
    """
    Run a group of agents concurrently via asyncio.gather.
    All agents in the group share the same PipelineState snapshot — they
    cannot see each other's outputs (by design: parallel agents are independent).

    Returns True if the pipeline should abort (any agent with on_failure=abort failed).
    """
    # Filter to eligible agents (enabled, run_condition met, not checkpointed)
    eligible = []
    for agent in group_agents:
        if not agent.enabled:
            continue
        if not should_agent_run(agent.run_condition, state):
            logger.debug(f"Parallel group: skipping {agent.role} (run_condition not met)")
            continue
        if agent.role in checkpoint and not _needs_rerun(agent.role, state):
            logger.debug(f"Parallel group: skipping {agent.role} (already checkpointed)")
            continue
        eligible.append(agent)

    if not eligible:
        return False

    async def _run_one(agent: AgentRow) -> tuple[AgentRow, dict | None, str | None]:
        result, session_id = await _run_agent(
            agent, task_id, state, pod, code_review_iterations,
            model_override=model_override, complexity=complexity,
        )
        return agent, result, session_id

    # Launch all agents concurrently
    results = await asyncio.gather(
        *[_run_one(a) for a in eligible],
        return_exceptions=True,
    )

    # Process results — merge into state
    abort = False
    for outcome in results:
        if isinstance(outcome, Exception):
            logger.error(f"Task {task_id}: Parallel agent raised exception: {outcome}")
            continue

        agent, result, session_id = outcome

        if result is None:
            # on_failure=abort
            logger.error(f"Task {task_id}: Parallel agent '{agent.role}' failed (abort)")
            abort = True
            continue

        # Merge into state
        state.completed[agent.role] = result
        await save_checkpoint(task_id, agent.role, result)
        await _audit(task_id, f"stage_{agent.role}_complete", "info",
                     {"verdict": result.get("verdict"), "blocked": result.get("blocked")})
        await _persist_stage_records(task_id, agent, session_id, result, code_review_iterations)

    return abort


# ── Agent runner ───────────────────────────────────────────────────────────────

async def _run_agent(
    agent: AgentRow,
    task_id: str,
    state: PipelineState,
    pod: PodRow,
    code_review_iteration: int = 0,
    model_override: str | None = None,
    complexity: str | None = None,
) -> tuple[dict | None, str | None]:
    """
    Instantiate and run a single agent. Returns (output_dict, session_id).
    Returns (None, session_id) if the agent failed and on_failure=abort.
    On on_failure=skip, returns ({}, session_id) so the pipeline continues.
    """
    from .agents.context     import ContextAgent
    from .agents.task        import TaskAgent
    from .agents.critique    import CritiqueDirectionAgent, CritiqueAcceptanceAgent
    from .agents.guardrail   import GuardrailAgent
    from .agents.code_review import CodeReviewAgent
    from .agents.decision    import DecisionAgent
    from ..tools.sandbox     import SandboxTier, set_sandbox, reset_sandbox

    # Resolve model: per-task override → agent → complexity → stage default → pod → auto
    # A "tier:<name>" value (e.g. "tier:cheap") delegates to the gateway's tier
    # resolver instead of specifying a concrete model — see Phase 4b step 3.
    from ..model_resolver import resolve_default_model
    from .stage_model_resolver import resolve_stage_model
    from .complexity_model_map import resolve_complexity_model

    _tier_override: str | None = None  # set when a "tier:*" value is found

    # Check for "tier:<name>" prefix in the highest-priority source.
    # When found, model is left as None so the gateway's tier resolver
    # picks the best available model at that tier.
    for _src in [model_override, agent.model]:
        if _src and _src.startswith("tier:"):
            _tier_override = _src[5:]  # e.g. "cheap", "mid", "best"
            break
        if _src:
            break  # concrete model found — stop checking

    if _tier_override:
        # Delegate entirely to the gateway tier resolver — no concrete model
        model = None
    else:
        model = (model_override
                 or agent.model
                 or await resolve_complexity_model(complexity, agent.role)
                 or await resolve_stage_model(agent.role)
                 or pod.default_model
                 or await resolve_default_model())

    AGENT_CLASSES = {
        "context":             ContextAgent,
        "task":                TaskAgent,
        "critique_direction":  CritiqueDirectionAgent,
        "guardrail":           GuardrailAgent,
        "code_review":         CodeReviewAgent,
        "critique_acceptance": CritiqueAcceptanceAgent,
        "decision":            DecisionAgent,
    }

    agent_cls = AGENT_CLASSES.get(agent.role)
    if not agent_cls:
        logger.warning(f"Unknown agent role '{agent.role}' — skipping")
        return {}

    # Map pipeline stage → routing tier + task_type for adaptive model routing
    # If a tier: prefix was found in model resolution, it overrides the default.
    _STAGE_TIER_MAP: dict[str, tuple[str, str]] = {
        "context":             ("cheap", "context_retrieval"),
        "task":                ("best", "task_execution"),
        "critique_direction":  ("mid", "critique"),
        "guardrail":           ("mid", "guardrail"),
        "code_review":         ("mid", "code_review"),
        "critique_acceptance": ("mid", "critique"),
        "decision":            ("cheap", "decision"),
    }
    _tier, _task_type = _STAGE_TIER_MAP.get(agent.role, ("mid", "task_execution"))
    if _tier_override:
        _tier = _tier_override

    # ── Stage merging: expand Task Agent for simple tasks (Phase 4b Step 9) ──
    # When the Context Agent was skipped (merged), give the Task Agent access
    # to read-only context tools so it can gather context itself.
    _allowed_tools = agent.allowed_tools
    _system_prompt = agent.system_prompt
    _context_merged = (
        agent.role == "task"
        and state.completed.get("context", {}).get("_merged")
    )
    if _context_merged:
        CONTEXT_READ_TOOLS = {"list_dir", "read_file", "search_codebase", "git_status", "git_log"}
        if _allowed_tools is not None:
            # Agent has an explicit tool allowlist — expand it with context tools
            _allowed_tools = list(set(_allowed_tools) | CONTEXT_READ_TOOLS)
        # else: allowed_tools=None means all tools — context tools already included

        _merge_note = (
            "NOTE: No separate Context Agent ran for this task. Before making "
            "changes, briefly explore the relevant parts of the codebase using "
            "the read-only tools (list_dir, read_file, search_codebase) to "
            "understand the current implementation and conventions.\n\n"
        )
        # Prepend the merge note to whichever system prompt will be used.
        # If _system_prompt is None, the class DEFAULT_SYSTEM would be used,
        # so we resolve it here to ensure the merge note is included.
        base_prompt = _system_prompt or agent_cls.DEFAULT_SYSTEM
        _system_prompt = _merge_note + base_prompt

    instance = agent_cls(
        model=model,
        system_prompt=_system_prompt,
        allowed_tools=_allowed_tools,
        temperature=agent.temperature,
        max_tokens=agent.max_tokens,
        fallback_models=agent.fallback_models,
        tier=_tier,
        task_type=_task_type,
    )

    # Create agent_session row — store the actually-resolved model, not agent.model
    session_id = await _create_session(task_id, agent, resolved_model=model)
    await _set_task_status(task_id, f"{agent.role}_running", current_stage=agent.role)

    # Set sandbox tier from pod config for this agent execution
    tier = SandboxTier(pod.sandbox) if pod.sandbox in SandboxTier.__members__ else SandboxTier.workspace
    sandbox_token = set_sandbox(tier)

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
        await _complete_session(session_id, result, elapsed_ms, usage=instance._usage)

        # Phase 4: Write training log entries (best-effort)
        await _write_training_logs(
            task_id, session_id, agent.role, instance._training_log,
            complexity=complexity,
            stage_verdict=result.get("verdict") if agent.role == "code_review" else None,
        )

        # Score stage outcome for adaptive routing
        try:
            _oscore, _oconf = _score_stage_outcome(agent.role, result, state.flags)
            _meta = {
                "task_type": _task_type,
                "stage": agent.role,
                "task_id": task_id,
            }
            from app.usage import log_usage
            log_usage(
                api_key_id=None,
                agent_id=None,
                session_id=session_id,
                model=model,
                input_tokens=instance._usage.get("input_tokens", 0),
                output_tokens=instance._usage.get("output_tokens", 0),
                cost_usd=instance._usage.get("cost_usd"),
                duration_ms=elapsed_ms,
                metadata=_meta,
                outcome_score=_oscore,
                outcome_confidence=_oconf,
            )
        except Exception as exc:
            logger.debug("Stage outcome scoring failed: %s", exc)

        return result, session_id

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.error(f"Agent '{agent.role}' error on task {task_id}: {exc}")
        await _fail_session(session_id, str(exc), elapsed_ms)

        if agent.on_failure == "skip":
            logger.info(f"Agent '{agent.role}' failed with on_failure=skip — continuing")
            return {}, session_id
        if agent.on_failure == "escalate":
            await _pause_for_human_review(task_id, f"Agent '{agent.role}' failed: {exc}", state)
            return None, session_id
        # on_failure == "abort" (default)
        return None, session_id
    finally:
        reset_sandbox(sandbox_token)


# ── Stage record persistence ───────────────────────────────────────────────────

async def _persist_stage_records(
    task_id: str,
    agent: AgentRow,
    session_id: str | None,
    result: dict,
    iteration: int,
) -> None:
    """
    Best-effort persistence of guardrail findings, code reviews, and artifacts
    into their respective tables. Never blocks the pipeline on failure.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            # ── Guardrail findings ────────────────────────────────────
            if agent.role == "guardrail":
                for finding in result.get("findings", []):
                    await conn.execute(
                        """
                        INSERT INTO guardrail_findings
                            (task_id, agent_session_id, finding_type, severity, description, evidence)
                        VALUES ($1, $2::uuid, $3, $4, $5, $6)
                        """,
                        task_id,
                        session_id,
                        finding.get("type", "other"),
                        finding.get("severity", "medium"),
                        finding.get("description", ""),
                        finding.get("evidence"),
                    )
                # Emit activity for high/critical guardrail findings
                high_findings = [f for f in result.get("findings", []) if f.get("severity") in ("high", "critical")]
                if high_findings:
                    from ..activity import emit_activity
                    await emit_activity(
                        pool, "guardrail_finding", "pipeline",
                        f"Guardrail flagged {len(high_findings)} high-severity finding(s) on task {task_id[:8]}...",
                        severity="warning",
                        metadata={"task_id": task_id, "count": len(high_findings)},
                    )

            # ── Code review verdicts ──────────────────────────────────
            if agent.role == "code_review":
                import json as _json
                await conn.execute(
                    """
                    INSERT INTO code_reviews
                        (task_id, agent_session_id, iteration, verdict, issues, summary)
                    VALUES ($1, $2::uuid, $3, $4, $5::jsonb, $6)
                    """,
                    task_id,
                    session_id,
                    iteration + 1,
                    result.get("verdict", "pass"),
                    _json.dumps(result.get("issues", [])),
                    result.get("summary"),
                )

            # ── Artifacts ─────────────────────────────────────────────
            if agent.artifact_type:
                content = result.get("output") or result.get("adr") or result.get("content", "")
                if content:
                    content_str = content if isinstance(content, str) else str(content)
                    content_hash = hashlib.sha256(content_str.encode()).hexdigest()
                    import json as _json
                    await conn.execute(
                        """
                        INSERT INTO artifacts
                            (task_id, agent_session_id, artifact_type, name, content,
                             content_hash, file_path, metadata)
                        VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8::jsonb)
                        """,
                        task_id,
                        session_id,
                        agent.artifact_type,
                        f"{agent.role}_{task_id[:8]}",
                        content_str,
                        content_hash,
                        result.get("file_path"),
                        _json.dumps(result.get("metadata", {})),
                    )
    except Exception as exc:
        logger.warning("Failed to persist stage records for %s/%s: %s", task_id, agent.role, exc)


def _score_stage_outcome(role: str, result: dict, flags: set[str]) -> tuple[float, float]:
    """Compute outcome score + confidence for a pipeline stage.

    Returns (score, confidence) where both are 0.0-1.0.
    """
    if role == "guardrail":
        if result.get("blocked"):
            return 0.2, 0.95
        return 0.9, 0.95

    if role == "code_review":
        verdict = result.get("verdict", "pass")
        if verdict == "pass":
            return 0.85, 0.9
        if verdict == "needs_refactor":
            return 0.5, 0.85
        return 0.2, 0.9  # reject

    if role == "task":
        if result.get("error") or not result.get("output"):
            return 0.3, 0.9
        return 0.8, 0.8

    if role == "context":
        return 0.7, 0.6

    if role == "decision":
        return 0.7, 0.6

    # Unknown role — neutral
    return 0.5, 0.5


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
    """Load a pod by ID, or the default pod if pod_id is None."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if pod_id:
            row = await conn.fetchrow(
                "SELECT id, name, default_model, max_cost_usd, max_execution_seconds, "
                "require_human_review, escalation_threshold, sandbox "
                "FROM pods WHERE id = $1 AND enabled = true",
                pod_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT id, name, default_model, max_cost_usd, max_execution_seconds, "
                "require_human_review, escalation_threshold, sandbox "
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
    # Emit activity event for dashboard feed
    try:
        from ..activity import emit_activity
        await emit_activity(pool, "task_completed", "pipeline", f"Task {task_id[:8]}... completed", metadata={"task_id": task_id, "flags": list(state.flags)})
    except Exception:
        pass


async def _pause_for_human_review(
    task_id: str, escalation_message: str, state: PipelineState | None = None
) -> None:
    pool = get_pool()

    # Build a preview of what the task agent produced so reviewers see actual results
    preview_output: str | None = None
    if state:
        task_result = state.completed.get("task", {})
        parts = []
        summary = task_result.get("output", "")
        if summary:
            parts.append(summary)
        explanation = task_result.get("explanation", "")
        if explanation:
            parts.append(explanation)
        files_changed = task_result.get("files_changed", [])
        if files_changed:
            parts.append(f"**Files changed:** {', '.join(files_changed)}")
        commands_run = task_result.get("commands_run", [])
        if commands_run:
            parts.append("**Commands run:**\n" + "\n".join(f"- {c}" for c in commands_run))
        if parts:
            preview_output = "\n\n".join(parts)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'pending_human_review',
                output = COALESCE($3, output),
                metadata = metadata || jsonb_build_object('escalation_message', $2::text),
                current_stage = NULL
            WHERE id = $1
            """,
            task_id, escalation_message, preview_output,
        )
    await _audit(task_id, "task_escalated", "warning", {"message": escalation_message})
    logger.warning(f"Task {task_id} paused for human review: {escalation_message}")


async def _pause_for_clarification(task_id: str, questions: list[str]) -> None:
    """Pause pipeline for user clarification."""
    import json as _json
    from datetime import datetime, timezone
    from uuid import UUID as _UUID

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'clarification_needed',
                metadata = COALESCE(metadata, '{}'::jsonb)
                    || jsonb_build_object(
                        'clarification_questions', $2::jsonb,
                        'clarification_requested_at', $3::text
                    )
            WHERE id = $1
            """,
            _UUID(task_id) if not isinstance(task_id, _UUID) else task_id,
            _json.dumps(questions),
            datetime.now(timezone.utc).isoformat(),
        )
    logger.info(f"Task {task_id}: paused for clarification ({len(questions)} questions)")


async def _create_session(task_id: str, agent: AgentRow, resolved_model: str | None = None) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_sessions
                (task_id, pod_agent_id, role, position, status, model, started_at)
            VALUES ($1, $2::uuid, $3, $4, 'running', $5, now())
            RETURNING id
            """,
            task_id, agent.id, agent.role, agent.position, resolved_model or agent.model,
        )
    return str(row["id"])


async def _complete_session(
    session_id: str,
    output: dict,
    elapsed_ms: int,
    usage: dict | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        if usage and (usage.get("input_tokens") or usage.get("output_tokens")):
            await conn.execute(
                """
                UPDATE agent_sessions
                SET status = 'complete', output = $2::jsonb,
                    completed_at = now(), duration_ms = $3,
                    input_tokens = $4, output_tokens = $5, cost_usd = $6
                WHERE id = $1
                """,
                session_id, output, elapsed_ms,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cost_usd", 0.0),
            )
        else:
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


# ── Adaptive stage skipping (Phase 4b) ─────────────────────────────────────────

# Keywords indicating the task involves code — used to decide whether
# code_review can be skipped for simple tasks.
_CODE_KEYWORDS = frozenset({
    "code", "function", "class", "file", "git", "commit", "test", "bug",
    "fix", "implement", "refactor", "write", "create", "build", "deploy",
})


def _is_code_task(user_input: str) -> bool:
    """Return True if the user input contains any code-related keyword."""
    words = set(user_input.lower().split())
    return bool(words & _CODE_KEYWORDS)


def _apply_adaptive_skips(
    complexity: str,
    user_input: str,
    state: PipelineState,
    checkpoint: dict,
    task_id: str,
) -> list[str]:
    """
    Inject synthetic checkpoint entries for stages that can be skipped
    based on task complexity.

    Rules:
      - simple   → skip context  (stage merged into Task Agent, which gets
                    read-only tools and a self-gather prompt — Phase 4b Step 9)
      - simple + non-code task → skip code_review  (no code to review)

    Decision Agent is already conditional (only runs when guardrail AND
    code_review both fail) so it doesn't need special handling here.

    Returns list of stage roles that were newly skipped.
    """
    skipped: list[str] = []

    # simple tasks: merge Context into Task Agent (Phase 4b Step 9)
    # Instead of running a separate Context Agent, the Task Agent gets the
    # Context Agent's read-only tools and gathers context itself. This saves
    # an entire LLM round-trip for straightforward requests.
    if complexity == "simple" and "context" not in checkpoint:
        state.completed["context"] = {
            "skipped": True,
            "reason": "stage_merged_simple",
            "_merged": True,
            "curated_context": "",
            "relevant_files": [],
            "key_patterns": [],
            "recommendations": "",
        }
        checkpoint["context"] = state.completed["context"]
        skipped.append("context")
        logger.info(
            f"Task {task_id}: Stage merging — skipping Context Agent "
            f"(complexity={complexity}), Task Agent will self-gather context"
        )

    # simple + non-code tasks: skip Code Review — no code to review
    if complexity == "simple" and "code_review" not in checkpoint:
        if not _is_code_task(user_input):
            state.completed["code_review"] = {
                "skipped": True,
                "reason": "simple_non_code_task",
                "verdict": "pass",
            }
            checkpoint["code_review"] = state.completed["code_review"]
            skipped.append("code_review")
            logger.info(f"Task {task_id}: Skipping code_review (complexity={complexity}, non-code task)")

    return skipped


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


async def _extract_task_memory(
    task_id: str,
    user_input: str,
    final_output: str,
    state: PipelineState,
) -> None:
    """
    Post-pipeline: emit a structured episode to the engram ingestion queue
    so Nova can learn from prior task runs.

    Constructs a rich text summary of the pipeline run (task input, output,
    flags, guardrail blocks, code review findings) and pushes it to the
    engram queue for decomposition into the memory graph.

    Failure is logged as a warning; the pipeline result is never affected.
    """
    import json as _json
    from datetime import datetime, timezone

    import redis.asyncio as aioredis

    from ..config import settings

    # Build rich text for engram decomposition
    flags = sorted(state.flags)
    lines = [
        f"Pipeline task completed.",
        f"Task: {user_input[:300]}",
        f"Output: {final_output[:400]}",
    ]
    if flags:
        lines.append(f"Flags: {', '.join(flags)}")

    guardrail = state.completed.get("guardrail", {})
    if guardrail.get("blocked"):
        findings = guardrail.get("findings", [])
        if findings:
            top = findings[0]
            lines.append(
                f"Guardrail blocked: {top.get('type', 'unknown')} — {top.get('description', '')}"
            )

    review = state.completed.get("code_review", {})
    issues = review.get("issues", [])
    if issues:
        issue_lines = [
            f"[{iss.get('severity', 'info').upper()}] {iss.get('description', '')}"
            + (f" in {iss['file']}:{iss.get('line', '')}" if iss.get("file") else "")
            for iss in issues[:5]
        ]
        lines.append("Code review findings:\n" + "\n".join(issue_lines))

    raw_text = "\n".join(lines)

    try:
        base_url = settings.redis_url.rsplit("/", 1)[0]
        redis = aioredis.from_url(f"{base_url}/0", decode_responses=True)
        payload = _json.dumps({
            "raw_text": raw_text,
            "source_type": "pipeline",
            "source_id": task_id,
            "session_id": task_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"task_id": task_id, "flags": flags},
        })
        await redis.lpush("engram:ingestion:queue", payload)
        await redis.aclose()
        logger.debug("Emitted pipeline memory to engram queue for task %s", task_id)
    except Exception as exc:
        logger.warning("Engram queue push failed for task %s: %s", task_id, exc)


async def _maybe_compact_state(state: PipelineState, task_id: str) -> None:
    """
    Check if pipeline state has grown beyond context_compaction_threshold.
    If so, summarize prior stage outputs into a compact string and replace
    the verbose originals.

    Token estimation: 1 token ~ 4 characters (same heuristic as memory service).
    Default context budget: 128k tokens. Threshold: 80% = ~102k tokens.
    """
    import json as _json

    # Estimate total tokens in pipeline state
    try:
        state_json = _json.dumps(state.completed, default=str)
    except (TypeError, ValueError):
        return
    estimated_tokens = len(state_json) // 4

    # Use a generous context budget — most models are 128k+
    context_budget = 128_000
    threshold = int(context_budget * settings.context_compaction_threshold)

    if estimated_tokens < threshold:
        return

    logger.info(
        "Task %s: state ~%d tokens exceeds compaction threshold (%d) — compacting",
        task_id, estimated_tokens, threshold,
    )

    # Roles that are safe to compact (context output is verbose, task output can be large)
    # Never compact _refactor_feedback or the most recent stage
    compactable = {"context", "task", "guardrail", "code_review"}
    roles_to_compact = [
        role for role in state.completed
        if role in compactable and not role.startswith("_")
    ]

    if not roles_to_compact:
        return

    # Build a summarization prompt
    sections = []
    for role in roles_to_compact:
        output = state.completed[role]
        output_str = _json.dumps(output, default=str) if isinstance(output, dict) else str(output)
        # Truncate very large outputs to avoid blowing the summarization call itself
        if len(output_str) > 8000:
            output_str = output_str[:8000] + "... [truncated]"
        sections.append(f"## {role} agent output:\n{output_str}")

    summary_prompt = (
        "You are a pipeline state compactor. Summarize the following agent outputs "
        "into a concise summary preserving all key decisions, findings, file paths, "
        "verdicts, and actionable information. Return plain text, not JSON.\n\n"
        + "\n\n".join(sections)
    )

    try:
        from ..clients import get_llm_client
        client = get_llm_client()
        resp = await client.post(
            "/complete",
            json={
                "model": settings.default_model,
                "messages": [
                    {"role": "system", "content": "You compress information concisely without losing key details."},
                    {"role": "user", "content": summary_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 2048,
            },
            timeout=30.0,
        )
        if resp.status_code == 200:
            summary = resp.json()["content"]
            # Replace verbose outputs with compact summary
            for role in roles_to_compact:
                del state.completed[role]
            state.completed["_compacted_summary"] = summary
            logger.info("Task %s: compacted %d stages into summary (%d chars)",
                        task_id, len(roles_to_compact), len(summary))
        else:
            logger.warning("Task %s: compaction LLM call failed HTTP %s", task_id, resp.status_code)
    except Exception as exc:
        logger.warning("Task %s: compaction failed (non-fatal): %s", task_id, exc)


async def _write_training_logs(
    task_id: str,
    session_id: str,
    role: str,
    training_log: list[dict],
    complexity: str | None = None,
    stage_verdict: str | None = None,
) -> None:
    """Best-effort: write training data entries to pipeline_training_logs."""
    if not training_log:
        return
    try:
        from ..db import get_pool as _gp
        pool = _gp()
        async with pool.acquire() as conn:
            # Check if training logging is enabled
            row = await conn.fetchrow(
                "SELECT value FROM platform_config WHERE key = 'pipeline.training_log_enabled'"
            )
            if not row:
                return
            import json as _json
            val = _json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
            if val != "true" and val is not True:
                return

            for entry in training_log:
                await conn.execute(
                    """
                    INSERT INTO pipeline_training_logs
                        (task_id, agent_session_id, role, prompt, response, model,
                         input_tokens, output_tokens, cost_usd, complexity,
                         stage_verdict, was_fallback, temperature)
                    VALUES ($1, $2::uuid, $3, $4::jsonb, $5, $6,
                            $7, $8, $9, $10, $11, $12, $13)
                    """,
                    task_id, session_id, role,
                    _json.dumps(entry.get("messages", [])),
                    entry.get("response", ""),
                    entry.get("model", ""),
                    entry.get("input_tokens", 0),
                    entry.get("output_tokens", 0),
                    entry.get("cost_usd"),
                    complexity,
                    stage_verdict,
                    entry.get("was_fallback", False),
                    entry.get("temperature"),
                )
    except Exception as exc:
        logger.warning("Failed to write training logs for %s/%s: %s", task_id, role, exc)


async def _backfill_training_success(task_id: str, success: bool) -> None:
    """Backfill pipeline_success on all training log entries for a task."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE pipeline_training_logs SET pipeline_success = $2 WHERE task_id = $1",
                task_id, success,
            )
    except Exception as exc:
        logger.debug("Training log backfill failed for %s: %s", task_id, exc)


async def _backfill_outcome_scores(task_id: str) -> None:
    """Bump outcome scores for all usage events in a successful pipeline task.

    Events with an existing score get +0.1 (capped at 1.0).
    Events with NULL score (inline scoring failed) get a baseline 0.7.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE usage_events
                SET outcome_score = CASE
                        WHEN outcome_score IS NOT NULL
                            THEN LEAST(1.0, outcome_score + 0.1)
                        ELSE 0.7
                    END
                WHERE metadata->>'task_id' = $1
                """,
                task_id,
            )
    except Exception as exc:
        logger.debug("Outcome score backfill failed for %s: %s", task_id, exc)


async def _audit(
    task_id: str,
    event_type: str,
    severity: str,
    data: dict | None = None,
) -> None:
    """Best-effort write to the immutable audit log."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await write_audit_log(
            conn,
            event_type=event_type,
            severity=severity,
            task_id=task_id,
            message=f"Pipeline: {event_type}",
            data=data,
        )
