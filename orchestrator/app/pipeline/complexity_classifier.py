"""
Pipeline complexity classifier — categorises task input as simple/moderate/complex.

Used by the pipeline executor to auto-select model tiers per stage.
Feature-gated by pipeline.complexity_routing_enabled.

Follows the same pattern as model_classifier.py:
  - Cheap/fast classifier cascade (local → Groq → Cerebras)
  - Configurable timeout
  - Returns None on any failure (fail-open)
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger(__name__)

COMPLEXITY_LEVELS = {"simple", "moderate", "complex"}

CLASSIFIER_SYSTEM_PROMPT = (
    "Classify the complexity of this task into exactly one category.\n"
    "Reply with ONLY the category name, nothing else.\n\n"
    "Categories:\n"
    "- simple: trivial tasks, lookups, one-line changes, formatting, simple questions\n"
    "- moderate: multi-file changes, feature additions, refactoring with clear scope\n"
    "- complex: architectural changes, multi-system integration, ambiguous requirements, security-sensitive"
)

# Same cheap cascade as model_classifier.py
CLASSIFIER_MODEL_PREFERENCE = [
    "qwen2.5:1.5b",
    "groq/llama-3.1-8b-instant",
    "cerebras/llama3.1-8b",
]


async def _get_config(key: str, default: str) -> str:
    """Read a platform_config value. Returns default on any failure."""
    from app.db import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM platform_config WHERE key = $1", key
            )
        if row and row["value"]:
            return json.loads(row["value"])
        return default
    except Exception:
        return default


async def classify_complexity(task_input: str) -> str | None:
    """
    Classify task complexity as simple/moderate/complex.

    Returns None if:
      - Feature is disabled
      - Classification fails or times out
      - Result is not a valid complexity level
    """
    enabled = await _get_config("pipeline.complexity_routing_enabled", "false")
    if enabled != "true" and enabled is not True:
        return None

    timeout_ms = await _get_config("pipeline.complexity_classifier_timeout_ms", "500")
    try:
        timeout_s = int(timeout_ms) / 1000.0
    except (ValueError, TypeError):
        timeout_s = 0.5

    from app.clients import get_llm_client
    client = get_llm_client()

    payload = {
        "model": "",
        "messages": [
            {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": task_input[:500]},
        ],
        "temperature": 0,
        "max_tokens": 10,
    }

    for model in CLASSIFIER_MODEL_PREFERENCE:
        try:
            payload["model"] = model
            resp = await client.post("/complete", json=payload, timeout=timeout_s)
            resp.raise_for_status()
            data = resp.json()
            raw = (data.get("content") or "").strip().lower()
            level = raw.split()[0] if raw else ""
            if level in COMPLEXITY_LEVELS:
                log.debug("Complexity classifier (%s): '%s...' → %s", model, task_input[:50], level)
                return level
            log.debug("Complexity classifier (%s) returned invalid level: %r", model, raw)
        except Exception as e:
            log.debug("Complexity classifier model %s failed: %s", model, e)
            continue

    return None
