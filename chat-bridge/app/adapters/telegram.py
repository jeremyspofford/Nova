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
