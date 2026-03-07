# Chat Bridge Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a `chat-bridge` service with platform adapter plugins, starting with Telegram, that lets users interact with Nova from external chat platforms.

**Architecture:** Single FastAPI service (port 8090, Redis db4) with a platform adapter pattern. Each adapter translates platform-specific events into Nova's message format, calls the orchestrator's streaming endpoint, and sends the response back formatted for the platform. Docker profile `bridges` for opt-in startup.

**Tech Stack:** Python 3.12, FastAPI, httpx, redis, python-telegram-bot, pydantic-settings, nova-contracts

---

### Task 1: Service Scaffold — pyproject.toml, Dockerfile, config

**Files:**
- Create: `chat-bridge/pyproject.toml`
- Create: `chat-bridge/app/__init__.py`
- Create: `chat-bridge/app/config.py`
- Create: `chat-bridge/Dockerfile`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "nova-chat-bridge"
version = "0.1.0"
description = "Nova Chat Bridge — multi-platform chat integration"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.27",
    "redis[hiredis]>=5.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "python-telegram-bot>=21.0",
    "nova-contracts",
]

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

**Step 2: Create config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    orchestrator_url: str = "http://orchestrator:8000"
    redis_url: str = "redis://redis:6379/4"

    # API key for authenticating with orchestrator
    nova_api_key: str = ""

    # Default agent settings for bridge sessions
    default_agent_name: str = "Nova"
    default_model: str = "auto"

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""  # If set, use webhook mode; otherwise polling

    # Slack (Phase 2)
    slack_bot_token: str = ""
    slack_app_token: str = ""

    service_host: str = "0.0.0.0"
    service_port: int = 8090
    log_level: str = "INFO"

    require_auth: bool = True


settings = Settings()
```

**Step 3: Create empty `__init__.py`**

```python
```

**Step 4: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY nova-contracts /nova-contracts
RUN pip install --no-cache-dir /nova-contracts

COPY chat-bridge/pyproject.toml .
RUN pip install --no-cache-dir .

COPY chat-bridge/app/ app/

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
```

**Step 5: Commit**

```bash
git add chat-bridge/
git commit -m "feat(chat-bridge): scaffold service with config and Dockerfile"
```

---

### Task 2: Core Bridge Logic — session mapping + orchestrator streaming

**Files:**
- Create: `chat-bridge/app/bridge.py`

This is the shared core that all adapters use. It handles:
1. Mapping platform IDs to Nova sessions (Redis)
2. Creating agents via the orchestrator
3. Sending messages and collecting streamed responses

**Step 1: Create bridge.py**

