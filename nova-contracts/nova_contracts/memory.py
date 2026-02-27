"""
Memory Service contracts — the API contract is the product.
Any implementation satisfying these models can replace the Memory Service.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoryTier(str, Enum):
    working = "working"       # Short-term, high-frequency, hot cache in Redis
    episodic = "episodic"     # Conversation history, time-partitioned by month
    semantic = "semantic"     # Extracted facts and relationships
    procedural = "procedural" # How-to knowledge, task patterns


class StoreMemoryRequest(BaseModel):
    agent_id: str
    content: str
    tier: MemoryTier = MemoryTier.episodic
    metadata: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int | None = None  # None = permanent


class StoreMemoryResponse(BaseModel):
    id: UUID
    agent_id: str
    tier: MemoryTier
    created_at: datetime


class SearchMemoryRequest(BaseModel):
    agent_id: str
    query: str
    tiers: list[MemoryTier] = Field(default_factory=lambda: [MemoryTier.episodic, MemoryTier.semantic])
    limit: int = Field(default=10, ge=1, le=100)
    # RRF weights — see Part 3: default 0.7 vector / 0.3 keyword for conversational
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    metadata_filter: dict[str, Any] = Field(default_factory=dict)


class MemoryResult(BaseModel):
    id: UUID
    content: str
    tier: MemoryTier
    score: float  # Combined RRF score
    metadata: dict[str, Any]
    created_at: datetime


class SearchMemoryResponse(BaseModel):
    results: list[MemoryResult]
    query: str
    total_found: int


class GetContextRequest(BaseModel):
    agent_id: str
    query: str
    # Token budget per tier — from Part 3: 40% of context for memory
    max_tokens: int = Field(default=4096)


class GetContextResponse(BaseModel):
    agent_id: str
    memories: list[MemoryResult]
    total_tokens_estimated: int
    assembled_at: datetime = Field(default_factory=datetime.utcnow)


class UpdateMemoryRequest(BaseModel):
    content: str | None = None
    metadata: dict[str, Any] | None = None


class BulkStoreRequest(BaseModel):
    memories: list[StoreMemoryRequest]


class BulkStoreResponse(BaseModel):
    stored: list[UUID]
    failed: list[int]  # indices of failed items
