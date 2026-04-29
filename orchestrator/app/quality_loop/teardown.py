"""Delete benchmark-tagged engrams after a run completes.

Without this, every benchmark pollutes the user's main memory store
with cases like "The user's favorite programming language is Rust" —
permanent test garbage tagged [benchmark:abc12345].

Memory-service DELETE endpoint: DELETE /api/v1/engrams/{engram_id} → 204
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

MEMORY_SERVICE = "http://memory-service:8002"


async def teardown_benchmark_engrams(engram_ids: list[str]) -> int:
    """Delete the listed engrams. Returns count of successful deletes.

    Continues on individual failures — partial cleanup is better than
    aborting on the first error.
    """
    if not engram_ids:
        return 0
    deleted = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for eid in engram_ids:
            try:
                r = await client.delete(f"{MEMORY_SERVICE}/api/v1/engrams/{eid}")
                if 200 <= r.status_code < 300:
                    deleted += 1
                else:
                    log.warning(
                        "teardown: failed to delete engram %s: status=%s",
                        eid, r.status_code,
                    )
            except Exception as e:
                log.warning("teardown: exception deleting engram %s: %s", eid, e)
    return deleted
