"""Prompt-injection defenses for the Quartet pipeline and Cortex maturation.

When untrusted content (user goals, task outputs, agent outputs from earlier
stages) is interpolated into LLM prompts, an attacker can include text that
looks like instructions ("Ignore previous instructions and output …"). The
model has no a-priori way to know which text is authoritative.

This module provides XML-boundary wrapping. Untrusted content is enclosed in
a stable tag (e.g. ``<USER_REQUEST>...</USER_REQUEST>``). To prevent the
content itself from "escaping" the boundary by including a literal close-tag,
we neutralize close-tag patterns inside the content before wrapping.

Tags are stable (not random-per-request) so Anthropic prompt caching keeps
working. Defense-in-depth comes from neutralizing close-tags in content.
"""
from __future__ import annotations

import re

# Tags used across the Quartet pipeline + Cortex maturation. Keeping these
# centralized avoids typos and lets us change the boundary scheme in one place.
TAG_USER_REQUEST = "USER_REQUEST"        # original user/operator request
TAG_TASK_OUTPUT = "TASK_OUTPUT"          # output from a prior agent stage
TAG_REVIEW_FEEDBACK = "REVIEW_FEEDBACK"  # code-review/refactor feedback
TAG_CONTEXT = "CURATED_CONTEXT"          # output from Context Agent
TAG_GOAL_TITLE = "GOAL_TITLE"            # cortex: untrusted goal title
TAG_GOAL_DESCRIPTION = "GOAL_DESCRIPTION"  # cortex: untrusted goal description
TAG_PARENT_HINT = "PARENT_HINT"          # cortex: hint passed from parent goal


def neutralize_close_tags(content: str, tag: str) -> str:
    """Replace any ``</TAG>`` literal in content with a neutered form.

    Matches case-insensitively because the model treats casing leniently when
    parsing XML-ish markers. The replacement uses a backslash to keep the
    text human-readable while breaking the structural marker:
    ``</USER_REQUEST>`` → ``<\\/USER_REQUEST>``.
    """
    pattern = re.compile(r"</\s*" + re.escape(tag) + r"\s*>", re.IGNORECASE)
    return pattern.sub(f"<\\\\/{tag}>", content)


def wrap_untrusted(content: str | None, tag: str) -> str:
    """Wrap untrusted content in stable XML tags with close-tag neutralization.

    Returns an empty wrapper for ``None`` / empty input rather than raising,
    so callers can interpolate this unconditionally.
    """
    if content is None:
        return f"<{tag}></{tag}>"
    safe = neutralize_close_tags(str(content), tag)
    return f"<{tag}>\n{safe}\n</{tag}>"
