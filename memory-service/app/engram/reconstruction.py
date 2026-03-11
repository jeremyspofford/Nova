"""
Memory reconstruction engine — Phase 2 of the Engram Network.

Assembles coherent memories from activated engram fragments. Two modes:
  - Template assembly (fast, no LLM, default)
  - Narrative reconstruction (LLM-powered, for dense clusters)

Reconstruction is ephemeral — the output is injected into the prompt
but never stored back to the graph. The engram fragments remain the
source of truth.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .activation import ActivatedEngram

log = logging.getLogger(__name__)

# Edge relation → natural language connector
RELATION_CONNECTORS = {
    "caused_by": "because",
    "preceded": "before that",
    "enables": "which enables",
    "part_of": "as part of",
    "instance_of": "as an example of",
    "contradicts": "however",
    "related_to": "also",
    "analogous_to": "similarly",
}


async def reconstruct(
    session: AsyncSession,
    activated: list[ActivatedEngram],
    context: str = "",
    self_model_summary: str = "",
) -> str:
    """Reconstruct coherent memory text from activated engrams.

    Uses template assembly for small sets, narrative reconstruction for
    dense clusters (>threshold interconnected engrams).
    """
    if not activated:
        return ""

    # Find clusters of interconnected engrams
    clusters = await _find_clusters(session, activated)

    parts: list[str] = []
    for cluster in clusters:
        if len(cluster) >= settings.engram_narrative_cluster_threshold:
            # Dense cluster → narrative reconstruction via LLM
            narrative = await _narrative_reconstruct(cluster, context, self_model_summary)
            if narrative:
                parts.append(narrative)
                continue

        # Sparse cluster or narrative failed → template assembly
        assembled = _template_assemble(cluster)
        if assembled:
            parts.append(assembled)

    return "\n\n".join(parts)


async def _find_clusters(
    session: AsyncSession,
    activated: list[ActivatedEngram],
) -> list[list[ActivatedEngram]]:
    """Group activated engrams into connected clusters using their edges.

    Returns list of clusters, each a list of ActivatedEngrams.
    Isolated engrams form singleton clusters.
    """
    if not activated:
        return []

    ids = [a.id for a in activated]
    id_to_engram = {a.id: a for a in activated}

    # Fetch edges between activated engrams
    result = await session.execute(
        text("""
            SELECT source_id::text, target_id::text, relation, weight
            FROM engram_edges
            WHERE source_id = ANY(CAST(:ids AS uuid[]))
              AND target_id = ANY(CAST(:ids AS uuid[]))
        """),
        {"ids": ids},
    )
    edges = result.fetchall()

    # Union-Find for clustering
    parent: dict[str, str] = {id: id for id in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for edge in edges:
        src, tgt = str(edge.source_id), str(edge.target_id)
        if src in id_to_engram and tgt in id_to_engram:
            union(src, tgt)

    # Group by cluster root
    groups: dict[str, list[ActivatedEngram]] = defaultdict(list)
    for id in ids:
        root = find(id)
        groups[root].append(id_to_engram[id])

    # Sort clusters by max activation (most relevant first)
    clusters = sorted(
        groups.values(),
        key=lambda c: max(e.final_score for e in c),
        reverse=True,
    )
    return clusters


def _template_assemble(cluster: list[ActivatedEngram]) -> str:
    """Fast template-based assembly. No LLM call.

    Groups by type, orders by activation, uses first-person perspective.
    """
    if not cluster:
        return ""

    # Sort by activation (most relevant first)
    ordered = sorted(cluster, key=lambda e: e.final_score, reverse=True)

    # Group by type for structured output
    by_type: dict[str, list[ActivatedEngram]] = defaultdict(list)
    for engram in ordered:
        by_type[engram.type].append(engram)

    lines: list[str] = []

    # Facts first
    if "fact" in by_type:
        for e in by_type["fact"]:
            lines.append(f"- {e.content}")

    # Preferences
    if "preference" in by_type:
        for e in by_type["preference"]:
            lines.append(f"- {e.content}")

    # Episodes (with temporal framing)
    if "episode" in by_type:
        for e in by_type["episode"]:
            lines.append(f"- {e.content}")

    # Procedures
    if "procedure" in by_type:
        for e in by_type["procedure"]:
            lines.append(f"- {e.content}")

    # Schemas (generalized patterns)
    if "schema" in by_type:
        for e in by_type["schema"]:
            lines.append(f"- Pattern: {e.content}")

    # Entities (brief mentions)
    if "entity" in by_type:
        entity_names = [e.content for e in by_type["entity"][:5]]
        if entity_names:
            lines.append(f"- Related: {', '.join(entity_names)}")

    # Goals
    if "goal" in by_type:
        for e in by_type["goal"]:
            lines.append(f"- Goal: {e.content}")

    # Self-model entries
    if "self_model" in by_type:
        for e in by_type["self_model"]:
            lines.append(f"- {e.content}")

    return "\n".join(lines)


async def _narrative_reconstruct(
    cluster: list[ActivatedEngram],
    context: str,
    self_model_summary: str,
) -> str:
    """LLM-powered narrative reconstruction for dense clusters.

    Produces first-person, context-sensitive memory narrative.
    """
    engram_text = "\n".join(
        f"- [{e.type}] {e.content} (importance: {e.importance:.1f})"
        for e in sorted(cluster, key=lambda e: e.final_score, reverse=True)
    )

    system = (
        "You are Nova, reconstructing a memory from fragments. "
        "Speak in first person. Be concise — 2-4 sentences. "
        "Emphasize what's most relevant to the current context."
    )
    if self_model_summary:
        system += f"\n\nYour identity: {self_model_summary}"

    user_prompt = f"Current context: {context}\n\nMemory fragments:\n{engram_text}"

    try:
        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=30.0) as client:
            resp = await client.post(
                "/complete",
                json={
                    "model": settings.engram_reconstruction_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 500,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", "")
            if isinstance(content, list):
                content = content[0].get("text", "") if content else ""
            return content.strip()
    except Exception:
        log.warning("Narrative reconstruction failed, falling back to template", exc_info=True)
        return ""


async def get_self_model_summary(session: AsyncSession) -> str:
    """Retrieve a concise summary of Nova's self-model engrams."""
    result = await session.execute(
        text("""
            SELECT content FROM engrams
            WHERE type = 'self_model'
              AND NOT superseded
            ORDER BY importance DESC, activation DESC
            LIMIT 10
        """)
    )
    rows = result.fetchall()
    if not rows:
        return "I am Nova, a helpful AI assistant with persistent memory."

    return " ".join(row.content for row in rows)
