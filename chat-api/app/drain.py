"""
Background drain loop — processes queued messages when the orchestrator
comes back online.

Started as an asyncio task in the FastAPI lifespan.  Polls every 10s,
checks orchestrator health, and drains one message at a time.  If the
orchestrator becomes unreachable mid-drain, the current message is
re-queued and the loop backs off until the next poll.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from app.config import settings
from app.queue import dequeue_message, enqueue_message, queue_length

log = logging.getLogger(__name__)

POLL_INTERVAL = 10  # seconds


async def _orchestrator_healthy() -> bool:
    """Quick health probe — True only when orchestrator returns 200."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.orchestrator_url, timeout=5.0,
        ) as client:
            resp = await client.get("/health/ready")
            return resp.status_code == 200
    except Exception:
        return False


async def _forward_message(item: dict) -> bool:
    """
    Forward a queued message to the orchestrator.

    Returns True on success, False if the orchestrator is unreachable
    (connect error / timeout).  HTTP errors (5xx etc.) are treated as
    permanent failures — the message is discarded with a warning.
    """
    try:
        async with httpx.AsyncClient(
            base_url=settings.orchestrator_url, timeout=120.0,
        ) as client:
            resp = await client.post("/api/v1/tasks/stream", json={
                "agent_id": item["agent_id"],
                "messages": item["messages"],
                "session_id": item["session_id"],
            })
            resp.raise_for_status()
            return True
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return False
    except httpx.HTTPStatusError as exc:
        log.warning(
            "Orchestrator returned %d for queued message (session %s) — discarding",
            exc.response.status_code,
            item.get("session_id"),
        )
        return True  # Don't re-queue on HTTP errors — orchestrator is up but broken


async def drain_loop() -> None:
    """Poll forever, draining queued messages when the orchestrator is up."""
    log.info("Queue drain loop started (poll every %ds)", POLL_INTERVAL)
    try:
        while True:
            await asyncio.sleep(POLL_INTERVAL)

            depth = await queue_length()
            if depth == 0:
                continue

            if not await _orchestrator_healthy():
                log.debug("Orchestrator unreachable — skipping drain (%d queued)", depth)
                continue

            log.info("Draining %d queued message(s)", depth)
            while True:
                item = await dequeue_message()
                if item is None:
                    break

                ok = await _forward_message(item)
                if not ok:
                    # Orchestrator went away mid-drain — re-queue and stop
                    await enqueue_message(
                        item["session_id"],
                        item["agent_id"],
                        item["messages"],
                    )
                    remaining = await queue_length()
                    log.warning(
                        "Orchestrator became unreachable during drain — "
                        "re-queued message for session %s (%d remaining)",
                        item["session_id"],
                        remaining,
                    )
                    break

                remaining = await queue_length()
                log.info(
                    "Drained queued message for session %s (%d remaining)",
                    item["session_id"],
                    remaining,
                )

    except asyncio.CancelledError:
        log.info("Queue drain loop stopped")
