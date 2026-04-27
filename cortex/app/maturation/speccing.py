"""Speccing phase — generate engineering spec from scope, write to goals.spec."""
from __future__ import annotations

import json
import logging

from ..clients import get_llm
from ..config import settings
from ..db import get_pool

log = logging.getLogger(__name__)

SPEC_PROMPT = """Generate an engineering spec for this goal.

Goal: {title}
Description: {description}

Scope analysis (already produced):
{scope_analysis}

Produce a markdown spec with these sections:
1. **Architecture** — 2-3 sentences on the approach
2. **File changes** — markdown table: Action | Path | Responsibility
3. **Sub-tasks in dependency order** — numbered list, each one a 1-day-or-less unit
4. **Cost/complexity estimate** — rough hours or days
5. **Open questions** — list, empty if none

Keep total spec under 1500 words. Be concrete; reference real file paths and known
services. The reader is an engineer who will execute this plan tomorrow.

Respond with the markdown spec only, no preamble."""


async def run_speccing(goal_id: str) -> str:
    """Generate spec, write to goals.spec, transition speccing → review."""
    pool = get_pool()
    async with pool.acquire() as conn:
        goal = await conn.fetchrow(
            "SELECT title, description, scope_analysis FROM goals WHERE id = $1::uuid",
            goal_id,
        )
    if not goal or not goal["scope_analysis"]:
        log.warning("Speccing called without scope_analysis for goal %s", goal_id)
        return ""

    scope_raw = goal["scope_analysis"]
    if isinstance(scope_raw, dict):
        scope_str = json.dumps(scope_raw, indent=2)
    elif isinstance(scope_raw, str):
        # asyncpg returns JSONB as a string in some configurations; pretty-print if valid JSON
        try:
            scope_str = json.dumps(json.loads(scope_raw), indent=2)
        except json.JSONDecodeError:
            scope_str = scope_raw
    else:
        scope_str = str(scope_raw)

    prompt = SPEC_PROMPT.format(
        title=goal["title"],
        description=goal["description"] or "(no description)",
        scope_analysis=scope_str,
    )

    llm = get_llm()
    resp = await llm.post(
        "/complete",
        json={
            "model": settings.planning_model or "",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 3000,
            "tier": "best",
        },
        timeout=180.0,
    )
    if resp.status_code != 200:
        log.warning("Speccing LLM returned %d for goal %s", resp.status_code, goal_id)
        return ""

    spec = resp.json().get("content", "").strip()
    if len(spec) < 50:
        log.warning("Speccing returned too-short spec for goal %s", goal_id)
        return ""

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET spec = $1,
                                  maturation_status = 'review',
                                  updated_at = NOW()
               WHERE id = $2::uuid""",
            spec, goal_id,
        )

    log.info("Speccing complete for goal %s — transitioned to review", goal_id)
    return spec
