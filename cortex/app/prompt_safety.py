"""Prompt-injection defenses for Cortex maturation prompts.

Mirrored from ``orchestrator/app/pipeline/prompt_safety.py`` because cortex
and orchestrator are separate Docker services and do not share a Python
import path at runtime. The utility is small and pure — duplicating is
simpler than introducing a shared package. If this grows, promote it to a
real shared lib.

Goal title/description and parent_hint flow into Cortex's autonomous
decomposition prompts. An attacker who poisons a goal title can influence
the spec, which then directs the entire Quartet pipeline downstream.
Wrapping these inputs in stable XML tags scopes them as data, not
instructions.
"""
from __future__ import annotations

import re

TAG_GOAL_TITLE = "GOAL_TITLE"
TAG_GOAL_DESCRIPTION = "GOAL_DESCRIPTION"
TAG_PARENT_HINT = "PARENT_HINT"
TAG_MEMORY_CONTEXT = "MEMORY_CONTEXT"
TAG_SCOPE_ANALYSIS = "SCOPE_ANALYSIS"


def neutralize_close_tags(content: str, tag: str) -> str:
    pattern = re.compile(r"</\s*" + re.escape(tag) + r"\s*>", re.IGNORECASE)
    return pattern.sub(f"<\\\\/{tag}>", content)


def wrap_untrusted(content: str | None, tag: str) -> str:
    if content is None:
        return f"<{tag}></{tag}>"
    safe = neutralize_close_tags(str(content), tag)
    return f"<{tag}>\n{safe}\n</{tag}>"
