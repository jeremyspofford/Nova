"""One thinking cycle — PERCEIVE → EVALUATE → PLAN → ACT → REFLECT.

Each cycle:
1. Gathers state (health, goals, budget, user messages)
2. Scores drives and picks the highest-urgency action
3. Uses LLM to plan how to execute the action
4. Dispatches work (pipeline tasks, health checks, etc.)
5. Journals the outcome
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .budget import get_budget_status, publish_budget_tier
from .memory import perceive_with_memory, reflect_to_engrams, maybe_consolidate, mark_engrams_used
from .scheduler import check_schedules
from .clients import get_llm, get_orchestrator
from .config import settings
from .db import get_pool
from .drives import DriveContext, DriveResult, DriveWinner, evaluate
from .drives import serve, maintain, improve, learn, reflect
from .journal import read_user_replies_since, write_entry
from .task_tracker import TaskOutcome, await_task

log = logging.getLogger(__name__)

ALL_DRIVES = [serve, maintain, improve, learn, reflect]


@dataclass
class CycleState:
    """Accumulated state for one cycle."""
    cycle_number: int = 0
    budget_tier: str = "best"
    budget_pct: float = 0.0
    drive_results: list[DriveResult] = field(default_factory=list)
    winner: DriveWinner | None = None
    user_messages: list[dict] = field(default_factory=list)
    stimuli: list[dict] = field(default_factory=list)
    memory_context: str = ""
    engram_ids: list[str] = field(default_factory=list)
    retrieval_log_id: str | None = None
    action_taken: str = "none"
    outcome: str = ""
    error: str | None = None
    resolved_model: str | None = None
    goal_id: str | None = None
    dispatched_task_id: str | None = None
    task_outcome: TaskOutcome | None = None


async def _report_outcome(
    state: CycleState, model: str, score: float, confidence: float,
) -> None:
    """Report cycle outcome to orchestrator for effectiveness tracking."""
    try:
        orch = get_orchestrator()
        await orch.post(
            "/api/v1/usage/events",
            json={
                "model": model,
                "outcome_score": score,
                "outcome_confidence": confidence,
                "agent_name": "Cortex",
                "metadata": {
                    "task_type": "planning",
                    "source": "cortex",
                    "cycle": state.cycle_number,
                    "drive": state.action_taken,
                },
            },
        )
    except Exception as e:
        log.warning("Failed to report cycle outcome: %s", e)


async def run_cycle(stimuli: list[dict] | None = None) -> CycleState:
    """Execute one complete thinking cycle. Returns the cycle state for logging."""
    state = CycleState()
    state.stimuli = stimuli or []

    try:
        # ── PERCEIVE ──────────────────────────────────────────────────────
        budget = await get_budget_status()
        state.budget_tier = budget["tier"]
        state.budget_pct = budget["percent_used"]

        # Publish budget tier to Redis for gateway consumption
        await publish_budget_tier()

        # Read cycle count
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT cycle_count, last_cycle_at FROM cortex_state WHERE id = true")
        state.cycle_number = (row["cycle_count"] + 1) if row else 1

        # Check for user replies since last cycle
        last_cycle_at = row["last_cycle_at"] if row and row["last_cycle_at"] else datetime(2020, 1, 1, tzinfo=timezone.utc)
        state.user_messages = await read_user_replies_since(last_cycle_at)

        # Check for due scheduled goals (self-inject stimuli)
        try:
            schedule_stimuli = await check_schedules()
            if schedule_stimuli:
                state.stimuli.extend(schedule_stimuli)
                log.info("Injected %d schedule stimuli", len(schedule_stimuli))
        except Exception as e:
            log.warning("Schedule check failed: %s", e)

        # Query engram memory for context
        goal_context = ""
        if state.stimuli:
            for s in state.stimuli:
                if s.get("type") == "goal.schedule_due":
                    goal_context = s.get("payload", {}).get("title", "")
                    break

        mem_result = await perceive_with_memory(state.stimuli, goal_context)
        state.memory_context = mem_result["memory_context"]
        state.engram_ids = mem_result["engram_ids"]
        state.retrieval_log_id = mem_result["retrieval_log_id"]

        # ── EVALUATE ──────────────────────────────────────────────────────
        drive_ctx = DriveContext(
            stimuli=state.stimuli,
            memory_context=state.memory_context,
            budget_tier=state.budget_tier,
            cycle_count=state.cycle_number,
        )

        for drive_module in ALL_DRIVES:
            try:
                result = await drive_module.assess(drive_ctx)
                state.drive_results.append(result)
            except Exception as e:
                log.error("Drive %s.assess() failed: %s", drive_module.__name__, e)

        state.winner = evaluate(state.drive_results, state.budget_tier)

        if state.winner is None:
            state.action_taken = "idle"
            state.outcome = "No drives have urgency — nothing to do"

            # Use idle time for memory consolidation
            if state.budget_tier != "none":
                try:
                    consolidated = await maybe_consolidate()
                    if consolidated:
                        state.action_taken = "idle_consolidation"
                        state.outcome = "Triggered memory consolidation during idle"
                except Exception as e:
                    log.debug("Idle consolidation failed: %s", e)

            await write_entry(
                f"Cycle {state.cycle_number}: idle. Budget {state.budget_pct:.0f}% used ({state.budget_tier}). "
                f"All drives quiet.",
                entry_type="narration",
                metadata={"cycle": state.cycle_number, "action": "idle"},
            )
            await _update_state(state)
            return state

        drive = state.winner.result

        # ── PLAN ──────────────────────────────────────────────────────────
        plan = await _plan_action(drive, state)

        # ── ACT ───────────────────────────────────────────────────────────
        state.action_taken = drive.name
        state.outcome = await _execute_action(drive, plan, state)

        # ── TRACK ────────────────────────────────────────────────────────
        # If a pipeline task was dispatched, poll for completion and update goal
        if state.dispatched_task_id:
            state.task_outcome = await _track_dispatched_task(state)

        # ── REFLECT ──────────────────────────────────────────────────────
        await _reflect(state)

        # Write cycle outcome to engram memory
        if state.action_taken not in ("idle", "none", "idle_consolidation"):
            await reflect_to_engrams(
                cycle_number=state.cycle_number,
                drive=state.action_taken,
                urgency=state.winner.result.urgency if state.winner else 0,
                action_summary=state.winner.result.proposed_action or state.action_taken if state.winner else state.action_taken,
                outcome=state.outcome[:500],
                goal_id=(state.winner.result.context.get("scheduled_goal_ids") or [None])[0] if state.winner else None,
                budget_tier=state.budget_tier,
            )

        # Mark engrams used (all retrieved engrams — coarse heuristic)
        if state.retrieval_log_id and state.engram_ids:
            await mark_engrams_used(state.retrieval_log_id, state.engram_ids)

        await _update_state(state)

        # ── SCORE ───────────────────────────────────────────────────
        if state.resolved_model:
            if state.error:
                await _report_outcome(state, state.resolved_model, 0.2, 0.9)
            elif state.task_outcome:
                # Use actual task result instead of hardcoded score
                await _report_outcome(
                    state, state.resolved_model,
                    state.task_outcome.score, state.task_outcome.confidence,
                )
            else:
                # Non-serve drives or serve without a dispatched task
                await _report_outcome(state, state.resolved_model, 0.7, 0.5)

    except Exception as e:
        state.error = str(e)
        log.error("Cycle %d failed: %s", state.cycle_number, e, exc_info=True)
        try:
            await write_entry(
                f"Cycle {state.cycle_number} FAILED: {e}",
                entry_type="escalation",
                metadata={"cycle": state.cycle_number, "error": str(e)},
            )
        except Exception:
            pass  # Don't let journal failure mask the original error
        if state.resolved_model:
            await _report_outcome(state, state.resolved_model, 0.2, 0.9)

    return state


async def _plan_action(drive: DriveResult, state: CycleState) -> str:
    """Use LLM to decide what specific action to take for the winning drive."""
    if state.budget_tier == "none":
        return f"Budget exhausted — skip LLM planning. Drive: {drive.name}"

    # Build a compact prompt
    user_msg_summary = ""
    if state.user_messages:
        msgs = "; ".join(m["content"][:100] for m in state.user_messages[:3])
        user_msg_summary = f"\nUser messages since last cycle: {msgs}"

    stimulus_summary = ""
    if state.stimuli:
        stim_types = ", ".join(s.get("type", "?") for s in state.stimuli[:5])
        stimulus_summary = f"\nStimuli this cycle: {stim_types}"

    if state.memory_context:
        stimulus_summary += f"\n\nRelevant memories:\n{state.memory_context[:1000]}"

    prompt = f"""You are Nova's autonomous brain (Cortex). You are deciding what to do this cycle.

