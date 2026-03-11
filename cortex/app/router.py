"""Cortex control endpoints — status, pause, resume."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from .db import get_pool

log = logging.getLogger(__name__)

cortex_router = APIRouter(prefix="/api/v1/cortex", tags=["cortex"])


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


@cortex_router.get("/drives")
async def get_drives():
    """Current drive urgency scores (placeholder — returns static structure)."""
    return {
        "drives": [
            {"name": "serve", "priority": 1, "urgency": 0.0, "description": "Pursue user-set goals"},
            {"name": "maintain", "priority": 2, "urgency": 0.0, "description": "Keep Nova healthy"},
            {"name": "improve", "priority": 3, "urgency": 0.0, "description": "Make Nova's code better"},
            {"name": "learn", "priority": 4, "urgency": 0.0, "description": "Build knowledge"},
            {"name": "reflect", "priority": 5, "urgency": 0.0, "description": "Learn from experience"},
        ]
    }
