"""Learn drive — build knowledge. Stub for now."""
from __future__ import annotations

from . import DriveResult


async def assess() -> DriveResult:
    return DriveResult(
        name="learn", priority=4, urgency=0.0,
        description="No learning signals (stub)",
    )
