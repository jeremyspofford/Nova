"""Tests for API key authentication and rate limiting."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.auth import AuthenticatedKey, _apply_rate_limit, require_admin, require_api_key


def _mock_request(*, trusted: bool = False):
    """Build a minimal Request-like mock.

    require_api_key and require_admin only read request.state.is_trusted_network
    and request.client.host from the Request object. This mock satisfies both.
    """
    req = MagicMock()
    req.state.is_trusted_network = trusted
    req.client = None  # keep hostname path off; auth code handles None
    return req


# ── require_api_key ──────────────────────────────────────────────────────────

async def test_dev_bypass_when_auth_disabled():
    """When REQUIRE_AUTH=false (DB config), returns synthetic bypass key without checking header."""
    with patch("app.auth._get_require_auth", new_callable=AsyncMock, return_value=False):
        key = await require_api_key(request=_mock_request(), x_api_key=None)
        assert isinstance(key, AuthenticatedKey)
        assert key.name == "dev-bypass"
        assert key.id is None


async def test_trusted_network_bypass():
    """Requests from a trusted network return a synthetic trusted-network key without hitting DB."""
    key = await require_api_key(request=_mock_request(trusted=True), x_api_key=None)
    assert isinstance(key, AuthenticatedKey)
    assert key.name == "trusted-network"


async def test_missing_key_raises_401():
    """When auth required and no key provided, raises 401."""
    with patch("app.auth._get_require_auth", new_callable=AsyncMock, return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request=_mock_request(), x_api_key=None)
        assert exc_info.value.status_code == 401


async def test_invalid_key_raises_401():
    """When auth required and key not found in DB, raises 401."""
    with (
        patch("app.auth._get_require_auth", new_callable=AsyncMock, return_value=True),
        patch("app.auth.lookup_api_key", new_callable=AsyncMock, return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request=_mock_request(), x_api_key="sk-nova-bad")
        assert exc_info.value.status_code == 401


async def test_valid_key_returns_authenticated():
    """Valid key returns AuthenticatedKey with correct fields."""
    fake_row = {
        "id": UUID("00000000-0000-0000-0000-000000000099"),
        "name": "test-key",
        "rate_limit_rpm": 100,
    }
    with (
        patch("app.auth._get_require_auth", new_callable=AsyncMock, return_value=True),
        patch("app.auth.lookup_api_key", new_callable=AsyncMock, return_value=fake_row),
        patch("app.auth._apply_rate_limit", new_callable=AsyncMock),
        patch("app.auth.touch_api_key", new_callable=AsyncMock),
    ):
        key = await require_api_key(request=_mock_request(), x_api_key="sk-nova-valid")
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
    """Valid admin secret passes through (no HTTPException raised)."""
    with patch("app.auth.get_admin_secret", new_callable=AsyncMock, return_value="correct-secret"):
        await require_admin(request=_mock_request(), x_admin_secret="correct-secret")


async def test_admin_invalid_secret():
    """Invalid admin secret raises 403."""
    with patch("app.auth.get_admin_secret", new_callable=AsyncMock, return_value="correct-secret"):
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(request=_mock_request(), x_admin_secret="wrong-secret")
        assert exc_info.value.status_code == 403


async def test_admin_trusted_network_bypass():
    """Admin requests from trusted network skip the secret check entirely."""
    # No patch on get_admin_secret — if it's called, the test will fail via AsyncMock default
    await require_admin(request=_mock_request(trusted=True), x_admin_secret=None)
