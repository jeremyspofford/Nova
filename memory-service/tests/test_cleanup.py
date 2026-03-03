"""Tests for working memory cleanup job."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def test_delete_expired_runs_correct_query():
    """_delete_expired executes DELETE for rows past expires_at."""
    mock_result = MagicMock()
    mock_result.rowcount = 3

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    # Mock the context manager
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("app.cleanup.AsyncSessionLocal", mock_session_factory):
        from app.cleanup import _delete_expired
        deleted = await _delete_expired()

    assert deleted == 3
    mock_session.execute.assert_called_once()
    # Verify the SQL contains the right WHERE clause
    sql_arg = mock_session.execute.call_args[0][0]
    assert "expires_at" in str(sql_arg)
    assert "DELETE" in str(sql_arg).upper()
    mock_session.commit.assert_called_once()


async def test_delete_expired_returns_zero_when_none():
    """When no rows expired, returns 0."""
    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("app.cleanup.AsyncSessionLocal", mock_session_factory):
        from app.cleanup import _delete_expired
        deleted = await _delete_expired()

    assert deleted == 0
