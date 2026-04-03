"""
Memory Provider Interface contracts — the abstract contract for any memory system.

Any service implementing endpoints that accept/return these types
is a valid drop-in memory provider for Nova's orchestrator.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Context retrieval ────────────────────────────────────────────────────────


class ContextRequest(BaseModel):
    """Request to retrieve relevant context for a query."""
    query: str
    session_id: str = ""
    current_turn: int = 0
    depth: str = "standard"  # shallow, standard, deep
    query_embedding: list[float] | None = None  # Optional pre-computed embedding for fair benchmarking
    max_results: int = 20


class ContextResponse(BaseModel):
    """Response from a memory provider's context retrieval."""
    context: str  # Formatted text ready for LLM injection
    total_tokens: int
    engram_ids: list[str] = Field(default_factory=list)  # Provider-specific item IDs
    retrieval_log_id: str | None = None  # For feedback loop
    metadata: dict[str, Any] = Field(default_factory=dict)  # Provider-specific data


# ── Ingestion ────────────────────────────────────────────────────────────────


class MemoryIngestRequest(BaseModel):
    """Request to store new information in the memory system."""
    raw_text: str
    source_type: str = "chat"
    source_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryIngestResponse(BaseModel):
    """Response from memory ingestion."""
    items_created: int
    items_updated: int
    item_ids: list[str] = Field(default_factory=list)


# ── Feedback ─────────────────────────────────────────────────────────────────


class MarkUsedRequest(BaseModel):
    """Feedback on which retrieved items were actually used."""
    retrieval_log_id: str
    used_ids: list[str]
    session_id: str = ""


# ── Provider stats ───────────────────────────────────────────────────────────


class ProviderStats(BaseModel):
    """Health and metrics from a memory provider."""
    provider_name: str
    provider_version: str = "0.1.0"
    total_items: int = 0
    total_edges: int = 0  # 0 for non-graph providers
    last_ingestion: datetime | None = None
    capabilities: list[str] = Field(default_factory=list)  # e.g., ["graph_traversal", "consolidation", "neural_reranking"]
    metadata: dict[str, Any] = Field(default_factory=dict)
