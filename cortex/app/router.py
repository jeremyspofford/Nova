"""Cortex control endpoints — status, pause, resume, drives, journal."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from uuid import UUID

from fastapi import HTTPException

from .budget import get_budget_status
from .clients import get_orchestrator
from .config import settings
from .db import get_pool
from .drives import serve, maintain, improve, learn, reflect
from .journal import read_recent

log = logging.getLogger(__name__)

cortex_router = APIRouter(prefix="/api/v1/cortex", tags=["cortex"])

ALL_DRIVES = [serve, maintain, improve, learn, reflect]


@cortex_router.get("/status")
async def get_status():
    """Current Cortex state — running/paused, cycle count, active drive."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM cortex_state WHERE id = true")
    if not row:
        return {"status": "uninitialized"}
    return {
        "status": row["status"],
        "current_drive": row["current_drive"],
        "cycle_count": row["cycle_count"],
        "last_cycle_at": row["last_cycle_at"].isoformat() if row["last_cycle_at"] else None,
        "last_checkpoint": row["last_checkpoint"],
    }


@cortex_router.post("/pause")
async def pause():
    """Pause autonomous operation."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cortex_state SET status = 'paused', updated_at = NOW() WHERE id = true"
        )
    log.info("Cortex paused")
    return {"status": "paused"}


@cortex_router.post("/resume")
async def resume():
    """Resume autonomous operation."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cortex_state SET status = 'running', updated_at = NOW() WHERE id = true"
        )
    log.info("Cortex resumed")
    return {"status": "running"}


@cortex_router.post("/trigger/{goal_id}")
async def trigger_goal(goal_id: UUID):
    """Directly dispatch a pipeline task for a goal, bypassing drive evaluation."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, title, description FROM goals WHERE id = $1 AND status = 'active'",
            goal_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Goal not found or not active")

    # Dispatch task directly to orchestrator
    try:
        orch = get_orchestrator()
        resp = await orch.post(
            "/api/v1/pipeline/tasks",
            json={
                "user_input": f"[Cortex goal work] Goal: {row['title']}."
                              + (f" Description: {row['description']}" if row["description"] else "")
                              + " Analyze the goal and take the next meaningful step toward completion.",
                "goal_id": str(goal_id),
                "metadata": {"source": "cortex", "trigger": "manual", "drive": "serve"},
            },
            headers={"Authorization": f"Bearer {settings.cortex_api_key}"},
        )
        if resp.status_code not in (200, 201, 202):
            raise HTTPException(status_code=502, detail=f"Orchestrator returned {resp.status_code}")
        task_id = resp.json().get("task_id", "unknown")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to dispatch: {e}")

    # Only update after successful dispatch
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE goals SET last_checked_at = NOW(), iteration = iteration + 1, updated_at = NOW() WHERE id = $1",
            goal_id,
        )

    log.info("Manual trigger for goal %s → task %s", goal_id, task_id)
    return {"status": "dispatched", "task_id": task_id, "goal_id": str(goal_id)}


@cortex_router.get("/drives")
async def get_drives():
    """Live drive urgency scores — calls each drive's assess() method."""
    results = []
    for drive_module in ALL_DRIVES:
        try:
            r = await drive_module.assess()
            results.append({
                "name": r.name,
                "priority": r.priority,
                "urgency": r.urgency,
                "description": r.description,
                "proposed_action": r.proposed_action,
                "context": r.context,
            })
        except Exception as e:
            log.warning("Drive %s.assess() failed: %s", drive_module.__name__, e)
            results.append({
                "name": drive_module.__name__.split(".")[-1],
                "priority": 0,
                "urgency": 0.0,
                "description": f"Error: {e}",
                "proposed_action": None,
            })
    return {"drives": results}


@cortex_router.get("/budget")
async def budget():
    """Current budget state — daily spend, remaining, tier."""
    return await get_budget_status()


@cortex_router.get("/journal")
async def journal(limit: int = Query(default=20, le=100)):
    """Recent journal entries from the Cortex conversation."""
    entries = await read_recent(limit)
    return {"entries": entries}


@cortex_router.get("/reflections/{goal_id}")
async def get_reflections(goal_id: UUID, limit: int = Query(default=20, le=100)):
    """Reflections (experience log) for a specific goal."""
    from .reflections import query_reflections
    refs = await query_reflections(str(goal_id), limit=limit)
    return {"reflections": refs, "count": len(refs)}
