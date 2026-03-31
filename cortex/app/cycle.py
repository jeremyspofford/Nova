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
from . import task_monitor
from .task_tracker import TaskOutcome
from .reflections import (
    query_reflections, format_reflection_history, record_reflection,
    check_approach_blocked, count_consecutive_failures,
    compute_stuck_threshold, compute_approach_hash, TIER_ORDER,
)

log = logging.getLogger(__name__)

# Track consecutive skips per goal to prevent infinite skip loops
_consecutive_skips: dict[str, int] = {}
MAX_CONSECUTIVE_SKIPS = 3

# Round-robin counter for multi-goal rotation
_goal_round_robin: int = 0

ALL_DRIVES = [serve, maintain, improve, learn, reflect]


def _select_goal(stale_goals: list[dict], scheduled_goal_ids: list[str]) -> dict:
    """Pick the next goal to work on. Scheduled goals always win; otherwise round-robin."""
    global _goal_round_robin
    # Scheduled goals take priority (they have deadlines)
    for g in stale_goals:
        if str(g["id"]) in scheduled_goal_ids:
            return g
    # Round-robin through the priority-sorted list
    idx = _goal_round_robin % len(stale_goals)
    _goal_round_robin += 1
    return stale_goals[idx]


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
    selected_goal: dict | None = None  # Set by _plan_action for _execute_serve
    task_outcome: TaskOutcome | None = None
    plan_text: str | None = None


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
    completed_tasks: list[tuple[task_monitor.PendingTask, TaskOutcome]] = []

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

        # Periodic zombie goal cleanup
        if state.cycle_number % 100 == 0:
            try:
                await _sweep_zombie_goals()
            except Exception as e:
                log.warning("Zombie sweep failed: %s", e)

        # Collect results from background task monitor
        completed_tasks = task_monitor.collect_completed()
        for pending, outcome in completed_tasks:
            try:
                await _update_goal_progress(pending.goal_id, outcome, pending.cycle_dispatched)
                log.info(
                    "Processed background result: task %s goal %s status=%s",
                    pending.task_id, pending.goal_id, outcome.status,
                )
                # Record reflection for completed background tasks
                if outcome.status in ("complete", "failed"):
                    bg_state = CycleState(
                        cycle_number=pending.cycle_dispatched,
                        goal_id=pending.goal_id,
                        action_taken="serve",
                        task_outcome=outcome,
                        plan_text=pending.plan_text,
                        outcome=f"Background task {pending.task_id}: {outcome.status}",
                    )
                    try:
                        await _record_cycle_reflection(bg_state)
                    except Exception as e2:
                        log.debug("Failed to record background reflection: %s", e2)
            except Exception as e:
                log.warning("Failed to process background task %s: %s", pending.task_id, e)

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
        # Background monitor handles task polling — results collected in PERCEIVE.
        # Record cycle reflection for completed tasks from this cycle if available.
        if state.goal_id and state.action_taken == "serve":
            # Check if any just-collected results are for this cycle's goal
            for pending, outcome in completed_tasks:
                if pending.goal_id == state.goal_id:
                    state.task_outcome = outcome
                    state.plan_text = pending.plan_text
                    break
            if state.task_outcome:
                await _record_cycle_reflection(state)

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

    # Build rich goal context for serve drive
    forced = False
    goal_context_block = ""
    reflection_history = ""
    if drive.name == "serve":
        stale_goals = drive.context.get("stale_goals", [])
        if stale_goals:
            scheduled_ids = drive.context.get("scheduled_goal_ids", [])
            goal = _select_goal(stale_goals, scheduled_ids)
            state.selected_goal = goal
            goal_id = goal.get("id", "")
            plan_data = goal.get("current_plan") or {}
            db_skip_count = plan_data.get("consecutive_skips", 0) if isinstance(plan_data, dict) else 0
            skip_count = max(db_skip_count, _consecutive_skips.get(goal_id, 0))
            if skip_count >= MAX_CONSECUTIVE_SKIPS:
                forced = True

            parts = [f"Title: {goal.get('title', 'unknown')}"]
            desc = goal.get("description")
            if desc:
                parts.append(f"Description: {desc[:300]}")
            plan_data = goal.get("current_plan")
            if plan_data and isinstance(plan_data, dict):
                if plan_data.get("last_task_status") == "failed":
                    parts.append(f"Last attempt FAILED: {plan_data.get('last_task_error', 'unknown')[:200]}")
                elif plan_data.get("last_task_output"):
                    parts.append(f"Last result: {plan_data['last_task_output'][:200]}")
                if plan_data.get("plan"):
                    parts.append(f"Previous plan: {plan_data['plan'][:200]}")
            parts.append(f"Progress: iteration {goal.get('iteration', 0)}/{goal.get('max_iterations', 50)}")
            cost = goal.get("cost_so_far_usd")
            if cost:
                limit = goal.get("max_cost_usd")
                parts.append(f"Cost: ${cost:.2f}" + (f" / ${limit:.2f} limit" if limit else ""))
            goal_context_block = "\n".join(parts)

            # Query prior experience with this goal
            reflection_history = ""
            try:
                phase = goal.get("maturation_status")
                reflections = await query_reflections(goal_id, phase=phase, limit=5)
                desc = goal.get("description") or ""
                desc_hash = compute_approach_hash(desc) if desc else None
                reflection_history = format_reflection_history(reflections, current_goal_desc_hash=desc_hash)
            except Exception as e:
                log.debug("Failed to query reflections for goal %s: %s", goal_id, e)

    skip_instruction = ""
    if forced:
        skip_instruction = (
            "\n\nIMPORTANT: This goal has been skipped multiple times consecutively. "
            "You MUST produce an actionable plan this time. Do NOT say 'skip'. "
            "If the goal is unclear, create a task to gather more information or clarify requirements."
        )
    elif drive.name == "serve" and goal_context_block:
        skip_instruction = (
            '\n\nOnly say "skip" if you genuinely cannot identify ANY useful next step. '
            "If the goal has a description, you should be able to plan work."
        )

    prompt = f"""You are Nova's autonomous brain (Cortex). You are deciding what to do this cycle.

Winning drive: {drive.name} (urgency {drive.urgency}, score {state.winner.score:.2f})
Drive says: {drive.description}
Proposed action: {drive.proposed_action or 'none specified'}

{"Goal details:\n" + goal_context_block if goal_context_block else ""}
{reflection_history}
{"Do NOT repeat approaches that previously failed. Build on partial successes or try something new." if reflection_history else ""}
Context: {json.dumps(drive.context, default=str)[:1000]}

Budget: {state.budget_pct:.0f}% used today (tier: {state.budget_tier})
Cycle: #{state.cycle_number}{user_msg_summary}{stimulus_summary}{skip_instruction}

Based on this, decide what SPECIFIC action to take. Be concise (1-3 sentences).
If the drive is "serve", describe the next concrete task to dispatch for this goal.
If the drive is "maintain" and services are degraded, describe the health issue.

Your response is the action plan (not code, just a description)."""

    try:
        llm = get_llm()
        model = settings.planning_model or ""
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
        # Track consecutive skips per goal
        if drive.name == "serve" and state.selected_goal:
            goal_id = state.selected_goal["id"]
            _consecutive_skips[goal_id] = _consecutive_skips.get(goal_id, 0) + 1
            log.info(
                "Goal %s skipped (%d consecutive)",
                goal_id, _consecutive_skips[goal_id],
            )
            # Update last_checked_at and persist skip count so it survives restarts
            try:
                pool = get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE goals SET
                             last_checked_at = NOW(),
                             current_plan = jsonb_set(COALESCE(current_plan, '{}'::jsonb), '{consecutive_skips}', $1::text::jsonb),
                             updated_at = NOW()
                           WHERE id = $2::uuid""",
                        str(_consecutive_skips[goal_id]),
                        goal_id,
                    )
            except Exception as e:
                log.warning("Failed to update last_checked_at on skip: %s", e)

        # Mark as idle so adaptive timeout stays long (not 30s)
        state.action_taken = "idle"
        return "Skipped — no meaningful action to take"

    # Reset skip counter on successful action
    if drive.name == "serve" and state.selected_goal:
        goal_id = state.selected_goal["id"]
        if goal_id in _consecutive_skips:
            del _consecutive_skips[goal_id]

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
    """Execute a serve action — work on the selected goal (set by _plan_action)."""
    stale_goals = drive.context.get("stale_goals", [])
    if not stale_goals:
        return "No stale goals to work on"

    goal = state.selected_goal or stale_goals[0]
    goal_id = goal["id"]
    state.goal_id = goal_id

    # Check if this approach has already failed (oscillation prevention)
    try:
        is_blocked, failed = await check_approach_blocked(goal_id, plan, state.budget_tier)
        if is_blocked:
            log.info("Approach blocked for goal %s — already failed: %s", goal_id, failed[:2])
            try:
                llm = get_llm()
                resp = await llm.post("/complete", json={
                    "model": settings.planning_model or "",
                    "messages": [{"role": "user", "content":
                        "The following approaches have already failed for this goal:\n"
                        + "\n".join(f"- {f}" for f in failed[:3])
                        + "\n\nPropose a DIFFERENT strategy."}],
                    "temperature": 0.5, "max_tokens": 300, "tier": "mid",
                    "task_type": "planning",
                    "metadata": {"agent_id": "cortex", "task_id": f"replan-{state.cycle_number}"},
                })
                if resp.status_code == 200:
                    plan = resp.json().get("content", plan)
            except Exception as e:
                log.debug("Re-plan after dedup block failed: %s", e)
    except Exception as e:
        log.debug("Approach dedup check failed: %s", e)

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

            # Register for background monitoring instead of blocking poll
            task_monitor.dispatch(task_id, goal_id, state.cycle_number, plan)

            # Persist plan AFTER successful dispatch (iteration/progress updated after task completes)
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE goals
                       SET last_checked_at = NOW(),
                           current_plan = $1::jsonb,
                           updated_at = NOW()
                       WHERE id = $2::uuid""",
                    json.dumps({"plan": plan, "cycle": state.cycle_number, "task_id": task_id, "consecutive_skips": 0}),
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

        # ── Check if goal has reached its limits ──
        await _check_goal_limits(conn, goal_id, row)


