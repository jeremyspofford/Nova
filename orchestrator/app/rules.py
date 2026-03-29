"""Rules — declarative behavior constraints with hard enforcement."""
from __future__ import annotations

import json
import logging
import re
from uuid import UUID

from pydantic import BaseModel

from app.db import get_pool

log = logging.getLogger(__name__)

# Compiled regex cache: rule_id -> (updated_at_str, compiled_pattern)
_regex_cache: dict[str, tuple[str, re.Pattern]] = {}


class RuleCreate(BaseModel):
    name: str
    description: str = ""
    rule_text: str
    enforcement: str = "hard"
    pattern: str | None = None
    target_tools: list[str] | None = None
    action: str = "block"
    category: str = "safety"
    severity: str = "high"


class RuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    rule_text: str | None = None
    enforcement: str | None = None
    pattern: str | None = None
    target_tools: list[str] | None = None
    action: str | None = None
    category: str | None = None
    severity: str | None = None
    enabled: bool | None = None


async def list_rules() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM rules ORDER BY severity DESC, name")
    return [dict(r) for r in rows]


async def create_rule(req: RuleCreate) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO rules (name, description, rule_text, enforcement, pattern,
                   target_tools, action, category, severity)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING *""",
            req.name, req.description, req.rule_text, req.enforcement,
            req.pattern, req.target_tools, req.action, req.category, req.severity,
        )
    return dict(row)


async def update_rule(rule_id: UUID, req: RuleUpdate) -> dict | None:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM rules WHERE id = $1", rule_id)
        return dict(row) if row else None

    set_clauses = []
    params = []
    idx = 1
    for key, val in updates.items():
        set_clauses.append(f"{key} = ${idx}")
        params.append(val)
        idx += 1
    set_clauses.append("updated_at = NOW()")
    params.append(rule_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE rules SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *",
            *params,
        )
    _regex_cache.pop(str(rule_id), None)
    return dict(row) if row else None


async def delete_rule(rule_id: UUID) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        is_sys = await conn.fetchval(
            "SELECT is_system FROM rules WHERE id = $1", rule_id
        )
        if is_sys:
            return False
        result = await conn.execute("DELETE FROM rules WHERE id = $1", rule_id)
    _regex_cache.pop(str(rule_id), None)
    return result == "DELETE 1"


def _get_compiled(rule_id: str, updated_at: str, pattern: str) -> re.Pattern:
    """Get or compile a regex pattern with caching."""
    cached = _regex_cache.get(rule_id)
    if cached and cached[0] == updated_at:
        return cached[1]
    compiled = re.compile(pattern, re.IGNORECASE)
    _regex_cache[rule_id] = (updated_at, compiled)
    return compiled


async def check_hard_rules(tool_name: str, arguments: dict) -> tuple[bool, str | None]:
    """Check if a tool call violates any hard rules.

    Returns (allowed, violation_message).
    Called from execute_tool() before dispatching.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, rule_text, pattern, target_tools, action, updated_at
               FROM rules
               WHERE enabled = true
                 AND enforcement IN ('hard', 'both')
                 AND pattern IS NOT NULL"""
        )

    if not rows:
        return True, None

    match_str = f"{tool_name} {json.dumps(arguments, default=str)}"

    for r in rows:
        targets = r["target_tools"]
        if targets and tool_name not in targets:
            continue

        try:
            compiled = _get_compiled(str(r["id"]), str(r["updated_at"]), r["pattern"])
            if compiled.search(match_str):
                if r["action"] == "warn":
                    log.warning(
                        "Rule '%s' matched tool call %s (warn): %s",
                        r["name"], tool_name, r["rule_text"],
                    )
                    continue
                else:
                    return False, f"Blocked by rule '{r['name']}': {r['rule_text']}"
        except re.error as e:
            log.error("Invalid regex in rule '%s': %s", r["name"], e)
            continue

    return True, None