```python
"""
Core bridge logic — session mapping and orchestrator communication.
Shared by all platform adapters.
"""
from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
import redis.asyncio as aioredis

from app.config import settings

log = logging.getLogger(__name__)

SESSION_KEY = "nova:bridge:{platform}:{platform_id}"
SESSION_TTL = 60 * 60 * 24 * 7  # 7 days

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _auth_headers() -> dict[str, str]:
    """Headers for authenticating with the orchestrator."""
    headers = {}
    if settings.nova_api_key:
        headers["X-API-Key"] = settings.nova_api_key
    return headers


async def get_or_create_session(platform: str, platform_id: str) -> tuple[str, str]:
    """
    Returns (session_id, agent_id) for a platform-specific chat.
    Creates a new agent if no session exists.
    """
    r = get_redis()
    key = SESSION_KEY.format(platform=platform, platform_id=platform_id)

    # Check for existing session
    raw = await r.get(key)
    if raw:
        data = json.loads(raw)
        await r.expire(key, SESSION_TTL)
        return data["session_id"], data["agent_id"]

    # Create new agent via orchestrator
    session_id = str(uuid4())
    async with httpx.AsyncClient(
        base_url=settings.orchestrator_url, timeout=30.0
    ) as client:
        resp = await client.post(
            "/api/v1/agents",
            json={
                "config": {
                    "name": settings.default_agent_name,
                    "system_prompt": (
                        "You are a helpful AI assistant with persistent memory across conversations. "
                        "You are thoughtful, accurate, and concise. You remember what users tell you and "
                        "reference past context when relevant."
                    ),
                    "model": settings.default_model,
                }
            },
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        agent = resp.json()

    agent_id = agent["id"]
    await r.set(
        key,
        json.dumps({"session_id": session_id, "agent_id": agent_id}),
        ex=SESSION_TTL,
    )
    log.info("New session: %s/%s -> session=%s agent=%s", platform, platform_id, session_id, agent_id)
    return session_id, agent_id


async def reset_session(platform: str, platform_id: str) -> None:
    """Delete the session mapping, forcing a new agent on next message."""
    r = get_redis()
    key = SESSION_KEY.format(platform=platform, platform_id=platform_id)
    await r.delete(key)
    log.info("Reset session: %s/%s", platform, platform_id)


async def send_message(session_id: str, agent_id: str, text: str) -> str:
    """
    Send a message to the orchestrator's streaming endpoint.
    Collects the full response and returns it as a string.
    """
    messages = [{"role": "user", "content": text}]

    try:
        async with httpx.AsyncClient(
            base_url=settings.orchestrator_url, timeout=120.0
        ) as client:
            async with client.stream(
                "POST",
                "/api/v1/tasks/stream",
                json={
                    "agent_id": agent_id,
                    "messages": messages,
                    "session_id": session_id,
                },
                headers=_auth_headers(),
            ) as resp:
                resp.raise_for_status()
                parts: list[str] = []
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: "):
                        delta = line[6:]
                        # Check for error JSON
                        try:
                            parsed = json.loads(delta)
                            if "error" in parsed:
                                return f"Error: {parsed['error']}"
                        except (json.JSONDecodeError, TypeError):
                            pass
                        if delta:
                            parts.append(delta)
                return "".join(parts)

    except httpx.HTTPStatusError as e:
        log.error("Orchestrator HTTP error: %s", e.response.status_code)
        return f"Sorry, I encountered an error (HTTP {e.response.status_code}). Please try again."
    except Exception as e:
        log.error("Orchestrator error: %s", e)
        return "Sorry, I encountered an error. Please try again."
```

**Step 2: Commit**

```bash
git add chat-bridge/app/bridge.py
git commit -m "feat(chat-bridge): core bridge logic — session mapping + orchestrator streaming"
```

---

### Task 3: Adapter Base Class

**Files:**
- Create: `chat-bridge/app/adapters/__init__.py`
- Create: `chat-bridge/app/adapters/base.py`

**Step 1: Create the adapter interface**

`chat-bridge/app/adapters/__init__.py`:
```python
```

`chat-bridge/app/adapters/base.py`:
```python
"""Base class for platform adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import FastAPI


class PlatformAdapter(ABC):
    """
    Interface that each platform adapter implements.

    Lifecycle:
      1. __init__() — validate config (e.g. token present)
      2. setup(app) — register routes/start polling
      3. shutdown() — clean up connections
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Short identifier: 'telegram', 'slack', etc."""
        ...

    @abstractmethod
    async def setup(self, app: FastAPI) -> None:
        """Register webhook routes or start background polling."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources (stop polling, close connections)."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if this adapter has the required config (e.g. bot token)."""
        ...
```

**Step 2: Commit**

```bash
git add chat-bridge/app/adapters/
git commit -m "feat(chat-bridge): adapter base class interface"
```

---

### Task 4: Telegram Adapter

**Files:**
- Create: `chat-bridge/app/adapters/telegram.py`

This is the first real adapter. It uses `python-telegram-bot` to receive messages and send responses.

**Step 1: Create telegram.py**