async def _check_goal_limits(conn, goal_id: str, original_row) -> None:
    """Check if goal has hit max_iterations or max_cost and transition accordingly."""
    # Re-read current state (may have been updated by the branch above)
    row = await conn.fetchrow(
        "SELECT iteration, max_iterations, cost_so_far_usd, max_cost_usd, title, status FROM goals WHERE id = $1::uuid",
        goal_id,
    )
    if not row or row["status"] != "active":
        return

    max_iterations = row["max_iterations"]
    max_cost_usd = row["max_cost_usd"]
    iteration = row["iteration"]
    cost = float(row["cost_so_far_usd"] or 0)
    title = row["title"] or "unknown"

    # Max iterations reached -> completed (natural lifecycle end)
    if max_iterations is not None and iteration >= max_iterations:
        await conn.execute(
            "UPDATE goals SET status = 'completed', progress = 100.0, updated_at = NOW() WHERE id = $1::uuid",
            goal_id,
        )
        log.info("Goal %s completed: max_iterations reached (%d/%d)", goal_id, iteration, max_iterations)
        try:
            from .stimulus import emit, GOAL_COMPLETED
            await emit(GOAL_COMPLETED, "cortex", payload={"goal_id": goal_id, "title": title, "reason": "max_iterations"})
        except Exception as e:
            log.debug("Failed to emit goal.completed stimulus: %s", e)
        try:
            await write_entry(
                f"**Goal completed** — \"{title}\" reached max iterations ({iteration}/{max_iterations})",
                entry_type="narration",
                metadata={"goal_id": goal_id, "reason": "max_iterations"},
            )
        except Exception:
            pass
        return

    # Max cost reached -> paused (needs user decision)
    if max_cost_usd is not None and cost >= max_cost_usd:
        await conn.execute(
            """UPDATE goals SET status = 'paused',
                  current_plan = jsonb_set(COALESCE(current_plan, '{}'::jsonb), '{paused_reason}', '"budget_exhausted"'),
                  updated_at = NOW()
               WHERE id = $1::uuid""",
            goal_id,
        )
        log.info("Goal %s paused: budget exhausted ($%.2f/$%.2f)", goal_id, cost, max_cost_usd)
        try:
            from .stimulus import emit, GOAL_BUDGET_PAUSED
            await emit(GOAL_BUDGET_PAUSED, "cortex", payload={"goal_id": goal_id, "title": title, "cost": cost, "limit": max_cost_usd})
        except Exception as e:
            log.debug("Failed to emit goal.budget_paused stimulus: %s", e)
        try:
            await write_entry(
                f"**Goal paused** — \"{title}\" budget exhausted (${cost:.2f}/${max_cost_usd:.2f})",
                entry_type="escalation",
                metadata={"goal_id": goal_id, "reason": "budget_exhausted"},
            )
        except Exception:
            pass


