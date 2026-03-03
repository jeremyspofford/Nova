"""Shared test fixtures for orchestrator tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest


@pytest.fixture
def mock_pool():
    """Mock asyncpg connection pool with acquire() context manager."""
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.fixture
def mock_redis():
    """Mock async Redis client."""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis


SAMPLE_TASK_ID = UUID("00000000-0000-0000-0000-000000000001")
SAMPLE_AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")
