"""OpenAI Whisper STT provider."""
from __future__ import annotations

import io
import logging
import math

from openai import AsyncOpenAI

from .base import STTProvider, TranscriptResult

log = logging.getLogger(__name__)

FORMAT_TO_EXT = {
    "webm": "webm",
    "mp4": "mp4",
    "ogg": "ogg",
    "wav": "wav",
    "mpeg": "mp3",
    "m4a": "m4a",
}


class OpenAISTT(STTProvider):
    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    async def transcribe(
        self, audio: bytes, format: str = "webm", language: str | None = None
    ) -> TranscriptResult:
        ext = FORMAT_TO_EXT.get(format, "webm")
        audio_file = io.BytesIO(audio)
        audio_file.name = f"recording.{ext}"

        kwargs: dict = {
            "model": "whisper-1",
            "file": audio_file,
            "response_format": "verbose_json",
        }
        if language:
            kwargs["language"] = language

        response = await self._client.audio.transcriptions.create(**kwargs)

        # Estimate confidence from segment log probabilities
        confidence = 0.0
        segments = getattr(response, "segments", None)
        if segments:
            avg_logprob = sum(
                s.get("avg_logprob", -1) if isinstance(s, dict) else getattr(s, "avg_logprob", -1)
                for s in segments
            ) / len(segments)
            confidence = min(1.0, max(0.0, math.exp(avg_logprob)))

        duration_ms = int(getattr(response, "duration", 0) * 1000)

        return TranscriptResult(
            text=response.text.strip(),
            language=getattr(response, "language", "en"),
            duration_ms=duration_ms,
            confidence=confidence,
        )
