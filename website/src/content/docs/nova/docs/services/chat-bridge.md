---
title: "Chat Bridge"
description: "Multi-platform chat integration service. Port 8090."
---

The Chat Bridge connects Nova to external messaging platforms like Telegram and Slack. It runs as a single service with pluggable platform adapters that auto-enable based on which bot tokens are configured.

## Overview

| Property | Value |
|----------|-------|
| **Port** | 8090 |
| **Framework** | FastAPI |
| **State store** | Redis (db 4) |
| **Source** | `chat-bridge/` |
| **Profile** | `bridges` (opt-in) |

## Key responsibilities

- **Platform adapters** -- connect to messaging platforms via their native APIs (polling or webhooks)
- **Session mapping** -- map platform-specific chat IDs to Nova agent sessions, persisted in Redis with a 7-day TTL
- **Orchestrator streaming** -- send user messages to the Orchestrator's streaming endpoint and collect the full response
- **Auto-enable** -- adapters activate automatically when their required tokens are present in the environment

## Supported platforms

| Platform | Status | Required config |
|----------|--------|----------------|
| **Telegram** | Implemented | `TELEGRAM_BOT_TOKEN` |
| **Slack** | Planned | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |

## Enabling the service

The chat-bridge runs under a Docker Compose profile and does not start by default:

```bash
docker compose --profile bridges up -d
```

To include it alongside the full stack:

```bash
docker compose --profile bridges up -d --build
```

## Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe (checks Orchestrator connectivity and adapter status) |
| GET | `/api/status` | Reports which adapters are configured |
| POST | `/webhook/telegram` | Telegram webhook receiver (only registered when webhook mode is active) |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ORCHESTRATOR_URL` | URL of the Orchestrator service | `http://orchestrator:8000` |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/4` |
| `NOVA_API_KEY` | API key for authenticating with the Orchestrator | (empty) |
| `DEFAULT_AGENT_NAME` | Display name for bridge-created agents | `Nova` |
| `DEFAULT_MODEL` | Model to use for bridge sessions | `auto` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token from BotFather | (empty) |
| `TELEGRAM_WEBHOOK_URL` | Public URL for webhook mode; omit to use polling | (empty) |
| `SLACK_BOT_TOKEN` | Slack bot token (Phase 2) | (empty) |
| `SLACK_APP_TOKEN` | Slack app-level token (Phase 2) | (empty) |
| `SERVICE_PORT` | Port to listen on | `8090` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `REQUIRE_AUTH` | Whether to require auth for API calls | `true` |

## Adapter architecture

Each platform adapter implements the `PlatformAdapter` base class:

```python
class PlatformAdapter(ABC):
    platform_name: str          # e.g. "telegram"
    def is_configured() -> bool  # check if required tokens are set
    async def setup(app)         # register routes or start polling
    async def shutdown()         # clean up connections
```

At startup, the bridge iterates over all registered adapters. Any adapter whose `is_configured()` returns `True` gets activated. Adapters with missing tokens are silently skipped, so a single deployment can serve multiple platforms by simply adding tokens to the environment.

## Telegram setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram and create a new bot with `/newbot`
2. Copy the bot token and add it to your `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   ```
3. Start the bridge: `docker compose --profile bridges up -d`

### Polling vs webhook mode

By default the Telegram adapter uses **long polling** -- it connects outbound to the Telegram API and pulls updates. This works behind NAT and firewalls with no additional setup.

For production with a public URL, set `TELEGRAM_WEBHOOK_URL` to enable **webhook mode**. The bridge registers a POST endpoint at `/webhook/telegram` and tells Telegram to push updates there:

```
TELEGRAM_WEBHOOK_URL=https://your-domain.com
```

### Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with available commands |
| `/new` | Start a fresh conversation (resets the session) |
| `/status` | Check connection status |

Any other text message is forwarded to Nova as a chat message. Responses are returned with Markdown formatting when supported.

## Redis session mapping

Sessions are stored in Redis db 4 with the key pattern:

```
nova:bridge:{platform}:{platform_id}
```

For example, a Telegram chat with ID `12345` maps to `nova:bridge:telegram:12345`. Each key stores a JSON object with `session_id` and `agent_id`, and expires after 7 days of inactivity. The `/new` command deletes the key, forcing a fresh agent on the next message.

## Implementation notes

- **Fault-tolerant** -- adapter startup failures are caught and logged; other adapters continue to run
- **Streaming collection** -- the bridge consumes the Orchestrator's SSE stream and collects the full response before replying (messaging platforms expect complete messages)
- **Markdown fallback** -- Telegram replies attempt Markdown formatting first, falling back to plain text if parsing fails
- **Typing indicators** -- the Telegram adapter sends a typing action while waiting for the Orchestrator response
