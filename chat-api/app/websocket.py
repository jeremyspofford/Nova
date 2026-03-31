"""
WebSocket handler — the user-facing real-time chat interface.

Protocol (JSON over WebSocket):
  Client → Server: {"type": "auth", "token": "sk-nova-..."}  (if REQUIRE_AUTH=true)
  Client → Server: {"type": "user", "content": "Hello!", "session_id": "optional-uuid"}
  Server → Client: {"type": "stream_chunk", "delta": "Hi", "session_id": "..."}
  Server → Client: {"type": "stream_end", "session_id": "..."}
  Server → Client: {"type": "error", "content": "...", "session_id": "..."}

session_id persists across reconnects — conversation continuity survives disconnects.
Auth: token can be passed as ?token= query param, or as the first message with type "auth".
When REQUIRE_AUTH=false (dev mode), auth is skipped entirely.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from nova_contracts import ChatMessageType

from app.config import settings
from app.queue import enqueue_message
from app.session import get_or_create_session

log = logging.getLogger(__name__)

# ── Connection limits ─────────────────────────────────────────────────────────
_conn_semaphore = asyncio.Semaphore(settings.ws_max_connections)
_ip_connections: dict[str, int] = defaultdict(int)


async def _validate_token(token: str) -> bool:
    """Validate an API key against the orchestrator's key lookup."""
    try:
        async with httpx.AsyncClient(base_url=settings.orchestrator_url, timeout=5.0) as client:
            resp = await client.get(
                "/api/v1/keys/validate",
                headers={"X-API-Key": token},
            )
            return resp.status_code == 200
    except Exception as e:
        log.warning("Token validation failed: %s", e)
        return False


async def _authenticate(websocket: WebSocket) -> bool:
    """Authenticate the WebSocket connection. Returns True if auth succeeds or is not required."""
    if not settings.require_auth:
        return True

    # Check query param first: ws://host/ws/chat?token=sk-nova-...
    token = websocket.query_params.get("token")
    if token:
        if await _validate_token(token):
            return True
        await websocket.send_json({
            "type": ChatMessageType.error,
            "content": "Authentication failed — invalid token",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return False

    # Wait for first message to be an auth message
    try:
        raw = await websocket.receive_text()
        msg = json.loads(raw)
        if msg.get("type") == "auth" and msg.get("token"):
            if await _validate_token(msg["token"]):
                return True
            await websocket.send_json({
                "type": ChatMessageType.error,
                "content": "Authentication failed — invalid token",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return False
    except Exception as e:
        log.warning("Auth message parse/validation failed: %s", e)

    await websocket.send_json({
        "type": ChatMessageType.error,
        "content": "Authentication required — send token as ?token= query param or {type: 'auth', token: '...'}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return False


async def handle_websocket(websocket: WebSocket):
    client_ip = websocket.client.host if websocket.client else "unknown"

    # Per-IP connection limit
    if _ip_connections[client_ip] >= settings.ws_max_per_ip:
        await websocket.close(code=4008, reason="Too many connections from this IP")
        log.warning("WebSocket rejected: IP %s exceeded per-IP limit (%d)", client_ip, settings.ws_max_per_ip)
        return

    # Global connection limit (non-blocking check)
    if _conn_semaphore._value == 0:  # noqa: SLF001
        await websocket.close(code=4008, reason="Server connection limit reached")
        log.warning("WebSocket rejected: global connection limit reached (%d)", settings.ws_max_connections)
        return

    async with _conn_semaphore:
        _ip_connections[client_ip] += 1
        try:
            await _handle_websocket_inner(websocket, client_ip)
        finally:
            _ip_connections[client_ip] -= 1
            if _ip_connections[client_ip] <= 0:
                del _ip_connections[client_ip]


async def _handle_websocket_inner(websocket: WebSocket, client_ip: str):
    await websocket.accept()
    log.info("WebSocket connection accepted from %s", websocket.client)

    # Authenticate before processing messages
    if not await _authenticate(websocket):
        log.warning("WebSocket auth failed from %s", websocket.client)
        await websocket.close(code=4001, reason="Authentication required")
        return

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
                    "content": "Session started",
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            conversation_history.append({"role": "user", "content": user_content})

            # Cap conversation history to prevent unbounded memory growth
            if len(conversation_history) > settings.ws_max_history:
                conversation_history = conversation_history[-settings.ws_max_history:]

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
                        raw = line[6:]
                        if not raw:
                            continue
                        # Unwrap JSON-encoded text deltas {"t": "..."}
                        # and skip status/meta events (not relevant for WS clients)
                        delta = raw
                        if raw.startswith("{"):
                            try:
                                parsed = json.loads(raw)
                                if isinstance(parsed, dict):
                                    if "t" in parsed:
                                        delta = parsed["t"]
                                    elif "status" in parsed or "meta" in parsed:
                                        continue
                            except (json.JSONDecodeError, KeyError):
                                pass
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
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        # Orchestrator unreachable — queue the message for later
        log.warning("Orchestrator unreachable, queuing message for session %s: %s", session_id, e)
        position = await enqueue_message(session_id, agent_id, conversation_history)
        try:
            await websocket.send_json({
                "type": "queued",
                "position": position,
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
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
