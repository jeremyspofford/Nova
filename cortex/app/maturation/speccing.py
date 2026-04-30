"""Speccing phase — generate engineering spec from scope, write to goals.spec."""
from __future__ import annotations

import json
import logging

from ..clients import get_llm
from ..config import settings
from ..db import get_pool

log = logging.getLogger(__name__)

SPEC_PROMPT = """Generate an engineering plan for this goal.

Goal: {title}
Description: {description}

Scope analysis (already produced):
{scope_analysis}

Parent goal hint (if any, treat as starting context, not a constraint):
{parent_hint}

You are at depth {depth} of {max_depth}. If you're close to max_depth, prefer flat task-sized
children (single-file changes) over deep recursion.

Respond with a single JSON object exactly matching this shape (no markdown fences, no preamble):

{{
  "spec_markdown": "<2-page markdown narrative for human review: architecture, file changes table, sub-tasks in dependency order, cost estimate, open questions>",
  "spec_children": [
    {{
      "title": "<short imperative>",
      "description": "<2-3 sentences>",
      "hint": "<one-line nudge for the child's own scoping>",
      "depends_on": [<int indices into spec_children>],
      "estimated_cost_usd": <float>,
      "estimated_complexity": "<simple|complex>"
    }}
  ],
  "verification_commands": [
    {{"cmd": "<shell command>", "cwd": null, "timeout_s": <int>}}
  ],
  "success_criteria_structured": [
    {{"statement": "<plain english>", "check": "<command|engram_query|llm_judge>", "check_arg": "<command-or-query-or-prompt>"}}
  ]
}}

Rules:
- Sum of children.estimated_cost_usd MUST be ≤ 0.85 × parent_max_cost (you have ${max_cost} parent budget).
- depends_on indices must reference valid earlier entries in spec_children.
- estimated_complexity='simple' children get materialized as flat tasks (no further recursion).
- Verification commands should be runnable with no human in the loop (no interactive prompts).
- Keep spec_markdown under 1500 words.
"""


async def run_speccing(goal_id: str) -> dict | None:
    """Generate spec, write spec_markdown + spec_children + verification_commands + criteria.

    Transitions: speccing → review on success.
    On hard failure: writes minimal markdown-only envelope and forces complexity='simple' so
    building can flat-materialize in a recovery path.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        goal = await conn.fetchrow(
            """SELECT title, description, scope_analysis, max_cost_usd, depth, max_depth, current_plan
               FROM goals WHERE id = $1::uuid""",
            goal_id,
        )
    if not goal or not goal["scope_analysis"]:
        log.warning("Speccing called without scope_analysis for goal %s", goal_id)
        return None

    scope_raw = goal["scope_analysis"]
    if isinstance(scope_raw, str):
        try:
            scope_str = json.dumps(json.loads(scope_raw), indent=2)
        except json.JSONDecodeError:
            scope_str = scope_raw
    else:
        scope_str = json.dumps(scope_raw, indent=2)

    parent_hint = ""
    plan = goal["current_plan"] or {}
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            plan = {}
    if isinstance(plan, dict):
        parent_hint = plan.get("hint", "") or "(none)"

    prompt = SPEC_PROMPT.format(
        title=goal["title"],
        description=goal["description"] or "(no description)",
        scope_analysis=scope_str,
        parent_hint=parent_hint,
        depth=goal["depth"],
        max_depth=goal["max_depth"],
        max_cost=f"{goal['max_cost_usd']:.2f}",
    )

    llm = get_llm()
    envelope: dict | None = None
    for attempt, temp in enumerate((0.2, 0.4, 0.6), start=1):
        resp = await llm.post(
            "/complete",
            json={
                "model": settings.planning_model or "",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp,
                "max_tokens": 4000,
                "tier": "best",
                "response_format": {"type": "json_object"},
            },
            timeout=240.0,
        )
        if resp.status_code != 200:
            log.warning("Speccing LLM returned %d for goal %s (attempt %d)",
                        resp.status_code, goal_id, attempt)
            continue
        content = resp.json().get("content", "").strip()
        if not content:
            log.warning("Speccing returned empty for goal %s (attempt %d)", goal_id, attempt)
            continue
        try:
            parsed = json.loads(content)
            if (isinstance(parsed, dict)
                and parsed.get("spec_markdown")
                and isinstance(parsed.get("spec_children"), list)):
                envelope = parsed
                break
            log.warning("Speccing envelope malformed for goal %s (attempt %d)", goal_id, attempt)
        except json.JSONDecodeError as e:
            log.warning("Speccing JSON decode failed for goal %s (attempt %d): %s",
                        goal_id, attempt, e)

    if envelope is None:
        log.warning("Speccing exhausted retries for goal %s; writing minimal envelope", goal_id)
        envelope = {
            "spec_markdown": (
                f"## Speccing Deferred\n\n"
                f"LLM returned no usable structured output after 3 retries for goal "
                f"`{goal['title']}`.\n\n"
                f"Description: {goal['description'] or '(none)'}\n\n"
                f"Action: review manually before approving."
            ),
            "spec_children": [],
            "verification_commands": [],
            "success_criteria_structured": [],
            "_fallback": True,
        }

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE goals SET
                  spec = $1,
                  spec_children = $2::jsonb,
                  verification_commands = $3::jsonb,
                  success_criteria_structured = $4::jsonb,
                  complexity = COALESCE(complexity, CASE WHEN $5 THEN 'simple' ELSE 'complex' END),
                  maturation_status = 'review',
                  updated_at = NOW()
               WHERE id = $6::uuid""",
            envelope["spec_markdown"],
            json.dumps(envelope.get("spec_children") or []),
            json.dumps(envelope.get("verification_commands") or []),
            json.dumps(envelope.get("success_criteria_structured") or []),
            envelope.get("_fallback", False),
            goal_id,
        )

    from ..journal import emit_journal
    await emit_journal(goal_id, "speccing.complete",
        {"children_count": len(envelope.get("spec_children") or []),
         "fallback": envelope.get("_fallback", False)})
    log.info("Speccing complete for goal %s — transitioned to review (children=%d)",
             goal_id, len(envelope.get("spec_children") or []))
    return envelope