```python
"""
Telegram adapter — receives messages via bot polling or webhook,
sends them through the Nova bridge, and replies with the response.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response
from telegram import Bot, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.adapters.base import PlatformAdapter
from app.bridge import get_or_create_session, reset_session, send_message
from app.config import settings

log = logging.getLogger(__name__)


def _escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    # Characters that need escaping in MarkdownV2
    special = r"_*[]()~`>#+-=|{}.!\\"
    result = []
    for char in text:
        if char in special:
            result.append(f"\\{char}")
        else:
            result.append(char)
    return "".join(result)


class TelegramAdapter(PlatformAdapter):
    platform_name = "telegram"

    def __init__(self) -> None:
        self._app: Application | None = None

    def is_configured(self) -> bool:
        return bool(settings.telegram_bot_token)

    async def setup(self, app: FastAPI) -> None:
        if not self.is_configured():
            return

        self._app = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("new", self._cmd_new))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        if settings.telegram_webhook_url:
            # Webhook mode — register a FastAPI route
            await self._app.initialize()
            bot: Bot = self._app.bot
            webhook_path = "/webhook/telegram"
            webhook_url = settings.telegram_webhook_url.rstrip("/") + webhook_path

            await bot.set_webhook(url=webhook_url)
            log.info("Telegram webhook set to %s", webhook_url)

            @app.post(webhook_path)
            async def telegram_webhook(request: Request) -> Response:
                data = await request.json()
                update = Update.de_json(data, bot)
                await self._app.process_update(update)
                return Response(status_code=200)
        else:
            # Polling mode — runs in background
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            log.info("Telegram polling started")

    async def shutdown(self) -> None:
        if self._app:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            log.info("Telegram adapter shut down")

    # ── Command handlers ──────────────────────────────────────────────

    async def _cmd_start(self, update: Update, context) -> None:
        await update.message.reply_text(
            "Hi! I'm Nova. Send me a message and I'll respond.\n\n"
            "Commands:\n"
            "/new - Start a new conversation\n"
            "/status - Check connection status"
        )

    async def _cmd_new(self, update: Update, context) -> None:
        chat_id = str(update.effective_chat.id)
        await reset_session("telegram", chat_id)
        await update.message.reply_text("New conversation started.")

    async def _cmd_status(self, update: Update, context) -> None:
        await update.message.reply_text("Connected and ready.")

    # ── Message handler ───────────────────────────────────────────────

    async def _handle_message(self, update: Update, context) -> None:
        if not update.message or not update.message.text:
            return

        chat_id = str(update.effective_chat.id)
        user_text = update.message.text

        # Show typing indicator
        await update.effective_chat.send_action(ChatAction.TYPING)

        try:
            session_id, agent_id = await get_or_create_session("telegram", chat_id)
            response = await send_message(session_id, agent_id, user_text)

            if response:
                # Try sending with markdown, fall back to plain text
                try:
                    await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await update.message.reply_text(response)
            else:
                await update.message.reply_text("I didn't get a response. Please try again.")

        except Exception as e:
            log.error("Error handling Telegram message: %s", e, exc_info=True)
            await update.message.reply_text("Sorry, something went wrong. Please try again.")
```

**Step 2: Commit**

```bash
git add chat-bridge/app/adapters/telegram.py
git commit -m "feat(chat-bridge): Telegram adapter with polling and webhook support"
```

---

### Task 5: FastAPI Main App — adapter registration + health endpoints

**Files:**
- Create: `chat-bridge/app/main.py`

**Step 1: Create main.py**

```python
"""Nova Chat Bridge — multi-platform chat integration."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nova_contracts.logging import configure_logging

from app.adapters.base import PlatformAdapter
from app.adapters.telegram import TelegramAdapter
from app.config import settings

configure_logging("chat-bridge", settings.log_level)
log = logging.getLogger(__name__)

# Registry of all platform adapters
ADAPTERS: list[PlatformAdapter] = [
    TelegramAdapter(),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    active = []
    for adapter in ADAPTERS:
        if adapter.is_configured():
            try:
                await adapter.setup(app)
                active.append(adapter.platform_name)
                log.info("Adapter enabled: %s", adapter.platform_name)
            except Exception as e:
                log.error("Failed to start adapter %s: %s", adapter.platform_name, e, exc_info=True)

    if not active:
        log.warning("No platform adapters configured. Set TELEGRAM_BOT_TOKEN or SLACK_BOT_TOKEN in .env")
    else:
        log.info("Chat bridge started with adapters: %s", ", ".join(active))

    yield

    for adapter in ADAPTERS:
        if adapter.is_configured():
            try:
                await adapter.shutdown()
            except Exception as e:
                log.error("Error shutting down adapter %s: %s", adapter.platform_name, e)
    log.info("Chat bridge shut down")


app = FastAPI(
    title="Nova Chat Bridge",
    version="0.1.0",
    description="Multi-platform chat integration for Nova",
    lifespan=lifespan,
)


@app.get("/health/live")
async def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness():
    import httpx
    checks: dict[str, str] = {}

    # Check orchestrator
    try:
        async with httpx.AsyncClient(base_url=settings.orchestrator_url, timeout=3.0) as c:
            r = await c.get("/health/ready")
            checks["orchestrator"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        checks["orchestrator"] = f"error: {e}"

    # Report active adapters
    for adapter in ADAPTERS:
        checks[f"adapter_{adapter.platform_name}"] = (
            "configured" if adapter.is_configured() else "not_configured"
        )

    all_ok = checks.get("orchestrator") == "ok"
    return {"status": "ready" if all_ok else "degraded", "checks": checks}


@app.get("/api/status")
async def adapter_status():
    """Status of all platform adapters — used by dashboard Settings UI."""
    return {
        "adapters": [
            {
                "platform": a.platform_name,
                "configured": a.is_configured(),
            }
            for a in ADAPTERS
        ]
    }
```

**Step 2: Commit**

```bash
git add chat-bridge/app/main.py
git commit -m "feat(chat-bridge): FastAPI app with adapter lifecycle and health endpoints"
```

---

### Task 6: Docker Compose Integration

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example` (if it exists, otherwise skip)

**Step 1: Add chat-bridge service to docker-compose.yml**

Add after the `chat-api` service block (after line 272). Find the `chat-api` healthcheck closing line and add after it:

```yaml
  chat-bridge:
    <<: *nova-common
    profiles: ["bridges"]
    build:
      context: .
      dockerfile: chat-bridge/Dockerfile
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--reload"]
    develop:
      watch:
        - action: sync
          path: ./chat-bridge/app
          target: /app/app
          ignore:
            - __pycache__
            - "*.pyc"
    environment:
      ORCHESTRATOR_URL: http://orchestrator:8000
      REDIS_URL: redis://redis:6379/4
      NOVA_API_KEY: ${NOVA_API_KEY:-}
      DEFAULT_MODEL: ${DEFAULT_CHAT_MODEL:-auto}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      REQUIRE_AUTH: ${REQUIRE_AUTH:-false}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:-}
      TELEGRAM_WEBHOOK_URL: ${TELEGRAM_WEBHOOK_URL:-}
      SLACK_BOT_TOKEN: ${SLACK_BOT_TOKEN:-}
      SLACK_APP_TOKEN: ${SLACK_APP_TOKEN:-}
    ports:
      - "8090:8090"
    depends_on:
      orchestrator:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      <<: *nova-healthcheck
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8090/health/live', timeout=3)"]
```

**Step 2: Add env vars to .env.example** (if the file exists)

Add these lines:

```bash
# ── Chat Bridge (optional, start with: docker compose --profile bridges up) ──
# TELEGRAM_BOT_TOKEN=          # Get from @BotFather on Telegram
# TELEGRAM_WEBHOOK_URL=        # Public URL for webhook mode (leave empty for polling)
# SLACK_BOT_TOKEN=             # Slack bot OAuth token (xoxb-...)
# SLACK_APP_TOKEN=             # Slack app-level token for Socket Mode (xapp-...)
```

**Step 3: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat(chat-bridge): Docker Compose integration with bridges profile"
```

---

### Task 7: Integration Test — Bridge Health + Telegram Smoke Test

**Files:**
- Create: `tests/test_chat_bridge.py`

Integration tests follow Nova's pattern: hit real running services over HTTP. These tests verify the bridge service starts and its health endpoints work. The Telegram adapter test is conditional on `TELEGRAM_BOT_TOKEN` being set.

**Step 1: Create the test file**

```python
"""
Integration tests for the chat-bridge service.

