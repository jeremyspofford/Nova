"""Tests for reaper race condition fix — UPDATE RETURNING guards."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest


TASK_UUID = UUID("00000000-0000-0000-0000-000000000001")


def _make_task_row(retry_count=0, max_retries=2, status="context_running"):
    """Create a mock asyncpg Record-like object."""
    row = {
        "id": TASK_UUID,
        "status": status,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "checkpoint": {},
    }
    return MagicMock(**{k: row[k] for k in row}, __getitem__=lambda self, k: row[k])


async def test_requeue_when_update_succeeds():
    """When UPDATE RETURNING returns a row, the task is enqueued to Redis."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_make_task_row(retry_count=0, max_retries=2)])
    conn.fetchval = AsyncMock(return_value=TASK_UUID)  # UPDATE RETURNING succeeds
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_enqueue = AsyncMock()

    with (
        patch("app.reaper.get_pool", return_value=pool),
        patch("app.reaper.enqueue_task", mock_enqueue),
        patch("app.reaper.move_to_dead_letter", AsyncMock()),
        patch("app.reaper.load_checkpoint", AsyncMock()),
    ):
        from app.reaper import _reap_stale_running_tasks
        await _reap_stale_running_tasks()

    mock_enqueue.assert_called_once_with(str(TASK_UUID))


async def test_skip_requeue_when_update_returns_none():
    """When UPDATE RETURNING returns None (another process won), skip enqueue."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_make_task_row(retry_count=0, max_retries=2)])
    conn.fetchval = AsyncMock(return_value=None)  # Another process won the race
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_enqueue = AsyncMock()

    with (
        patch("app.reaper.get_pool", return_value=pool),
        patch("app.reaper.enqueue_task", mock_enqueue),
        patch("app.reaper.move_to_dead_letter", AsyncMock()),
        patch("app.reaper.load_checkpoint", AsyncMock()),
    ):
        from app.reaper import _reap_stale_running_tasks
        await _reap_stale_running_tasks()

    mock_enqueue.assert_not_called()


async def test_exhausted_retries_moves_to_dead_letter():
    """When retry_count >= max_retries, task is failed + dead-lettered."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_make_task_row(retry_count=2, max_retries=2)])
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_dead_letter = AsyncMock()

    with (
        patch("app.reaper.get_pool", return_value=pool),
        patch("app.reaper.enqueue_task", AsyncMock()),
        patch("app.reaper.move_to_dead_letter", mock_dead_letter),
        patch("app.reaper.load_checkpoint", AsyncMock()),
    ):
        from app.reaper import _reap_stale_running_tasks
        await _reap_stale_running_tasks()

    mock_dead_letter.assert_called_once_with(
        str(TASK_UUID), reason="heartbeat_timeout_max_retries"
    )


async def test_stuck_queued_skips_if_no_longer_queued():
    """If a stuck queued task is no longer queued by the time we check, skip it."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[MagicMock(
        **{"__getitem__": lambda self, k: TASK_UUID if k == "id" else None, "id": TASK_UUID}
    )])
    conn.fetchval = AsyncMock(return_value=None)  # No longer queued

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_enqueue = AsyncMock()

    with (
        patch("app.reaper.get_pool", return_value=pool),
        patch("app.reaper.enqueue_task", mock_enqueue),
    ):
        from app.reaper import _reap_stuck_queued_tasks
        await _reap_stuck_queued_tasks()

    mock_enqueue.assert_not_called()
