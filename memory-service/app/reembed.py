"""
Background re-embedding — detects memories stored with a different embedding model
and re-embeds them in batches using the current configured model.

Runs as a fire-and-forget asyncio task after startup. Idempotent and resumable:
rows are updated individually, so a crash mid-batch picks up where it left off.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.config import settings
from app.db.database import AsyncSessionLocal
from app.embedding import get_embeddings_batch
from app.retrieval import TIER_TABLES, to_pg_vector

log = logging.getLogger(__name__)

BATCH_SIZE = 50


async def reembed_loop():
    """Check for and re-embed mismatched memories once, then exit."""
    # Brief delay to let other startup tasks settle
    await asyncio.sleep(5)

    target_model = settings.embedding_model
    total_updated = 0

    for tier, table in TIER_TABLES.items():
        try:
            count = await _reembed_table(table, tier, target_model)
            total_updated += count
        except Exception as e:
            log.error("Re-embed failed for tier %s: %s", tier, e, exc_info=True)

    if total_updated:
        log.info("Re-embed complete: %d memories updated to model '%s'", total_updated, target_model)
    else:
        log.info("Re-embed: all memories already use model '%s'", target_model)


async def _reembed_table(table: str, tier: str, target_model: str) -> int:
    """Re-embed all rows in a table that don't match the target model. Returns count updated."""
    updated = 0

    while True:
        # Fetch a batch of rows needing re-embedding
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"""
                    SELECT id::text, content
                    FROM {table}
                    WHERE embedding_model IS NULL OR embedding_model != :model
                    LIMIT :limit
                """),
                {"model": target_model, "limit": BATCH_SIZE},
            )
            rows = result.fetchall()

        if not rows:
            break

        batch_count = len(rows)
        log.info("Re-embed %s: processing %d rows (total so far: %d)", tier, batch_count, updated)

        # Get embeddings for the batch
        texts = [row.content[:2000] for row in rows]
        try:
            async with AsyncSessionLocal() as session:
                embeddings = await get_embeddings_batch(texts, session, model=target_model)
        except Exception as e:
            log.error("Re-embed %s: embedding batch failed, will retry later: %s", tier, e)
            break

        # Update each row with new embedding + model tag
        async with AsyncSessionLocal() as session:
            for row, embedding in zip(rows, embeddings):
                try:
                    await session.execute(
                        text(f"""
                            UPDATE {table}
                            SET embedding = CAST(:embedding AS halfvec),
                                embedding_model = :model
                            WHERE id = CAST(:id AS uuid)
                        """),
                        {
                            "id": row.id,
                            "embedding": to_pg_vector(embedding),
                            "model": target_model,
                        },
                    )
                except Exception as e:
                    log.warning("Re-embed %s: failed to update row %s: %s", tier, row.id, e)
            await session.commit()

        updated += batch_count

        # Rate limit: brief pause between batches to avoid hammering the embedding API
        await asyncio.sleep(1)

    return updated
