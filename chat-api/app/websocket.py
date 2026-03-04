"""
WebSocket handler — the user-facing real-time chat interface.

Protocol (JSON over WebSocket):
  Client → Server: {"type": "user", "content": "Hello!", "session_id": "optional-uuid"}
  Server → Client: {"type": "stream_chunk", "delta": "Hi", "session_id": "..."}
  Server → Client: {"type": "stream_end", "session_id": "..."}
  Server → Client: {"type": "error", "content": "...", "session_id": "..."}

session_id persists across reconnects — conversation continuity survives disconnects.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from nova_contracts import ChatMessageType

from app.config import settings
from app.session import get_or_create_session

log = logging.getLogger(__name__)


async def handle_websocket(websocket: WebSocket):
    await websocket.accept()
    log.info("WebSocket connection accepted from %s", websocket.client)

    session_id: str | None = None
    agent_id: str | None = None
    conversation_history: list[dict] = []

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, "Invalid JSON", session_id)
                continue

            if msg.get("type") != "user" or not msg.get("content"):
                await _send_error(websocket, "Expected {type: 'user', content: '...'}", session_id)
                continue

            user_content = msg["content"].strip()
            incoming_session = msg.get("session_id")

            # Resolve or create session on first message
            if session_id is None:
                session_id, agent_id = await get_or_create_session(incoming_session)
                # Send session_id back so client can persist it across reconnects
                await websocket.send_json({
                    "type": "system",
                    "content": f"Session started",
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            conversation_history.append({"role": "user", "content": user_content})

            # Stream response from Orchestrator
            full_response = await _stream_response(
                websocket=websocket,
                session_id=session_id,
                agent_id=agent_id,
                conversation_history=conversation_history,
            )

            if full_response:
                conversation_history.append({"role": "assistant", "content": full_response})

    except WebSocketDisconnect:
        log.info("WebSocket disconnected, session: %s", session_id)
    except Exception as e:
        log.error("WebSocket error: %s", e, exc_info=True)
        try:
            await _send_error(websocket, str(e), session_id)
        except Exception:
            pass


async def _stream_response(
    websocket: WebSocket,
    session_id: str,
    agent_id: str,
    conversation_history: list[dict],
) -> str:
    """Forward streaming response from Orchestrator to WebSocket client."""
    full_response_parts = []

    try:
        async with httpx.AsyncClient(base_url=settings.orchestrator_url, timeout=120.0) as client:
            async with client.stream("POST", "/api/v1/tasks/stream", json={
                "agent_id": agent_id,
                "messages": conversation_history,
                "session_id": session_id,
            }) as resp:
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line == "data: [DONE]":
                        await websocket.send_json({
                            "type": ChatMessageType.stream_end,
                            "session_id": session_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        break
                    if line.startswith("data: "):
                        delta = line[6:]
                        if delta:
                            full_response_parts.append(delta)
                            await websocket.send_json({
                                "type": ChatMessageType.stream_chunk,
                                "delta": delta,
                                "session_id": session_id,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })

    except httpx.HTTPStatusError as e:
        await _send_error(websocket, f"Orchestrator error: {e.response.status_code}", session_id)
    except Exception as e:
        await _send_error(websocket, f"Stream error: {e}", session_id)

    return "".join(full_response_parts)


async def _send_error(websocket: WebSocket, message: str, session_id: str | None):
    try:
        await websocket.send_json({
            "type": ChatMessageType.error,
            "content": message,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass
