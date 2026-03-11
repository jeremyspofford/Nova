"""
Engram decomposition pipeline — extracts structured engrams from raw text.

Uses a Haiku-class model with structured output to decompose conversation
turns into atomic memory nodes (engrams) with typed relationships.
"""
from __future__ import annotations

import json
import logging

import httpx
from nova_contracts.engram import DecompositionResult

from app.config import settings

log = logging.getLogger(__name__)

DECOMPOSITION_SYSTEM_PROMPT = """You are a memory decomposition agent. You break down conversation text into atomic memory units called engrams.

Return ONLY valid JSON matching this exact schema — no other text, no markdown fences:
{
  "engrams": [
    {
      "type": "fact|episode|entity|preference|procedure",
      "content": "concise statement capturing one atomic piece of information",
      "importance": 0.0-1.0,
      "entities_referenced": ["entity_name_1", "entity_name_2"],
      "temporal": {"when": "iso8601 or relative description"}
    }
  ],
  "relationships": [
    {
      "from_index": 0,
      "to_index": 1,
      "relation": "caused_by|related_to|preceded|enables|part_of|contradicts",
      "strength": 0.0-1.0
    }
  ],
  "contradictions": [
    {
      "new_index": 0,
      "existing_content_hint": "description of what this contradicts"
    }
  ]
}

Rules:
- Extract ONLY clear, factual information. Skip greetings, filler, and transient context.
- Each engram should be ONE atomic piece of information.
- Entity engrams are for people, places, tools, concepts that are referenced.
- Fact engrams are for objective knowledge claims.
- Episode engrams are for specific events with temporal context.
- Preference engrams are for expressed likes, dislikes, or choices.
- Procedure engrams are for how-to knowledge or step-by-step processes.
- importance: 0.1 = trivial, 0.5 = normal, 0.8 = significant, 1.0 = critical
- If the text contains little useful information, return {"engrams": [], "relationships": [], "contradictions": []}.
- entities_referenced should list entity names mentioned in the engram (for linking).
- contradictions.existing_content_hint: describe the prior belief this new info contradicts."""

DECOMPOSITION_USER_TEMPLATE = """Decompose this conversation exchange into atomic engrams:

{raw_text}"""


async def decompose(raw_text: str) -> DecompositionResult:
    """Call LLM Gateway to decompose raw text into structured engrams.

    Returns a DecompositionResult with engrams, relationships, and contradictions.
    On any failure, returns an empty result (never crashes the ingestion pipeline).
    """
    if not raw_text.strip():
        return DecompositionResult()

    try:
        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=60.0) as client:
            resp = await client.post(
                "/complete",
                json={
                    "model": settings.engram_decomposition_model,
                    "messages": [
                        {"role": "system", "content": DECOMPOSITION_SYSTEM_PROMPT},
                        {"role": "user", "content": DECOMPOSITION_USER_TEMPLATE.format(raw_text=raw_text)},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 4000,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data.get("content", "")
        if isinstance(content, list):
            content = content[0].get("text", "") if content else ""

        content = content.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        parsed = json.loads(content)
        return DecompositionResult.model_validate(parsed)

    except json.JSONDecodeError:
        log.warning("Failed to parse decomposition response as JSON")
        return DecompositionResult()
    except Exception:
        log.exception("Decomposition LLM call failed")
        return DecompositionResult()