Winning drive: {drive.name} (urgency {drive.urgency}, score {state.winner.score:.2f})
Drive says: {drive.description}
Proposed action: {drive.proposed_action or 'none specified'}
Context: {json.dumps(drive.context, default=str)}

Budget: {state.budget_pct:.0f}% used today (tier: {state.budget_tier})
Cycle: #{state.cycle_number}{user_msg_summary}{stimulus_summary}

Based on this, decide what SPECIFIC action to take. Be concise (1-3 sentences).
If the drive is "serve" and there are stale goals, pick the highest-priority one and describe what to do next.
If the drive is "maintain" and services are degraded, describe the health issue.
If nothing meaningful can be done, say "skip".

Your response is the action plan (not code, just a description)."""

    try:
        llm = get_llm()
        model = settings.planning_model or ""  # empty string = gateway uses default
        resp = await llm.post("/complete", json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 300,
            "tier": "mid",
            "task_type": "planning",
            "metadata": {"agent_id": "cortex", "task_id": f"cycle-{state.cycle_number}"},
        })
        if resp.status_code == 200:
            data = resp.json()
            # Capture the actual model the gateway resolved to
            state.resolved_model = data.get("model") or state.resolved_model
            return data.get("content", "No plan generated")
        else:
            log.warning("LLM planning call failed: %d %s", resp.status_code, resp.text[:200])
            return f"LLM unavailable ({resp.status_code}) — using drive's proposed action: {drive.proposed_action}"
    except Exception as e:
        log.warning("LLM planning call error: %s", e)
        return f"LLM error — using drive's proposed action: {drive.proposed_action}"


async def _execute_action(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute the planned action. Returns outcome description."""
    if "skip" in plan.lower()[:20]:
        return "Skipped — no meaningful action to take"

    if drive.name == "serve":
        return await _execute_serve(drive, plan, state)
    elif drive.name == "maintain":
        return await _execute_maintain(drive, plan)
    elif drive.name == "improve":
        return await _execute_improve(drive, plan)
    elif drive.name == "reflect":
        return await _execute_reflect(drive, plan, state)
    elif drive.name == "learn":
        return await _execute_learn(drive, plan, state)
    else:
        return f"Drive '{drive.name}' has no executor"


