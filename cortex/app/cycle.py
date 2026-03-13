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
from .scheduler import check_schedules
from .clients import get_llm, get_orchestrator
from .config import settings
from .db import get_pool
from .drives import DriveContext, DriveResult, DriveWinner, evaluate
from .drives import serve, maintain, improve, learn, reflect
from .journal import read_user_replies_since, write_entry

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
    action_taken: str = "none"
    outcome: str = ""
    error: str | None = None


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
                "metadata": {
                    "task_type": "planning",
                    "source": "cortex",
                    "cycle": state.cycle_number,
                    "drive": state.action_taken,
                },
            },
        )
    except Exception as e:
        log.debug("Failed to report cycle outcome: %s", e)


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

        # ── EVALUATE ──────────────────────────────────────────────────────
        drive_ctx = DriveContext(
            stimuli=state.stimuli,
            memory_context="",
            budget_tier=state.budget_tier,
            cycle_count=state.cycle_number,
        )

        for drive_module in ALL_DRIVES:
            try:
                result = await drive_module.assess(drive_ctx)
                state.drive_results.append(result)
            except Exception as e:
                log.warning("Drive %s.assess() failed: %s", drive_module.__name__, e)

        state.winner = evaluate(state.drive_results, state.budget_tier)

        if state.winner is None:
            state.action_taken = "idle"
            state.outcome = "No drives have urgency — nothing to do"
            await _update_state(state)
            await write_entry(
                f"Cycle {state.cycle_number}: idle. Budget {state.budget_pct:.0f}% used ({state.budget_tier}). "
                f"All drives quiet.",
                entry_type="narration",
                metadata={"cycle": state.cycle_number, "action": "idle"},
            )
            await _report_outcome(state, settings.planning_model or "unknown", 0.6, 0.5)
            return state

        drive = state.winner.result

        # ── PLAN ──────────────────────────────────────────────────────────
        plan = await _plan_action(drive, state)

        # ── ACT ───────────────────────────────────────────────────────────
        state.action_taken = drive.name
        state.outcome = await _execute_action(drive, plan, state)

        # ── REFLECT ──────────────────────────────────────────────────────
        await _reflect(state)
        await _update_state(state)

        # ── SCORE ───────────────────────────────────────────────────
        _model = settings.planning_model or "unknown"
        if state.action_taken == "idle":
            await _report_outcome(state, _model, 0.6, 0.5)
        elif state.error:
            await _report_outcome(state, _model, 0.2, 0.9)
        else:
            await _report_outcome(state, _model, 0.7, 0.7)

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
        if state.budget_tier != "none":
            await _report_outcome(state, settings.planning_model or "unknown", 0.2, 0.9)

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
    else:
        return f"Drive '{drive.name}' has no executor yet (stub)"


async def _execute_serve(drive: DriveResult, plan: str, state: CycleState) -> str:
    """Execute a serve action — work on the highest-priority stale goal."""
    stale_goals = drive.context.get("stale_goals", [])
    if not stale_goals:
        return "No stale goals to work on"

    goal = stale_goals[0]
    goal_id = goal["id"]

    # Mark goal as checked
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE goals SET last_checked_at = NOW(), iteration = iteration + 1, updated_at = NOW() WHERE id = $1::uuid",
            goal_id,
        )

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

    if state.user_messages:
        content += f"\n\nUser messages: {len(state.user_messages)}"

    entry_type = "narration"
    if state.error:
        content += f"\n\nERROR: {state.error}"
        entry_type = "escalation"

    await write_entry(content, entry_type=entry_type, metadata={
        "cycle": state.cycle_number,
        "drive": state.action_taken,
        "budget_tier": state.budget_tier,
    })


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
