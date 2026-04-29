"""Tests for the Quality drive — monitors AI quality, triggers loops on regressions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.drives.quality import assess


@pytest.mark.asyncio
async def test_low_composite_raises_urgency():
    """When the live summary shows low composite, urgency rises."""
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "period_days": 7,
        "composite": 60.0,
        "dimensions": {"memory_relevance": {"avg": 0.55, "count": 30, "trend": -0.1}},
    }
    with patch("app.drives.quality.get_orchestrator") as mock_orch:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_orch.return_value = mock_client
        result = await assess(ctx=None)
    assert result.urgency >= 0.3
    assert "composite" in result.description.lower() or "weak" in result.description.lower()


@pytest.mark.asyncio
async def test_healthy_composite_low_urgency():
    """When composite is healthy and dims are healthy, urgency is near 0."""
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "period_days": 7,
        "composite": 82.0,
        "dimensions": {"memory_relevance": {"avg": 0.85, "count": 100, "trend": 0.02}},
    }
    with patch("app.drives.quality.get_orchestrator") as mock_orch:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_orch.return_value = mock_client
        result = await assess(ctx=None)
    assert result.urgency < 0.3
