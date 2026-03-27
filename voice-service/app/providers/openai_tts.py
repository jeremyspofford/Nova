"""OpenAI TTS provider."""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from .base import TTSProvider

log = logging.getLogger(__name__)

OPENAI_VOICES = [
    {"id": "alloy", "name": "Alloy"},
    {"id": "echo", "name": "Echo"},
    {"id": "fable", "name": "Fable"},
    {"id": "onyx", "name": "Onyx"},
    {"id": "nova", "name": "Nova"},
    {"id": "shimmer", "name": "Shimmer"},
]


class OpenAITTS(TTSProvider):
    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    async def synthesize(self, text: str, voice: str, model: str) -> bytes:
        response = await self._client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        return response.content

    def available_voices(self) -> list[dict]:
        return OPENAI_VOICES
