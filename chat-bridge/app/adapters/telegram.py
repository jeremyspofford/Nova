"""
Telegram adapter — receives messages via bot polling or webhook,
sends them through the Nova unified bridge, and replies with the response.
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
from app import bridge
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
        self._app.add_handler(CommandHandler("link", self._cmd_link))
        self._app.add_handler(CommandHandler("unlink", self._cmd_unlink))
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
            "Welcome to Nova!\n\n"
            "Commands:\n"
            "/link <code> — Connect your Nova account\n"
            "/unlink — Disconnect your Telegram from Nova\n"
            "/status — Check connection status\n\n"
            "If this is your first time, just send a message and Nova will connect automatically."
        )

    async def _cmd_link(self, update: Update, context) -> None:
        chat_id = str(update.effective_chat.id)
        username = update.effective_user.username if update.effective_user else None
        text = update.message.text or ""

        # Extract code: "/link ABC123" → "ABC123"
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await update.message.reply_text(
                "Usage: /link <code>\n\nGenerate a link code from the Nova dashboard under Settings > Chat Integrations."
            )
            return

        code = parts[1].strip()

        try:
            result = await bridge.redeem_link_code(code, "telegram", chat_id, username)
        except Exception as e:
            log.error("Error redeeming link code for chat_id=%s: %s", chat_id, e, exc_info=True)
            await update.message.reply_text("Something went wrong. Please try again.")
            return

        if result:
            await update.message.reply_text("Linked to Nova! You can start chatting.")
        else:
            await update.message.reply_text(
                "Invalid or expired code. Generate a new one from the Nova dashboard."
            )

    async def _cmd_unlink(self, update: Update, context) -> None:
        await update.message.reply_text(
            "To unlink your account, visit Settings > Chat Integrations in the Nova dashboard."
        )

    async def _cmd_status(self, update: Update, context) -> None:
        chat_id = str(update.effective_chat.id)

        try:
            user_info = await bridge.resolve_user("telegram", chat_id)
        except Exception as e:
            log.error("Error resolving user for status chat_id=%s: %s", chat_id, e, exc_info=True)
            await update.message.reply_text("Could not check status. Please try again.")
            return

        if user_info:
            display_name = user_info.get("display_name", "your Nova account")
            await update.message.reply_text(f"Connected to Nova as {display_name}.")
        else:
            await update.message.reply_text(
                "Not connected. Send /link <code> or just send a message to connect."
            )

    # ── Message handler ───────────────────────────────────────────────

    async def _handle_message(self, update: Update, context) -> None:
        if not update.message or not update.message.text:
            return

        chat_id = str(update.effective_chat.id)
        username = update.effective_user.username if update.effective_user else None
        user_text = update.message.text

        # Show typing indicator while processing
        await update.effective_chat.send_action(ChatAction.TYPING)

        try:
            # Resolve platform identity to Nova user
            user_info = await bridge.resolve_user("telegram", chat_id)

            if not user_info:
                # Attempt auto-link (succeeds only for the first user / single-user installs)
                auto_result = await bridge.try_auto_link("telegram", chat_id, username)
                if auto_result:
                    user_info = await bridge.resolve_user("telegram", chat_id)

            if not user_info:
                await update.message.reply_text(
                    "I don't recognize your account. Send /link <code> to connect your Nova account."
                )
                return

            user_id = user_info["user_id"]
            conversation_id = user_info["conversation_id"]

            response = await bridge.send_message(
                user_id, conversation_id, user_text, channel="telegram"
            )

            chunks = bridge.chunk_message(response)
            for chunk in chunks:
                try:
                    await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await update.message.reply_text(chunk)

        except Exception as e:
            log.error("Error handling Telegram message: %s", e, exc_info=True)
            await update.message.reply_text("Sorry, something went wrong. Please try again.")
