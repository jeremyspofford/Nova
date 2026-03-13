"""Improve drive — investigate contradictions and system improvements.

Reacts to engram.contradiction stimuli and neural router readiness.
"""
from __future__ import annotations

import logging

from ..clients import get_memory
from . import DriveContext, DriveResult

log = logging.getLogger(__name__)


async def assess(ctx: DriveContext | None = None) -> DriveResult:
    """Assess improve drive urgency based on contradictions and system signals."""
    urgency = 0.0
    description_parts = []
    context = {}

    # React to contradiction stimuli
    if ctx:
        contradictions = ctx.stimuli_of_type("engram.contradiction")
        if contradictions:
            urgency = max(urgency, 0.4)
            description_parts.append(f"{len(contradictions)} contradictions detected")
            context["contradictions"] = [s.get("payload", {}) for s in contradictions]

    # Check neural router status
    try:
        mem = get_memory()
        resp = await mem.get("/api/v1/engrams/router-status", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ready_for_training") and not data.get("model_loaded"):
                urgency = max(urgency, 0.3)
                description_parts.append("Neural router ready for training")
                context["router_status"] = data
    except Exception as e:
        log.debug("Failed to check router status: %s", e)

    if urgency == 0.0:
        return DriveResult(
            name="improve", priority=3, urgency=0.0,
            description="No improvement signals",
        )

    return DriveResult(
        name="improve",
        priority=3,
        urgency=round(urgency, 2),
        description="; ".join(description_parts),
        proposed_action="Investigate and resolve detected issues",
        context=context,
    )
