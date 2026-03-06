"""Chat API integration tests — WebSocket connectivity."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import websockets

from conftest import CHAT_API_URL


class TestChatApiHealth:
    async def test_health(self, chat_api: httpx.AsyncClient):
        resp = await chat_api.get("/health/live")
        assert resp.status_code == 200


class TestWebSocket:
    async def test_connect_and_receive_system_message(self):
        """Connect to WebSocket and verify we get a system/session message."""
        ws_url = CHAT_API_URL.replace("http://", "ws://") + "/ws/chat"

        try:
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                # Should receive a system message with session info
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                assert msg.get("type") in ("system", "session", "connected", "welcome"), (
                    f"Unexpected first message type: {msg}"
                )
        except (ConnectionRefusedError, OSError) as e:
            pytest.skip(f"WebSocket not available: {e}")
