"""Provider interfaces for STT and TTS."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranscriptResult:
    text: str
    language: str = "en"
    duration_ms: int = 0
    confidence: float = 0.0
    speaker_id: str | None = None  # v2: voiceprint match


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(
        self, audio: bytes, format: str = "webm", language: str | None = None
    ) -> TranscriptResult:
        """Transcribe audio to text. Format is MIME subtype (webm, mp4, ogg, wav)."""
        ...


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str, model: str) -> bytes:
        """Convert text to audio. Returns complete MP3 bytes."""
        ...

    def available_voices(self) -> list[dict]:
        """Return list of available voices for this provider."""
        return []