async def _sweep_zombie_goals() -> None:
    """Periodic cleanup: transition goals that already hit their limits."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Goals past max_iterations -> completed
        completed = await conn.fetch(
            """UPDATE goals SET status = 'completed', progress = 100.0, updated_at = NOW()
               WHERE status = 'active' AND max_iterations IS NOT NULL AND iteration >= max_iterations
               RETURNING id, title""",
        )
        for row in completed:
            log.info("Zombie sweep: goal %s '%s' completed (max_iterations reached)", row["id"], row["title"])

        # Goals past max_cost -> paused
        paused = await conn.fetch(
            """UPDATE goals SET status = 'paused',
                  current_plan = jsonb_set(COALESCE(current_plan, '{}'::jsonb), '{paused_reason}', '"budget_exhausted"'),
                  updated_at = NOW()
               WHERE status = 'active' AND max_cost_usd IS NOT NULL AND cost_so_far_usd >= max_cost_usd
               RETURNING id, title""",
        )
        for row in paused:
            log.info("Zombie sweep: goal %s '%s' paused (budget exhausted)", row["id"], row["title"])


async def _record_cycle_reflection(state: CycleState) -> None:
    """Record a structured reflection after a Serve drive cycle with a task outcome."""
    outcome = state.task_outcome
    if not outcome:
        return

    # Map task status to reflection outcome
    if outcome.timed_out:
        ref_outcome, ref_score = "timeout", 0.5
    elif outcome.status == "complete" and outcome.findings_count == 0:
        ref_outcome, ref_score = "success", outcome.score
    elif outcome.status == "complete":
        ref_outcome, ref_score = "partial", outcome.score
    elif outcome.status == "failed":
        ref_outcome, ref_score = "failure", outcome.score
    elif outcome.status == "cancelled":
        ref_outcome, ref_score = "cancelled", outcome.score
    else:
        ref_outcome, ref_score = "failure", 0.2

    # Use the actual plan text stored during dispatch
    approach = state.plan_text or state.outcome.split(" | ")[0] if state.outcome else "unknown approach"

    # Get goal metadata
    goal_title = ""
    goal_description = ""
    maturation_phase = None
    max_iterations = 50
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT title, description, maturation_status, max_iterations FROM goals WHERE id = $1::uuid",
                state.goal_id,
            )
            if row:
                goal_title = row["title"]
                goal_description = row["description"] or ""
                maturation_phase = row["maturation_status"]
                max_iterations = row["max_iterations"] or 50
    except Exception as e:
        log.debug("Failed to read goal metadata: %s", e)

    context_snapshot = {
        "budget_tier": state.budget_tier,
        "model": state.resolved_model,
        "findings_count": outcome.findings_count,
        "task_cost_usd": outcome.total_cost_usd,
        "memory_hits": len(state.engram_ids),
        "goal_description_hash": compute_approach_hash(goal_description) if goal_description else None,
    }

    # LLM lesson extraction (only at mid/best tier, only for non-success)
    lesson = None
    failure_mode = None
    tier_ok = TIER_ORDER.get(state.budget_tier, 0) >= TIER_ORDER.get(settings.lesson_extraction_min_tier, 2)
    if tier_ok and ref_outcome in ("failure", "partial", "timeout"):
        lesson, failure_mode = await _extract_lesson(
            approach, ref_outcome, outcome.error or outcome.output or ""
        )

    try:
        await record_reflection(
            goal_id=state.goal_id,
            cycle_number=state.cycle_number,
            approach=approach,
            outcome=ref_outcome,
            outcome_score=ref_score,
            task_id=outcome.task_id,
            drive="serve",
            maturation_phase=maturation_phase,
            lesson=lesson,
            failure_mode=failure_mode,
            context_snapshot=context_snapshot,
        )
    except Exception as e:
        log.warning("Failed to record reflection: %s", e)
        return

    # Stuck detection
    try:
        from .stimulus import emit, GOAL_STUCK
        failure_count = await count_consecutive_failures(state.goal_id)
        threshold = compute_stuck_threshold(max_iterations)
        if failure_count >= threshold:
            log.warning("Goal %s stuck: %d consecutive failures (threshold %d)",
                        state.goal_id, failure_count, threshold)
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE goals SET maturation_status = 'review', updated_at = NOW() WHERE id = $1::uuid",
                    state.goal_id,
                )
            all_refs = await query_reflections(state.goal_id, limit=20)
            approaches_tried = [r["approach"][:80] for r in all_refs if r["outcome"] in ("failure", "timeout")]
            await record_reflection(
                goal_id=state.goal_id, cycle_number=state.cycle_number,
                approach="escalation", outcome="escalated", outcome_score=0.0,
                drive="serve", maturation_phase=maturation_phase,
                lesson=f"Stuck after {failure_count} failures. Tried: {'; '.join(approaches_tried[:5])}",
            )
            await write_entry(
                f"**Escalation** — Goal '{goal_title}' stuck after {failure_count} consecutive failures.\n\n"
                f"Approaches tried:\n" + "\n".join(f"- {a}" for a in approaches_tried[:5])
                + "\n\nMoving to 'review' status for human input.",
                entry_type="escalation",
                metadata={"goal_id": state.goal_id, "failure_count": failure_count, "action": "stuck_escalation"},
            )
            await emit(GOAL_STUCK, "cortex",
                       payload={"goal_id": state.goal_id, "title": goal_title,
                                "failure_count": failure_count, "approaches_tried": approaches_tried[:5]})
    except Exception as e:
        log.warning("Stuck detection failed for goal %s: %s", state.goal_id, e)

    # Ingest lesson into engrams for cross-goal learning
    if lesson:
        try:
            from .memory import ingest_lesson
            await ingest_lesson(
                goal_title=goal_title, maturation_phase=maturation_phase,
                approach=approach, outcome=ref_outcome, lesson=lesson,
                goal_id=state.goal_id, failure_mode=failure_mode,
            )
        except Exception as e:
            log.debug("Lesson ingestion failed: %s", e)


async def _extract_lesson(approach: str, outcome: str, detail: str) -> tuple[str | None, str | None]:
    """Use LLM to extract a lesson and failure mode from a cycle outcome."""
    prompt = (
        f"A task was executed with this approach: {approach[:200]}\n"
        f"Result: {outcome}\nDetails: {detail[:300]}\n\n"
        "Extract:\n1. LESSON: One sentence about what to do differently (max 100 tokens)\n"
        '2. FAILURE_MODE: Short category (e.g., "ambiguous requirements", "timeout")\n\n'
        "Respond exactly:\nLESSON: <lesson>\nFAILURE_MODE: <category>"
    )
    try:
        llm = get_llm()
        resp = await llm.post("/complete", json={
            "model": settings.planning_model or "",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1, "max_tokens": 100, "tier": "mid",
            "task_type": "planning",
            "metadata": {"agent_id": "cortex", "task_id": "lesson-extraction"},
        })
        if resp.status_code == 200:
            text = resp.json().get("content", "")
            lesson = failure_mode = None
            for line in text.strip().split("\n"):
                if line.startswith("LESSON:"):
                    lesson = line[7:].strip()[:500]
                elif line.startswith("FAILURE_MODE:"):
                    failure_mode = line[13:].strip()[:200]
            return lesson, failure_mode
    except Exception as e:
        log.debug("Lesson extraction LLM call failed: %s", e)
    return None, None


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
