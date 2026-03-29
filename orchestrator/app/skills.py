"""Skills — reusable prompt templates for agents."""
from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from app.db import get_pool

log = logging.getLogger(__name__)


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    content: str
    scope: str = "global"
    category: str = "custom"
    priority: int = 0


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    scope: str | None = None
    category: str | None = None
    priority: int | None = None
    enabled: bool | None = None


async def list_skills() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM skills ORDER BY priority DESC, name"
        )
    return [dict(r) for r in rows]


async def create_skill(req: SkillCreate) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO skills (name, description, content, scope, category, priority)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING *""",
            req.name, req.description, req.content, req.scope, req.category, req.priority,
        )
    return dict(row)


async def update_skill(skill_id: UUID, req: SkillUpdate) -> dict | None:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM skills WHERE id = $1", skill_id)
        return dict(row) if row else None

    set_clauses = []
    params = []
    idx = 1
    for key, val in updates.items():
        set_clauses.append(f"{key} = ${idx}")
        params.append(val)
        idx += 1
    set_clauses.append("updated_at = NOW()")
    params.append(skill_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE skills SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *",
            *params,
        )
    return dict(row) if row else None


async def delete_skill(skill_id: UUID) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        is_sys = await conn.fetchval(
            "SELECT is_system FROM skills WHERE id = $1", skill_id
        )
        if is_sys:
            return False
        result = await conn.execute("DELETE FROM skills WHERE id = $1", skill_id)
    return result == "DELETE 1"


async def resolve_skills() -> str:
    """Resolve all active global skills into a formatted prompt section."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT name, content FROM skills
               WHERE enabled = true AND scope = 'global'
               ORDER BY priority DESC, name"""
        )
    if not rows:
        return ""

    parts = ["## Active Skills\n"]
    for r in rows:
        parts.append(f"### {r['name']}\n{r['content']}\n")
    return "\n".join(parts)
