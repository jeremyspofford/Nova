"""Maintain drive — keep Nova healthy.

Urgency is based on:
- Service health check results
- Error rates (future)
- Backup freshness (future)
"""
from __future__ import annotations

import logging

from ..clients import get_orchestrator, get_llm, get_memory
from . import DriveResult

log = logging.getLogger(__name__)

SERVICES = [
    ("orchestrator", get_orchestrator),
    ("llm_gateway", get_llm),
    ("memory_service", get_memory),
]


async def assess() -> DriveResult:
    """Assess maintain drive urgency based on service health."""
    checks: dict[str, str] = {}

    for name, get_client in SERVICES:
        try:
            client = get_client()
            resp = await client.get("/health/live", timeout=5.0)
            checks[name] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            checks[name] = f"error: {type(e).__name__}"

    degraded = [name for name, status in checks.items() if status != "ok"]

    if not degraded:
        return DriveResult(
            name="maintain", priority=2, urgency=0.0,
            description="All services healthy",
            context={"checks": checks},
        )

    urgency = min(1.0, len(degraded) / len(SERVICES) + 0.3)

    return DriveResult(
        name="maintain",
        priority=2,
        urgency=round(urgency, 2),
        description=f"Degraded: {', '.join(degraded)}",
        proposed_action=f"Investigate {degraded[0]} health issue",
        context={"checks": checks, "degraded": degraded},
    )
