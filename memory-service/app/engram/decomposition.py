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

# Cache the resolved model so we don't probe every call.
# Set to None to force re-resolution (e.g. after config change via dashboard).
_resolved_model: str | None = None
_resolved_model_source: str | None = None  # "redis", "env", "probe" — for logging


def clear_model_cache() -> None:
    """Force re-resolution on next decompose() call. Called when config changes."""
    global _resolved_model, _resolved_model_source
    _resolved_model = None
    _resolved_model_source = None


async def resolve_model(model: str) -> str:
    """Resolve 'auto' to a concrete model by asking the gateway what's available.

    Resolution order:
      1. Redis nova:config:engram.decomposition_model (set via dashboard Settings)
      2. Env var ENGRAM_DECOMPOSITION_MODEL (bootstrap fallback)
      3. Gateway model resolution endpoint
      4. Probe common local models
    """
    global _resolved_model
    if model != "auto":
        return model
    if _resolved_model:
        return _resolved_model

    # Check Redis for dashboard-configured model (db1 = config DB)
    try:
        import json as _json
        import redis.asyncio as aioredis
        from app.config import settings as _settings
        config_redis_url = _settings.redis_url.rsplit("/", 1)[0] + "/1"
        r = aioredis.from_url(config_redis_url, decode_responses=True)
        try:
            raw = await r.get("nova:config:engram.decomposition_model")
            if raw:
                val = _json.loads(raw) if raw.startswith('"') else raw
                if val and val != "auto":
                    _resolved_model = val
                    log.info("Decomposition model from platform config: %s", val)
                    return _resolved_model
        finally:
            await r.aclose()
    except Exception:
        pass  # Redis unavailable — continue to other resolution methods

    # Try the gateway's model resolution endpoint
    try:
        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=5.0) as c:
            r = await c.get("/v1/models/resolve")
            if r.status_code == 200:
                _resolved_model = r.json().get("model", "")
                if _resolved_model:
                    log.info("Auto-resolved decomposition model: %s", _resolved_model)
                    return _resolved_model
    except Exception:
        pass

    # Fallback: probe common local models (ordered by structured output quality)
    for candidate in ["qwen2.5:7b", "qwen2.5", "qwen3:8b", "mistral", "llama3.2", "llama3.1:8b"]:
        try:
            async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=10.0) as c:
                r = await c.post("/complete", json={
                    "model": candidate,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                })
                if r.status_code == 200:
                    _resolved_model = candidate
                    log.info("Auto-resolved decomposition model via probe: %s", candidate)
                    return _resolved_model
        except Exception:
            continue

    log.warning("Could not auto-resolve decomposition model, using llama3.1:8b")
    _resolved_model = "llama3.1:8b"
    return _resolved_model


DECOMPOSITION_SYSTEM_PROMPT_CHAT = """You extract facts from conversations into structured JSON memory units.

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

DECOMPOSITION_SYSTEM_PROMPT_INTEL = """You extract factual information from third-party content (news articles, RSS feeds, Reddit posts, release notes) into structured JSON memory units.

CRITICAL: This is NOT a conversation with the user. This is external content from the internet. Do NOT attribute opinions or preferences to "the user" — attribute them to the author, community, or source. Extract objective facts, trends, announcements, and notable opinions with attribution.

Return ONLY valid JSON — no other text, no markdown fences, no explanation:
{"engrams":[{"type":"fact","content":"...","importance":0.5,"entities_referenced":[]}],"relationships":[],"contradictions":[]}

Types: fact (knowledge/claims/announcements), entity (people/orgs/tools/products), preference (community sentiment — NOT the user's preference), episode (events/releases/incidents), procedure (how-to/tutorials)

Importance: 0.3=minor news, 0.5=normal, 0.7=significant announcement, 0.9=major release or breakthrough

EXAMPLES:

Title: "OpenAI releases GPT-5 with 1M context"
Body: "OpenAI announced GPT-5 today with a 1 million token context window..."
Output: {"engrams":[{"type":"episode","content":"OpenAI released GPT-5 with 1 million token context window","importance":0.8,"entities_referenced":["OpenAI","GPT-5"]},{"type":"entity","content":"GPT-5 is OpenAI's latest model with 1M token context","importance":0.7,"entities_referenced":["GPT-5","OpenAI"]}],"relationships":[{"from_index":0,"to_index":1,"relation":"related_to","strength":0.8}],"contradictions":[]}

Title: "Reddit: Claude is better than GPT for coding"
Body: "Most commenters agree Claude handles complex refactors better..."
Output: {"engrams":[{"type":"fact","content":"Reddit community sentiment: Claude is preferred over GPT for complex coding refactors","importance":0.4,"entities_referenced":["Claude","GPT"]}],"relationships":[],"contradictions":[]}

Rules:
- This is EXTERNAL content — never say "the user thinks/wants/prefers"
- Attribute opinions to the source (e.g. "Reddit community", "the author", the named person)
- Focus on factual content: releases, announcements, benchmarks, trends
- Each engram = ONE atomic fact
- Always include entities_referenced (can be empty list)"""

DECOMPOSITION_USER_TEMPLATE = """Decompose this into atomic engrams:

{raw_text}"""


def _get_system_prompt(source_type: str) -> str:
    """Select decomposition prompt based on content source."""
    if source_type in ("intel", "knowledge"):
        return DECOMPOSITION_SYSTEM_PROMPT_INTEL
    return DECOMPOSITION_SYSTEM_PROMPT_CHAT


async def decompose(raw_text: str, source_type: str = "chat") -> DecompositionResult:
    """Call LLM Gateway to decompose raw text into structured engrams.

    Returns a DecompositionResult with engrams, relationships, and contradictions.
    On any failure, returns an empty result (never crashes the ingestion pipeline).
    """
    if not raw_text.strip():
        return DecompositionResult()

    try:
        model = await resolve_model(settings.engram_decomposition_model)

        system_prompt = _get_system_prompt(source_type)

        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=60.0) as client:
            resp = await client.post(
                "/complete",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
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
