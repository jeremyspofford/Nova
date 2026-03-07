"""
Session summarization — generates concise summaries of idle chat sessions.

Provides:
- summarize_session()  — summarize a single session via LLM, store as semantic memory
- session_summary_sweep() — background loop that finds idle sessions and summarizes them
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from app.clients import get_llm_client, get_memory_client
from app.config import settings

log = logging.getLogger(__name__)

SUMMARY_PROMPT = (
    "Summarize this conversation in 2-4 sentences. Capture:\n"
    "- What the user wanted to accomplish\n"
    "- Key decisions made or information exchanged\n"
    "- Any unresolved questions or next steps\n\n"
    "Be factual and specific. Use names, technical terms, and details from the conversation."
)

# Background sweep interval
_SWEEP_INTERVAL_SECONDS = 600  # 10 minutes


async def summarize_session(
    session_id: str,
    messages: list[dict],
    agent_id: str,
) -> str | None:
    """Summarize a conversation session and store the result as semantic memory.

    Args:
        session_id: The session identifier.
        messages: List of dicts with ``role`` and ``content`` keys.
        agent_id: The agent that owns this session.

    Returns:
        The summary text on success, or ``None`` if skipped/failed.
    """
    if len(messages) < 2:
        log.debug("Skipping summary for session %s — fewer than 2 messages", session_id)
        return None

    try:
        # Build the conversation text for the LLM
        conversation = "\n".join(
            f"{msg['role'].capitalize()}: {msg['content']}" for msg in messages
        )

        llm = get_llm_client()
        resp = await llm.post(
            "/complete",
            json={
                "model": settings.session_summary_model,
                "messages": [
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": conversation},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("content", "")
        if isinstance(content, list):
            content = content[0].get("text", "") if content else ""
        summary = content.strip()

        if not summary:
            log.warning("Empty summary returned for session %s", session_id)
            return None

        # Store as semantic memory
        mem = get_memory_client()
        store_resp = await mem.post(
            "/api/v1/memories/facts",
            json={
                "agent_id": agent_id,
                "project_id": agent_id,
                "category": "conversation_summary",
                "key": session_id,
                "content": summary,
                "base_confidence": 0.9,
                "metadata": {
                    "source": "session_summary",
                    "message_count": len(messages),
                    "session_id": session_id,
                },
            },
        )
        store_resp.raise_for_status()

        log.info(
            "Summarized session %s (%d messages) for agent %s",
            session_id, len(messages), agent_id,
        )
        return summary

    except Exception:
        log.exception("Failed to summarize session %s", session_id)
        return None


async def session_summary_sweep() -> None:
    """Background loop: find idle sessions and summarize them.

    Runs every 10 minutes. A session is eligible when it has been idle
    longer than ``settings.session_summary_timeout_seconds`` and does not
    already have a summary stored.
    """
    log.info(
        "Session summary sweep started (interval=%ds, idle_threshold=%ds)",
        _SWEEP_INTERVAL_SECONDS,
        settings.session_summary_timeout_seconds,
    )

    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
            await _run_sweep()
        except asyncio.CancelledError:
            log.info("Session summary sweep shutting down")
            break
        except Exception:
            log.exception("Session summary sweep error — will retry next interval")


async def _run_sweep() -> None:
    """Single sweep cycle: browse episodic memories, group by session, summarize idle ones."""
    mem = get_memory_client()

    # Fetch recent episodic memories
    resp = await mem.get(
        "/api/v1/memories/browse",
        params={"tier": "episodic", "limit": 200},
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

    if not items:
        return

    # Group episodes by (agent_id, session_id)
    sessions: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in items:
        sid = (item.get("metadata") or {}).get("session_id")
        aid = item.get("agent_id")
        if sid and aid:
            sessions[(aid, sid)].append(item)

    now = datetime.now(timezone.utc)
    summarized = 0

    for (agent_id, session_id), episodes in sessions.items():
        try:
            # Check if the session is still active (most recent message too recent)
            latest = max(
                (ep.get("created_at", "") for ep in episodes),
                default="",
            )
            if latest:
                # Parse ISO timestamp
                ts = latest.replace("Z", "+00:00")
                last_activity = datetime.fromisoformat(ts)
                idle_seconds = (now - last_activity).total_seconds()
                if idle_seconds < settings.session_summary_timeout_seconds:
                    continue

            # Check if summary already exists
            if await _summary_exists(agent_id, session_id):
                continue

            # Reconstruct messages from episodic content
            # Sort by created_at to maintain conversation order
            episodes.sort(key=lambda e: e.get("created_at", ""))
            messages = []
            for ep in episodes:
                raw = ep.get("content", "")
                role, content = _parse_episodic_content(raw)
                messages.append({"role": role, "content": content})

            result = await summarize_session(session_id, messages, agent_id)
            if result:
                summarized += 1

        except Exception:
            log.exception(
                "Failed to process session %s for agent %s during sweep",
                session_id, agent_id,
            )

    if summarized:
        log.info("Session summary sweep completed: %d sessions summarized", summarized)


async def _summary_exists(agent_id: str, session_id: str) -> bool:
    """Check whether a summary already exists for this session."""
    try:
        mem = get_memory_client()
        resp = await mem.post(
            "/api/v1/memories/search",
            json={
                "agent_id": agent_id,
                "query": f"conversation_summary {session_id}",
                "tiers": ["semantic"],
                "limit": 1,
                "metadata_filter": {
                    "category": "conversation_summary",
                    "session_id": session_id,
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", data.get("items", []))
        return len(results) > 0
    except Exception:
        log.warning("Could not check for existing summary of session %s", session_id)
        # If we can't check, skip to avoid duplicates
        return True


def _parse_episodic_content(raw: str) -> tuple[str, str]:
    """Strip 'User: ' or 'Assistant: ' prefix from episodic memory content.

    Returns (role, content) tuple.
    """
    if raw.startswith("User: "):
        return "user", raw[6:]
    if raw.startswith("Assistant: "):
        return "assistant", raw[11:]
    # Fallback — treat as user message
    return "user", raw