async def _execute_serve(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute a serve action — work on the highest-priority stale goal."""
    stale_goals = drive.context.get("stale_goals", [])
    if not stale_goals:
        return "No stale goals to work on"

    goal = stale_goals[0]
    goal_id = goal["id"]
    state.goal_id = goal_id

    # Dispatch a pipeline task for this goal
    try:
        orch = get_orchestrator()
        resp = await orch.post(
            "/api/v1/pipeline/tasks",
            json={
                "user_input": f"[Cortex goal work] Goal: {goal['title']}. Plan: {plan}",
                "goal_id": goal_id,
                "metadata": {"source": "cortex", "cycle": state.cycle_number, "drive": "serve"},
            },
            headers={"Authorization": f"Bearer {settings.cortex_api_key}"},
        )
        if resp.status_code in (200, 201, 202):
            data = resp.json()
            task_id = data.get("task_id", "unknown")
            state.dispatched_task_id = task_id

            # Persist plan AFTER successful dispatch (iteration/progress updated after task completes)
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE goals
                       SET last_checked_at = NOW(),
                           current_plan = $1::jsonb,
                           updated_at = NOW()
                       WHERE id = $2::uuid""",
                    json.dumps({"plan": plan, "cycle": state.cycle_number, "task_id": task_id}),
                    goal_id,
                )

            return f"Dispatched task {task_id} for goal '{goal['title']}'"
        else:
            return f"Failed to dispatch task: HTTP {resp.status_code} — {resp.text[:200]}"
    except Exception as e:
        return f"Failed to dispatch task: {e}"


async def _execute_maintain(drive: DriveResult, plan: str) -> str:
    """Execute a maintain action — log health issues for now."""
    degraded = drive.context.get("degraded", [])
    if not degraded:
        return "All services healthy — nothing to do"

    # For now, just report. Future: trigger recovery actions.
    return f"Health issues detected: {', '.join(degraded)}. Logged for attention. Plan: {plan}"


async def _execute_improve(drive: DriveResult, plan: str) -> str:
    """Execute an improve action — log improvement opportunity."""
    contradictions = drive.context.get("contradictions", [])
    router_status = drive.context.get("router_status")

    parts = []
    if contradictions:
        parts.append(f"Noted {len(contradictions)} engram contradictions for review")
    if router_status:
        parts.append(f"Neural router status: {router_status.get('mode', 'unknown')}")
    parts.append(f"Plan: {plan[:200]}")

    return "; ".join(parts) if parts else "No specific improvement action taken"


