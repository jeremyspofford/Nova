"""
Shared audit log writer — single source of truth for the audit_log INSERT.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

log = logging.getLogger(__name__)


async def write_audit_log(
    conn: asyncpg.Connection,
    *,
    event_type: str,
    severity: str = "info",
    task_id: str | None = None,
    agent_session_id: str | None = None,
    message: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Insert a row into audit_log. Fire-and-forget safe — logs on error, never raises."""
    try:
        await conn.execute(
            """
            INSERT INTO audit_log
                (event_type, severity, task_id, agent_session_id, message, data)
            VALUES ($1, $2, $3::uuid, $4::uuid, $5, $6::jsonb)
            """,
            event_type,
            severity,
            task_id,
            agent_session_id,
            message or event_type,
            json.dumps(data or {}),
        )
    except Exception:
        log.warning("Failed to write audit log: %s", event_type, exc_info=True)
