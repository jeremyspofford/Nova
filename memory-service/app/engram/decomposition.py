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

DECOMPOSITION_SYSTEM_PROMPT = """You extract facts from conversations into structured JSON memory units.

CRITICAL: Focus on what the USER says about themselves, their preferences, their work, and their requests. The assistant's responses are context, but the user's statements are what matter for memory.

Return ONLY valid JSON — no other text, no markdown fences, no explanation:
{"engrams":[{"type":"fact","content":"...","importance":0.5,"entities_referenced":[]}],"relationships":[],"contradictions":[]}

Types: fact (knowledge/claims), entity (people/places/tools), preference (likes/dislikes), episode (events), procedure (how-to)

Importance: 0.3=trivial, 0.5=normal, 0.7=significant, 0.9=critical (user identity, core preferences)

EXAMPLES:

User: "My name is Jeremy and I'm a software engineer"
Assistant: "Nice to meet you Jeremy!"
Output: {"engrams":[{"type":"entity","content":"The user's name is Jeremy","importance":0.9,"entities_referenced":["Jeremy"]},{"type":"fact","content":"Jeremy is a software engineer","importance":0.7,"entities_referenced":["Jeremy"]}],"relationships":[{"from_index":0,"to_index":1,"relation":"related_to","strength":0.8}],"contradictions":[]}

User: "I prefer Python over JavaScript"
Assistant: "Python is great for backend work"
Output: {"engrams":[{"type":"preference","content":"The user prefers Python over JavaScript","importance":0.6,"entities_referenced":["Python","JavaScript"]}],"relationships":[],"contradictions":[]}

User: "Good morning!"
Assistant: "Good morning! How can I help?"
Output: {"engrams":[],"relationships":[],"contradictions":[]}

Rules:
- Extract info about the USER, not the assistant
- User's name, role, company, preferences = high importance (0.7-0.9)
- Greetings, filler, small talk = return empty engrams list
- Each engram = ONE atomic fact
- Always include entities_referenced (can be empty list)"""

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
        # Resolve model — if "auto", ask the gateway for the best available
        model = settings.engram_decomposition_model
        if model == "auto":
            try:
                async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=5.0) as c:
                    r = await c.get("/v1/models/resolve")
                    if r.status_code == 200:
                        model = r.json().get("model", "llama3.1:8b")
            except Exception:
                model = "llama3.1:8b"

        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=60.0) as client:
            resp = await client.post(
                "/complete",
                json={
                    "model": model,
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
