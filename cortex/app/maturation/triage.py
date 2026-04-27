"""Triage classifier — decides whether a goal enters the maturation pipeline."""
from __future__ import annotations

import logging
from typing import Literal

from ..clients import get_llm
from ..config import settings

log = logging.getLogger(__name__)

TRIAGE_PROMPT = """Classify this engineering goal as `simple` or `complex`.

Title: {title}
Description: {description}

A goal is COMPLEX if any apply:
- Touches multiple services (orchestrator, cortex, memory, dashboard, etc.)
- Requires database migrations
- Needs frontend AND backend changes
- Has security implications (auth, secrets, RBAC)
- Changes infrastructure (docker, networking, deployment)
- Estimates 3+ files changed

A goal is SIMPLE if it's a focused single-file or single-concern change.

Respond with exactly one word: `simple` or `complex`."""


async def triage_goal_complexity(
    title: str, description: str | None
) -> Literal["simple", "complex"]:
    """Classify a goal's complexity. Defaults to `complex` on any error (safer)."""
    try:
        llm = get_llm()
        prompt = TRIAGE_PROMPT.format(
            title=title or "(untitled)",
            description=description or "(no description)",
        )
        body: dict = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 10,
            "tier": "cheap",
        }
        if settings.planning_model:
            body["model"] = settings.planning_model
        resp = await llm.post("/complete", json=body, timeout=30.0)
        if resp.status_code != 200:
            log.warning("Triage LLM returned %d, defaulting to complex", resp.status_code)
            return "complex"
        text = resp.json().get("content", "").strip().lower()
        if "simple" in text and "complex" not in text:
            return "simple"
        return "complex"
    except Exception as e:
        log.warning("Triage failed (%s), defaulting to complex", e)
        return "complex"
