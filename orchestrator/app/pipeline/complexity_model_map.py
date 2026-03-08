"""
Complexity → model mapping for pipeline stages.

Maps (complexity_level, agent_role) → model_id.
Users can override defaults via pipeline.complexity_model_map in platform_config.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

# Default model assignments per complexity level and role.
# None = use the next layer in the resolution chain (stage default / pod default / auto).
DEFAULT_MAP: dict[str, dict[str, str | None]] = {
    "simple": {
        "context":     "groq/llama-3.1-8b-instant",
        "task":        "groq/llama-3.3-70b-versatile",
        "guardrail":   "groq/llama-3.1-8b-instant",
        "code_review": "groq/llama-3.1-8b-instant",
        "decision":    "groq/llama-3.1-8b-instant",
    },
    "moderate": {
        "context":     None,  # use stage/pod default
        "task":        None,  # use stage/pod default (likely frontier)
        "guardrail":   "groq/llama-3.1-8b-instant",
        "code_review": None,  # use stage/pod default
        "decision":    "groq/llama-3.1-8b-instant",
    },
    "complex": {
        "context":     None,
        "task":        None,
        "guardrail":   "groq/llama-3.1-8b-instant",  # Tier 1 only — cheap is fine
        "code_review": None,
        "decision":    None,
    },
}


async def resolve_complexity_model(complexity: str | None, role: str) -> str | None:
    """
    Resolve a model for a given complexity level and agent role.

    Returns None if:
      - complexity is None (classification failed/disabled)
      - No mapping exists for this (complexity, role) pair
      - User override maps to null/empty
    """
    if not complexity:
        return None

    # Try user overrides first
    user_map = await _get_user_map()
    if user_map:
        level_map = user_map.get(complexity, {})
        if isinstance(level_map, dict):
            model = level_map.get(role)
            if model:
                return model

    # Fall back to defaults
    level_map = DEFAULT_MAP.get(complexity, {})
    model = level_map.get(role)
    if model:
        log.debug("Complexity model: %s/%s → %s", complexity, role, model)
    return model


async def _get_user_map() -> dict | None:
    """Load user overrides from platform_config."""
    from app.db import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM platform_config WHERE key = 'pipeline.complexity_model_map'"
            )
        if not row or not row["value"]:
            return None
        val = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
        return val if isinstance(val, dict) and val else None
    except Exception:
        return None
