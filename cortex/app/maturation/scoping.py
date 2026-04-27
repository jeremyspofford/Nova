"""Scoping phase — analyze goal, identify affected areas, write scope_analysis."""
from __future__ import annotations

import json
import logging

from ..clients import get_llm
from ..config import settings
from ..db import get_pool
from ..memory import perceive_with_memory

log = logging.getLogger(__name__)

SCOPE_PROMPT = """Analyze this engineering goal. Identify all areas of the codebase affected.

Goal: {title}
Description: {description}

Related context from memory (top 5):
{memory_context}

Output JSON with these keys:
- "affected_scopes": list of strings from {{backend, frontend, data, security, infra, networking, ci_cd, testing}}
- "estimated_files_changed": integer
- "key_components": list of file paths or service names that will change
- "open_questions": list of clarifying questions for the human (empty list if none)
- "summary": one paragraph explaining what's affected and why

Respond with valid JSON only, no prose."""


async def run_scoping(goal_id: str) -> dict:
    """Execute the scoping phase for a goal. Writes scope_analysis, transitions to speccing."""
    pool = get_pool()
    async with pool.acquire() as conn:
        goal = await conn.fetchrow(
            "SELECT title, description FROM goals WHERE id = $1::uuid",
            goal_id,
        )
    if not goal:
        log.warning("Scoping called for missing goal %s", goal_id)
        return {}

    perception = await perceive_with_memory(
        stimuli=[{"type": "goal.scoping", "payload": {"goal_id": goal_id}}],
        goal_context=f"{goal['title']} — {goal['description'] or ''}",
    )
    memory_str = perception.get("memory_context") or "(no relevant memories)"

    prompt = SCOPE_PROMPT.format(
        title=goal["title"],
        description=goal["description"] or "(no description)",
        memory_context=memory_str,
    )

    llm = get_llm()
    resp = await llm.post(
        "/complete",
        json={
            "model": settings.planning_model or "",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1500,
            "tier": "mid",
            "response_format": {"type": "json_object"},
        },
        timeout=120.0,
    )
    if resp.status_code != 200:
        log.warning("Scoping LLM returned %d for goal %s", resp.status_code, goal_id)
        return {}

    try:
        scope_data = json.loads(resp.json().get("content", "{}"))
    except json.JSONDecodeError as e:
        log.warning("Scoping LLM returned invalid JSON for goal %s: %s", goal_id, e)
        return {}

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET scope_analysis = $1::jsonb,
                                  maturation_status = 'speccing',
                                  updated_at = NOW()
               WHERE id = $2::uuid""",
            json.dumps(scope_data), goal_id,
        )
    log.info("Scoping complete for goal %s — transitioned to speccing", goal_id)
    return scope_data