async def _execute_reflect(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute a reflect action — summarize recent patterns."""
    from .drives.reflect import reset_reflect_counter
    reset_reflect_counter()

    # Write a reflection journal entry
    await write_entry(
        f"**Reflection** — {plan[:500]}",
        entry_type="reflection",
        metadata={"cycle": state.cycle_number, "drive": "reflect"},
    )
    return f"Reflection recorded. {plan[:200]}"


async def _execute_learn(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute a learn action — log learning opportunity."""
    gaps = drive.context.get("gaps", [])
    if gaps:
        gap_types = ", ".join(g.get("task_type", "unknown") for g in gaps)
        return f"Investigating capability gaps: {gap_types}. Plan: {plan[:200]}"
    return f"Learning action: {plan[:200]}"


async def _track_dispatched_task(state: CycleState) -> TaskOutcome | None:
    """Poll a dispatched task to completion and update goal progress accordingly."""
    task_id = state.dispatched_task_id
    if not task_id or task_id == "unknown":
        return None

    try:
        outcome = await await_task(task_id)
    except Exception as e:
        log.warning("Task tracking failed for %s: %s", task_id, e)
        return None

    # Update the outcome description with the actual result
    if outcome.timed_out:
        state.outcome += f" | Task {task_id} still running after {settings.task_poll_max_wait}s"
    elif outcome.status == "complete":
        summary = (outcome.output or "")[:200]
        state.outcome += f" | Task completed: {summary}"
    elif outcome.status == "failed":
        err = (outcome.error or "unknown error")[:200]
        state.outcome += f" | Task FAILED: {err}"
    elif outcome.status == "cancelled":
        state.outcome += f" | Task cancelled"

    # Update goal progress based on task result
    if state.goal_id:
        try:
            await _update_goal_progress(state.goal_id, outcome, state.cycle_number)
        except Exception as e:
            log.warning("Failed to update goal progress for %s: %s", state.goal_id, e)

    # Journal notable task outcomes
    if outcome.status == "failed":
        try:
            await write_entry(
                f"**Task failure** — task {task_id} for goal {state.goal_id}: "
                f"{(outcome.error or 'unknown')[:300]}",
                entry_type="escalation",
                metadata={
                    "cycle": state.cycle_number,
                    "task_id": task_id,
                    "goal_id": state.goal_id,
                    "task_status": outcome.status,
                },
            )
        except Exception as e:
            log.debug("Failed to journal task failure: %s", e)

    return outcome


async def _update_goal_progress(goal_id: str, outcome: TaskOutcome, cycle: int) -> None:
    """Update goal iteration count and progress estimate based on task outcome."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Read current goal state
        row = await conn.fetchrow(
            "SELECT iteration, max_iterations, progress, current_plan, cost_so_far_usd FROM goals WHERE id = $1::uuid",
            goal_id,
        )
        if not row:
            log.warning("Goal %s not found for progress update", goal_id)
            return

        iteration = row["iteration"]
        max_iterations = row["max_iterations"] or 50
        current_plan = row["current_plan"] or {}

        new_cost = float(row["cost_so_far_usd"] or 0) + outcome.total_cost_usd

        if outcome.status == "complete":
            # Successful task — increment iteration, estimate progress from iteration ratio
            new_iteration = iteration + 1
            # Progress: blend iteration ratio with a completion boost
            iter_ratio = min(new_iteration / max_iterations, 1.0)
            new_progress = min(round(iter_ratio * 100, 1), 100.0)

            plan_update = {
                **current_plan,
                "last_task_id": outcome.task_id,
                "last_task_status": outcome.status,
                "last_task_output": (outcome.output or "")[:500],
                "cycle": cycle,
            }
            if outcome.findings_count > 0:
                plan_update["last_findings_count"] = outcome.findings_count

            await conn.execute(
                """UPDATE goals
                   SET iteration = $1,
                       progress = $2,
                       current_plan = $3::jsonb,
                       cost_so_far_usd = $5,
                       updated_at = NOW()
                   WHERE id = $4::uuid""",
                new_iteration,
                new_progress,
                json.dumps(plan_update),
                goal_id,
                new_cost,
            )
            log.info(
                "Goal %s: iteration %d/%d, progress %.1f%% (task %s complete)",
                goal_id, new_iteration, max_iterations, new_progress, outcome.task_id,
            )

        elif outcome.status == "failed":
            # Failed task — store error context for next cycle's planning, don't advance iteration
            plan_update = {
                **current_plan,
                "last_task_id": outcome.task_id,
                "last_task_status": "failed",
                "last_task_error": (outcome.error or "unknown")[:500],
                "cycle": cycle,
            }
            await conn.execute(
                """UPDATE goals
                   SET current_plan = $1::jsonb,
                       cost_so_far_usd = $3,
                       updated_at = NOW()
                   WHERE id = $2::uuid""",
                json.dumps(plan_update),
                goal_id,
                new_cost,
            )
            log.info(
                "Goal %s: task %s failed — error stored for re-planning",
                goal_id, outcome.task_id,
            )

        elif outcome.status == "cancelled":
            # Cancelled — just note it, don't advance
            plan_update = {
                **current_plan,
                "last_task_id": outcome.task_id,
                "last_task_status": "cancelled",
                "cycle": cycle,
            }
            await conn.execute(
                """UPDATE goals
                   SET current_plan = $1::jsonb,
                       cost_so_far_usd = $3,
                       updated_at = NOW()
                   WHERE id = $2::uuid""",
                json.dumps(plan_update),
                goal_id,
                new_cost,
            )

        elif outcome.timed_out:
            # Still running — store task_id so next cycle can check again
            plan_update = {
                **current_plan,
                "last_task_id": outcome.task_id,
                "last_task_status": "running",
                "cycle": cycle,
            }
            await conn.execute(
                """UPDATE goals
                   SET current_plan = $1::jsonb,
                       cost_so_far_usd = $3,
                       updated_at = NOW()
                   WHERE id = $2::uuid""",
                json.dumps(plan_update),
                goal_id,
                new_cost,
            )
            log.info(
                "Goal %s: task %s still running — noted for next cycle",
                goal_id, outcome.task_id,
            )


async def _reflect(state: CycleState) -> None:
    """Write a journal entry summarizing this cycle."""
    drive_summary = ", ".join(
        f"{r.name}={r.urgency:.2f}" for r in state.drive_results
    )

    if state.winner:
        content = (
            f"**Cycle {state.cycle_number}** — drive: **{state.winner.result.name}** "
            f"(score {state.winner.score:.2f})\n\n"
            f"Drives: {drive_summary}\n"
            f"Budget: {state.budget_pct:.0f}% ({state.budget_tier})\n"
            f"Action: {state.action_taken}\n"
            f"Outcome: {state.outcome}"
        )
    else:
        content = (
            f"**Cycle {state.cycle_number}** — idle\n\n"
            f"Drives: {drive_summary}\n"
            f"Budget: {state.budget_pct:.0f}% ({state.budget_tier})"
        )

    if state.task_outcome:
        to = state.task_outcome
        content += (
            f"\nTask: {to.task_id} — {to.status} (score={to.score:.1f})"
        )
        if to.findings_count > 0:
            content += f" [{to.findings_count} guardrail findings]"
        if to.timed_out:
            content += " [timed out]"

    if state.user_messages:
        content += f"\n\nUser messages: {len(state.user_messages)}"

    entry_type = "narration"
    if state.error:
        content += f"\n\nERROR: {state.error}"
        entry_type = "escalation"

    metadata = {
        "cycle": state.cycle_number,
        "drive": state.action_taken,
        "budget_tier": state.budget_tier,
    }
    if state.goal_id:
        metadata["goal_id"] = state.goal_id
    if state.task_outcome:
        metadata["task_id"] = state.task_outcome.task_id
        metadata["task_status"] = state.task_outcome.status
        metadata["task_score"] = state.task_outcome.score
    await write_entry(content, entry_type=entry_type, metadata=metadata)


async def _update_state(state: CycleState) -> None:
    """Update cortex_state singleton after a cycle."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE cortex_state
            SET cycle_count = $1,
                last_cycle_at = NOW(),
                current_drive = $2,
                last_checkpoint = $3::jsonb,
                updated_at = NOW()
            WHERE id = true
            """,
            state.cycle_number,
            state.action_taken if state.action_taken != "none" else None,
            json.dumps({
                "budget_tier": state.budget_tier,
                "budget_pct": state.budget_pct,
                "outcome": state.outcome[:500] if state.outcome else None,
            }),
        )
