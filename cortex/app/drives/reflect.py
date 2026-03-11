"""Reflect drive — learn from experience. Stub for now."""
from __future__ import annotations

from . import DriveResult


async def assess() -> DriveResult:
    return DriveResult(
        name="reflect", priority=5, urgency=0.0,
        description="No reflection signals (stub)",
    )
