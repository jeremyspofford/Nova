"""
Chat API contracts — WebSocket message protocol.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChatMessageType(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"
    error = "error"
    stream_chunk = "stream_chunk"
    stream_end = "stream_end"


class ChatMessage(BaseModel):
    type: ChatMessageType
    content: str
    session_id: str
    agent_id: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamChunkMessage(BaseModel):
    type: ChatMessageType = ChatMessageType.stream_chunk
    session_id: str
    delta: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SessionInfo(BaseModel):
    session_id: str
    agent_id: str
    created_at: datetime
    message_count: int = 0