Requires: docker compose --profile bridges up
Tests are skipped if chat-bridge is not running.
"""
import os

import httpx
import pytest

BRIDGE_URL = os.getenv("CHAT_BRIDGE_URL", "http://localhost:8090")


async def _bridge_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{BRIDGE_URL}/health/live")
            return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def skip_if_unavailable():
    if not await _bridge_available():
        pytest.skip("chat-bridge not running")


@pytest.mark.asyncio
async def test_bridge_health_live():
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{BRIDGE_URL}/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_bridge_health_ready():
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{BRIDGE_URL}/health/ready")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ready", "degraded")
    assert "orchestrator" in data["checks"]


@pytest.mark.asyncio
async def test_bridge_adapter_status():
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{BRIDGE_URL}/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "adapters" in data
    platforms = [a["platform"] for a in data["adapters"]]
    assert "telegram" in platforms
```

**Step 2: Commit**

```bash
git add tests/test_chat_bridge.py
git commit -m "test(chat-bridge): integration tests for health and adapter status"
```

---

### Task 8: Update Roadmap + CLAUDE.md

**Files:**
- Modify: `docs/roadmap.md` — mark Phase 8b Telegram as in-progress
- Modify: `CLAUDE.md` — add chat-bridge to service list and port table

**Step 1: Update CLAUDE.md**

Add `chat-bridge` to the Architecture section's service list:
```
- **chat-bridge** (8090) — Multi-platform chat integration: Telegram, Slack (FastAPI + httpx + redis)
```

Add to the Inter-service communication notes:
```
Chat-bridge calls orchestrator (`/api/v1/tasks/stream`) to relay messages from external platforms.
```

Add to Redis DB allocation:
```
chat-bridge=db4
```

**Step 2: Update roadmap**

In Phase 8b, add a status marker showing Telegram is in progress. Find the Telegram line and add a status indicator.

**Step 3: Commit**

```bash
git add CLAUDE.md docs/roadmap.md
git commit -m "docs: add chat-bridge to architecture docs and mark roadmap progress"
```

---

### Task 9: Website Documentation

**Files:**
- Check: `website/src/content/docs/nova/docs/architecture.md` — add chat-bridge
- Check: `website/src/content/docs/nova/docs/services/` — consider new `chat-bridge.md`
- Check: `website/src/data/features.ts` — add multi-platform chat as a feature

This task is conditional — only update website docs if those files already exist and have content about the existing services. Follow the code-to-docs mapping in CLAUDE.md.

**Step 1: Update architecture docs with new service**

**Step 2: Commit**

```bash
git add website/
git commit -m "docs(website): add chat-bridge service documentation"
```

---

## Implementation Order

| Task | Description | Dependencies |
|------|-------------|--------------|
| 1 | Service scaffold (pyproject, Dockerfile, config) | None |
| 2 | Core bridge logic (session mapping, orchestrator calls) | Task 1 |
| 3 | Adapter base class | Task 1 |
| 4 | Telegram adapter | Tasks 2, 3 |
| 5 | FastAPI main app (adapter lifecycle, health) | Tasks 3, 4 |
| 6 | Docker Compose integration | Task 5 |
| 7 | Integration tests | Task 6 |
| 8 | Update CLAUDE.md + roadmap | Task 6 |
| 9 | Website documentation | Task 8 |

Tasks 2 and 3 can run in parallel (no dependencies on each other).
Tasks 8 and 9 can run in parallel.
