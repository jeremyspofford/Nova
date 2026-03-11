"""
Engram Network contracts — the graph memory API contract.

Engrams are atomic units of memory in a self-organizing neural graph.
This module defines the types used for ingestion, storage, and querying.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EngramType(str, Enum):
    fact = "fact"
    episode = "episode"
    entity = "entity"
    preference = "preference"
    procedure = "procedure"
    schema_ = "schema"
    goal = "goal"
    self_model = "self_model"


class EdgeRelation(str, Enum):
    caused_by = "caused_by"
    related_to = "related_to"
    contradicts = "contradicts"
    preceded = "preceded"
    enables = "enables"
    part_of = "part_of"
    instance_of = "instance_of"
    analogous_to = "analogous_to"


class IngestionSourceType(str, Enum):
    chat = "chat"
    pipeline = "pipeline"
    tool = "tool"
    consolidation = "consolidation"
    cortex = "cortex"
    journal = "journal"
    external = "external"
    self_reflection = "self_reflection"


# ── Queue payload ────────────────────────────────────────────────────────────


class IngestionEvent(BaseModel):
    """Payload pushed to the engram:ingestion:queue Redis list."""
    raw_text: str
    source_type: IngestionSourceType = IngestionSourceType.chat
    source_id: UUID | None = None
    session_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Decomposition output (structured LLM response) ──────────────────────────


class DecomposedEngram(BaseModel):
    """A single engram extracted by the decomposition LLM."""
    type: EngramType
    content: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    entities_referenced: list[str] = Field(default_factory=list)
    temporal: dict[str, Any] = Field(default_factory=dict)


class DecomposedRelationship(BaseModel):
    """A relationship between two engrams in the decomposition output."""
    from_index: int
    to_index: int
    relation: EdgeRelation
    strength: float = Field(default=0.5, ge=0.0, le=1.0)


class DecomposedContradiction(BaseModel):
    """A contradiction detected between a new engram and an existing one."""
    new_index: int
    existing_content_hint: str


class DecompositionResult(BaseModel):
    """Full structured output from the decomposition LLM."""
    engrams: list[DecomposedEngram] = Field(default_factory=list)
    relationships: list[DecomposedRelationship] = Field(default_factory=list)
    contradictions: list[DecomposedContradiction] = Field(default_factory=list)


# ── API request/response models ─────────────────────────────────────────────


class IngestRequest(BaseModel):
    """Direct ingestion request (bypasses queue)."""
    raw_text: str
    source_type: IngestionSourceType = IngestionSourceType.chat
    source_id: UUID | None = None
    session_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    engrams_created: int
    engrams_updated: int
    edges_created: int
    engram_ids: list[UUID]


class EngramDetail(BaseModel):
    """Full engram detail for API responses."""
    id: UUID
    type: EngramType
    content: str
    importance: float
    activation: float
    confidence: float
    access_count: int
    source_type: IngestionSourceType
    source_id: UUID | None = None
    superseded: bool = False
    created_at: datetime
    updated_at: datetime
