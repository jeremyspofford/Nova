"""
REL-001: reaper must force-fail stuck *_running tasks instead of looping
on a rejected task_running -> queued transition.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import pytest
import pytest_asyncio

from conftest import ORCHESTRATOR_URL, ADMIN_SECRET

# Derive PG DSN from .env (loaded by conftest via dotenv).
import os
PG_DSN = os.getenv(
    "NOVA_PG_DSN",
    "postgresql://nova:nova_dev_password@localhost:5432/nova",
)


@pytest_asyncio.fixture
async def pg_pool():
    """asyncpg pool for direct DB manipulation in tests."""
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def stuck_task(pg_pool):
    """Insert a task directly in 'task_running' state with an expired heartbeat."""
    task_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tasks (id, user_input, status, last_heartbeat_at, retry_count, max_retries)
            VALUES ($1, 'nova-test-reaper-stale', 'task_running', $2, 0, 3)
            """,
            task_id,
            datetime.now(timezone.utc) - timedelta(seconds=3600),  # 1h stale
        )
    yield task_id
    async with pg_pool.acquire() as conn:
        # Delete even if still present (e.g. test failed before reaper ran)
        await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)


@pytest.mark.asyncio
async def test_reaper_fails_stale_running_task(pg_pool, stuck_task):
    """After one reaper cycle, the stale task should be in 'failed' state."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{ORCHESTRATOR_URL}/api/v1/admin/reaper/tick",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
    assert resp.status_code == 200, f"Admin tick returned {resp.status_code}: {resp.text}"

    # Verify DB state
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, error FROM tasks WHERE id = $1", stuck_task,
        )
    assert row is not None, "Test task disappeared"
    assert row["status"] == "failed", (
        f"Expected status=failed after reaper tick, got {row['status']}. "
        f"Error column: {row['error']}"
    )
    assert row["error"] is not None and "reaped" in row["error"].lower(), (
        f"Expected 'reaped' in error column, got: {row['error']}"
    )
