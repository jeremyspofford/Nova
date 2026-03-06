"""
Memory compaction pipeline — extracts structured facts from episodic memories.

Runs as an asyncio background task. Calls LLM Gateway to extract facts,
then upserts them via _save_fact_internal().
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
from sqlalchemy import text

from app.config import settings
from app.db.database import AsyncSessionLocal

log = logging.getLogger(__name__)

FACT_EXTRACTION_PROMPT = """You are a memory compaction agent. Extract structured facts from the following conversation episodes.

Return a JSON array of facts. Each fact should have:
- "category": a short category label (e.g., "preference", "contact", "project", "skill")
- "key": a unique identifier within the category (e.g., "preferred_language", "email")
- "content": the fact content as a clear statement
- "confidence": a float 0.0-1.0 indicating how confident you are in this fact

Only extract clear, factual information. Skip opinions, greetings, and transient context.
Return ONLY the JSON array, no other text.

Episodes:
"""


async def compaction_loop() -> None:
    """Periodically compact episodic memories into semantic facts."""
    if not settings.compaction_enabled:
        log.info("Memory compaction disabled")
        return

    log.info(
        "Compaction loop started (interval=%ds, batch=%d, lookback=%dd)",
        settings.compaction_interval_seconds,
        settings.compaction_batch_size,
        settings.compaction_lookback_days,
    )

    while True:
        try:
            await asyncio.sleep(settings.compaction_interval_seconds)
            await _run_compaction_cycle()
        except asyncio.CancelledError:
            log.info("Compaction loop shutting down")
            break
        except Exception:
            log.exception("Compaction cycle error — will retry next interval")


async def _run_compaction_cycle() -> None:
    """Single compaction cycle: fetch uncompacted episodes, extract facts, upsert."""
    from app.service import save_fact_internal

    async with AsyncSessionLocal() as session:
        # Fetch uncompacted episodes
        rows = await session.execute(
            text("""
                SELECT id, agent_id, content, metadata, created_at
                FROM episodic_memories
                WHERE (metadata->>'compacted') IS NULL
                  AND created_at > now() - make_interval(days => :lookback)
                ORDER BY created_at ASC
                LIMIT :batch_size
            """),
            {
                "lookback": settings.compaction_lookback_days,
                "batch_size": settings.compaction_batch_size,
            },
        )
        episodes = rows.fetchall()

        if not episodes:
            return

        # Group by agent_id
        by_agent: dict[str, list] = {}
        for ep in episodes:
            by_agent.setdefault(ep.agent_id, []).append(ep)

        for agent_id, agent_episodes in by_agent.items():
            try:
                # Build episode text for LLM
                episode_text = "\n\n---\n\n".join(
                    f"[{ep.created_at}] {ep.content}" for ep in agent_episodes
                )

                # Call LLM Gateway for fact extraction
                facts = await _extract_facts(episode_text)

                # Upsert each fact
                for fact in facts:
                    try:
                        await save_fact_internal(
                            session=session,
                            agent_id=agent_id,
                            project_id=agent_id,  # Default project = agent
                            category=fact.get("category", "general"),
                            key=fact.get("key", "unknown"),
                            content=fact.get("content", ""),
                            base_confidence=min(max(fact.get("confidence", 0.8), 0.0), 1.0),
                            metadata={"source": "compaction"},
                        )
                    except Exception:
                        log.warning("Failed to upsert fact: %s", fact, exc_info=True)

                # Mark episodes as compacted
                episode_ids = [ep.id for ep in agent_episodes]
                await session.execute(
                    text("""
                        UPDATE episodic_memories
                        SET metadata = metadata || '{"compacted": true}'::jsonb
                        WHERE id = ANY(CAST(:ids AS uuid[]))
                    """),
                    {"ids": [str(eid) for eid in episode_ids]},
                )
                await session.commit()

                log.info(
                    "Compacted %d episodes → %d facts for agent %s",
                    len(agent_episodes), len(facts), agent_id,
                )
            except Exception:
                log.exception("Compaction failed for agent %s", agent_id)


async def _extract_facts(episode_text: str) -> list[dict]:
    """Call LLM Gateway to extract structured facts from episodes."""
    prompt = FACT_EXTRACTION_PROMPT + episode_text

    try:
        async with httpx.AsyncClient(base_url=settings.llm_gateway_url, timeout=60.0) as client:
            resp = await client.post(
                "/complete",
                json={
                    "model": settings.compaction_model,
                    "messages": [
                        {"role": "system", "content": "You extract structured facts from conversations. Return only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse the response content
        content = data.get("content", "")
        if isinstance(content, list):
            # Handle message format
            content = content[0].get("text", "") if content else ""

        # Extract JSON array from response
        content = content.strip()
        if content.startswith("```"):
            # Strip markdown code fences
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        return json.loads(content)
    except json.JSONDecodeError:
        log.warning("Failed to parse LLM fact extraction response as JSON")
        return []
    except Exception:
        log.exception("Fact extraction LLM call failed")
        return []
