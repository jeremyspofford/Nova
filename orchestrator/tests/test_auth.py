"""Tests for API key authentication and rate limiting."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.auth import AuthenticatedKey, _apply_rate_limit, require_api_key, require_admin


# ── require_api_key ──────────────────────────────────────────────────────────

async def test_dev_bypass_when_auth_disabled():
    """When REQUIRE_AUTH=false, returns synthetic bypass key without checking header."""
    with patch("app.auth.settings") as mock_settings:
        mock_settings.require_auth = False
        key = await require_api_key(x_api_key=None)
        assert isinstance(key, AuthenticatedKey)
        assert key.name == "dev-bypass"
        assert key.id is None


async def test_missing_key_raises_401():
    """When auth required and no key provided, raises 401."""
    with patch("app.auth.settings") as mock_settings:
        mock_settings.require_auth = True
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(x_api_key=None)
        assert exc_info.value.status_code == 401


async def test_invalid_key_raises_401():
    """When auth required and key not found in DB, raises 401."""
    with (
        patch("app.auth.settings") as mock_settings,
        patch("app.auth.lookup_api_key", new_callable=AsyncMock, return_value=None),
    ):
        mock_settings.require_auth = True
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(x_api_key="sk-nova-bad")
        assert exc_info.value.status_code == 401


async def test_valid_key_returns_authenticated():
    """Valid key returns AuthenticatedKey with correct fields."""
    fake_row = {
        "id": UUID("00000000-0000-0000-0000-000000000099"),
        "name": "test-key",
        "rate_limit_rpm": 100,
    }
    with (
        patch("app.auth.settings") as mock_settings,
        patch("app.auth.lookup_api_key", new_callable=AsyncMock, return_value=fake_row),
        patch("app.auth._apply_rate_limit", new_callable=AsyncMock),
        patch("app.auth.touch_api_key", new_callable=AsyncMock),
    ):
        mock_settings.require_auth = True
        key = await require_api_key(x_api_key="sk-nova-valid")
        assert key.name == "test-key"
        assert key.id == fake_row["id"]


# ── Rate limiting ────────────────────────────────────────────────────────────

async def test_rate_limit_allows_under_threshold(mock_redis):
    """Requests under the RPM limit pass through."""
    mock_redis.incr.return_value = 5
    with patch("app.auth.get_redis", return_value=mock_redis):
        # Should not raise
        await _apply_rate_limit(
            api_key_id=UUID("00000000-0000-0000-0000-000000000001"),
            rate_limit_rpm=100,
        )


async def test_rate_limit_blocks_over_threshold(mock_redis):
    """Requests over the RPM limit raise 429."""
    mock_redis.incr.return_value = 101
    with patch("app.auth.get_redis", return_value=mock_redis):
        with pytest.raises(HTTPException) as exc_info:
            await _apply_rate_limit(
                api_key_id=UUID("00000000-0000-0000-0000-000000000001"),
                rate_limit_rpm=100,
            )
        assert exc_info.value.status_code == 429


# ── Admin auth ───────────────────────────────────────────────────────────────

async def test_admin_valid_secret():
    """Valid admin secret passes through."""
    with patch("app.auth.settings") as mock_settings:
        mock_settings.nova_admin_secret = "correct-secret"
        await require_admin(x_admin_secret="correct-secret")


async def test_admin_invalid_secret():
    """Invalid admin secret raises 403."""
    with patch("app.auth.settings") as mock_settings:
        mock_settings.nova_admin_secret = "correct-secret"
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(x_admin_secret="wrong-secret")
        assert exc_info.value.status_code == 403
