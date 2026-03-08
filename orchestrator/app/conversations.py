"""Conversation and message CRUD — raw asyncpg queries."""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from app.db import get_pool

log = logging.getLogger(__name__)


def _conv_dict(row) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["user_id"] = str(d["user_id"])
    return d


def _msg_dict(row) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["conversation_id"] = str(d["conversation_id"])
    return d


async def create_conversation(user_id: str, title: str | None = None) -> dict[str, Any]:
    pool = get_pool()
    uid = UUID(user_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (user_id, title)
            VALUES ($1, $2)
            RETURNING id, user_id, title, created_at, updated_at, last_message_at, is_archived
            """,
            uid, title,
        )
    return _conv_dict(row)


async def list_conversations(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    pool = get_pool()
    uid = UUID(user_id)
    archive_clause = "" if include_archived else "AND NOT is_archived"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, user_id, title, created_at, updated_at, last_message_at, is_archived
            FROM conversations
            WHERE user_id = $1 {archive_clause}
            ORDER BY last_message_at DESC NULLS LAST, created_at DESC
            LIMIT $2 OFFSET $3
            """,
            uid, limit, offset,
        )
    return [_conv_dict(r) for r in rows]


async def get_conversation(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    cid, uid = UUID(conversation_id), UUID(user_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, title, created_at, updated_at, last_message_at, is_archived
            FROM conversations WHERE id = $1 AND user_id = $2
            """,
            cid, uid,
        )
    return _conv_dict(row) if row else None


async def update_conversation(
    conversation_id: str, user_id: str, **fields
) -> dict[str, Any] | None:
    allowed = {"title", "is_archived"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return await get_conversation(conversation_id, user_id)

    cid, uid = UUID(conversation_id), UUID(user_id)
    set_clause = ", ".join(f"{k} = ${i+3}" for i, k in enumerate(updates))
    values = [cid, uid] + list(updates.values())

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE conversations SET {set_clause}, updated_at = NOW()
            WHERE id = $1 AND user_id = $2
            RETURNING id, user_id, title, created_at, updated_at, last_message_at, is_archived
            """,
            *values,
        )
    return _conv_dict(row) if row else None


async def delete_conversation(conversation_id: str, user_id: str) -> bool:
    pool = get_pool()
    cid, uid = UUID(conversation_id), UUID(user_id)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM conversations WHERE id = $1 AND user_id = $2",
            cid, uid,
        )
    return result == "DELETE 1"


async def add_message(
    conversation_id: str,
    role: str,
    content: str,
    model_used: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    pool = get_pool()
    cid = UUID(conversation_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO messages (conversation_id, role, content, model_used, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING id, conversation_id, role, content, model_used, metadata, created_at
            """,
            cid, role, content, model_used, json.dumps(metadata or {}),
        )
        await conn.execute(
            "UPDATE conversations SET last_message_at = NOW(), updated_at = NOW() WHERE id = $1",
            cid,
        )
    return _msg_dict(row)


async def get_messages(
    conversation_id: str,
    user_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    pool = get_pool()
    cid, uid = UUID(conversation_id), UUID(user_id)
    async with pool.acquire() as conn:
        # Verify ownership
        owner = await conn.fetchval(
            "SELECT user_id FROM conversations WHERE id = $1", cid
        )
        if owner is None or str(owner) != str(uid):
            return []
        rows = await conn.fetch(
            """
            SELECT id, conversation_id, role, content, model_used, metadata, created_at
            FROM messages WHERE conversation_id = $1
            ORDER BY created_at ASC
            LIMIT $2 OFFSET $3
            """,
            cid, limit, offset,
        )
    return [_msg_dict(r) for r in rows]


async def import_messages(
    conversation_id: str,
    user_id: str,
    messages: list[dict],
) -> int:
    """Bulk import messages (for localStorage migration). Returns count imported."""
    pool = get_pool()
    cid, uid = UUID(conversation_id), UUID(user_id)
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT user_id FROM conversations WHERE id = $1", cid
        )
        if owner is None or str(owner) != str(uid):
            return 0

        count = 0
        for msg in messages:
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, model_used, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                """,
                cid,
                msg["role"],
                msg["content"],
                msg.get("model_used"),
                json.dumps(msg.get("metadata", {})),
                msg.get("created_at"),
            )
            count += 1

        if count > 0:
            await conn.execute(
                "UPDATE conversations SET last_message_at = NOW(), updated_at = NOW() WHERE id = $1",
                cid,
            )
    return count


async def generate_title(conversation_id: str, first_message: str) -> str | None:
    """Fire-and-forget: ask LLM to generate a short title for a conversation."""
    try:
        from app.clients import get_llm_client
        from app.config import settings

        client = get_llm_client()
        resp = await client.post(
            "/complete",
            json={
                "model": settings.session_summary_model,
                "messages": [
                    {"role": "system", "content": "Generate a concise title (5 words max) for this conversation. Return ONLY the title text, no quotes or punctuation."},
                    {"role": "user", "content": first_message[:500]},
                ],
                "max_tokens": 20,
            },
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            title = data.get("content", "").strip().strip('"').strip("'")
            if title:
                pool = get_pool()
                cid = UUID(conversation_id)
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE conversations SET title = $1, updated_at = NOW() WHERE id = $2",
                        title[:100], cid,
                    )
                return title
    except Exception as e:
        log.warning("Failed to generate conversation title: %s", e)
    return None
