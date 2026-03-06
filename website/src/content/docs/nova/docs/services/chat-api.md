---
title: "Chat API"
description: "WebSocket streaming bridge for external clients. Port 8080."
---

The Chat API is a lightweight WebSocket bridge that connects external clients to Nova's Orchestrator. It provides a real-time streaming chat interface with automatic session management and reconnection handling.

## Overview

| Property | Value |
|----------|-------|
| **Port** | 8080 |
| **Framework** | FastAPI |
| **State store** | Redis (db 3) |
| **Source** | `chat-api/` |

## Key responsibilities

- **WebSocket bridge** -- accept client WebSocket connections and forward messages to the Orchestrator's streaming endpoint
- **Session management** -- assign session IDs to track conversation continuity across reconnections
- **Stream relay** -- receive SSE chunks from the Orchestrator and relay them as WebSocket messages to the client
- **Test UI** -- serve a built-in browser-based chat interface at the root URL for quick testing

## WebSocket protocol

### Connection

Connect to `ws://localhost:8080/ws/chat`. If authentication is enabled, pass the API key as a query parameter:

```
ws://localhost:8080/ws/chat?token=sk-nova-...
```

### Message types

**Client to server:**

```json
{
  "type": "user",
  "content": "Your message here",
  "session_id": "optional-session-id"
}
```

**Server to client:**

| Type | Description | Fields |
|------|-------------|--------|
| `system` | Connection established | `session_id` |
| `stream_chunk` | Streaming response fragment | `delta` |
| `stream_end` | Response complete | -- |
| `error` | Error occurred | `content` |

### Authentication errors

If authentication is required and the token is invalid, the WebSocket closes with code `4001`. The client should prompt for credentials and reconnect.

## Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| WebSocket | `/ws/chat` | Streaming chat connection |
| GET | `/` | Built-in test chat UI (HTML) |
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe (checks Orchestrator connectivity) |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ORCHESTRATOR_URL` | URL of the Orchestrator service | `http://orchestrator:8000` |
| `SERVICE_PORT` | Port to listen on | `8080` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed origins | `*` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Test UI

The Chat API includes a built-in browser chat interface at `http://localhost:8080/`. It features:

- Real-time streaming with a typing cursor animation
- Markdown rendering (code blocks, tables, lists, headings)
- Session persistence across page reloads
- API key input for authenticated instances
- Auto-reconnect on connection loss
- Nova's stone/teal design theme

This test UI is useful for verifying that the full pipeline works end-to-end without needing the dashboard.

## Implementation notes

- **Minimal service** -- the Chat API is intentionally thin; all business logic lives in the Orchestrator
- **Readiness check** -- the `/health/ready` endpoint pings the Orchestrator to verify upstream connectivity
- **CORS** -- configured with `allow_credentials=True` to support cross-origin WebSocket connections
- **No database** -- the Chat API has no direct database dependency; all state flows through the Orchestrator and Redis
