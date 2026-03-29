"""Bridge core — routes platform messages through orchestrator's unified chat endpoint."""

import logging
import httpx

from .config import settings

logger = logging.getLogger(__name__)


def _service_headers():
    """Headers for service-to-service auth with orchestrator."""
    return {"X-Service-Secret": settings.bridge_service_secret}


def _impersonation_headers(user_id: str):
    """Headers to call chat/stream on behalf of a user."""
    return {
        "X-Service-Secret": settings.bridge_service_secret,
        "X-On-Behalf-Of": user_id,
        "Content-Type": "application/json",
    }


async def resolve_user(platform: str, platform_id: str) -> dict | None:
    """Resolve a platform identity to a Nova user. Returns user_id, conversation_id, display_name."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{settings.orchestrator_url}/api/v1/linked-accounts/resolve",
            json={"platform": platform, "platform_id": str(platform_id)},
            headers=_service_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def try_auto_link(platform: str, platform_id: str,
                        platform_username: str | None = None) -> dict | None:
    """Attempt auto-link for first user. Returns link info or None."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{settings.orchestrator_url}/api/v1/linked-accounts/auto-link",
            json={
                "platform": platform,
                "platform_id": str(platform_id),
                "platform_username": platform_username,
            },
            headers=_service_headers(),
        )
        if r.status_code == 409:
            return None
        if r.status_code >= 400:
            return None
        return r.json()


async def redeem_link_code(code: str, platform: str, platform_id: str,
                           platform_username: str | None = None) -> dict | None:
    """Redeem a link code. Returns link info or None if invalid."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{settings.orchestrator_url}/api/v1/linked-accounts/redeem",
            json={
                "code": code.strip().upper(),
                "platform": platform,
                "platform_id": str(platform_id),
                "platform_username": platform_username,
            },
            headers=_service_headers(),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def send_message(user_id: str, conversation_id: str, text: str,
                       channel: str = "telegram") -> str:
    """Send a message through orchestrator's chat stream endpoint. Returns full response text."""
    import json as json_mod
    payload = {
        "messages": [{"role": "user", "content": text}],
        "conversation_id": conversation_id,
        "metadata": {"channel": channel},
    }
    full_response = []

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{settings.orchestrator_url}/api/v1/chat/stream",
            json=payload,
            headers=_impersonation_headers(user_id),
        ) as response:
            if response.status_code == 409:
                return "Nova is currently thinking. Try again in a moment."
            if response.status_code >= 400:
                logger.error("Chat stream error: %s", response.status_code)
                return "Sorry, I encountered an error. Please try again."

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    parsed = json_mod.loads(data)
                    if "t" in parsed:
                        full_response.append(parsed["t"])
                except (json_mod.JSONDecodeError, KeyError):
                    continue

    return "".join(full_response) or "I had nothing to say."


def chunk_message(text: str, max_length: int = 4096) -> list[str]:
    """Split a long message into chunks at paragraph boundaries for Telegram."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) + 2 > max_length:
            chunks.append(current.strip())
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph

    if current.strip():
        chunks.append(current.strip())

    # Safety: if any chunk is still too long, hard-split
    final = []
    for chunk in chunks:
        while len(chunk) > max_length:
            final.append(chunk[:max_length])
            chunk = chunk[max_length:]
        if chunk:
            final.append(chunk)

    return final
