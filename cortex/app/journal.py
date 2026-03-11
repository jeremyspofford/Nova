"""Cortex journal — narrates thinking to a reserved conversation."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from .config import settings
from .db import get_pool

log = logging.getLogger(__name__)

JOURNAL_ID = UUID(settings.journal_conversation_id)
CORTEX_USER_ID = UUID(settings.cortex_user_id)


async def write_entry(
    content: str,
    entry_type: str = "narration",
    metadata: dict | None = None,
) -> UUID:
    """Write a journal entry to the Cortex conversation.

    entry_type: narration | progress | completion | question | escalation | reflection
    """
    meta = {
        "type": entry_type,
        "source": "cortex",
        **(metadata or {}),
    }
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO messages (conversation_id, role, content, metadata)
            VALUES ($1, 'assistant', $2, $3::jsonb)
            RETURNING id
            """,
            JOURNAL_ID,
            content,
            meta,
        )
        await conn.execute(
            "UPDATE conversations SET last_message_at = NOW(), updated_at = NOW() WHERE id = $1",
            JOURNAL_ID,
        )
    msg_id = row["id"]
    log.debug("Journal entry [%s]: %s", entry_type, content[:80])
    return msg_id


async def read_recent(limit: int = 20) -> list[dict]:
    """Read recent journal entries, newest first."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, role, content, metadata, created_at
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            JOURNAL_ID,
            limit,
        )
    return [
        {
            "id": str(r["id"]),
            "role": r["role"],
            "content": r["content"],
            "metadata": r["metadata"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def read_user_replies_since(since: datetime) -> list[dict]:
    """Read user replies to the journal since a given time.

    These are messages from the human directing Cortex behavior.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, metadata, created_at
            FROM messages
            WHERE conversation_id = $1 AND role = 'user' AND created_at > $2
            ORDER BY created_at
            """,
            JOURNAL_ID,
            since,
        )
    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "metadata": r["metadata"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
