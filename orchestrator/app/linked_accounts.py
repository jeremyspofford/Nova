"""Linked account management — maps external platform identities to Nova users."""
from __future__ import annotations

import secrets
import string
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.db import get_pool
from app.store import get_redis

log = logging.getLogger(__name__)

LINK_CODE_TTL = 600  # 10 minutes
LINK_CODE_PREFIX = "nova:link:"


def _link_dict(row) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["user_id"] = str(d["user_id"])
    return d


async def resolve_platform_account(platform: str, platform_id: str) -> dict | None:
    """Look up a linked account by platform identity. Returns user_id + display_name."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT la.user_id, la.platform_username, u.display_name, u.email
            FROM linked_accounts la
            JOIN users u ON u.id = la.user_id
            WHERE la.platform = $1 AND la.platform_id = $2
            """,
            platform, platform_id
        )
    if not row:
        return None
    d = dict(row)
    d["user_id"] = str(d["user_id"])
    return d


async def get_active_conversation_for_user(user_id: str) -> dict[str, Any]:
    """Get the user's most recent conversation, or create one if none exists."""
    pool = get_pool()
    uid = UUID(user_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, created_at, last_message_at
            FROM conversations
            WHERE user_id = $1 AND is_archived = false
            ORDER BY last_message_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            uid
        )
        if row:
            d = dict(row)
            d["id"] = str(d["id"])
            return d
        # Create a new conversation
        new_row = await conn.fetchrow(
            """
            INSERT INTO conversations (user_id, title)
            VALUES ($1, NULL)
            RETURNING id, title, created_at, last_message_at
            """,
            uid
        )
    d = dict(new_row)
    d["id"] = str(d["id"])
    return d


async def auto_link(platform: str, platform_id: str, platform_username: str | None = None) -> dict | None:
    """Auto-link if exactly one user exists and no one is linked for this platform.
    Returns the linked account info, or None if conditions not met."""
    pool = get_pool()
    async with pool.acquire() as conn:
        user_count = await conn.fetchval("SELECT count(*) FROM users")
        if user_count != 1:
            return None
        link_count = await conn.fetchval(
            "SELECT count(*) FROM linked_accounts WHERE platform = $1", platform
        )
        if link_count > 0:
            return None
        user = await conn.fetchrow("SELECT id, display_name FROM users LIMIT 1")
    if not user:
        return None
    return await create_link(str(user["id"]), platform, platform_id, platform_username)


async def create_link(user_id: str, platform: str, platform_id: str,
                      platform_username: str | None = None) -> dict:
    """Create a linked account binding."""
    pool = get_pool()
    uid = UUID(user_id)
    link_id = uuid4()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO linked_accounts (id, user_id, platform, platform_id, platform_username, linked_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (platform, platform_id) DO UPDATE
                SET user_id = EXCLUDED.user_id,
                    platform_username = EXCLUDED.platform_username,
                    linked_at = EXCLUDED.linked_at
            """,
            link_id, uid, platform, platform_id, platform_username, now
        )
    return {
        "id": str(link_id), "user_id": user_id, "platform": platform,
        "platform_id": platform_id, "platform_username": platform_username,
        "linked_at": now.isoformat()
    }


async def list_links(user_id: str | None = None) -> list[dict]:
    """List linked accounts. If user_id provided, filter to that user."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if user_id:
            rows = await conn.fetch(
                """
                SELECT la.*, u.display_name, u.email FROM linked_accounts la
                JOIN users u ON u.id = la.user_id
                WHERE la.user_id = $1 ORDER BY la.linked_at DESC
                """,
                UUID(user_id)
            )
        else:
            rows = await conn.fetch(
                """
                SELECT la.*, u.display_name, u.email FROM linked_accounts la
                JOIN users u ON u.id = la.user_id
                ORDER BY la.linked_at DESC
                """
            )
    return [_link_dict(r) for r in rows]


async def delete_link(link_id: str) -> bool:
    """Remove a linked account binding."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM linked_accounts WHERE id = $1", UUID(link_id)
        )
    return result == "DELETE 1"


async def generate_link_code(user_id: str) -> str:
    """Generate a 6-char alphanumeric code mapped to a user_id, stored in Redis with TTL."""
    code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    r = get_redis()
    await r.set(f"{LINK_CODE_PREFIX}{code}", user_id, ex=LINK_CODE_TTL)
    return code


async def redeem_link_code(code: str, platform: str, platform_id: str,
                           platform_username: str | None = None) -> dict | None:
    """Validate a link code and create the binding. Returns link info or None if invalid."""
    r = get_redis()
    user_id = await r.get(f"{LINK_CODE_PREFIX}{code}")
    if not user_id:
        return None
    await r.delete(f"{LINK_CODE_PREFIX}{code}")
    return await create_link(user_id, platform, platform_id, platform_username)
