"""Improve drive — make Nova's code better. Stub for now."""
from __future__ import annotations

from . import DriveResult


async def assess() -> DriveResult:
    return DriveResult(
        name="improve", priority=3, urgency=0.0,
        description="No improvement signals (stub)",
    )
